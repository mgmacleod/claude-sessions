"""Event types for realtime session monitoring.

This module defines the event dataclasses emitted during realtime session
processing. All events are immutable (frozen dataclasses) and share a
common protocol for type checking.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Literal, Optional, Protocol, Union

from ..models import Message, ToolCall


class SessionEvent(Protocol):
    """Protocol for all session events.

    All concrete event types must have these attributes for consistent
    handling by event emitters and handlers.
    """

    timestamp: datetime
    session_id: str
    event_type: str
    agent_id: Optional[str]


@dataclass(frozen=True)
class MessageEvent:
    """Emitted when a new message is parsed.

    Attributes:
        timestamp: When the message was created
        session_id: The session this message belongs to
        message: The parsed Message object
        agent_id: Agent ID if from a sub-agent, None for main thread
        event_type: Always "message"
    """

    timestamp: datetime
    session_id: str
    message: Message
    agent_id: Optional[str] = None
    event_type: str = field(default="message", repr=False)


@dataclass(frozen=True)
class ToolUseEvent:
    """Emitted when a tool is invoked.

    Attributes:
        timestamp: When the tool was invoked
        session_id: The session this tool use belongs to
        tool_name: Name of the tool (e.g., "Read", "Bash", "Edit")
        tool_category: Category of the tool (e.g., "file_read", "bash")
        tool_input: Tool input parameters (truncated for large values)
        tool_use_id: Unique ID for pairing with ToolResultEvent
        message: The Message containing this tool use
        agent_id: Agent ID if from a sub-agent, None for main thread
        event_type: Always "tool_use"
    """

    timestamp: datetime
    session_id: str
    tool_name: str
    tool_category: str
    tool_input: Dict[str, Any]
    tool_use_id: str
    message: Message
    agent_id: Optional[str] = None
    event_type: str = field(default="tool_use", repr=False)


@dataclass(frozen=True)
class ToolResultEvent:
    """Emitted when a tool result is received.

    Attributes:
        timestamp: When the result was received
        session_id: The session this result belongs to
        tool_use_id: ID linking back to the ToolUseEvent
        content: The tool result content (may be truncated)
        is_error: Whether the tool execution resulted in an error
        message: The Message containing this tool result
        agent_id: Agent ID if from a sub-agent, None for main thread
        event_type: Always "tool_result"
    """

    timestamp: datetime
    session_id: str
    tool_use_id: str
    content: str
    is_error: bool
    message: Message
    agent_id: Optional[str] = None
    event_type: str = field(default="tool_result", repr=False)


@dataclass(frozen=True)
class ErrorEvent:
    """Emitted when a parsing error occurs.

    Attributes:
        timestamp: When the error occurred
        session_id: The session where the error occurred (may be empty)
        error_message: Description of the error
        raw_entry: The raw JSON line that caused the error, if available
        agent_id: Agent ID if from a sub-agent file, None otherwise
        event_type: Always "error"
    """

    timestamp: datetime
    session_id: str
    error_message: str
    raw_entry: Optional[str] = None
    agent_id: Optional[str] = None
    event_type: str = field(default="error", repr=False)


@dataclass(frozen=True)
class SessionStartEvent:
    """Emitted when a new session file is detected.

    Attributes:
        timestamp: When the session was detected
        session_id: UUID of the session (derived from filename)
        project_slug: The project directory name
        file_path: Path to the session file
        cwd: Working directory if known from first message
        agent_id: Always None for session events
        event_type: Always "session_start"
    """

    timestamp: datetime
    session_id: str
    project_slug: str
    file_path: Path
    cwd: Optional[str] = None
    agent_id: Optional[str] = None
    event_type: str = field(default="session_start", repr=False)


@dataclass(frozen=True)
class SessionEndEvent:
    """Emitted when a session is determined to have ended.

    End detection uses heuristics:
    - Idle timeout exceeded
    - File unchanged and no Claude processes
    - Explicit detection (future)

    Attributes:
        timestamp: When the end was detected
        session_id: UUID of the session
        reason: Why session was considered ended
        idle_duration: How long session was idle (if idle timeout)
        message_count: Total messages in session
        tool_count: Total tool calls in session
        agent_id: Always None for session events
        event_type: Always "session_end"
    """

    timestamp: datetime
    session_id: str
    reason: Literal["idle_timeout", "file_unchanged", "process_exit", "manual"]
    idle_duration: Optional[timedelta] = None
    message_count: int = 0
    tool_count: int = 0
    agent_id: Optional[str] = None
    event_type: str = field(default="session_end", repr=False)


@dataclass(frozen=True)
class SessionIdleEvent:
    """Emitted when a session goes idle (may resume later).

    Attributes:
        timestamp: When idle state was detected
        session_id: UUID of the session
        idle_since: When last activity occurred
        agent_id: Always None for session events
        event_type: Always "session_idle"
    """

    timestamp: datetime
    session_id: str
    idle_since: datetime
    agent_id: Optional[str] = None
    event_type: str = field(default="session_idle", repr=False)


@dataclass(frozen=True)
class SessionResumeEvent:
    """Emitted when an idle session becomes active again.

    Attributes:
        timestamp: When activity resumed
        session_id: UUID of the session
        idle_duration: How long session was idle
        agent_id: Always None for session events
        event_type: Always "session_resume"
    """

    timestamp: datetime
    session_id: str
    idle_duration: timedelta
    agent_id: Optional[str] = None
    event_type: str = field(default="session_resume", repr=False)


@dataclass(frozen=True)
class ToolCallCompletedEvent:
    """Emitted when a tool use is matched with its result.

    This event contains the complete ToolCall pair, making it easy
    to analyze completed tool operations. It is emitted by the
    LiveSessionManager when a ToolResultEvent matches a pending
    ToolUseEvent.

    Attributes:
        timestamp: When the pairing was detected
        session_id: UUID of the session
        tool_call: The complete ToolCall with use and result
        agent_id: Agent ID if from a sub-agent, None for main thread
        event_type: Always "tool_call_completed"
    """

    timestamp: datetime
    session_id: str
    tool_call: ToolCall
    agent_id: Optional[str] = None
    event_type: str = field(default="tool_call_completed", repr=False)

    @property
    def tool_name(self) -> str:
        """Name of the tool that was called."""
        return self.tool_call.tool_name

    @property
    def is_error(self) -> bool:
        """Whether the tool execution resulted in an error."""
        return self.tool_call.is_error

    @property
    def duration(self) -> Optional[timedelta]:
        """Time between tool use and result, if both have timestamps."""
        if self.tool_call.request_message and self.tool_call.response_message:
            return (
                self.tool_call.response_message.timestamp
                - self.tool_call.request_message.timestamp
            )
        return None


# Type alias for all event types
SessionEventType = Union[
    MessageEvent,
    ToolUseEvent,
    ToolResultEvent,
    ErrorEvent,
    SessionStartEvent,
    SessionEndEvent,
    SessionIdleEvent,
    SessionResumeEvent,
    ToolCallCompletedEvent,
]


def truncate_tool_input(
    input_dict: Dict[str, Any],
    max_length: int = 1024
) -> Dict[str, Any]:
    """Recursively truncate string values in a tool input dict.

    Large tool inputs (like file contents from Read results) can consume
    significant memory. This function truncates string values that exceed
    the max_length threshold.

    Args:
        input_dict: The tool input dictionary to truncate
        max_length: Maximum length for string values (default 1KB)

    Returns:
        A new dict with truncated string values

    Example:
        >>> truncate_tool_input({"content": "x" * 2000})
        {"content": "xxx...[truncated]"}
    """
    result: Dict[str, Any] = {}

    for key, value in input_dict.items():
        if isinstance(value, str) and len(value) > max_length:
            result[key] = value[:max_length] + "...[truncated]"
        elif isinstance(value, dict):
            result[key] = truncate_tool_input(value, max_length)
        elif isinstance(value, list):
            result[key] = [
                truncate_tool_input(item, max_length) if isinstance(item, dict)
                else (item[:max_length] + "...[truncated]" if isinstance(item, str) and len(item) > max_length else item)
                for item in value
            ]
        else:
            result[key] = value

    return result
