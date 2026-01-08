"""Tests for claude_sessions.query module."""

import pytest
from datetime import datetime, timedelta, timezone

from claude_sessions.query import (
    # Message filters
    by_role, by_tool_use, by_date_range, by_sidechain, by_model, text_contains,
    # Tool call filters
    tool_by_name, tool_by_category, tool_with_error, tool_by_date_range,
    # Session filters
    session_has_tool, session_has_agents, session_in_date_range,
    session_min_messages, session_in_project,
    # Query class
    SessionQuery,
    DATETIME_MIN,
)
from claude_sessions.models import MessageRole, ToolCall, Message, TextBlock

# Constants from conftest
SAMPLE_SESSION_ID = "abc12345-1234-5678-9abc-def012345678"
SAMPLE_AGENT_ID = "agent-99999999-9999-9999-9999-999999999999"


# ============================================================================
# Message Filter Tests
# ============================================================================

class TestByRole:
    """Tests for by_role filter."""

    def test_matches_user(self, user_message):
        """Should match user messages."""
        f = by_role(MessageRole.USER)
        assert f(user_message) is True

    def test_rejects_wrong_role(self, user_message):
        """Should reject non-matching role."""
        f = by_role(MessageRole.ASSISTANT)
        assert f(user_message) is False


class TestByToolUse:
    """Tests for by_tool_use filter."""

    def test_matches_any_tool(self, assistant_message_with_tool):
        """Without tool_name, should match any tool use."""
        f = by_tool_use()
        assert f(assistant_message_with_tool) is True

    def test_matches_specific_tool(self, assistant_message_with_tool):
        """With tool_name, should match specific tool."""
        f = by_tool_use("Read")
        assert f(assistant_message_with_tool) is True

    def test_rejects_different_tool(self, assistant_message_with_tool):
        """Should reject different tool name."""
        f = by_tool_use("Write")
        assert f(assistant_message_with_tool) is False

    def test_rejects_no_tools(self, user_message):
        """Should reject message without tools."""
        f = by_tool_use()
        assert f(user_message) is False


class TestByDateRange:
    """Tests for by_date_range filter."""

    def test_within_range(self, user_message, sample_datetime):
        """Should match message within range."""
        start = sample_datetime - timedelta(hours=1)
        end = sample_datetime + timedelta(hours=1)
        f = by_date_range(start, end)
        assert f(user_message) is True

    def test_before_start(self, user_message, sample_datetime):
        """Should reject message before start."""
        start = sample_datetime + timedelta(hours=1)
        f = by_date_range(start=start)
        assert f(user_message) is False

    def test_after_end(self, user_message, sample_datetime):
        """Should reject message after end."""
        end = sample_datetime - timedelta(hours=1)
        f = by_date_range(end=end)
        assert f(user_message) is False

    def test_no_bounds(self, user_message):
        """No bounds should match all."""
        f = by_date_range()
        assert f(user_message) is True


class TestBySidechain:
    """Tests for by_sidechain filter."""

    def test_matches_sidechain(self, agent_message):
        """Should match sidechain messages."""
        f = by_sidechain(True)
        assert f(agent_message) is True

    def test_matches_main_thread(self, user_message):
        """Should match main thread messages when is_sidechain=False."""
        f = by_sidechain(False)
        assert f(user_message) is True


class TestByModel:
    """Tests for by_model filter."""

    def test_matches_partial(self, assistant_message):
        """Should match partial model name."""
        f = by_model("sonnet")
        assert f(assistant_message) is True

    def test_case_insensitive(self, assistant_message):
        """Should be case insensitive."""
        f = by_model("SONNET")
        assert f(assistant_message) is True

    def test_no_model(self, user_message):
        """Should return falsy for messages without model."""
        f = by_model("sonnet")
        # Note: returns None for m.model=None due to short-circuit evaluation
        assert not f(user_message)


class TestTextContains:
    """Tests for text_contains filter."""

    def test_matches_text(self, user_message):
        """Should match text pattern."""
        f = text_contains("help")
        assert f(user_message) is True

    def test_case_insensitive(self, user_message):
        """Should be case insensitive by default."""
        f = text_contains("HELP")
        assert f(user_message) is True

    def test_case_sensitive(self, user_message):
        """Should respect case_sensitive flag."""
        f = text_contains("HELP", case_sensitive=True)
        assert f(user_message) is False

    def test_no_match(self, user_message):
        """Should reject non-matching text."""
        f = text_contains("xyz123")
        assert f(user_message) is False


# ============================================================================
# Tool Call Filter Tests
# ============================================================================

class TestToolByName:
    """Tests for tool_by_name filter."""

    @pytest.fixture
    def tool_call(self, assistant_message_with_tool, user_message_with_tool_result):
        """Create a ToolCall."""
        return ToolCall(
            tool_use=assistant_message_with_tool.tool_uses[0],
            tool_result=user_message_with_tool_result.tool_results[0],
            request_message=assistant_message_with_tool,
            response_message=user_message_with_tool_result
        )

    def test_matches_name(self, tool_call):
        """Should match exact tool name."""
        f = tool_by_name("Read")
        assert f(tool_call) is True

    def test_rejects_different(self, tool_call):
        """Should reject different name."""
        f = tool_by_name("Write")
        assert f(tool_call) is False


class TestToolByCategory:
    """Tests for tool_by_category filter."""

    @pytest.fixture
    def tool_call(self, assistant_message_with_tool, user_message_with_tool_result):
        return ToolCall(
            tool_use=assistant_message_with_tool.tool_uses[0],
            tool_result=user_message_with_tool_result.tool_results[0],
            request_message=assistant_message_with_tool,
            response_message=user_message_with_tool_result
        )

    def test_matches_category(self, tool_call):
        """Should match tool category."""
        f = tool_by_category("file_read")
        assert f(tool_call) is True

    def test_rejects_different(self, tool_call):
        """Should reject different category."""
        f = tool_by_category("bash")
        assert f(tool_call) is False


class TestToolWithError:
    """Tests for tool_with_error filter."""

    @pytest.fixture
    def error_tool_call(self, assistant_message_with_tool, sample_datetime, tool_result_error_block):
        msg = Message(
            uuid="error-result",
            parent_uuid=None,
            timestamp=sample_datetime,
            role=MessageRole.USER,
            content=[tool_result_error_block],
            session_id="test"
        )
        return ToolCall(
            tool_use=assistant_message_with_tool.tool_uses[0],
            tool_result=tool_result_error_block,
            request_message=assistant_message_with_tool,
            response_message=msg
        )

    def test_matches_error(self, error_tool_call):
        """Should match error tool calls."""
        f = tool_with_error()
        assert f(error_tool_call) is True


class TestToolByDateRange:
    """Tests for tool_by_date_range filter."""

    @pytest.fixture
    def tool_call(self, assistant_message_with_tool, user_message_with_tool_result):
        return ToolCall(
            tool_use=assistant_message_with_tool.tool_uses[0],
            tool_result=user_message_with_tool_result.tool_results[0],
            request_message=assistant_message_with_tool,
            response_message=user_message_with_tool_result
        )

    def test_within_range(self, tool_call, sample_datetime):
        """Should match within range."""
        start = sample_datetime
        end = sample_datetime + timedelta(hours=1)
        f = tool_by_date_range(start, end)
        assert f(tool_call) is True


# ============================================================================
# Session Filter Tests
# ============================================================================

class TestSessionHasTool:
    """Tests for session_has_tool filter."""

    def test_matches_tool(self, session_with_agents):
        """Should match session with tool."""
        f = session_has_tool("Read")
        assert f(session_with_agents) is True

    def test_rejects_no_tool(self, simple_session):
        """Should reject session without tool."""
        f = session_has_tool("UnknownTool")
        assert f(simple_session) is False


class TestSessionHasAgents:
    """Tests for session_has_agents filter."""

    def test_matches_with_agents(self, session_with_agents):
        """Should match session with agents."""
        f = session_has_agents()
        assert f(session_with_agents) is True

    def test_rejects_no_agents(self, simple_session):
        """Should reject session without agents."""
        f = session_has_agents()
        assert f(simple_session) is False


class TestSessionInDateRange:
    """Tests for session_in_date_range filter."""

    def test_within_range(self, simple_session, sample_datetime):
        """Should match session within range."""
        start = sample_datetime - timedelta(hours=1)
        end = sample_datetime + timedelta(hours=1)
        f = session_in_date_range(start, end)
        assert f(simple_session) is True

    def test_no_start_time(self, empty_session):
        """Should reject session without start_time."""
        f = session_in_date_range()
        assert f(empty_session) is False


class TestSessionMinMessages:
    """Tests for session_min_messages filter."""

    def test_meets_minimum(self, simple_session):
        """Should match session with enough messages."""
        f = session_min_messages(2)
        assert f(simple_session) is True

    def test_below_minimum(self, simple_session):
        """Should reject session below minimum."""
        f = session_min_messages(10)
        assert f(simple_session) is False


class TestSessionInProject:
    """Tests for session_in_project filter."""

    def test_matches_partial(self, simple_session):
        """Should match partial project slug."""
        f = session_in_project("mgm")
        assert f(simple_session) is True

    def test_case_insensitive(self, simple_session):
        """Should be case insensitive."""
        f = session_in_project("MGM")
        assert f(simple_session) is True


# ============================================================================
# SessionQuery Tests
# ============================================================================

class TestSessionQuery:
    """Tests for SessionQuery class."""

    @pytest.fixture
    def sessions(self, multi_session_project):
        """Get sessions from multi-session project."""
        return list(multi_session_project.sessions.values())

    def test_to_list(self, sessions):
        """to_list should return all sessions."""
        query = SessionQuery(sessions)
        result = query.to_list()
        assert len(result) == 5

    def test_first(self, sessions):
        """first should return first session."""
        query = SessionQuery(sessions)
        result = query.first()
        assert result is not None

    def test_first_empty(self):
        """first should return None for empty query."""
        query = SessionQuery([])
        assert query.first() is None

    def test_filter(self, sessions):
        """filter should apply predicate."""
        query = SessionQuery(sessions)
        result = query.filter(lambda s: s.session_id == "session-000").to_list()
        assert len(result) == 1

    def test_by_project(self, sessions):
        """by_project should filter by slug."""
        query = SessionQuery(sessions)
        result = query.by_project("mgm").to_list()
        assert len(result) == 5  # All in same project

    def test_by_date(self, sessions, sample_datetime):
        """by_date should filter by date range."""
        query = SessionQuery(sessions)
        start = sample_datetime + timedelta(days=2)
        result = query.by_date(start=start).to_list()
        assert len(result) == 3

    def test_with_tool(self, sessions):
        """with_tool should filter by tool name."""
        query = SessionQuery(sessions)
        result = query.with_tool("Read").to_list()
        assert len(result) >= 1

    def test_min_messages(self, sessions):
        """min_messages should filter by count."""
        query = SessionQuery(sessions)
        result = query.min_messages(1).to_list()
        assert len(result) == 5

    def test_sort_by_date(self, sessions):
        """sort_by_date should sort by start_time."""
        query = SessionQuery(sessions)
        result = query.sort_by_date().to_list()
        times = [s.start_time for s in result]
        assert times == sorted(times)

    def test_sort_by_date_descending(self, sessions):
        """sort_by_date descending should reverse order."""
        query = SessionQuery(sessions)
        result = query.sort_by_date(descending=True).to_list()
        times = [s.start_time for s in result]
        assert times == sorted(times, reverse=True)

    def test_sort_by_messages(self, sessions):
        """sort_by_messages should sort by message count."""
        query = SessionQuery(sessions)
        result = query.sort_by_messages().to_list()
        counts = [s.message_count for s in result]
        assert counts == sorted(counts, reverse=True)

    def test_limit(self, sessions):
        """limit should restrict results."""
        query = SessionQuery(sessions)
        result = query.limit(2).to_list()
        assert len(result) == 2

    def test_offset(self, sessions):
        """offset should skip results."""
        query = SessionQuery(sessions)
        result = query.offset(3).to_list()
        assert len(result) == 2

    def test_chaining(self, sessions, sample_datetime):
        """Methods should chain."""
        query = SessionQuery(sessions)
        result = (query
            .by_date(start=sample_datetime)
            .min_messages(1)
            .sort_by_date()
            .limit(3)
            .to_list())
        assert len(result) <= 3

    def test_iter(self, sessions):
        """Should be iterable."""
        query = SessionQuery(sessions)
        count = sum(1 for _ in query)
        assert count == 5

    def test_len(self, sessions):
        """__len__ should return count."""
        query = SessionQuery(sessions)
        assert len(query) == 5

    # Aggregation tests
    def test_count(self, sessions):
        """count should return session count."""
        query = SessionQuery(sessions)
        assert query.count() == 5

    def test_total_messages(self, sessions):
        """total_messages should sum all messages."""
        query = SessionQuery(sessions)
        total = query.total_messages()
        assert total == 10  # 2 messages per session * 5 sessions

    def test_total_tool_calls(self, sessions):
        """total_tool_calls should sum all tool calls."""
        query = SessionQuery(sessions)
        total = query.total_tool_calls()
        assert total >= 0

    def test_tool_usage_stats(self, sessions):
        """tool_usage_stats should count by tool name."""
        query = SessionQuery(sessions)
        stats = query.tool_usage_stats()
        assert isinstance(stats, dict)

    def test_tool_category_stats(self, sessions):
        """tool_category_stats should count by category."""
        query = SessionQuery(sessions)
        stats = query.tool_category_stats()
        assert isinstance(stats, dict)

    def test_model_usage_stats(self, sessions):
        """model_usage_stats should count by model."""
        query = SessionQuery(sessions)
        stats = query.model_usage_stats()
        assert isinstance(stats, dict)

    def test_project_stats(self, sessions):
        """project_stats should count by project."""
        query = SessionQuery(sessions)
        stats = query.project_stats()
        assert "-home-mgm-project" in stats

    # Extraction tests
    def test_all_messages(self, sessions):
        """all_messages should extract all messages."""
        query = SessionQuery(sessions)
        msgs = query.all_messages()
        assert len(msgs) == 10

    def test_all_tool_calls(self, sessions):
        """all_tool_calls should extract all tool calls."""
        query = SessionQuery(sessions)
        calls = query.all_tool_calls()
        assert isinstance(calls, list)

    def test_filter_messages(self, sessions):
        """filter_messages should filter by predicate."""
        query = SessionQuery(sessions)
        users = query.filter_messages(by_role(MessageRole.USER))
        assert all(m.role == MessageRole.USER for m in users)

    def test_filter_tool_calls(self, sessions):
        """filter_tool_calls should filter by predicate."""
        query = SessionQuery(sessions)
        reads = query.filter_tool_calls(tool_by_name("Read"))
        assert all(tc.tool_name == "Read" for tc in reads)


class TestSessionQueryEmpty:
    """Tests for SessionQuery with empty session list."""

    def test_empty_to_list(self):
        """Empty query should return empty list."""
        query = SessionQuery([])
        assert query.to_list() == []

    def test_empty_count(self):
        """Empty query should have count 0."""
        query = SessionQuery([])
        assert query.count() == 0

    def test_empty_total_messages(self):
        """Empty query should have 0 total messages."""
        query = SessionQuery([])
        assert query.total_messages() == 0

    def test_empty_tool_usage_stats(self):
        """Empty query should have empty stats."""
        query = SessionQuery([])
        assert query.tool_usage_stats() == {}

    def test_empty_all_messages(self):
        """Empty query should have empty messages list."""
        query = SessionQuery([])
        assert query.all_messages() == []


class TestFilterCombinations:
    """Tests for combining multiple filters."""

    @pytest.mark.parametrize("min_count,expected", [
        (1, 5),
        (2, 5),
        (3, 0),
        (10, 0),
    ])
    def test_min_messages_param(self, multi_session_project, min_count, expected):
        """Parameterized test for min_messages filter."""
        sessions = list(multi_session_project.sessions.values())
        query = SessionQuery(sessions)
        result = query.filter(session_min_messages(min_count)).count()
        assert result == expected
