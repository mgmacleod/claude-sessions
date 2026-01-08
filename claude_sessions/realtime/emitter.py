"""Event emitter for realtime session monitoring.

This module provides the EventEmitter class for dispatching session
events to registered handlers.
"""

import logging
from collections import defaultdict
from typing import Callable, Dict, List, Literal, Optional, Union, overload

from .events import (
    SessionEvent,
    SessionEventType,
    MessageEvent,
    ToolUseEvent,
    ToolResultEvent,
    ErrorEvent,
)


logger = logging.getLogger(__name__)


# Event types that can be subscribed to
EventType = Literal[
    "message",
    "tool_use",
    "tool_result",
    "error",
    "session_start",
    "session_end",
    "session_idle",
    "session_resume",
]

# Handler function type
EventHandler = Callable[[SessionEventType], None]


class EventEmitter:
    """Dispatches session events to registered handlers.

    Supports subscribing to specific event types or all events.
    Handler exceptions are caught and logged to prevent one faulty
    handler from breaking the event stream.

    Example:
        >>> emitter = EventEmitter()
        >>>
        >>> @emitter.on("message")
        ... def handle_message(event):
        ...     print(f"{event.message.role}: {event.message.text_content[:50]}")
        >>>
        >>> @emitter.on("tool_use")
        ... def handle_tool(event):
        ...     print(f"  -> {event.tool_name}")
        >>>
        >>> # Emit events
        >>> for event in events:
        ...     emitter.emit(event)
    """

    # Special key for wildcard handlers
    _ANY_KEY = "_any"

    def __init__(self):
        """Initialize the event emitter."""
        self._handlers: Dict[str, List[EventHandler]] = defaultdict(list)

    def on(
        self,
        event_type: EventType,
        handler: Optional[EventHandler] = None
    ) -> Union[EventHandler, Callable[[EventHandler], EventHandler]]:
        """Register a handler for a specific event type.

        Can be used as a decorator:
            @emitter.on("message")
            def handle(event):
                ...

        Or called directly:
            emitter.on("message", my_handler)

        Args:
            event_type: Type of event to handle
            handler: Callback function (optional if used as decorator)

        Returns:
            The handler, or a decorator function
        """
        if handler is not None:
            # Direct call: emitter.on("message", handler)
            self._handlers[event_type].append(handler)
            return handler

        # Decorator call: @emitter.on("message")
        def decorator(fn: EventHandler) -> EventHandler:
            self._handlers[event_type].append(fn)
            return fn

        return decorator

    def off(self, event_type: EventType, handler: EventHandler) -> bool:
        """Unregister a handler for a specific event type.

        Args:
            event_type: Type of event
            handler: Handler to remove

        Returns:
            True if handler was found and removed
        """
        handlers = self._handlers[event_type]
        try:
            handlers.remove(handler)
            return True
        except ValueError:
            return False

    def on_any(self, handler: EventHandler) -> EventHandler:
        """Register a handler for all event types.

        Can be used as a decorator:
            @emitter.on_any
            def handle_all(event):
                print(f"Event: {event.event_type}")

        Args:
            handler: Callback function

        Returns:
            The handler (for decorator use)
        """
        self._handlers[self._ANY_KEY].append(handler)
        return handler

    def off_any(self, handler: EventHandler) -> bool:
        """Unregister a wildcard handler.

        Args:
            handler: Handler to remove

        Returns:
            True if handler was found and removed
        """
        handlers = self._handlers[self._ANY_KEY]
        try:
            handlers.remove(handler)
            return True
        except ValueError:
            return False

    def emit(self, event: SessionEventType) -> int:
        """Dispatch an event to all registered handlers.

        Handlers are called in registration order. Exceptions are
        caught and logged to prevent one handler from breaking others.

        Args:
            event: The event to dispatch

        Returns:
            Number of handlers that were called
        """
        handlers_called = 0

        # Get handlers for this event type
        type_handlers = self._handlers.get(event.event_type, [])
        any_handlers = self._handlers.get(self._ANY_KEY, [])

        all_handlers = type_handlers + any_handlers

        for handler in all_handlers:
            try:
                handler(event)
                handlers_called += 1
            except Exception as e:
                logger.exception(
                    f"Error in event handler {handler.__name__} for {event.event_type}: {e}"
                )

        return handlers_called

    def emit_all(self, events: List[SessionEventType]) -> int:
        """Dispatch multiple events.

        Args:
            events: List of events to dispatch

        Returns:
            Total number of handler calls
        """
        total = 0
        for event in events:
            total += self.emit(event)
        return total

    def clear(self, event_type: Union[EventType, None] = None) -> None:
        """Remove all handlers for an event type.

        Args:
            event_type: Type to clear, or None to clear all handlers
        """
        if event_type is None:
            self._handlers.clear()
        else:
            self._handlers[event_type].clear()

    @property
    def handler_count(self) -> int:
        """Total number of registered handlers."""
        return sum(len(handlers) for handlers in self._handlers.values())

    def has_handlers(self, event_type: EventType) -> bool:
        """Check if any handlers are registered for an event type.

        Args:
            event_type: Type to check

        Returns:
            True if at least one handler is registered
        """
        type_handlers = self._handlers.get(event_type, [])
        any_handlers = self._handlers.get(self._ANY_KEY, [])
        return bool(type_handlers or any_handlers)
