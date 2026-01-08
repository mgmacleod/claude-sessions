"""Async session watcher for realtime monitoring.

This module provides AsyncSessionWatcher, an async-native interface
for monitoring Claude Code sessions. It supports both decorator-style
event handlers and async iteration patterns.

Example usage (async iteration):
    async def main():
        async with AsyncSessionWatcher() as watcher:
            async for event in watcher.events():
                match event.event_type:
                    case "message":
                        print(f"{event.message.role}: {event.message.text_content[:80]}")
                    case "tool_use":
                        print(f"  -> {event.tool_name}")

    asyncio.run(main())

Example usage (decorator style):
    watcher = AsyncSessionWatcher()

    @watcher.on("message")
    async def on_message(event):
        print(f"{event.message.role}: {event.message.text_content[:80]}")

    @watcher.on("tool_use")
    def on_tool(event):  # Can also be sync
        print(f"  -> {event.tool_name}")

    async def main():
        await watcher.start()
        await asyncio.sleep(60)
        await watcher.stop()

    asyncio.run(main())
"""

import asyncio
import inspect
import logging
from collections import defaultdict
from typing import (
    Any,
    AsyncIterator,
    Callable,
    Dict,
    List,
    Optional,
    Set,
    TYPE_CHECKING,
    Union,
)

from .events import SessionEventType
from .watcher import SessionWatcher, WatcherConfig

if TYPE_CHECKING:
    from .live import LiveSessionConfig, LiveSessionManager

logger = logging.getLogger(__name__)


# Type for handlers that can be sync or async
EventHandler = Union[
    Callable[[SessionEventType], None],
    Callable[[SessionEventType], "asyncio.coroutine"],
]


class AsyncSessionWatcher:
    """Async-native session watcher with event streaming.

    Provides both decorator-style handlers and async iteration for
    processing session events. Uses a background thread for file
    watching and delivers events via asyncio.Queue.

    The watcher supports both sync and async handlers. Async handlers
    are awaited properly, while sync handlers are called directly.

    Attributes:
        live_sessions: Access to LiveSessionManager if enabled.

    Example (async iteration):
        async with AsyncSessionWatcher() as watcher:
            async for event in watcher.events():
                print(event)

    Example (decorators):
        watcher = AsyncSessionWatcher()

        @watcher.on("message")
        async def handle(event):
            print(event)

        await watcher.start()
    """

    def __init__(
        self,
        config: Optional[WatcherConfig] = None,
        live_sessions: bool = False,
        live_config: Optional["LiveSessionConfig"] = None,
        queue_size: int = 1000,
    ):
        """Initialize the async session watcher.

        Args:
            config: Configuration options (uses defaults if None)
            live_sessions: If True, enable live session state tracking.
            live_config: Configuration for live sessions.
            queue_size: Maximum size of the event queue.
        """
        self._config = config or WatcherConfig()
        self._queue_size = queue_size

        # Create underlying sync watcher
        self._watcher = SessionWatcher(
            config=self._config,
            live_sessions=live_sessions,
            live_config=live_config,
        )

        # Event queue for async delivery
        self._queue: Optional[asyncio.Queue[Optional[SessionEventType]]] = None

        # Handler storage
        self._handlers: Dict[str, List[EventHandler]] = defaultdict(list)
        self._any_handlers: List[EventHandler] = []

        # State
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._dispatch_task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Track active iterators for cleanup
        self._active_iterators: Set[int] = set()

    # --- Public API: Decorators ---

    def on(
        self,
        event_type: str,
        handler: Optional[EventHandler] = None,
    ) -> Callable:
        """Register a handler for a specific event type.

        Can be used as a decorator or called directly. Handlers can be
        sync or async functions.

        Args:
            event_type: Event type to handle ("message", "tool_use", etc.)
            handler: Handler function (optional for decorator use)

        Returns:
            Handler or decorator

        Example:
            @watcher.on("message")
            async def handle(event):
                print(event)

            # Or sync:
            @watcher.on("tool_use")
            def handle(event):
                print(event)
        """
        if handler is not None:
            self._handlers[event_type].append(handler)
            return handler

        def decorator(fn: EventHandler) -> EventHandler:
            self._handlers[event_type].append(fn)
            return fn

        return decorator

    def on_any(self, handler: EventHandler) -> EventHandler:
        """Register a handler for all events.

        Args:
            handler: Handler function (sync or async)

        Returns:
            The handler function
        """
        self._any_handlers.append(handler)
        return handler

    def off(self, event_type: str, handler: EventHandler) -> bool:
        """Unregister a handler.

        Args:
            event_type: Event type the handler was registered for
            handler: Handler to remove

        Returns:
            True if handler was found and removed
        """
        try:
            self._handlers[event_type].remove(handler)
            return True
        except ValueError:
            return False

    def off_any(self, handler: EventHandler) -> bool:
        """Unregister a wildcard handler.

        Args:
            handler: Handler to remove

        Returns:
            True if handler was found and removed
        """
        try:
            self._any_handlers.remove(handler)
            return True
        except ValueError:
            return False

    # --- Public API: Async Iteration ---

    async def events(self) -> AsyncIterator[SessionEventType]:
        """Async iterator for session events.

        Yields events as they arrive. Multiple callers can iterate
        concurrently - each gets all events.

        Yields:
            Session events as they occur

        Example:
            async for event in watcher.events():
                print(event.event_type)
        """
        if not self._running:
            raise RuntimeError("Watcher not started. Call start() first.")

        if self._queue is None:
            raise RuntimeError("Event queue not initialized")

        # Create a dedicated queue for this iterator
        iter_id = id(asyncio.current_task())
        self._active_iterators.add(iter_id)

        try:
            while self._running:
                try:
                    event = await asyncio.wait_for(
                        self._queue.get(),
                        timeout=0.5,
                    )
                    if event is None:
                        # Shutdown signal
                        break
                    yield event
                except asyncio.TimeoutError:
                    # Check if still running
                    continue
        finally:
            self._active_iterators.discard(iter_id)

    # --- Public API: Lifecycle ---

    async def start(self) -> None:
        """Start watching for sessions (non-blocking).

        Starts the background watcher and event dispatch loop.
        Use stop() to terminate.
        """
        if self._running:
            return

        self._running = True
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=self._queue_size)

        # Set up event routing from sync watcher to our queue
        self._watcher.on_any(self._on_sync_event)

        # Start the sync watcher in a thread
        self._task = asyncio.create_task(self._run_watcher())

        # Start the handler dispatch loop
        self._dispatch_task = asyncio.create_task(self._dispatch_loop())

        logger.debug("Started async session watcher")

    async def stop(self) -> None:
        """Stop watching for sessions."""
        if not self._running:
            return

        self._running = False

        # Signal queue consumers to stop
        if self._queue is not None:
            try:
                self._queue.put_nowait(None)
            except asyncio.QueueFull:
                pass

        # Stop the sync watcher
        self._watcher.stop()

        # Cancel tasks
        if self._dispatch_task is not None:
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass
            self._dispatch_task = None

        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        self._queue = None
        self._loop = None

        logger.debug("Stopped async session watcher")

    async def run_for(self, seconds: float) -> None:
        """Run watcher for a limited duration.

        Args:
            seconds: How long to run
        """
        await self.start()
        try:
            await asyncio.sleep(seconds)
        finally:
            await self.stop()

    # --- Public API: Properties ---

    @property
    def live_sessions(self) -> Optional["LiveSessionManager"]:
        """Access the live session manager.

        Returns:
            LiveSessionManager if live_sessions=True was passed,
            None otherwise.
        """
        return self._watcher.live_sessions

    @property
    def config(self) -> WatcherConfig:
        """Get the watcher configuration."""
        return self._config

    @property
    def is_running(self) -> bool:
        """Whether the watcher is currently running."""
        return self._running

    # --- Context Manager ---

    async def __aenter__(self) -> "AsyncSessionWatcher":
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: Any,
        exc_val: Any,
        exc_tb: Any,
    ) -> bool:
        await self.stop()
        return False

    # --- Internal Methods ---

    def _on_sync_event(self, event: SessionEventType) -> None:
        """Handle event from sync watcher (called in watcher thread).

        Safely transfers event to async world via queue.
        """
        if self._queue is None or self._loop is None:
            return

        try:
            # Thread-safe way to put event in asyncio queue
            self._loop.call_soon_threadsafe(
                self._queue.put_nowait,
                event,
            )
        except asyncio.QueueFull:
            logger.warning("Event queue full, dropping event")
        except RuntimeError:
            # Loop closed
            pass

    async def _run_watcher(self) -> None:
        """Run the sync watcher in a thread executor."""
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._watcher.start)
        except Exception as e:
            logger.exception("Error in watcher thread: %s", e)

    async def _dispatch_loop(self) -> None:
        """Dispatch events to registered handlers."""
        if self._queue is None:
            return

        while self._running:
            try:
                event = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=0.5,
                )
                if event is None:
                    break

                await self._dispatch_event(event)

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Error in dispatch loop: %s", e)

    async def _dispatch_event(self, event: SessionEventType) -> None:
        """Dispatch a single event to all handlers."""
        event_type = getattr(event, "event_type", None)

        # Get handlers for this event type
        handlers = list(self._handlers.get(event_type, []))
        handlers.extend(self._any_handlers)

        for handler in handlers:
            try:
                if inspect.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as e:
                logger.exception(
                    "Error in handler %s for %s: %s",
                    handler.__name__,
                    event_type,
                    e,
                )

    # --- Utility Methods ---

    def get_active_sessions(self) -> List[str]:
        """Get list of active (non-ended) session IDs."""
        return self._watcher.get_active_sessions()

    def get_session_stats(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get statistics for a tracked session."""
        return self._watcher.get_session_stats(session_id)

    @property
    def handler_count(self) -> int:
        """Total number of registered handlers."""
        type_count = sum(len(h) for h in self._handlers.values())
        return type_count + len(self._any_handlers)

    def __repr__(self) -> str:
        status = "running" if self._running else "stopped"
        return f"AsyncSessionWatcher({status}, {self.handler_count} handlers)"
