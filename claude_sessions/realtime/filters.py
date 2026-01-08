"""Composable event filters for realtime session monitoring.

This module provides filter functions and combinators for selectively
processing session events. Filters can be combined using logical operators
and used with the FilterPipeline class for handler registration.

Example usage:
    from claude_sessions.realtime import SessionWatcher, filters

    watcher = SessionWatcher()

    # Filter for file write operations in a specific project
    file_writes = filters.and_(
        filters.project("my-project"),
        filters.tool_category("file_write")
    )

    # Use with pipeline
    pipeline = filters.FilterPipeline(file_writes)

    @pipeline.on("tool_use")
    def on_file_write(event):
        print(f"File operation: {event.tool_name}")

    @watcher.on_any
    def route(event):
        pipeline.process(event)

    watcher.start()
"""

from collections import defaultdict
from typing import Callable, Dict, List, Optional, Set, Union

from .events import SessionEventType

# Type alias for filter predicates
EventFilter = Callable[[SessionEventType], bool]


# --- Basic Filter Factories ---


def project(slug: str) -> EventFilter:
    """Create a filter that matches events from a specific project.

    Args:
        slug: The project slug to match (e.g., "my-project")

    Returns:
        A filter function that returns True for matching events.

    Example:
        >>> f = project("my-project")
        >>> f(event)  # True if event.project_slug == "my-project"
    """
    def _filter(event: SessionEventType) -> bool:
        # SessionStartEvent has project_slug directly
        if hasattr(event, "project_slug"):
            return event.project_slug == slug
        # MessageEvent has it via message
        if hasattr(event, "message") and hasattr(event.message, "project_slug"):
            return getattr(event.message, "project_slug", None) == slug
        return False

    return _filter


def session(session_id: str) -> EventFilter:
    """Create a filter that matches events from a specific session.

    Args:
        session_id: The session UUID to match

    Returns:
        A filter function that returns True for matching events.

    Example:
        >>> f = session("abc-123-def")
        >>> f(event)  # True if event.session_id == "abc-123-def"
    """
    def _filter(event: SessionEventType) -> bool:
        return getattr(event, "session_id", None) == session_id

    return _filter


def session_prefix(prefix: str) -> EventFilter:
    """Create a filter that matches sessions whose ID starts with a prefix.

    Useful for matching short session IDs (e.g., "abc123").

    Args:
        prefix: The session ID prefix to match

    Returns:
        A filter function that returns True for matching events.

    Example:
        >>> f = session_prefix("abc")
        >>> f(event)  # True if event.session_id.startswith("abc")
    """
    def _filter(event: SessionEventType) -> bool:
        sid = getattr(event, "session_id", None)
        return sid is not None and sid.startswith(prefix)

    return _filter


def event_type(*types: str) -> EventFilter:
    """Create a filter that matches specific event types.

    Args:
        *types: Event types to match (e.g., "message", "tool_use")

    Returns:
        A filter function that returns True for matching events.

    Example:
        >>> f = event_type("message", "tool_use")
        >>> f(message_event)  # True
        >>> f(session_start_event)  # False
    """
    type_set: Set[str] = set(types)

    def _filter(event: SessionEventType) -> bool:
        return getattr(event, "event_type", None) in type_set

    return _filter


def tool_name(*names: str) -> EventFilter:
    """Create a filter that matches specific tool names.

    Only matches ToolUseEvent and ToolCallCompletedEvent types.

    Args:
        *names: Tool names to match (e.g., "Read", "Bash", "Edit")

    Returns:
        A filter function that returns True for matching events.

    Example:
        >>> f = tool_name("Read", "Write")
        >>> f(read_tool_event)  # True
        >>> f(bash_tool_event)  # False
    """
    name_set: Set[str] = set(names)

    def _filter(event: SessionEventType) -> bool:
        # ToolUseEvent has tool_name directly
        if hasattr(event, "tool_name"):
            return event.tool_name in name_set
        # ToolCallCompletedEvent has tool_name property
        if hasattr(event, "tool_call") and hasattr(event.tool_call, "tool_name"):
            return event.tool_call.tool_name in name_set
        return False

    return _filter


def tool_category(*categories: str) -> EventFilter:
    """Create a filter that matches tools by category.

    Categories: bash, file_read, file_write, search, agent, planning, web, interaction

    Only matches ToolUseEvent types.

    Args:
        *categories: Tool categories to match

    Returns:
        A filter function that returns True for matching events.

    Example:
        >>> f = tool_category("file_write", "bash")
        >>> f(edit_tool_event)  # True (file_write category)
        >>> f(read_tool_event)  # False (file_read category)
    """
    category_set: Set[str] = set(categories)

    def _filter(event: SessionEventType) -> bool:
        return getattr(event, "tool_category", None) in category_set

    return _filter


def agent(agent_id: Optional[str] = None) -> EventFilter:
    """Create a filter for agent-related events.

    If agent_id is None, matches any event from an agent (non-main thread).
    If agent_id is specified, matches only events from that specific agent.

    Args:
        agent_id: Specific agent ID to match, or None for any agent

    Returns:
        A filter function that returns True for matching events.

    Example:
        >>> f = agent()  # Any agent
        >>> f(agent_message)  # True
        >>> f(main_thread_message)  # False

        >>> f = agent("agent-abc123")  # Specific agent
        >>> f(event_from_agent_abc123)  # True
    """
    def _filter(event: SessionEventType) -> bool:
        event_agent_id = getattr(event, "agent_id", None)
        if agent_id is None:
            # Match any agent event
            return event_agent_id is not None
        else:
            # Match specific agent
            return event_agent_id == agent_id

    return _filter


def main_thread() -> EventFilter:
    """Create a filter that matches only main thread events (not agents).

    Returns:
        A filter function that returns True for main thread events.

    Example:
        >>> f = main_thread()
        >>> f(main_thread_message)  # True
        >>> f(agent_message)  # False
    """
    def _filter(event: SessionEventType) -> bool:
        return getattr(event, "agent_id", None) is None

    return _filter


def has_error() -> EventFilter:
    """Create a filter that matches error events or tool results with errors.

    Returns:
        A filter function that returns True for error events.

    Example:
        >>> f = has_error()
        >>> f(error_event)  # True
        >>> f(tool_result_with_error)  # True
        >>> f(successful_tool_result)  # False
    """
    def _filter(event: SessionEventType) -> bool:
        # ErrorEvent
        if getattr(event, "event_type", None) == "error":
            return True
        # ToolResultEvent with is_error
        if getattr(event, "is_error", False):
            return True
        # ToolCallCompletedEvent with is_error
        if hasattr(event, "tool_call"):
            return getattr(event.tool_call, "is_error", False)
        return False

    return _filter


def role(role_value: str) -> EventFilter:
    """Create a filter that matches messages by role.

    Args:
        role_value: Role to match ("user" or "assistant")

    Returns:
        A filter function that returns True for matching events.

    Example:
        >>> f = role("user")
        >>> f(user_message_event)  # True
        >>> f(assistant_message_event)  # False
    """
    def _filter(event: SessionEventType) -> bool:
        if not hasattr(event, "message"):
            return False
        msg = event.message
        msg_role = getattr(msg, "role", None)
        if msg_role is None:
            return False
        # Role might be an enum
        role_str = msg_role.value if hasattr(msg_role, "value") else str(msg_role)
        return role_str == role_value

    return _filter


# --- Combinators ---


def and_(*filters: EventFilter) -> EventFilter:
    """Combine filters with AND logic.

    Args:
        *filters: Filter functions to combine

    Returns:
        A filter that returns True only if ALL filters return True.

    Example:
        >>> f = and_(project("my-proj"), tool_category("bash"))
        >>> # True only for bash tools in my-proj
    """
    def _filter(event: SessionEventType) -> bool:
        return all(f(event) for f in filters)

    return _filter


def or_(*filters: EventFilter) -> EventFilter:
    """Combine filters with OR logic.

    Args:
        *filters: Filter functions to combine

    Returns:
        A filter that returns True if ANY filter returns True.

    Example:
        >>> f = or_(tool_name("Read"), tool_name("Write"))
        >>> # True for Read OR Write tools
    """
    def _filter(event: SessionEventType) -> bool:
        return any(f(event) for f in filters)

    return _filter


def not_(filter_fn: EventFilter) -> EventFilter:
    """Negate a filter.

    Args:
        filter_fn: Filter function to negate

    Returns:
        A filter that returns True when the original returns False.

    Example:
        >>> f = not_(has_error())
        >>> # True for non-error events
    """
    def _filter(event: SessionEventType) -> bool:
        return not filter_fn(event)

    return _filter


def always() -> EventFilter:
    """Create a filter that always matches.

    Returns:
        A filter that always returns True.
    """
    return lambda event: True


def never() -> EventFilter:
    """Create a filter that never matches.

    Returns:
        A filter that always returns False.
    """
    return lambda event: False


# --- FilterPipeline Class ---


class FilterPipeline:
    """A pipeline for filtering events and dispatching to handlers.

    FilterPipeline combines a base filter with an event emitter pattern,
    allowing you to register handlers that only receive events matching
    the filter criteria.

    Example:
        # Create pipeline for file operations
        file_ops = FilterPipeline(tool_category("file_read", "file_write"))

        @file_ops.on("tool_use")
        def on_file_tool(event):
            print(f"File operation: {event.tool_name}")

        @file_ops.on_any
        def on_any_file_event(event):
            print(f"Any file event: {event.event_type}")

        # Process events from watcher
        @watcher.on_any
        def route(event):
            file_ops.process(event)
    """

    def __init__(self, *filters: EventFilter):
        """Initialize the pipeline with optional base filters.

        Args:
            *filters: Filter functions to apply. If multiple are provided,
                they are combined with AND logic.
        """
        if len(filters) == 0:
            self._base_filter = always()
        elif len(filters) == 1:
            self._base_filter = filters[0]
        else:
            self._base_filter = and_(*filters)

        # Type-specific handlers
        self._handlers: Dict[str, List[Callable[[SessionEventType], None]]] = (
            defaultdict(list)
        )
        # Wildcard handlers
        self._any_handlers: List[Callable[[SessionEventType], None]] = []

    def matches(self, event: SessionEventType) -> bool:
        """Check if an event matches the pipeline's filter.

        Args:
            event: The event to check

        Returns:
            True if the event matches the filter criteria
        """
        return self._base_filter(event)

    def on(
        self,
        event_type: str,
        handler: Optional[Callable[[SessionEventType], None]] = None,
    ) -> Callable:
        """Register a handler for a specific event type.

        Can be used as a decorator or called directly.

        Args:
            event_type: Event type to handle
            handler: Handler function (optional for decorator use)

        Returns:
            The handler or a decorator function
        """
        if handler is not None:
            self._handlers[event_type].append(handler)
            return handler

        def decorator(fn: Callable[[SessionEventType], None]) -> Callable:
            self._handlers[event_type].append(fn)
            return fn

        return decorator

    def on_any(
        self, handler: Callable[[SessionEventType], None]
    ) -> Callable[[SessionEventType], None]:
        """Register a handler for all matching events.

        Args:
            handler: Handler function

        Returns:
            The handler function
        """
        self._any_handlers.append(handler)
        return handler

    def off(
        self, event_type: str, handler: Callable[[SessionEventType], None]
    ) -> bool:
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

    def off_any(self, handler: Callable[[SessionEventType], None]) -> bool:
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

    def process(self, event: SessionEventType) -> int:
        """Process an event through the pipeline.

        If the event matches the filter, dispatches to registered handlers.

        Args:
            event: The event to process

        Returns:
            Number of handlers that were called
        """
        if not self._base_filter(event):
            return 0

        handlers_called = 0
        event_type = getattr(event, "event_type", None)

        # Call type-specific handlers
        if event_type and event_type in self._handlers:
            for handler in self._handlers[event_type]:
                try:
                    handler(event)
                    handlers_called += 1
                except Exception:
                    pass  # Log in production

        # Call wildcard handlers
        for handler in self._any_handlers:
            try:
                handler(event)
                handlers_called += 1
            except Exception:
                pass

        return handlers_called

    def clear(self, event_type: Optional[str] = None) -> None:
        """Remove handlers.

        Args:
            event_type: Type to clear, or None to clear all handlers
        """
        if event_type is None:
            self._handlers.clear()
            self._any_handlers.clear()
        else:
            self._handlers[event_type].clear()

    @property
    def handler_count(self) -> int:
        """Total number of registered handlers."""
        type_count = sum(len(h) for h in self._handlers.values())
        return type_count + len(self._any_handlers)

    def __repr__(self) -> str:
        return f"FilterPipeline({self.handler_count} handlers)"
