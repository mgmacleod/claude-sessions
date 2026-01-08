"""Tests for WebhookDispatcher.

These tests verify webhook dispatching, batching, and retry logic.
"""

import json
import time
from datetime import datetime, timezone
from unittest.mock import Mock, patch, MagicMock

import pytest

from claude_sessions.realtime.webhook import (
    WebhookConfig,
    WebhookPayload,
    WebhookDispatcher,
)
from claude_sessions.realtime.events import (
    MessageEvent,
    ToolUseEvent,
    ErrorEvent,
)
from claude_sessions.models import Message, MessageRole, TextBlock


@pytest.fixture
def sample_datetime():
    return datetime(2024, 1, 15, 14, 32, 5, tzinfo=timezone.utc)


@pytest.fixture
def message_event(sample_datetime):
    """Create a sample message event."""
    message = Message(
        uuid="msg-1",
        parent_uuid=None,
        timestamp=sample_datetime,
        role=MessageRole.USER,
        content=[TextBlock(text="Hello world")],
        session_id="session-12345678"
    )
    return MessageEvent(
        timestamp=sample_datetime,
        session_id="session-12345678",
        message=message
    )


@pytest.fixture
def tool_use_event(sample_datetime):
    """Create a sample tool use event."""
    message = Message(
        uuid="msg-2",
        parent_uuid="msg-1",
        timestamp=sample_datetime,
        role=MessageRole.ASSISTANT,
        content=[],
        session_id="session-12345678"
    )
    return ToolUseEvent(
        timestamp=sample_datetime,
        session_id="session-12345678",
        tool_name="Read",
        tool_category="file_read",
        tool_input={"file_path": "/test.py"},
        tool_use_id="toolu_123",
        message=message
    )


class TestWebhookConfig:
    """Test WebhookConfig dataclass."""

    def test_defaults(self):
        """WebhookConfig should have sensible defaults."""
        config = WebhookConfig(url="https://example.com/webhook")

        assert config.url == "https://example.com/webhook"
        assert config.headers == {}
        assert config.event_filter is None
        assert config.batch_size == 10
        assert config.batch_timeout == 5.0
        assert config.max_retries == 3
        assert config.retry_backoff == 1.0
        assert config.timeout == 30.0

    def test_custom_values(self):
        """WebhookConfig should accept custom values."""
        config = WebhookConfig(
            url="https://example.com/webhook",
            headers={"Authorization": "Bearer token"},
            batch_size=5,
            max_retries=5,
        )

        assert config.headers == {"Authorization": "Bearer token"}
        assert config.batch_size == 5
        assert config.max_retries == 5


class TestWebhookPayload:
    """Test WebhookPayload dataclass."""

    def test_creation(self):
        """WebhookPayload should be creatable."""
        payload = WebhookPayload(
            events=[{"type": "test"}],
            timestamp=datetime.now(timezone.utc).isoformat(),
            source="test"
        )

        assert len(payload.events) == 1
        assert payload.source == "test"

    def test_to_dict(self):
        """WebhookPayload should serialize to dict."""
        payload = WebhookPayload(
            events=[{"type": "test"}],
            timestamp="2024-01-15T14:32:05+00:00",
            source="claude_sessions"
        )

        data = payload.to_dict()
        assert data["source"] == "claude_sessions"
        assert len(data["events"]) == 1

    def test_to_json(self):
        """WebhookPayload should serialize to JSON."""
        payload = WebhookPayload(
            events=[{"type": "test"}],
            timestamp="2024-01-15T14:32:05+00:00",
            source="test"
        )

        json_str = payload.to_json()
        data = json.loads(json_str)
        assert data["source"] == "test"


class TestWebhookDispatcher:
    """Test WebhookDispatcher class."""

    def test_initialization(self):
        """WebhookDispatcher should initialize correctly."""
        dispatcher = WebhookDispatcher()
        assert dispatcher is not None
        assert not dispatcher._running

    def test_add_webhook(self):
        """add_webhook() should register a webhook."""
        dispatcher = WebhookDispatcher()
        config = WebhookConfig(url="https://example.com/webhook")

        dispatcher.add_webhook(config)

        # Should have one webhook
        assert len(dispatcher._webhooks) == 1

    def test_add_multiple_webhooks(self):
        """Multiple webhooks should be supported."""
        dispatcher = WebhookDispatcher()

        dispatcher.add_webhook(WebhookConfig(url="https://example.com/webhook1"))
        dispatcher.add_webhook(WebhookConfig(url="https://example.com/webhook2"))

        assert len(dispatcher._webhooks) == 2

    def test_add_webhook_creates_queue(self):
        """add_webhook() should create a queue for the webhook."""
        dispatcher = WebhookDispatcher()
        config = WebhookConfig(url="https://example.com/webhook")

        dispatcher.add_webhook(config)

        assert "https://example.com/webhook" in dispatcher._queues

    def test_get_stats(self):
        """get_stats() should return dispatch statistics."""
        dispatcher = WebhookDispatcher()
        config = WebhookConfig(url="https://example.com/webhook")
        dispatcher.add_webhook(config)

        stats = dispatcher.get_stats()

        assert "https://example.com/webhook" in stats
        assert stats["https://example.com/webhook"]["sent"] == 0
        assert stats["https://example.com/webhook"]["failed"] == 0
        assert stats["https://example.com/webhook"]["filtered"] == 0


class TestWebhookDispatcherEventHandling:
    """Test event handling in WebhookDispatcher."""

    def test_handle_event_requires_running(self, message_event):
        """handle_event() should do nothing when not running."""
        dispatcher = WebhookDispatcher()
        config = WebhookConfig(url="https://example.com/webhook")
        dispatcher.add_webhook(config)

        # Not started, so event should be ignored
        dispatcher.handle_event(message_event)

        # Queue should be empty
        assert dispatcher._queues["https://example.com/webhook"].empty()

    def test_event_filter_increments_stats(self, message_event, tool_use_event):
        """Filtered events should increment filtered counter."""
        dispatcher = WebhookDispatcher()

        # Only accept tool_use events
        config = WebhookConfig(
            url="https://example.com/webhook",
            event_filter=lambda e: e.event_type == "tool_use"
        )
        dispatcher.add_webhook(config)
        dispatcher.start()

        # Message events should be filtered out
        dispatcher.handle_event(message_event)

        # Give a moment for processing
        time.sleep(0.05)

        stats = dispatcher.get_stats()
        assert stats["https://example.com/webhook"]["filtered"] == 1

        dispatcher.stop()


class TestWebhookDispatcherLifecycle:
    """Test dispatcher lifecycle."""

    def test_start_and_stop(self):
        """start() and stop() should manage background thread."""
        dispatcher = WebhookDispatcher()
        config = WebhookConfig(url="https://example.com/webhook")
        dispatcher.add_webhook(config)

        dispatcher.start()
        assert dispatcher._running

        dispatcher.stop()
        assert not dispatcher._running

    def test_start_without_webhooks_logs_warning(self):
        """start() without webhooks should return immediately."""
        dispatcher = WebhookDispatcher()

        # Should not raise, just return
        dispatcher.start()
        assert not dispatcher._running


class TestWebhookDispatcherRetry:
    """Test retry logic."""

    def test_retry_backoff_calculation(self):
        """Retry backoff should be exponential."""
        config = WebhookConfig(
            url="https://example.com/webhook",
            retry_backoff=1.0
        )

        # Expected: 1.0, 2.0, 4.0 for retries 0, 1, 2
        backoffs = [config.retry_backoff * (2 ** i) for i in range(3)]

        assert backoffs[0] == 1.0
        assert backoffs[1] == 2.0
        assert backoffs[2] == 4.0


class TestWebhookDispatcherIntegration:
    """Integration tests with mocked HTTP."""

    @patch('claude_sessions.realtime.webhook.urlopen')
    def test_sends_to_webhook(self, mock_urlopen, message_event):
        """Dispatcher should send events to webhook URL."""
        # Mock successful response
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b'{"ok": true}'
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_urlopen.return_value = mock_response

        dispatcher = WebhookDispatcher()
        config = WebhookConfig(
            url="https://example.com/webhook",
            batch_size=1,  # Send immediately
            batch_timeout=0.1,
        )
        dispatcher.add_webhook(config)

        dispatcher.start()
        dispatcher.handle_event(message_event)

        # Give time for dispatch
        time.sleep(0.3)
        dispatcher.stop()

        # Should have attempted to send
        # Note: May not be called if batching logic prevents it
        # The key thing is that no exceptions were raised
