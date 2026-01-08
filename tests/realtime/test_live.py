"""Tests for claude_sessions.realtime.live module."""

from datetime import datetime, timedelta, timezone
import threading
import time

import pytest

from claude_sessions.realtime.live import (
    LiveSession,
    LiveSessionManager,
    LiveSessionConfig,
    RetentionPolicy,
)
from claude_sessions.realtime.events import (
    MessageEvent,
    ToolUseEvent,
    ToolResultEvent,
)
from claude_sessions.models import Message, MessageRole, TextBlock


@pytest.fixture
def sample_datetime():
    return datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)


@pytest.fixture
def live_session():
    """Create a basic LiveSession."""
    return LiveSession(
        session_id="session-123",
        project_slug="test-project"
    )


@pytest.fixture
def live_session_sliding():
    """Create a LiveSession with sliding window retention."""
    config = LiveSessionConfig(
        retention_policy=RetentionPolicy.SLIDING,
        max_messages=5
    )
    return LiveSession(
        session_id="session-123",
        project_slug="test-project",
        config=config
    )


@pytest.fixture
def live_session_none():
    """Create a LiveSession with no message retention."""
    config = LiveSessionConfig(retention_policy=RetentionPolicy.NONE)
    return LiveSession(
        session_id="session-123",
        project_slug="test-project",
        config=config
    )


def make_message_event(
    session_id: str,
    uuid: str,
    role: str = "user",
    text: str = "Hello",
    agent_id: str = None,
    timestamp: datetime = None,
    cwd: str = None,
    git_branch: str = None,
    version: str = None,
) -> MessageEvent:
    """Helper to create MessageEvent for testing."""
    ts = timestamp or datetime.now(timezone.utc)
    message = Message(
        uuid=uuid,
        parent_uuid=None,
        timestamp=ts,
        role=MessageRole(role),
        content=[TextBlock(text=text)],
        session_id=session_id,
        agent_id=agent_id,
        is_sidechain=agent_id is not None,
        cwd=cwd,
        git_branch=git_branch,
        version=version,
    )
    return MessageEvent(
        timestamp=ts,
        session_id=session_id,
        message=message,
        agent_id=agent_id,
    )


def make_tool_use_event(
    session_id: str,
    tool_use_id: str,
    tool_name: str = "Read",
    timestamp: datetime = None,
) -> ToolUseEvent:
    """Helper to create ToolUseEvent for testing."""
    ts = timestamp or datetime.now(timezone.utc)
    message = Message(
        uuid="msg-tool-use",
        parent_uuid=None,
        timestamp=ts,
        role=MessageRole.ASSISTANT,
        content=[],
        session_id=session_id,
    )
    return ToolUseEvent(
        timestamp=ts,
        session_id=session_id,
        tool_name=tool_name,
        tool_category="file_read",
        tool_input={"file_path": "/test.py"},
        tool_use_id=tool_use_id,
        message=message,
    )


def make_tool_result_event(
    session_id: str,
    tool_use_id: str,
    content: str = "result",
    is_error: bool = False,
    timestamp: datetime = None,
) -> ToolResultEvent:
    """Helper to create ToolResultEvent for testing."""
    ts = timestamp or datetime.now(timezone.utc)
    message = Message(
        uuid="msg-tool-result",
        parent_uuid="msg-tool-use",
        timestamp=ts,
        role=MessageRole.USER,
        content=[],
        session_id=session_id,
    )
    return ToolResultEvent(
        timestamp=ts,
        session_id=session_id,
        tool_use_id=tool_use_id,
        content=content,
        is_error=is_error,
        message=message,
    )


class TestLiveSession:
    """Test LiveSession class."""

    def test_initial_state(self, live_session):
        """LiveSession should initialize with correct defaults."""
        assert live_session.session_id == "session-123"
        assert live_session.project_slug == "test-project"
        assert live_session.message_count == 0
        assert live_session.tool_call_count == 0
        assert live_session.pending_tool_count == 0
        assert live_session.completed_tool_count == 0

    def test_handle_message_event(self, live_session):
        """handle_event() should accumulate messages."""
        event = make_message_event("session-123", "msg-1")
        live_session.handle_event(event)

        assert live_session.message_count == 1
        assert len(live_session.messages) == 1

    def test_handle_multiple_messages(self, live_session):
        """Multiple messages should accumulate."""
        for i in range(5):
            event = make_message_event("session-123", f"msg-{i}")
            live_session.handle_event(event)

        assert live_session.message_count == 5
        assert len(live_session.messages) == 5

    def test_metadata_captured_from_first_message(self, live_session):
        """Metadata should be captured from first message."""
        event = make_message_event(
            "session-123",
            "msg-1",
            cwd="/home/user/project",
            git_branch="main",
            version="1.0.0"
        )
        live_session.handle_event(event)

        assert live_session.cwd == "/home/user/project"
        assert live_session.git_branch == "main"
        assert live_session.version == "1.0.0"

    def test_agent_messages_routed_separately(self, live_session):
        """Agent messages should be stored separately."""
        # Main thread message
        main_event = make_message_event("session-123", "msg-1")
        live_session.handle_event(main_event)

        # Agent message
        agent_event = make_message_event(
            "session-123", "msg-2", agent_id="agent-xyz"
        )
        live_session.handle_event(agent_event)

        assert live_session.message_count == 2
        assert len(live_session.messages) == 1  # Main thread only
        assert "agent-xyz" in live_session.agent_ids
        assert len(live_session.get_agent_messages("agent-xyz")) == 1


class TestLiveSessionToolPairing:
    """Test tool call pairing in LiveSession."""

    def test_tool_use_creates_pending(self, live_session):
        """Tool use should create pending entry."""
        event = make_tool_use_event("session-123", "toolu_123")
        live_session.handle_event(event)

        assert live_session.tool_call_count == 1
        assert live_session.pending_tool_count == 1
        assert "toolu_123" in live_session.pending_tool_calls

    def test_tool_result_completes_call(self, live_session):
        """Tool result should complete pending call."""
        # First, tool use
        use_event = make_tool_use_event("session-123", "toolu_123")
        live_session.handle_event(use_event)

        # Then, tool result
        result_event = make_tool_result_event("session-123", "toolu_123")
        completed = live_session.handle_event(result_event)

        assert completed is not None
        assert completed.tool_use.id == "toolu_123"
        assert completed.tool_result.tool_use_id == "toolu_123"
        assert live_session.pending_tool_count == 0
        assert live_session.completed_tool_count == 1

    def test_orphan_tool_result_ignored(self, live_session):
        """Tool result without matching use should return None."""
        result_event = make_tool_result_event("session-123", "toolu_orphan")
        completed = live_session.handle_event(result_event)

        assert completed is None
        assert live_session.pending_tool_count == 0
        assert live_session.completed_tool_count == 0

    def test_multiple_tool_calls(self, live_session):
        """Multiple tool calls should be tracked independently."""
        # Start two tool calls
        live_session.handle_event(make_tool_use_event("session-123", "toolu_1"))
        live_session.handle_event(make_tool_use_event("session-123", "toolu_2"))

        assert live_session.pending_tool_count == 2

        # Complete first
        live_session.handle_event(make_tool_result_event("session-123", "toolu_1"))
        assert live_session.pending_tool_count == 1
        assert live_session.completed_tool_count == 1

        # Complete second
        live_session.handle_event(make_tool_result_event("session-123", "toolu_2"))
        assert live_session.pending_tool_count == 0
        assert live_session.completed_tool_count == 2


class TestLiveSessionRetentionPolicies:
    """Test retention policy behavior."""

    def test_full_retention(self, live_session):
        """FULL retention should keep all messages."""
        for i in range(100):
            event = make_message_event("session-123", f"msg-{i}")
            live_session.handle_event(event)

        assert live_session.message_count == 100
        assert len(live_session.messages) == 100

    def test_sliding_retention(self, live_session_sliding):
        """SLIDING retention should limit messages."""
        for i in range(10):
            event = make_message_event("session-123", f"msg-{i}")
            live_session_sliding.handle_event(event)

        assert live_session_sliding.message_count == 10
        # Only last 5 kept (max_messages=5)
        assert len(live_session_sliding.messages) == 5

    def test_none_retention(self, live_session_none):
        """NONE retention should not store messages."""
        for i in range(10):
            event = make_message_event("session-123", f"msg-{i}")
            live_session_none.handle_event(event)

        assert live_session_none.message_count == 10
        assert len(live_session_none.messages) == 0


class TestLiveSessionProperties:
    """Test LiveSession properties."""

    def test_duration(self, live_session):
        """duration should track time since start."""
        # Duration should be very small right after creation
        assert live_session.duration.total_seconds() < 1

    def test_idle_duration(self, live_session):
        """idle_duration should track time since last activity."""
        assert live_session.idle_duration.total_seconds() < 1

    def test_is_idle(self):
        """is_idle should respect idle_threshold."""
        config = LiveSessionConfig(idle_threshold=timedelta(seconds=0.1))
        session = LiveSession(
            session_id="session-123",
            project_slug="test",
            config=config
        )

        assert session.is_idle is False

        # Wait for idle threshold
        time.sleep(0.15)
        assert session.is_idle is True


class TestLiveSessionConversion:
    """Test LiveSession conversion methods."""

    def test_to_dict(self, live_session):
        """to_dict() should serialize session state."""
        event = make_message_event("session-123", "msg-1")
        live_session.handle_event(event)

        data = live_session.to_dict()

        assert data["session_id"] == "session-123"
        assert data["project_slug"] == "test-project"
        assert data["message_count"] == 1
        assert "start_time" in data
        assert "duration_seconds" in data

    def test_to_session(self, live_session):
        """to_session() should create immutable Session."""
        event = make_message_event("session-123", "msg-1")
        live_session.handle_event(event)

        session = live_session.to_session()

        assert session.session_id == "session-123"
        assert len(session.main_thread.messages) == 1

    def test_to_session_with_none_retention_raises(self, live_session_none):
        """to_session() should raise with NONE retention."""
        with pytest.raises(ValueError, match="NONE retention"):
            live_session_none.to_session()


class TestLiveSessionThreadSafety:
    """Test thread safety of LiveSession."""

    def test_concurrent_message_handling(self, live_session):
        """Concurrent handle_event calls should be safe."""
        def add_messages(count):
            for i in range(count):
                event = make_message_event("session-123", f"msg-{threading.current_thread().name}-{i}")
                live_session.handle_event(event)

        threads = [
            threading.Thread(target=add_messages, args=(100,))
            for _ in range(5)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All messages should be counted
        assert live_session.message_count == 500


class TestLiveSessionManager:
    """Test LiveSessionManager class."""

    def test_get_or_create_new_session(self):
        """get_or_create() should create new session."""
        manager = LiveSessionManager()
        session = manager.get_or_create("session-123", "test-project")

        assert session is not None
        assert session.session_id == "session-123"
        assert manager.get_session("session-123") is session

    def test_get_or_create_existing_session(self):
        """get_or_create() should return existing session."""
        manager = LiveSessionManager()
        session1 = manager.get_or_create("session-123", "test-project")
        session2 = manager.get_or_create("session-123", "test-project")

        assert session1 is session2

    def test_get_session_not_found(self):
        """get_session() should return None for unknown ID."""
        manager = LiveSessionManager()
        assert manager.get_session("unknown") is None

    def test_get_active_sessions(self):
        """get_active_sessions() should return all active sessions."""
        manager = LiveSessionManager()
        manager.get_or_create("session-1", "project")
        manager.get_or_create("session-2", "project")
        manager.get_or_create("session-3", "project")

        sessions = manager.get_active_sessions()
        assert len(sessions) == 3

    def test_on_session_created_callback(self):
        """on_session_created callback should be called."""
        manager = LiveSessionManager()
        created = []

        manager._on_session_created.append(lambda s: created.append(s))
        manager.get_or_create("session-123", "test-project")

        assert len(created) == 1
        assert created[0].session_id == "session-123"

    def test_handle_event_routes_to_session(self):
        """handle_event() should route to correct session."""
        manager = LiveSessionManager()
        event = make_message_event("session-123", "msg-1")

        # Should auto-create session
        manager.get_or_create("session-123", "test-project")
        manager.get_session("session-123").handle_event(event)

        session = manager.get_session("session-123")
        assert session.message_count == 1

    def test_aggregation_properties(self):
        """Aggregation properties should sum across sessions."""
        manager = LiveSessionManager()

        session1 = manager.get_or_create("session-1", "project")
        session2 = manager.get_or_create("session-2", "project")

        # Add messages to each session
        for i in range(5):
            session1.handle_event(make_message_event("session-1", f"msg-1-{i}"))
        for i in range(3):
            session2.handle_event(make_message_event("session-2", f"msg-2-{i}"))

        assert manager.total_message_count == 8

    def test_default_config_used(self):
        """Default config should be applied to new sessions."""
        config = LiveSessionConfig(
            retention_policy=RetentionPolicy.SLIDING,
            max_messages=10
        )
        manager = LiveSessionManager(default_config=config)

        session = manager.get_or_create("session-123", "test-project")

        # Add more than max messages
        for i in range(20):
            session.handle_event(make_message_event("session-123", f"msg-{i}"))

        # Should be limited by sliding window
        assert len(session.messages) == 10
