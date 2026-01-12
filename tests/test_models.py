"""Tests for claude_sessions.models module."""

import pytest
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

from claude_sessions.models import (
    MessageRole, ContentBlockType, TOOL_CATEGORIES,
    TextBlock, ToolUseBlock, ToolResultBlock,
    Message, ToolCall, Thread, Agent, Session, Project
)

# Import constants directly - pytest makes conftest available automatically
SAMPLE_SESSION_ID = "abc12345-1234-5678-9abc-def012345678"
SAMPLE_UUID_1 = "msg-11111111-1111-1111-1111-111111111111"
SAMPLE_UUID_2 = "msg-22222222-2222-2222-2222-222222222222"
SAMPLE_UUID_3 = "msg-33333333-3333-3333-3333-333333333333"
SAMPLE_TOOL_USE_ID = "toolu_01ABC123DEF456"
SAMPLE_AGENT_ID = "agent-99999999-9999-9999-9999-999999999999"


class TestTextBlock:
    """Tests for TextBlock frozen dataclass."""

    def test_creation(self, text_block):
        """TextBlock should be created with text."""
        assert text_block.text == "Sample text content"
        assert text_block.type == ContentBlockType.TEXT

    def test_immutability(self, text_block):
        """TextBlock should be immutable (frozen)."""
        with pytest.raises(FrozenInstanceError):
            text_block.text = "modified"

    def test_empty_text(self):
        """TextBlock should allow empty text."""
        block = TextBlock(text="")
        assert block.text == ""


class TestToolUseBlock:
    """Tests for ToolUseBlock frozen dataclass."""

    def test_creation(self, tool_use_block):
        """ToolUseBlock should have id, name, input."""
        assert tool_use_block.id == SAMPLE_TOOL_USE_ID
        assert tool_use_block.name == "Read"
        assert tool_use_block.input == {"file_path": "/home/user/project/main.py"}
        assert tool_use_block.type == ContentBlockType.TOOL_USE

    def test_immutability(self, tool_use_block):
        """ToolUseBlock should be immutable."""
        with pytest.raises(FrozenInstanceError):
            tool_use_block.name = "Write"

    @pytest.mark.parametrize("tool_name,expected_category", [
        ("Read", "file_read"),
        ("Write", "file_write"),
        ("Edit", "file_write"),
        ("NotebookEdit", "file_write"),
        ("Bash", "bash"),
        ("KillShell", "bash"),
        ("Glob", "search"),
        ("Grep", "search"),
        ("Task", "agent"),
        ("TaskOutput", "agent"),
        ("TodoWrite", "planning"),
        ("EnterPlanMode", "planning"),
        ("ExitPlanMode", "planning"),
        ("WebFetch", "web"),
        ("WebSearch", "web"),
        ("AskUserQuestion", "interaction"),
        ("Skill", "other"),
        ("UnknownTool", "other"),
    ])
    def test_tool_category(self, tool_name, expected_category):
        """tool_category property should return correct category."""
        block = ToolUseBlock(id="test", name=tool_name, input={})
        assert block.tool_category == expected_category


class TestToolResultBlock:
    """Tests for ToolResultBlock frozen dataclass."""

    def test_creation_success(self, tool_result_block):
        """ToolResultBlock should have tool_use_id, content, is_error."""
        assert tool_result_block.tool_use_id == SAMPLE_TOOL_USE_ID
        assert "def main()" in tool_result_block.content
        assert tool_result_block.is_error is False

    def test_creation_error(self, tool_result_error_block):
        """ToolResultBlock with error should have is_error=True."""
        assert tool_result_error_block.is_error is True
        assert "Error" in tool_result_error_block.content

    def test_immutability(self, tool_result_block):
        """ToolResultBlock should be immutable."""
        with pytest.raises(FrozenInstanceError):
            tool_result_block.is_error = True

    def test_default_is_error(self):
        """ToolResultBlock should default is_error to False."""
        block = ToolResultBlock(tool_use_id="test", content="result")
        assert block.is_error is False


class TestMessage:
    """Tests for Message dataclass."""

    def test_creation(self, user_message):
        """Message should have all expected attributes."""
        assert user_message.uuid == SAMPLE_UUID_1
        assert user_message.parent_uuid is None
        assert user_message.role == MessageRole.USER
        assert user_message.session_id == SAMPLE_SESSION_ID
        assert user_message.cwd == "/home/user/project"
        assert user_message.git_branch == "main"

    def test_text_content_single_block(self, user_message):
        """text_content should return text from single block."""
        assert user_message.text_content == "Hello, can you help me?"

    def test_text_content_multiple_blocks(self, assistant_message_with_tool):
        """text_content should concatenate text from multiple blocks."""
        assert "Let me read that file." in assistant_message_with_tool.text_content

    def test_text_content_no_text_blocks(self, user_message_with_tool_result):
        """text_content should return empty string if no TextBlocks."""
        assert user_message_with_tool_result.text_content == ""

    def test_tool_uses(self, assistant_message_with_tool):
        """tool_uses should extract ToolUseBlocks."""
        uses = assistant_message_with_tool.tool_uses
        assert len(uses) == 1
        assert uses[0].name == "Read"

    def test_tool_uses_empty(self, user_message):
        """tool_uses should return empty list if no ToolUseBlocks."""
        assert user_message.tool_uses == []

    def test_tool_results(self, user_message_with_tool_result):
        """tool_results should extract ToolResultBlocks."""
        results = user_message_with_tool_result.tool_results
        assert len(results) == 1

    def test_tool_results_empty(self, user_message):
        """tool_results should return empty list if no ToolResultBlocks."""
        assert user_message.tool_results == []

    def test_has_tool_calls_true(self, assistant_message_with_tool):
        """has_tool_calls should return True if message has ToolUseBlocks."""
        assert assistant_message_with_tool.has_tool_calls is True

    def test_has_tool_calls_false(self, user_message):
        """has_tool_calls should return False if no ToolUseBlocks."""
        assert user_message.has_tool_calls is False

    def test_repr(self, user_message):
        """__repr__ should include role, timestamp, and text preview."""
        repr_str = repr(user_message)
        assert "user" in repr_str
        assert "Hello" in repr_str

    def test_repr_truncates_long_text(self, sample_datetime):
        """__repr__ should truncate long text content."""
        long_text = "x" * 100
        msg = Message(
            uuid="test",
            parent_uuid=None,
            timestamp=sample_datetime,
            role=MessageRole.USER,
            content=[TextBlock(text=long_text)],
            session_id="test"
        )
        repr_str = repr(msg)
        assert "..." in repr_str
        assert len(repr_str) < 200


class TestToolCall:
    """Tests for ToolCall dataclass."""

    @pytest.fixture
    def tool_call(self, assistant_message_with_tool, user_message_with_tool_result):
        """Create a ToolCall object."""
        tool_use = assistant_message_with_tool.tool_uses[0]
        tool_result = user_message_with_tool_result.tool_results[0]
        return ToolCall(
            tool_use=tool_use,
            tool_result=tool_result,
            request_message=assistant_message_with_tool,
            response_message=user_message_with_tool_result
        )

    def test_tool_name(self, tool_call):
        """tool_name should delegate to tool_use.name."""
        assert tool_call.tool_name == "Read"

    def test_tool_category(self, tool_call):
        """tool_category should delegate to tool_use.tool_category."""
        assert tool_call.tool_category == "file_read"

    def test_tool_input(self, tool_call):
        """tool_input should delegate to tool_use.input."""
        assert tool_call.tool_input == {"file_path": "/home/user/project/main.py"}

    def test_result_content(self, tool_call):
        """result_content should return tool_result.content."""
        assert "def main()" in tool_call.result_content

    def test_result_content_none(self, assistant_message_with_tool):
        """result_content should return None if no tool_result."""
        tool_use = assistant_message_with_tool.tool_uses[0]
        tc = ToolCall(
            tool_use=tool_use,
            tool_result=None,
            request_message=assistant_message_with_tool,
            response_message=None
        )
        assert tc.result_content is None

    def test_is_error_false(self, tool_call):
        """is_error should return False for successful call."""
        assert tool_call.is_error is False

    def test_is_error_true(self, assistant_message_with_tool, sample_datetime, tool_result_error_block):
        """is_error should return True for error result."""
        msg = Message(
            uuid="test",
            parent_uuid=None,
            timestamp=sample_datetime,
            role=MessageRole.USER,
            content=[tool_result_error_block],
            session_id="test"
        )
        tc = ToolCall(
            tool_use=assistant_message_with_tool.tool_uses[0],
            tool_result=tool_result_error_block,
            request_message=assistant_message_with_tool,
            response_message=msg
        )
        assert tc.is_error is True

    def test_is_error_no_result(self, assistant_message_with_tool):
        """is_error should return False if no tool_result."""
        tc = ToolCall(
            tool_use=assistant_message_with_tool.tool_uses[0],
            tool_result=None,
            request_message=assistant_message_with_tool,
            response_message=None
        )
        assert tc.is_error is False

    def test_timestamp(self, tool_call, assistant_message_with_tool):
        """timestamp should return request_message.timestamp."""
        assert tool_call.timestamp == assistant_message_with_tool.timestamp

    def test_session_id(self, tool_call):
        """session_id should return request_message.session_id."""
        assert tool_call.session_id == SAMPLE_SESSION_ID

    def test_repr(self, tool_call):
        """__repr__ should include tool_name and status."""
        repr_str = repr(tool_call)
        assert "Read" in repr_str
        assert "ok" in repr_str


class TestThread:
    """Tests for Thread dataclass."""

    def test_root_with_messages(self, simple_thread):
        """root should return first message with parent_uuid=None."""
        root = simple_thread.root
        assert root is not None
        assert root.parent_uuid is None

    def test_root_empty_thread(self, empty_thread):
        """root should return None for empty thread."""
        assert empty_thread.root is None

    def test_root_no_parentless_message(self, sample_datetime):
        """root should return first message if no parentless message."""
        msgs = [
            Message(
                uuid="msg-1",
                parent_uuid="parent",  # Has parent
                timestamp=sample_datetime,
                role=MessageRole.USER,
                content=[],
                session_id="test"
            )
        ]
        thread = Thread(messages=msgs)
        assert thread.root == msgs[0]

    def test_tool_calls_extracts_pairs(self, thread_with_tool_calls):
        """tool_calls should pair tool_use with tool_result."""
        calls = thread_with_tool_calls.tool_calls
        assert len(calls) == 1
        assert calls[0].tool_name == "Read"
        assert calls[0].tool_result is not None

    def test_tool_calls_deduplication(self, sample_datetime):
        """tool_calls should deduplicate by tool_use.id."""
        tool_use = ToolUseBlock(id="dup-id", name="Read", input={})
        msgs = [
            Message(
                uuid="msg-1",
                parent_uuid=None,
                timestamp=sample_datetime,
                role=MessageRole.ASSISTANT,
                content=[tool_use],
                session_id="test"
            ),
            Message(
                uuid="msg-2",
                parent_uuid="msg-1",
                timestamp=sample_datetime + timedelta(seconds=1),
                role=MessageRole.ASSISTANT,
                content=[tool_use],  # Duplicate tool_use
                session_id="test"
            ),
        ]
        thread = Thread(messages=msgs)
        calls = thread.tool_calls
        assert len(calls) == 1  # Should only have one

    def test_tool_calls_unmatched(self, sample_datetime):
        """tool_calls should include unmatched tool_use with None result."""
        tool_use = ToolUseBlock(id="unmatched", name="Read", input={})
        msgs = [
            Message(
                uuid="msg-1",
                parent_uuid=None,
                timestamp=sample_datetime,
                role=MessageRole.ASSISTANT,
                content=[tool_use],
                session_id="test"
            )
        ]
        thread = Thread(messages=msgs)
        calls = thread.tool_calls
        assert len(calls) == 1
        assert calls[0].tool_result is None

    def test_tool_calls_sorted_by_timestamp(self, sample_datetime):
        """tool_calls should be sorted by timestamp."""
        # Create tool calls with different timestamps
        msgs = []
        for i in [2, 0, 1]:  # Out of order
            msgs.append(Message(
                uuid=f"msg-{i}",
                parent_uuid=None,
                timestamp=sample_datetime + timedelta(seconds=i),
                role=MessageRole.ASSISTANT,
                content=[ToolUseBlock(id=f"tool-{i}", name="Read", input={})],
                session_id="test"
            ))
        thread = Thread(messages=msgs)
        calls = thread.tool_calls
        # Should be sorted by timestamp
        timestamps = [c.timestamp for c in calls]
        assert timestamps == sorted(timestamps)

    def test_filter_by_role_user(self, simple_thread):
        """filter_by_role should return messages with matching role."""
        users = simple_thread.filter_by_role(MessageRole.USER)
        assert len(users) == 1
        assert users[0].role == MessageRole.USER

    def test_filter_by_role_assistant(self, simple_thread):
        """filter_by_role should return assistant messages."""
        assistants = simple_thread.filter_by_role(MessageRole.ASSISTANT)
        assert len(assistants) == 1
        assert assistants[0].role == MessageRole.ASSISTANT

    def test_filter_by_tool(self, thread_with_tool_calls):
        """filter_by_tool should filter tool calls by name."""
        reads = thread_with_tool_calls.filter_by_tool("Read")
        assert len(reads) == 1
        assert reads[0].tool_name == "Read"

    def test_filter_by_tool_no_matches(self, thread_with_tool_calls):
        """filter_by_tool should return empty for non-matching tool."""
        writes = thread_with_tool_calls.filter_by_tool("Write")
        assert len(writes) == 0

    def test_user_messages(self, simple_thread):
        """user_messages should return all user messages."""
        users = simple_thread.user_messages
        assert len(users) == 1
        assert all(m.role == MessageRole.USER for m in users)

    def test_assistant_messages(self, simple_thread):
        """assistant_messages should return all assistant messages."""
        assistants = simple_thread.assistant_messages
        assert len(assistants) == 1
        assert all(m.role == MessageRole.ASSISTANT for m in assistants)

    def test_len(self, simple_thread, empty_thread):
        """__len__ should return message count."""
        assert len(simple_thread) == 2
        assert len(empty_thread) == 0

    def test_repr(self, simple_thread):
        """__repr__ should include message and tool call counts."""
        repr_str = repr(simple_thread)
        assert "2 messages" in repr_str


class TestAgent:
    """Tests for Agent dataclass."""

    @pytest.fixture
    def agent(self, sample_datetime):
        """Create an Agent object."""
        thread = Thread(messages=[
            Message(
                uuid="agent-msg-1",
                parent_uuid=None,
                timestamp=sample_datetime,
                role=MessageRole.ASSISTANT,
                content=[TextBlock(text="Agent response")],
                session_id=SAMPLE_SESSION_ID,
                agent_id=SAMPLE_AGENT_ID,
                is_sidechain=True
            )
        ])
        return Agent(
            agent_id=SAMPLE_AGENT_ID,
            session_id=SAMPLE_SESSION_ID,
            thread=thread
        )

    def test_start_time(self, agent, sample_datetime):
        """start_time should return thread root timestamp."""
        assert agent.start_time == sample_datetime

    def test_start_time_empty_thread(self):
        """start_time should return None for empty thread."""
        agent = Agent(
            agent_id="test",
            session_id="test",
            thread=Thread(messages=[])
        )
        assert agent.start_time is None

    def test_message_count(self, agent):
        """message_count should return thread length."""
        assert agent.message_count == 1

    def test_tool_calls_delegates(self, agent):
        """tool_calls should delegate to thread.tool_calls."""
        # No tool calls in this agent
        assert agent.tool_calls == []

    def test_repr(self, agent):
        """__repr__ should include agent_id and message count."""
        repr_str = repr(agent)
        assert SAMPLE_AGENT_ID in repr_str
        assert "1 messages" in repr_str


class TestSession:
    """Tests for Session dataclass."""

    def test_start_time(self, simple_session, sample_datetime):
        """start_time should return main_thread root timestamp."""
        assert simple_session.start_time == sample_datetime

    def test_start_time_empty(self, empty_session):
        """start_time should return None for empty session."""
        assert empty_session.start_time is None

    def test_end_time(self, simple_session, sample_datetime):
        """end_time should return max timestamp."""
        # Simple session has 2 messages, 5 seconds apart
        assert simple_session.end_time == sample_datetime + timedelta(seconds=5)

    def test_end_time_empty(self, empty_session):
        """end_time should return None for empty session."""
        assert empty_session.end_time is None

    def test_all_messages_includes_agents(self, session_with_agents):
        """all_messages should include agent messages."""
        all_msgs = session_with_agents.all_messages
        # Main thread (3) + agent (1)
        assert len(all_msgs) == 4

    def test_all_messages_sorted_by_timestamp(self, session_with_agents):
        """all_messages should be sorted by timestamp."""
        msgs = session_with_agents.all_messages
        timestamps = [m.timestamp for m in msgs]
        assert timestamps == sorted(timestamps)

    def test_all_tool_calls_includes_agents(self, session_with_agents):
        """all_tool_calls should include agent tool calls."""
        calls = session_with_agents.all_tool_calls
        # Should include tool call from main thread
        assert len(calls) >= 1

    def test_duration(self, simple_session):
        """duration should be end_time - start_time."""
        assert simple_session.duration == timedelta(seconds=5)

    def test_duration_empty(self, empty_session):
        """duration should return None for empty session."""
        assert empty_session.duration is None

    def test_message_count(self, simple_session):
        """message_count should return all_messages length."""
        assert simple_session.message_count == 2

    def test_tool_call_count(self, session_with_agents):
        """tool_call_count should return all_tool_calls length."""
        count = session_with_agents.tool_call_count
        assert count >= 1

    def test_get_agent(self, session_with_agents):
        """get_agent should return agent by ID."""
        agent = session_with_agents.get_agent(SAMPLE_AGENT_ID)
        assert agent is not None
        assert agent.agent_id == SAMPLE_AGENT_ID

    def test_get_agent_not_found(self, session_with_agents):
        """get_agent should return None for unknown ID."""
        assert session_with_agents.get_agent("unknown") is None

    def test_repr(self, simple_session):
        """__repr__ should include session_id and message count."""
        repr_str = repr(simple_session)
        assert SAMPLE_SESSION_ID[:8] in repr_str
        assert "2 messages" in repr_str

    def test_repr_with_agents(self, session_with_agents):
        """__repr__ should include agent count if present."""
        repr_str = repr(session_with_agents)
        assert "1 agents" in repr_str


class TestProject:
    """Tests for Project dataclass."""

    def test_project_path_decodes_slug(self):
        """project_path should decode slug to path."""
        project = Project(slug="-home-mgm-foo", path="/test", sessions={})
        assert project.project_path == "/home/mgm/foo"

    def test_project_path_invalid_slug(self):
        """project_path should return None for non-standard slug."""
        project = Project(slug="invalid-slug", path="/test", sessions={})
        assert project.project_path is None

    def test_session_count(self, simple_project):
        """session_count should return number of sessions."""
        assert simple_project.session_count == 1

    def test_sessions_by_date_all(self, multi_session_project):
        """sessions_by_date without filters returns all sessions."""
        sessions = multi_session_project.sessions_by_date()
        assert len(sessions) == 5

    def test_sessions_by_date_start_filter(self, multi_session_project, sample_datetime):
        """sessions_by_date with start filter excludes earlier sessions."""
        start = sample_datetime + timedelta(days=2)
        sessions = multi_session_project.sessions_by_date(start=start)
        assert len(sessions) == 3

    def test_sessions_by_date_end_filter(self, multi_session_project, sample_datetime):
        """sessions_by_date with end filter excludes later sessions."""
        end = sample_datetime + timedelta(days=2)
        sessions = multi_session_project.sessions_by_date(end=end)
        assert len(sessions) == 3

    def test_sessions_by_date_sorted(self, multi_session_project):
        """sessions_by_date should return sessions sorted by start_time."""
        sessions = multi_session_project.sessions_by_date()
        start_times = [s.start_time for s in sessions]
        assert start_times == sorted(start_times)

    def test_repr(self, simple_project):
        """__repr__ should include slug and session count."""
        repr_str = repr(simple_project)
        assert "-home-mgm-project" in repr_str
        assert "1 sessions" in repr_str


class TestToolCategories:
    """Tests for TOOL_CATEGORIES constant."""

    def test_all_categories_defined(self):
        """All known tools should have category mappings."""
        expected_tools = [
            "Read", "Write", "Edit", "NotebookEdit",
            "Bash", "KillShell",
            "Glob", "Grep",
            "Task", "TaskOutput",
            "TodoWrite", "EnterPlanMode", "ExitPlanMode",
            "WebFetch", "WebSearch",
            "AskUserQuestion",
            "Skill"
        ]
        for tool in expected_tools:
            assert tool in TOOL_CATEGORIES

    def test_category_values(self):
        """Categories should be expected values."""
        expected_categories = {
            "file_read", "file_write", "bash", "search",
            "agent", "planning", "web", "interaction", "other"
        }
        actual_categories = set(TOOL_CATEGORIES.values())
        assert actual_categories == expected_categories
