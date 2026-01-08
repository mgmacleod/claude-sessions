"""Webhook dispatcher for sending events to HTTP endpoints.

This module provides WebhookDispatcher for sending session events to
external HTTP endpoints with batching, retry logic, and filtering.

Example usage:
    from claude_sessions.realtime import SessionWatcher
    from claude_sessions.realtime.webhook import WebhookDispatcher, WebhookConfig

    watcher = SessionWatcher()
    dispatcher = WebhookDispatcher()

    dispatcher.add_webhook(WebhookConfig(
        url="https://example.com/webhook",
        headers={"Authorization": "Bearer token"},
        batch_size=10,
    ))

    watcher.on_any(dispatcher.handle_event)

    dispatcher.start()
    watcher.start()
    dispatcher.stop()

The webhook payload format:
    {
        "events": [
            {
                "event_type": "message",
                "timestamp": "2024-01-15T14:32:05.123456+00:00",
                "session_id": "abc123...",
                "role": "user",
                "text_preview": "Help me fix..."
            },
            ...
        ],
        "timestamp": "2024-01-15T14:32:10.456789+00:00",
        "source": "claude-sessions"
    }
"""

import json
import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .events import SessionEventType

logger = logging.getLogger(__name__)


# Try to import requests for better HTTP handling
try:
    import requests

    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


@dataclass
class WebhookConfig:
    """Configuration for a webhook endpoint.

    Attributes:
        url: The webhook URL to send events to
        headers: HTTP headers to include in requests (e.g., auth tokens)
        event_filter: Optional filter function to select which events to send
        batch_size: Number of events to batch before sending (default: 10)
        batch_timeout: Max seconds to wait before sending incomplete batch (default: 5.0)
        max_retries: Maximum retry attempts for failed requests (default: 3)
        retry_backoff: Base seconds for exponential backoff (default: 1.0)
        timeout: Request timeout in seconds (default: 30.0)
    """

    url: str
    headers: Dict[str, str] = field(default_factory=dict)
    event_filter: Optional[Callable[[SessionEventType], bool]] = None
    batch_size: int = 10
    batch_timeout: float = 5.0
    max_retries: int = 3
    retry_backoff: float = 1.0
    timeout: float = 30.0


@dataclass
class WebhookPayload:
    """Payload sent to webhooks.

    Attributes:
        events: List of serialized events
        timestamp: When the payload was created (ISO format)
        source: Identifier for the source system
    """

    events: List[Dict[str, Any]]
    timestamp: str
    source: str = "claude-sessions"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "events": self.events,
            "timestamp": self.timestamp,
            "source": self.source,
        }

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), default=str, ensure_ascii=False)


def serialize_event(event: SessionEventType) -> Dict[str, Any]:
    """Serialize an event to a JSON-compatible dictionary.

    Args:
        event: The event to serialize

    Returns:
        JSON-serializable dictionary representation
    """
    result: Dict[str, Any] = {
        "event_type": event.event_type,
        "timestamp": event.timestamp.isoformat(),
        "session_id": event.session_id,
    }

    if event.agent_id:
        result["agent_id"] = event.agent_id

    # Add type-specific fields
    if event.event_type == "message":
        result["role"] = event.message.role.value
        result["text_preview"] = event.message.text_content[:500]
        result["has_tool_calls"] = event.message.has_tool_calls
    elif event.event_type == "tool_use":
        result["tool_name"] = event.tool_name
        result["tool_category"] = event.tool_category
        result["tool_use_id"] = event.tool_use_id
        # Don't include full tool_input as it can be large
    elif event.event_type == "tool_result":
        result["tool_use_id"] = event.tool_use_id
        result["is_error"] = event.is_error
        # Don't include full content as it can be very large
    elif event.event_type == "tool_call_completed":
        result["tool_name"] = event.tool_name
        result["tool_use_id"] = event.tool_use_id
        result["is_error"] = event.is_error
        if event.duration:
            result["duration_ms"] = event.duration.total_seconds() * 1000
    elif event.event_type == "session_start":
        result["project_slug"] = event.project_slug
        result["file_path"] = str(event.file_path)
    elif event.event_type == "session_end":
        result["reason"] = event.reason
        result["message_count"] = event.message_count
        result["tool_count"] = event.tool_count
    elif event.event_type == "session_idle":
        pass  # No additional fields
    elif event.event_type == "session_resume":
        result["idle_duration_seconds"] = event.idle_duration.total_seconds()
    elif event.event_type == "error":
        result["error_message"] = event.error_message

    return result


class WebhookDispatcher:
    """Dispatches events to webhook endpoints with batching and retry.

    Manages multiple webhook configurations, batches events for efficiency,
    and handles retries with exponential backoff. Each webhook runs in its
    own background thread.

    Example:
        dispatcher = WebhookDispatcher()
        dispatcher.add_webhook(WebhookConfig(
            url="https://example.com/webhook",
            headers={"Authorization": "Bearer token"},
        ))

        watcher.on_any(dispatcher.handle_event)

        dispatcher.start()
        watcher.start()
        dispatcher.stop()  # Flushes remaining events

    As context manager:
        with WebhookDispatcher() as dispatcher:
            dispatcher.add_webhook(WebhookConfig(url="..."))
            watcher.on_any(dispatcher.handle_event)
            watcher.start()
    """

    def __init__(self):
        """Initialize the webhook dispatcher."""
        self._webhooks: List[WebhookConfig] = []
        self._queues: Dict[str, queue.Queue] = {}
        self._threads: Dict[str, threading.Thread] = {}
        self._stop_event = threading.Event()
        self._running = False
        self._stats: Dict[str, Dict[str, int]] = {}

    def add_webhook(self, config: WebhookConfig) -> None:
        """Add a webhook configuration.

        Must be called before start(). Adding webhooks after start()
        will have no effect.

        Args:
            config: Webhook configuration to add
        """
        if self._running:
            logger.warning("Cannot add webhook after dispatcher started")
            return

        self._webhooks.append(config)
        self._queues[config.url] = queue.Queue(maxsize=10000)
        self._stats[config.url] = {"sent": 0, "failed": 0, "filtered": 0}

    def handle_event(self, event: SessionEventType) -> None:
        """Handle an event from the watcher.

        Routes the event to appropriate webhook queues based on filters.
        This method is thread-safe and non-blocking.

        Args:
            event: The event to dispatch
        """
        if not self._running:
            return

        for config in self._webhooks:
            # Apply filter if configured
            if config.event_filter and not config.event_filter(event):
                self._stats[config.url]["filtered"] += 1
                continue

            # Queue the event (non-blocking)
            try:
                self._queues[config.url].put_nowait(event)
            except queue.Full:
                logger.warning(
                    "Webhook queue full for %s, dropping event", config.url
                )

    def start(self) -> None:
        """Start the dispatcher threads.

        Starts a background thread for each configured webhook.
        Events queued via handle_event() will be batched and sent.
        """
        if self._running:
            logger.warning("Dispatcher already running")
            return

        if not self._webhooks:
            logger.warning("No webhooks configured")
            return

        self._running = True
        self._stop_event.clear()

        for config in self._webhooks:
            thread = threading.Thread(
                target=self._dispatch_loop,
                args=(config,),
                name=f"webhook-{config.url[:30]}",
                daemon=True,
            )
            self._threads[config.url] = thread
            thread.start()
            logger.debug("Started webhook thread for %s", config.url)

    def stop(self, timeout: float = 10.0) -> None:
        """Stop the dispatcher and flush remaining events.

        Signals all threads to stop, waits for them to flush their
        queues, and joins the threads.

        Args:
            timeout: Maximum seconds to wait for threads to finish
        """
        if not self._running:
            return

        logger.debug("Stopping webhook dispatcher")
        self._stop_event.set()
        self._running = False

        for url, thread in self._threads.items():
            thread.join(timeout=timeout)
            if thread.is_alive():
                logger.warning("Webhook thread for %s did not terminate", url)

        self._threads.clear()

        # Log final stats
        for url, stats in self._stats.items():
            logger.info(
                "Webhook %s: sent=%d, failed=%d, filtered=%d",
                url[:50],
                stats["sent"],
                stats["failed"],
                stats["filtered"],
            )

    def get_stats(self) -> Dict[str, Dict[str, int]]:
        """Get statistics for all webhooks.

        Returns:
            Dictionary mapping URL to stats dict with keys:
            - sent: Number of batches successfully sent
            - failed: Number of batches that failed after retries
            - filtered: Number of events filtered out
        """
        return dict(self._stats)

    def _dispatch_loop(self, config: WebhookConfig) -> None:
        """Main loop for dispatching events to a webhook.

        Collects events into batches and sends them when either:
        - batch_size events are collected
        - batch_timeout seconds have passed since last send

        Args:
            config: Webhook configuration
        """
        q = self._queues[config.url]
        batch: List[SessionEventType] = []
        last_send = time.time()

        while not self._stop_event.is_set():
            # Try to get an event with timeout
            try:
                event = q.get(timeout=0.5)
                batch.append(event)
            except queue.Empty:
                pass

            # Check if we should send
            elapsed = time.time() - last_send
            should_send = (
                len(batch) >= config.batch_size
                or (batch and elapsed >= config.batch_timeout)
            )

            if should_send:
                success = self._send_batch(config, batch)
                if success:
                    self._stats[config.url]["sent"] += 1
                else:
                    self._stats[config.url]["failed"] += 1
                batch = []
                last_send = time.time()

        # Flush remaining events on shutdown
        while not q.empty():
            try:
                event = q.get_nowait()
                batch.append(event)
            except queue.Empty:
                break

        if batch:
            success = self._send_batch(config, batch)
            if success:
                self._stats[config.url]["sent"] += 1
            else:
                self._stats[config.url]["failed"] += 1

    def _send_batch(
        self,
        config: WebhookConfig,
        events: List[SessionEventType],
    ) -> bool:
        """Send a batch of events to a webhook.

        Retries with exponential backoff on failure.

        Args:
            config: Webhook configuration
            events: List of events to send

        Returns:
            True if successful, False if all retries failed
        """
        if not events:
            return True

        payload = WebhookPayload(
            events=[serialize_event(e) for e in events],
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        for attempt in range(config.max_retries + 1):
            try:
                self._send_request(config, payload)
                logger.debug(
                    "Sent %d events to %s",
                    len(events),
                    config.url[:50],
                )
                return True

            except Exception as e:
                logger.warning(
                    "Webhook request failed (attempt %d/%d): %s",
                    attempt + 1,
                    config.max_retries + 1,
                    e,
                )

                if attempt < config.max_retries:
                    backoff = config.retry_backoff * (2**attempt)
                    time.sleep(backoff)

        logger.error(
            "Failed to send %d events to %s after %d attempts",
            len(events),
            config.url[:50],
            config.max_retries + 1,
        )
        return False

    def _send_request(self, config: WebhookConfig, payload: WebhookPayload) -> None:
        """Send HTTP request to webhook.

        Uses requests library if available, falls back to urllib.

        Args:
            config: Webhook configuration
            payload: Payload to send

        Raises:
            Exception: If request fails
        """
        if REQUESTS_AVAILABLE:
            self._send_with_requests(config, payload)
        else:
            self._send_with_urllib(config, payload)

    def _send_with_requests(
        self,
        config: WebhookConfig,
        payload: WebhookPayload,
    ) -> None:
        """Send using requests library."""
        headers = {"Content-Type": "application/json", **config.headers}

        response = requests.post(
            config.url,
            data=payload.to_json(),
            headers=headers,
            timeout=config.timeout,
        )
        response.raise_for_status()

    def _send_with_urllib(
        self,
        config: WebhookConfig,
        payload: WebhookPayload,
    ) -> None:
        """Send using stdlib urllib."""
        headers = {"Content-Type": "application/json", **config.headers}

        req = Request(
            config.url,
            data=payload.to_json().encode("utf-8"),
            headers=headers,
            method="POST",
        )

        with urlopen(req, timeout=config.timeout) as response:
            if response.status >= 400:
                raise HTTPError(
                    config.url,
                    response.status,
                    f"HTTP Error {response.status}",
                    response.headers,
                    None,
                )

    def __enter__(self) -> "WebhookDispatcher":
        """Context manager entry - starts the dispatcher."""
        self.start()
        return self

    def __exit__(self, *args) -> None:
        """Context manager exit - stops the dispatcher."""
        self.stop()
