"""Live session state management for realtime monitoring.

This module provides mutable session representations that accumulate
state as events arrive, enabling tool call pairing, agent message
routing, and conversion to immutable Session objects.

Example usage:
    from claude_sessions.realtime import SessionWatcher

    # Enable live sessions
    watcher = SessionWatcher(live_sessions=True)

    @watcher.on("session_end")
    def on_end(event):
        session = watcher.live_sessions.get_session(event.session_id)
        if session:
            # Convert to immutable for export
            immutable = session.to_session()
            print(f"Session had {session.message_count} messages")

    watcher.start()
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from threading import RLock
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from ..models import (
    Message,
    Thread,
    Agent,
    Session,
    ToolUseBlock,
    ToolResultBlock,
    ToolCall,
)
from .events import MessageEvent, ToolUseEvent, ToolResultEvent

if TYPE_CHECKING:
    from .events import SessionEventType


class RetentionPolicy(Enum):
    """Memory management strategy for live session history.

    Attributes:
        FULL: Keep all messages (default). Suitable for short sessions
            or when full history is needed.
        SLIDING: Keep only the last N messages (configurable via
            max_messages). Useful for long-running sessions.
        NONE: Don't store messages at all. Only counters are maintained.
            Events are still emitted but history is not kept.
    """

    FULL = "full"
    SLIDING = "sliding"
    NONE = "none"


@dataclass
class LiveSessionConfig:
    """Configuration for a LiveSession.

    Attributes:
        retention_policy: How to manage message history. Default FULL.
        max_messages: Maximum messages to retain per thread when using
            SLIDING retention policy. Default 1000.
        idle_threshold: Duration of inactivity before session is
            considered idle. Default 2 minutes.
    """

    retention_policy: RetentionPolicy = RetentionPolicy.FULL
    max_messages: int = 1000
    idle_threshold: timedelta = field(
        default_factory=lambda: timedelta(minutes=2)
    )


class LiveSession:
    """Mutable representation of an in-progress session.

    Accumulates messages and tool calls as events arrive. Thread-safe
    for access from background watcher thread.

    Lifecycle:
        1. Created when session file is discovered
        2. Updated via handle_event() as new events arrive
        3. Converted to immutable Session via to_session()
        4. Optionally pruned when ended/idle

    Attributes:
        session_id: UUID of the session
        project_slug: Project directory name
        start_time: When the session was first seen
        last_activity: When the last event was processed
        cwd: Working directory from first message
        git_branch: Git branch from first message
        version: Claude Code version from first message
        slug: Session slug from first message

    Example:
        session = LiveSession("abc-123", "my-project")

        # Process events
        for event in event_stream:
            completed = session.handle_event(event)
            if completed:
                print(f"Tool call completed: {completed.tool_name}")

        # Convert to immutable when done
        immutable = session.to_session()
    """

    def __init__(
        self,
        session_id: str,
        project_slug: str,
        config: Optional[LiveSessionConfig] = None,
        cwd: Optional[str] = None,
    ):
        """Initialize a new live session.

        Args:
            session_id: UUID of the session
            project_slug: Project directory name
            config: Optional configuration (uses defaults if None)
            cwd: Optional working directory
        """
        self._lock = RLock()
        self._config = config or LiveSessionConfig()

        # Identity
        self.session_id = session_id
        self.project_slug = project_slug

        # Message storage
        self._main_messages: List[Message] = []
        self._agent_messages: Dict[str, List[Message]] = {}

        # Tool call tracking
        self._pending_tool_calls: Dict[str, ToolUseBlock] = {}
        self._pending_tool_messages: Dict[str, Message] = {}
        self._completed_tool_calls: List[ToolCall] = []

        # Timestamps
        self.start_time: datetime = datetime.now(timezone.utc)
        self.last_activity: datetime = datetime.now(timezone.utc)

        # Metadata from first message
        self.cwd: Optional[str] = cwd
        self.git_branch: Optional[str] = None
        self.version: Optional[str] = None
        self.slug: Optional[str] = None

        # Counters (maintained even with NONE retention)
        self._message_count: int = 0
        self._tool_call_count: int = 0

    # --- Event Handling ---

    def handle_event(self, event: "SessionEventType") -> Optional[ToolCall]:
        """Process an incoming event and update state.

        Routes the event to the appropriate handler based on event_type.
        For tool_result events, returns the completed ToolCall if the
        result matched a pending tool use.

        Args:
            event: A MessageEvent, ToolUseEvent, ToolResultEvent, or
                other session event.

        Returns:
            Completed ToolCall if a tool result matched a pending use,
            None otherwise.
        """
        with self._lock:
            self.last_activity = datetime.now(timezone.utc)

            event_type = getattr(event, "event_type", None)

            if event_type == "message":
                self._handle_message(event)  # type: ignore
                return None
            elif event_type == "tool_use":
                self._handle_tool_use(event)  # type: ignore
                return None
            elif event_type == "tool_result":
                return self._handle_tool_result(event)  # type: ignore

        return None

    def _handle_message(self, event: MessageEvent) -> None:
        """Store a message in the appropriate thread."""
        message = event.message
        self._message_count += 1

        # Capture metadata from first message
        if self._message_count == 1:
            self.cwd = message.cwd or self.cwd
            self.git_branch = message.git_branch
            self.version = message.version
            self.slug = message.slug

        # Skip storage if NONE retention
        if self._config.retention_policy == RetentionPolicy.NONE:
            return

        # Route to correct message list
        if message.agent_id and message.is_sidechain:
            if message.agent_id not in self._agent_messages:
                self._agent_messages[message.agent_id] = []
            self._agent_messages[message.agent_id].append(message)
        else:
            self._main_messages.append(message)

        # Apply sliding window if configured
        if self._config.retention_policy == RetentionPolicy.SLIDING:
            self._enforce_sliding_window()

    def _handle_tool_use(self, event: ToolUseEvent) -> None:
        """Track a pending tool call."""
        self._tool_call_count += 1

        # Create ToolUseBlock for tracking
        tool_use = ToolUseBlock(
            id=event.tool_use_id,
            name=event.tool_name,
            input=event.tool_input,
        )

        self._pending_tool_calls[event.tool_use_id] = tool_use
        self._pending_tool_messages[event.tool_use_id] = event.message

    def _handle_tool_result(self, event: ToolResultEvent) -> Optional[ToolCall]:
        """Match a tool result with its pending use, creating a ToolCall."""
        tool_use_id = event.tool_use_id

        if tool_use_id not in self._pending_tool_calls:
            # Orphan result - tool use not seen
            # (might be from before we started watching)
            return None

        # Pop the pending call
        tool_use = self._pending_tool_calls.pop(tool_use_id)
        request_message = self._pending_tool_messages.pop(tool_use_id)

        # Create result block
        tool_result = ToolResultBlock(
            tool_use_id=tool_use_id,
            content=event.content,
            is_error=event.is_error,
        )

        # Create completed ToolCall
        tool_call = ToolCall(
            tool_use=tool_use,
            tool_result=tool_result,
            request_message=request_message,
            response_message=event.message,
        )

        self._completed_tool_calls.append(tool_call)
        return tool_call

    def _enforce_sliding_window(self) -> None:
        """Remove oldest messages if exceeding max_messages."""
        max_msgs = self._config.max_messages

        # Trim main thread
        if len(self._main_messages) > max_msgs:
            self._main_messages = self._main_messages[-max_msgs:]

        # Trim each agent thread
        for agent_id in self._agent_messages:
            if len(self._agent_messages[agent_id]) > max_msgs:
                self._agent_messages[agent_id] = self._agent_messages[
                    agent_id
                ][-max_msgs:]

    # --- Properties ---

    @property
    def message_count(self) -> int:
        """Total messages seen (accurate even with NONE retention)."""
        return self._message_count

    @property
    def tool_call_count(self) -> int:
        """Total tool uses seen."""
        return self._tool_call_count

    @property
    def pending_tool_count(self) -> int:
        """Number of tool calls awaiting results."""
        with self._lock:
            return len(self._pending_tool_calls)

    @property
    def completed_tool_count(self) -> int:
        """Number of matched tool call pairs."""
        with self._lock:
            return len(self._completed_tool_calls)

    @property
    def duration(self) -> timedelta:
        """Time since session started."""
        return datetime.now(timezone.utc) - self.start_time

    @property
    def idle_duration(self) -> timedelta:
        """Time since last activity."""
        return datetime.now(timezone.utc) - self.last_activity

    @property
    def is_idle(self) -> bool:
        """True if idle longer than configured threshold."""
        return self.idle_duration > self._config.idle_threshold

    @property
    def messages(self) -> List[Message]:
        """Main thread messages (copy for thread safety)."""
        with self._lock:
            return list(self._main_messages)

    @property
    def agent_ids(self) -> List[str]:
        """List of agent IDs with messages."""
        with self._lock:
            return list(self._agent_messages.keys())

    def get_agent_messages(self, agent_id: str) -> List[Message]:
        """Get messages for a specific agent.

        Args:
            agent_id: The agent ID to look up

        Returns:
            List of messages for that agent (copy for thread safety)
        """
        with self._lock:
            return list(self._agent_messages.get(agent_id, []))

    @property
    def pending_tool_calls(self) -> Dict[str, ToolUseBlock]:
        """Tool calls awaiting results (copy for thread safety)."""
        with self._lock:
            return dict(self._pending_tool_calls)

    @property
    def completed_tool_calls(self) -> List[ToolCall]:
        """Matched tool call pairs (copy for thread safety)."""
        with self._lock:
            return list(self._completed_tool_calls)

    # --- Conversion ---

    def to_session(self) -> Session:
        """Convert to an immutable Session for analysis/export.

        Uses the same thread-building logic as the batch parser.
        The resulting Session can be used with the query and export
        APIs.

        Returns:
            Immutable Session object with main_thread and agents.

        Raises:
            ValueError: If retention policy is NONE (no messages stored)
        """
        from ..parser import build_thread

        with self._lock:
            if self._config.retention_policy == RetentionPolicy.NONE:
                raise ValueError(
                    "Cannot convert to Session with NONE retention policy "
                    "(no messages stored)"
                )

            # Build main thread
            main_thread = build_thread(list(self._main_messages))

            # Build agent objects
            agents = {}
            for agent_id, msgs in self._agent_messages.items():
                thread = build_thread(list(msgs))
                agents[agent_id] = Agent(
                    agent_id=agent_id,
                    session_id=self.session_id,
                    thread=thread,
                )

            return Session(
                session_id=self.session_id,
                project_slug=self.project_slug,
                main_thread=main_thread,
                agents=agents,
                cwd=self.cwd,
                git_branch=self.git_branch,
                version=self.version,
                slug=self.slug,
            )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary for JSON export.

        Returns:
            Dictionary with session state suitable for JSON serialization.
        """
        with self._lock:
            return {
                "session_id": self.session_id,
                "project_slug": self.project_slug,
                "message_count": self._message_count,
                "tool_call_count": self._tool_call_count,
                "pending_tool_calls": len(self._pending_tool_calls),
                "completed_tool_calls": len(self._completed_tool_calls),
                "agent_count": len(self._agent_messages),
                "start_time": self.start_time.isoformat(),
                "last_activity": self.last_activity.isoformat(),
                "duration_seconds": self.duration.total_seconds(),
                "is_idle": self.is_idle,
                "cwd": self.cwd,
            }

    def __repr__(self) -> str:
        agents = (
            f", {len(self._agent_messages)} agents"
            if self._agent_messages
            else ""
        )
        return (
            f"LiveSession({self.session_id[:8]}..., "
            f"{self._message_count} msgs, "
            f"{self._tool_call_count} tools{agents})"
        )


class LiveSessionManager:
    """Manages a collection of live sessions.

    Can operate standalone (consuming events directly) or integrated
    with SessionWatcher. Thread-safe for concurrent access.

    Attributes:
        active_session_count: Number of currently active sessions
        total_message_count: Sum of messages across all active sessions
        total_tool_call_count: Sum of tool calls across all sessions

    Example (standalone):
        manager = LiveSessionManager()

        @watcher.on_any
        def route(event):
            manager.handle_event(event)

        # Access sessions
        for session in manager.get_active_sessions():
            print(f"{session.session_id}: {session.message_count} msgs")

    Example (with SessionWatcher):
        watcher = SessionWatcher(live_sessions=True)
        # Manager is available as watcher.live_sessions
    """

    def __init__(
        self,
        default_config: Optional[LiveSessionConfig] = None,
    ):
        """Initialize the manager.

        Args:
            default_config: Default configuration for new sessions.
                Uses LiveSessionConfig defaults if None.
        """
        self._lock = RLock()
        self._sessions: Dict[str, LiveSession] = {}
        self._ended_sessions: Dict[str, LiveSession] = {}
        self._default_config = default_config or LiveSessionConfig()

        # Callbacks for session lifecycle
        self._on_session_created: List[Callable[[LiveSession], None]] = []
        self._on_tool_call_completed: List[
            Callable[[LiveSession, ToolCall], None]
        ] = []

    def get_or_create(
        self,
        session_id: str,
        project_slug: str = "",
        config: Optional[LiveSessionConfig] = None,
    ) -> LiveSession:
        """Get existing session or create a new one.

        Args:
            session_id: Session UUID
            project_slug: Project directory name
            config: Optional custom config (uses default if None)

        Returns:
            The LiveSession instance
        """
        with self._lock:
            if session_id not in self._sessions:
                session = LiveSession(
                    session_id=session_id,
                    project_slug=project_slug,
                    config=config or self._default_config,
                )
                self._sessions[session_id] = session

                # Notify callbacks
                for callback in self._on_session_created:
                    try:
                        callback(session)
                    except Exception:
                        pass

            return self._sessions[session_id]

    def get_session(self, session_id: str) -> Optional[LiveSession]:
        """Get a session by ID.

        Args:
            session_id: Session UUID

        Returns:
            LiveSession if exists, None otherwise
        """
        with self._lock:
            return self._sessions.get(session_id)

    def get_active_sessions(self) -> List[LiveSession]:
        """Get all active (non-ended) sessions.

        Returns:
            List of active LiveSession objects
        """
        with self._lock:
            return list(self._sessions.values())

    def get_idle_sessions(self) -> List[LiveSession]:
        """Get sessions that are currently idle.

        Returns:
            List of LiveSession objects that are past their idle threshold
        """
        with self._lock:
            return [s for s in self._sessions.values() if s.is_idle]

    def handle_event(self, event: "SessionEventType") -> Optional[ToolCall]:
        """Route an event to the appropriate session.

        This is the main integration point. Call this for each
        event from SessionWatcher to update live state.

        Args:
            event: Any session event (MessageEvent, ToolUseEvent, etc.)

        Returns:
            Completed ToolCall if a tool result matched a pending use,
            None otherwise.
        """
        session_id = getattr(event, "session_id", None)
        if not session_id:
            return None

        event_type = getattr(event, "event_type", None)

        # Handle session lifecycle events
        if event_type == "session_start":
            project_slug = getattr(event, "project_slug", "")
            self.get_or_create(session_id, project_slug)
            return None

        if event_type == "session_end":
            self.end_session(session_id)
            return None

        # Route to session for state update
        session = self.get_session(session_id)
        if session is None:
            # Session not yet created - auto-create for late-joining
            session = self.get_or_create(session_id)

        # Let session handle the event
        completed_tool_call = session.handle_event(event)

        # Notify if tool call completed
        if completed_tool_call:
            for callback in self._on_tool_call_completed:
                try:
                    callback(session, completed_tool_call)
                except Exception:
                    pass

        return completed_tool_call

    def end_session(self, session_id: str) -> Optional[LiveSession]:
        """Mark a session as ended and archive it.

        Moves the session from active to ended state. The session
        remains accessible via get_ended_session() until cleared.

        Args:
            session_id: Session to end

        Returns:
            The ended session if it existed
        """
        with self._lock:
            session = self._sessions.pop(session_id, None)
            if session:
                self._ended_sessions[session_id] = session
            return session

    def get_ended_session(self, session_id: str) -> Optional[LiveSession]:
        """Get an ended session by ID.

        Args:
            session_id: Session UUID

        Returns:
            LiveSession if in ended state, None otherwise
        """
        with self._lock:
            return self._ended_sessions.get(session_id)

    def prune_idle(
        self, threshold: Optional[timedelta] = None
    ) -> List[str]:
        """Remove sessions that have been idle beyond threshold.

        Moves idle sessions to ended state.

        Args:
            threshold: Idle duration to trigger pruning. Uses each
                session's configured threshold if None.

        Returns:
            List of pruned session IDs
        """
        with self._lock:
            pruned = []
            for session_id, session in list(self._sessions.items()):
                idle_threshold = threshold or session._config.idle_threshold
                if session.idle_duration > idle_threshold:
                    self._sessions.pop(session_id)
                    self._ended_sessions[session_id] = session
                    pruned.append(session_id)
            return pruned

    def clear_ended(self) -> int:
        """Clear all ended sessions from memory.

        Returns:
            Number of sessions cleared
        """
        with self._lock:
            count = len(self._ended_sessions)
            self._ended_sessions.clear()
            return count

    # --- Callbacks ---

    def on_session_created(
        self, callback: Callable[[LiveSession], None]
    ) -> None:
        """Register callback for new session creation.

        Args:
            callback: Function called with the new LiveSession
        """
        self._on_session_created.append(callback)

    def on_tool_call_completed(
        self,
        callback: Callable[[LiveSession, ToolCall], None],
    ) -> None:
        """Register callback for completed tool calls.

        Called when a ToolResultEvent is matched with its ToolUseEvent.

        Args:
            callback: Function called with (session, tool_call)
        """
        self._on_tool_call_completed.append(callback)

    # --- Aggregation ---

    @property
    def total_message_count(self) -> int:
        """Total messages across all active sessions."""
        with self._lock:
            return sum(s.message_count for s in self._sessions.values())

    @property
    def total_tool_call_count(self) -> int:
        """Total tool calls across all active sessions."""
        with self._lock:
            return sum(s.tool_call_count for s in self._sessions.values())

    @property
    def active_session_count(self) -> int:
        """Number of active sessions."""
        with self._lock:
            return len(self._sessions)

    @property
    def ended_session_count(self) -> int:
        """Number of ended sessions still in memory."""
        with self._lock:
            return len(self._ended_sessions)

    def __len__(self) -> int:
        return self.active_session_count

    def __repr__(self) -> str:
        return (
            f"LiveSessionManager("
            f"{len(self._sessions)} active, "
            f"{len(self._ended_sessions)} ended)"
        )
