"""Query and filter API for Claude Code sessions."""

from datetime import datetime, timezone
from typing import Callable, Optional, List, Dict

from .models import Message, MessageRole, ToolCall, Session

# Timezone-aware min datetime for consistent comparisons
DATETIME_MIN = datetime.min.replace(tzinfo=timezone.utc)


# Type aliases for filter predicates
MessageFilter = Callable[[Message], bool]
ToolCallFilter = Callable[[ToolCall], bool]
SessionFilter = Callable[[Session], bool]


# ============================================================================
# Message Filters
# ============================================================================

def by_role(role: MessageRole) -> MessageFilter:
    """Filter messages by role (USER or ASSISTANT)."""
    return lambda m: m.role == role


def by_tool_use(tool_name: Optional[str] = None) -> MessageFilter:
    """Filter messages that contain tool use blocks."""
    def filter_fn(m: Message) -> bool:
        uses = m.tool_uses
        if not uses:
            return False
        if tool_name:
            return any(u.name == tool_name for u in uses)
        return True
    return filter_fn


def by_date_range(
    start: Optional[datetime] = None,
    end: Optional[datetime] = None
) -> MessageFilter:
    """Filter messages within a date range."""
    def filter_fn(m: Message) -> bool:
        if start and m.timestamp < start:
            return False
        if end and m.timestamp > end:
            return False
        return True
    return filter_fn


def by_sidechain(is_sidechain: bool = True) -> MessageFilter:
    """Filter messages by sidechain status."""
    return lambda m: m.is_sidechain == is_sidechain


def by_model(model_name: str) -> MessageFilter:
    """Filter messages by model name (partial match)."""
    return lambda m: m.model and model_name.lower() in m.model.lower()


def text_contains(pattern: str, case_sensitive: bool = False) -> MessageFilter:
    """Filter messages containing text pattern."""
    def filter_fn(m: Message) -> bool:
        text = m.text_content
        if not case_sensitive:
            return pattern.lower() in text.lower()
        return pattern in text
    return filter_fn


# ============================================================================
# Tool Call Filters
# ============================================================================

def tool_by_name(name: str) -> ToolCallFilter:
    """Filter tool calls by exact tool name."""
    return lambda tc: tc.tool_name == name


def tool_by_category(category: str) -> ToolCallFilter:
    """Filter tool calls by category (file_read, bash, search, etc.)."""
    return lambda tc: tc.tool_category == category


def tool_with_error() -> ToolCallFilter:
    """Filter tool calls that resulted in error."""
    return lambda tc: tc.is_error


def tool_by_date_range(
    start: Optional[datetime] = None,
    end: Optional[datetime] = None
) -> ToolCallFilter:
    """Filter tool calls within a date range."""
    def filter_fn(tc: ToolCall) -> bool:
        if start and tc.timestamp < start:
            return False
        if end and tc.timestamp > end:
            return False
        return True
    return filter_fn


# ============================================================================
# Session Filters
# ============================================================================

def session_has_tool(tool_name: str) -> SessionFilter:
    """Filter sessions that used a specific tool."""
    def filter_fn(s: Session) -> bool:
        return any(tc.tool_name == tool_name for tc in s.all_tool_calls)
    return filter_fn


def session_has_agents() -> SessionFilter:
    """Filter sessions that spawned sub-agents."""
    return lambda s: len(s.agents) > 0


def session_in_date_range(
    start: Optional[datetime] = None,
    end: Optional[datetime] = None
) -> SessionFilter:
    """Filter sessions within a date range."""
    def filter_fn(s: Session) -> bool:
        ts = s.start_time
        if ts is None:
            return False
        if start and ts < start:
            return False
        if end and ts > end:
            return False
        return True
    return filter_fn


def session_min_messages(count: int) -> SessionFilter:
    """Filter sessions with at least N messages."""
    return lambda s: s.message_count >= count


def session_in_project(project_slug: str) -> SessionFilter:
    """Filter sessions by project slug (partial match)."""
    return lambda s: project_slug.lower() in s.project_slug.lower()


# ============================================================================
# SessionQuery: Fluent Query Interface
# ============================================================================

class SessionQuery:
    """
    Fluent query interface for sessions.

    Example:
        query = SessionQuery(sessions)
        results = (query
            .by_date(start=datetime(2025, 1, 1))
            .with_tool("Bash")
            .sort_by_date()
            .limit(10)
            .to_list())
    """

    def __init__(self, sessions: List[Session]):
        self._sessions = sessions

    def filter(self, predicate: SessionFilter) -> 'SessionQuery':
        """Apply a custom filter predicate."""
        return SessionQuery([s for s in self._sessions if predicate(s)])

    def by_project(self, project_slug: str) -> 'SessionQuery':
        """Filter by project slug (partial match)."""
        return self.filter(session_in_project(project_slug))

    def by_date(
        self,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None
    ) -> 'SessionQuery':
        """Filter by date range."""
        return self.filter(session_in_date_range(start, end))

    def with_tool(self, tool_name: str) -> 'SessionQuery':
        """Filter sessions that used a specific tool."""
        return self.filter(session_has_tool(tool_name))

    def with_agents(self) -> 'SessionQuery':
        """Filter sessions that spawned sub-agents."""
        return self.filter(session_has_agents())

    def min_messages(self, count: int) -> 'SessionQuery':
        """Filter sessions with at least N messages."""
        return self.filter(session_min_messages(count))

    def sort_by_date(self, descending: bool = False) -> 'SessionQuery':
        """Sort sessions by start time."""
        sorted_sessions = sorted(
            self._sessions,
            key=lambda s: s.start_time or DATETIME_MIN,
            reverse=descending
        )
        return SessionQuery(sorted_sessions)

    def sort_by_messages(self, descending: bool = True) -> 'SessionQuery':
        """Sort sessions by message count."""
        sorted_sessions = sorted(
            self._sessions,
            key=lambda s: s.message_count,
            reverse=descending
        )
        return SessionQuery(sorted_sessions)

    def limit(self, n: int) -> 'SessionQuery':
        """Limit to first N results."""
        return SessionQuery(self._sessions[:n])

    def offset(self, n: int) -> 'SessionQuery':
        """Skip first N results."""
        return SessionQuery(self._sessions[n:])

    def to_list(self) -> List[Session]:
        """Return results as a list."""
        return list(self._sessions)

    def first(self) -> Optional[Session]:
        """Return first result or None."""
        return self._sessions[0] if self._sessions else None

    def __iter__(self):
        return iter(self._sessions)

    def __len__(self) -> int:
        return len(self._sessions)

    # ========================================================================
    # Aggregations
    # ========================================================================

    def count(self) -> int:
        """Count matching sessions."""
        return len(self._sessions)

    def total_messages(self) -> int:
        """Sum of messages across all matching sessions."""
        return sum(s.message_count for s in self._sessions)

    def total_tool_calls(self) -> int:
        """Sum of tool calls across all matching sessions."""
        return sum(s.tool_call_count for s in self._sessions)

    def tool_usage_stats(self) -> Dict[str, int]:
        """Count tool calls by tool name, sorted by frequency."""
        counts: Dict[str, int] = {}
        for session in self._sessions:
            for tc in session.all_tool_calls:
                counts[tc.tool_name] = counts.get(tc.tool_name, 0) + 1
        return dict(sorted(counts.items(), key=lambda x: -x[1]))

    def tool_category_stats(self) -> Dict[str, int]:
        """Count tool calls by category, sorted by frequency."""
        counts: Dict[str, int] = {}
        for session in self._sessions:
            for tc in session.all_tool_calls:
                counts[tc.tool_category] = counts.get(tc.tool_category, 0) + 1
        return dict(sorted(counts.items(), key=lambda x: -x[1]))

    def model_usage_stats(self) -> Dict[str, int]:
        """Count messages by model, sorted by frequency."""
        counts: Dict[str, int] = {}
        for session in self._sessions:
            for msg in session.all_messages:
                if msg.model:
                    counts[msg.model] = counts.get(msg.model, 0) + 1
        return dict(sorted(counts.items(), key=lambda x: -x[1]))

    def project_stats(self) -> Dict[str, int]:
        """Count sessions by project."""
        counts: Dict[str, int] = {}
        for session in self._sessions:
            counts[session.project_slug] = counts.get(session.project_slug, 0) + 1
        return dict(sorted(counts.items(), key=lambda x: -x[1]))

    # ========================================================================
    # Extraction
    # ========================================================================

    def all_messages(self) -> List[Message]:
        """Extract all messages from matching sessions."""
        msgs = []
        for session in self._sessions:
            msgs.extend(session.all_messages)
        return sorted(msgs, key=lambda m: m.timestamp)

    def all_tool_calls(self) -> List[ToolCall]:
        """Extract all tool calls from matching sessions."""
        calls = []
        for session in self._sessions:
            calls.extend(session.all_tool_calls)
        return sorted(calls, key=lambda tc: tc.timestamp)

    def filter_messages(self, predicate: MessageFilter) -> List[Message]:
        """Filter and extract messages matching a predicate."""
        return [m for m in self.all_messages() if predicate(m)]

    def filter_tool_calls(self, predicate: ToolCallFilter) -> List[ToolCall]:
        """Filter and extract tool calls matching a predicate."""
        return [tc for tc in self.all_tool_calls() if predicate(tc)]
