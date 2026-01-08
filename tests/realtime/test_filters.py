"""Tests for claude_sessions.realtime.filters module."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from claude_sessions.realtime.filters import (
    project,
    session,
    session_prefix,
    event_type,
    tool_name,
    tool_category,
    agent,
    main_thread,
    has_error,
    role,
    and_,
    or_,
    not_,
    always,
    never,
    FilterPipeline,
)
from claude_sessions.realtime.events import (
    MessageEvent,
    ToolUseEvent,
    ToolResultEvent,
    ErrorEvent,
    SessionStartEvent,
)
from claude_sessions.models import Message, MessageRole, TextBlock


@pytest.fixture
def sample_datetime():
    return datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)


@pytest.fixture
def user_message_event(sample_datetime):
    """Create a user message event."""
    message = Message(
        uuid="msg-1",
        parent_uuid=None,
        timestamp=sample_datetime,
        role=MessageRole.USER,
        content=[TextBlock(text="Hello")],
        session_id="session-abc-123"
    )
    return MessageEvent(
        timestamp=sample_datetime,
        session_id="session-abc-123",
        message=message
    )


@pytest.fixture
def assistant_message_event(sample_datetime):
    """Create an assistant message event."""
    message = Message(
        uuid="msg-2",
        parent_uuid="msg-1",
        timestamp=sample_datetime,
        role=MessageRole.ASSISTANT,
        content=[TextBlock(text="Hi there!")],
        session_id="session-abc-123"
    )
    return MessageEvent(
        timestamp=sample_datetime,
        session_id="session-abc-123",
        message=message
    )


@pytest.fixture
def agent_message_event(sample_datetime):
    """Create an agent message event."""
    message = Message(
        uuid="msg-3",
        parent_uuid=None,
        timestamp=sample_datetime,
        role=MessageRole.ASSISTANT,
        content=[TextBlock(text="Agent response")],
        session_id="session-abc-123",
        agent_id="agent-xyz"
    )
    return MessageEvent(
        timestamp=sample_datetime,
        session_id="session-abc-123",
        message=message,
        agent_id="agent-xyz"
    )


@pytest.fixture
def read_tool_event(sample_datetime):
    """Create a Read tool use event."""
    message = Message(
        uuid="msg-4",
        parent_uuid=None,
        timestamp=sample_datetime,
        role=MessageRole.ASSISTANT,
        content=[],
        session_id="session-abc-123"
    )
    return ToolUseEvent(
        timestamp=sample_datetime,
        session_id="session-abc-123",
        tool_name="Read",
        tool_category="file_read",
        tool_input={"file_path": "/test.py"},
        tool_use_id="toolu_123",
        message=message
    )


@pytest.fixture
def bash_tool_event(sample_datetime):
    """Create a Bash tool use event."""
    message = Message(
        uuid="msg-5",
        parent_uuid=None,
        timestamp=sample_datetime,
        role=MessageRole.ASSISTANT,
        content=[],
        session_id="session-abc-123"
    )
    return ToolUseEvent(
        timestamp=sample_datetime,
        session_id="session-abc-123",
        tool_name="Bash",
        tool_category="bash",
        tool_input={"command": "ls -la"},
        tool_use_id="toolu_456",
        message=message
    )


@pytest.fixture
def tool_result_success_event(sample_datetime):
    """Create a successful tool result event."""
    message = Message(
        uuid="msg-6",
        parent_uuid="msg-5",
        timestamp=sample_datetime,
        role=MessageRole.USER,
        content=[],
        session_id="session-abc-123"
    )
    return ToolResultEvent(
        timestamp=sample_datetime,
        session_id="session-abc-123",
        tool_use_id="toolu_456",
        content="file1.txt\nfile2.txt",
        is_error=False,
        message=message
    )


@pytest.fixture
def tool_result_error_event(sample_datetime):
    """Create an error tool result event."""
    message = Message(
        uuid="msg-7",
        parent_uuid="msg-5",
        timestamp=sample_datetime,
        role=MessageRole.USER,
        content=[],
        session_id="session-abc-123"
    )
    return ToolResultEvent(
        timestamp=sample_datetime,
        session_id="session-abc-123",
        tool_use_id="toolu_789",
        content="Command failed",
        is_error=True,
        message=message
    )


@pytest.fixture
def error_event(sample_datetime):
    """Create an error event."""
    return ErrorEvent(
        timestamp=sample_datetime,
        session_id="session-abc-123",
        error_message="Parse error"
    )


@pytest.fixture
def session_start_event(sample_datetime):
    """Create a session start event."""
    return SessionStartEvent(
        timestamp=sample_datetime,
        session_id="session-abc-123",
        project_slug="my-project",
        file_path=Path("/test/session.jsonl")
    )


class TestSessionFilter:
    """Test session() filter."""

    def test_matches_exact_session(self, user_message_event):
        """session() should match exact session_id."""
        f = session("session-abc-123")
        assert f(user_message_event) is True

    def test_rejects_different_session(self, user_message_event):
        """session() should reject different session_id."""
        f = session("session-other")
        assert f(user_message_event) is False


class TestSessionPrefixFilter:
    """Test session_prefix() filter."""

    def test_matches_prefix(self, user_message_event):
        """session_prefix() should match session IDs starting with prefix."""
        f = session_prefix("session-abc")
        assert f(user_message_event) is True

    def test_matches_shorter_prefix(self, user_message_event):
        """session_prefix() should match shorter prefixes."""
        f = session_prefix("ses")
        assert f(user_message_event) is True

    def test_rejects_non_matching_prefix(self, user_message_event):
        """session_prefix() should reject non-matching prefixes."""
        f = session_prefix("other")
        assert f(user_message_event) is False


class TestEventTypeFilter:
    """Test event_type() filter."""

    def test_matches_single_type(self, user_message_event):
        """event_type() should match specified type."""
        f = event_type("message")
        assert f(user_message_event) is True

    def test_matches_multiple_types(self, user_message_event, read_tool_event):
        """event_type() should match any of multiple types."""
        f = event_type("message", "tool_use")
        assert f(user_message_event) is True
        assert f(read_tool_event) is True

    def test_rejects_non_matching_type(self, user_message_event):
        """event_type() should reject non-matching types."""
        f = event_type("tool_use", "error")
        assert f(user_message_event) is False


class TestToolNameFilter:
    """Test tool_name() filter."""

    def test_matches_tool_name(self, read_tool_event):
        """tool_name() should match specified tool."""
        f = tool_name("Read")
        assert f(read_tool_event) is True

    def test_matches_multiple_tool_names(self, read_tool_event, bash_tool_event):
        """tool_name() should match any of multiple tools."""
        f = tool_name("Read", "Bash")
        assert f(read_tool_event) is True
        assert f(bash_tool_event) is True

    def test_rejects_non_matching_tool(self, read_tool_event):
        """tool_name() should reject non-matching tools."""
        f = tool_name("Write", "Edit")
        assert f(read_tool_event) is False

    def test_rejects_non_tool_events(self, user_message_event):
        """tool_name() should reject non-tool events."""
        f = tool_name("Read")
        assert f(user_message_event) is False


class TestToolCategoryFilter:
    """Test tool_category() filter."""

    def test_matches_category(self, read_tool_event, bash_tool_event):
        """tool_category() should match specified categories."""
        f = tool_category("file_read")
        assert f(read_tool_event) is True
        assert f(bash_tool_event) is False

    def test_matches_multiple_categories(self, read_tool_event, bash_tool_event):
        """tool_category() should match any of multiple categories."""
        f = tool_category("file_read", "bash")
        assert f(read_tool_event) is True
        assert f(bash_tool_event) is True


class TestAgentFilter:
    """Test agent() filter."""

    def test_matches_any_agent(self, agent_message_event, user_message_event):
        """agent() without args should match any agent event."""
        f = agent()
        assert f(agent_message_event) is True
        assert f(user_message_event) is False

    def test_matches_specific_agent(self, agent_message_event):
        """agent() with ID should match specific agent."""
        f = agent("agent-xyz")
        assert f(agent_message_event) is True

    def test_rejects_different_agent(self, agent_message_event):
        """agent() should reject different agent IDs."""
        f = agent("agent-other")
        assert f(agent_message_event) is False


class TestMainThreadFilter:
    """Test main_thread() filter."""

    def test_matches_main_thread(self, user_message_event):
        """main_thread() should match events without agent_id."""
        f = main_thread()
        assert f(user_message_event) is True

    def test_rejects_agent_events(self, agent_message_event):
        """main_thread() should reject agent events."""
        f = main_thread()
        assert f(agent_message_event) is False


class TestHasErrorFilter:
    """Test has_error() filter."""

    def test_matches_error_event(self, error_event):
        """has_error() should match ErrorEvent."""
        f = has_error()
        assert f(error_event) is True

    def test_matches_tool_result_error(self, tool_result_error_event):
        """has_error() should match tool result with is_error=True."""
        f = has_error()
        assert f(tool_result_error_event) is True

    def test_rejects_successful_tool_result(self, tool_result_success_event):
        """has_error() should reject successful tool results."""
        f = has_error()
        assert f(tool_result_success_event) is False

    def test_rejects_non_error_events(self, user_message_event):
        """has_error() should reject normal message events."""
        f = has_error()
        assert f(user_message_event) is False


class TestRoleFilter:
    """Test role() filter."""

    def test_matches_user_role(self, user_message_event, assistant_message_event):
        """role() should match user messages."""
        f = role("user")
        assert f(user_message_event) is True
        assert f(assistant_message_event) is False

    def test_matches_assistant_role(self, user_message_event, assistant_message_event):
        """role() should match assistant messages."""
        f = role("assistant")
        assert f(user_message_event) is False
        assert f(assistant_message_event) is True


class TestCombinators:
    """Test filter combinators."""

    def test_and_all_true(self, user_message_event):
        """and_() should return True when all filters match."""
        f = and_(
            session("session-abc-123"),
            event_type("message"),
            role("user")
        )
        assert f(user_message_event) is True

    def test_and_one_false(self, user_message_event):
        """and_() should return False when any filter fails."""
        f = and_(
            session("session-abc-123"),
            role("assistant")  # Wrong role
        )
        assert f(user_message_event) is False

    def test_or_one_true(self, user_message_event):
        """or_() should return True when any filter matches."""
        f = or_(
            role("assistant"),  # False
            role("user")        # True
        )
        assert f(user_message_event) is True

    def test_or_all_false(self, user_message_event):
        """or_() should return False when no filters match."""
        f = or_(
            role("assistant"),
            session("other-session")
        )
        assert f(user_message_event) is False

    def test_not_negates(self, user_message_event):
        """not_() should negate a filter."""
        f = not_(role("assistant"))
        assert f(user_message_event) is True

        f = not_(role("user"))
        assert f(user_message_event) is False

    def test_always_matches_all(self, user_message_event, read_tool_event, error_event):
        """always() should match any event."""
        f = always()
        assert f(user_message_event) is True
        assert f(read_tool_event) is True
        assert f(error_event) is True

    def test_never_matches_none(self, user_message_event, read_tool_event, error_event):
        """never() should not match any event."""
        f = never()
        assert f(user_message_event) is False
        assert f(read_tool_event) is False
        assert f(error_event) is False


class TestFilterPipeline:
    """Test FilterPipeline class."""

    def test_pipeline_matches_filter(self, read_tool_event, user_message_event):
        """Pipeline should apply base filter."""
        pipeline = FilterPipeline(tool_category("file_read"))

        assert pipeline.matches(read_tool_event) is True
        assert pipeline.matches(user_message_event) is False

    def test_pipeline_multiple_filters_anded(self, read_tool_event, bash_tool_event):
        """Multiple filters should be ANDed."""
        pipeline = FilterPipeline(
            event_type("tool_use"),
            tool_category("file_read")
        )

        assert pipeline.matches(read_tool_event) is True
        assert pipeline.matches(bash_tool_event) is False

    def test_pipeline_no_filter_matches_all(self, user_message_event, read_tool_event):
        """Pipeline with no filters should match all events."""
        pipeline = FilterPipeline()

        assert pipeline.matches(user_message_event) is True
        assert pipeline.matches(read_tool_event) is True

    def test_on_decorator(self, read_tool_event):
        """on() should work as decorator."""
        pipeline = FilterPipeline(always())
        received = []

        @pipeline.on("tool_use")
        def handler(event):
            received.append(event)

        pipeline.process(read_tool_event)

        assert len(received) == 1
        assert received[0] is read_tool_event

    def test_on_direct_call(self, read_tool_event):
        """on() should work as direct call."""
        pipeline = FilterPipeline(always())
        received = []

        def handler(event):
            received.append(event)

        pipeline.on("tool_use", handler)
        pipeline.process(read_tool_event)

        assert len(received) == 1

    def test_on_any_receives_all(self, user_message_event, read_tool_event):
        """on_any() should receive all matching events."""
        pipeline = FilterPipeline(always())
        received = []

        @pipeline.on_any
        def handler(event):
            received.append(event)

        pipeline.process(user_message_event)
        pipeline.process(read_tool_event)

        assert len(received) == 2

    def test_process_returns_handler_count(self, read_tool_event):
        """process() should return number of handlers called."""
        pipeline = FilterPipeline(always())

        @pipeline.on("tool_use")
        def h1(event):
            pass

        @pipeline.on("tool_use")
        def h2(event):
            pass

        @pipeline.on_any
        def h3(event):
            pass

        count = pipeline.process(read_tool_event)
        assert count == 3

    def test_process_skips_non_matching(self, user_message_event):
        """process() should skip events that don't match filter."""
        pipeline = FilterPipeline(tool_category("file_read"))
        received = []

        @pipeline.on_any
        def handler(event):
            received.append(event)

        count = pipeline.process(user_message_event)

        assert count == 0
        assert len(received) == 0

    def test_off_removes_handler(self, read_tool_event):
        """off() should remove a handler."""
        pipeline = FilterPipeline(always())
        received = []

        def handler(event):
            received.append(event)

        pipeline.on("tool_use", handler)
        result = pipeline.off("tool_use", handler)

        assert result is True
        pipeline.process(read_tool_event)
        assert len(received) == 0

    def test_off_any_removes_handler(self, read_tool_event):
        """off_any() should remove a wildcard handler."""
        pipeline = FilterPipeline(always())
        received = []

        def handler(event):
            received.append(event)

        pipeline.on_any(handler)
        result = pipeline.off_any(handler)

        assert result is True
        pipeline.process(read_tool_event)
        assert len(received) == 0

    def test_clear_specific_type(self, read_tool_event):
        """clear() with type should only clear that type's handlers."""
        pipeline = FilterPipeline(always())

        @pipeline.on("tool_use")
        def h1(event):
            pass

        @pipeline.on("message")
        def h2(event):
            pass

        pipeline.clear("tool_use")

        # tool_use handlers cleared, message handlers remain
        assert pipeline.handler_count == 1

    def test_clear_all(self):
        """clear() without args should clear all handlers."""
        pipeline = FilterPipeline(always())

        @pipeline.on("tool_use")
        def h1(event):
            pass

        @pipeline.on_any
        def h2(event):
            pass

        pipeline.clear()

        assert pipeline.handler_count == 0

    def test_handler_count(self):
        """handler_count should track registered handlers."""
        pipeline = FilterPipeline(always())

        assert pipeline.handler_count == 0

        @pipeline.on("message")
        def h1(event):
            pass

        @pipeline.on("tool_use")
        def h2(event):
            pass

        @pipeline.on_any
        def h3(event):
            pass

        assert pipeline.handler_count == 3

    def test_handler_exception_isolated(self, read_tool_event):
        """Handler exceptions should not affect other handlers."""
        pipeline = FilterPipeline(always())
        received = []

        @pipeline.on("tool_use")
        def bad_handler(event):
            raise ValueError("Handler error")

        @pipeline.on("tool_use")
        def good_handler(event):
            received.append(event)

        # Should not raise
        count = pipeline.process(read_tool_event)

        # Good handler should still be called
        assert len(received) == 1
        # Count reflects only successful handlers
        assert count == 1
