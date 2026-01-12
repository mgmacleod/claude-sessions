"""Tests for claude_sessions.export module."""

import json
import pytest
from pathlib import Path

from claude_sessions.export import (
    # Markdown
    message_to_markdown,
    thread_to_markdown,
    session_to_markdown,
    export_session_markdown,
    # DataFrame (conditional)
    sessions_to_dataframe,
    messages_to_dataframe,
    tool_calls_to_dataframe,
    bash_commands_to_dataframe,
    file_operations_to_dataframe,
    # JSON
    content_block_to_dict,
    message_to_dict,
    session_to_dict,
    tool_call_to_dict,
    export_sessions_json,
    export_sessions_jsonl,
    export_tool_calls_json,
)
from claude_sessions.models import (
    TextBlock, ToolUseBlock, ToolResultBlock, ToolCall, Message, MessageRole
)

# Constants from conftest
SAMPLE_SESSION_ID = "abc12345-1234-5678-9abc-def012345678"
SAMPLE_AGENT_ID = "agent-99999999-9999-9999-9999-999999999999"


# ============================================================================
# Markdown Export Tests
# ============================================================================

class TestMessageToMarkdown:
    """Tests for message_to_markdown function."""

    def test_user_message(self, user_message):
        """Should format user message with role label."""
        md = message_to_markdown(user_message)
        assert "### User" in md
        assert "Hello" in md

    def test_assistant_message_with_model(self, assistant_message):
        """Should include short model name."""
        md = message_to_markdown(assistant_message)
        assert "### Assistant" in md
        assert "sonnet" in md.lower()

    def test_tool_use_formatting(self, assistant_message_with_tool):
        """Should format tool use blocks."""
        md = message_to_markdown(assistant_message_with_tool, include_tools=True)
        assert "Read" in md
        assert "file_path" in md or "/home/user/project/main.py" in md

    def test_tool_result_formatting(self, user_message_with_tool_result):
        """Should format tool result blocks."""
        md = message_to_markdown(user_message_with_tool_result, include_tools=True)
        assert "Result" in md

    def test_exclude_tools(self, assistant_message_with_tool):
        """include_tools=False should hide tools."""
        md = message_to_markdown(assistant_message_with_tool, include_tools=False)
        assert "Read" not in md or "Let me read" in md  # Only text, not tool block

    def test_include_metadata(self, user_message):
        """include_metadata should show cwd and branch."""
        md = message_to_markdown(user_message, include_metadata=True)
        assert "/home/user/project" in md
        assert "main" in md

    def test_agent_label(self, agent_message):
        """Agent messages should have agent label."""
        md = message_to_markdown(agent_message)
        assert "Agent:" in md


class TestThreadToMarkdown:
    """Tests for thread_to_markdown function."""

    def test_separates_messages(self, simple_thread):
        """Messages should be separated by ---."""
        md = thread_to_markdown(simple_thread.messages)
        assert "---" in md

    def test_includes_all_messages(self, simple_thread):
        """Should include all messages."""
        md = thread_to_markdown(simple_thread.messages)
        assert "User" in md
        assert "Assistant" in md


class TestSessionToMarkdown:
    """Tests for session_to_markdown function."""

    def test_header(self, simple_session):
        """Should have session header."""
        md = session_to_markdown(simple_session)
        assert "# Session:" in md

    def test_metadata_table(self, simple_session):
        """Should have metadata table."""
        md = session_to_markdown(simple_session)
        assert "| Property | Value |" in md
        assert "Messages" in md

    def test_includes_agents(self, session_with_agents):
        """Should include agent section."""
        md = session_to_markdown(session_with_agents, include_agents=True)
        assert "Sub-Agents" in md

    def test_exclude_agents(self, session_with_agents):
        """include_agents=False should hide agent conversation details."""
        md = session_to_markdown(session_with_agents, include_agents=False)
        # The "## Sub-Agents" section should not appear
        assert "## Sub-Agents" not in md
        # But the count in metadata table may still show
        # (the include_agents flag controls the detailed section)


class TestExportSessionMarkdown:
    """Tests for export_session_markdown function."""

    def test_writes_file(self, simple_session, tmp_path):
        """Should write markdown to file."""
        path = tmp_path / "session.md"
        export_session_markdown(simple_session, path)
        assert path.exists()
        content = path.read_text()
        assert "# Session:" in content


# ============================================================================
# DataFrame Export Tests
# ============================================================================

class TestSessionsToDataframe:
    """Tests for sessions_to_dataframe function."""

    @pytest.fixture
    def skip_if_no_pandas(self):
        """Skip if pandas not installed."""
        pytest.importorskip("pandas")

    def test_returns_dataframe(self, skip_if_no_pandas, simple_session):
        """Should return pandas DataFrame."""
        import pandas as pd
        df = sessions_to_dataframe([simple_session])
        assert isinstance(df, pd.DataFrame)

    def test_columns(self, skip_if_no_pandas, simple_session):
        """Should have expected columns."""
        df = sessions_to_dataframe([simple_session])
        assert "session_id" in df.columns
        assert "message_count" in df.columns
        assert "tool_call_count" in df.columns

    def test_empty_list(self, skip_if_no_pandas):
        """Empty list should return empty DataFrame."""
        df = sessions_to_dataframe([])
        assert len(df) == 0


class TestMessagesToDataframe:
    """Tests for messages_to_dataframe function."""

    @pytest.fixture
    def skip_if_no_pandas(self):
        pytest.importorskip("pandas")

    def test_returns_dataframe(self, skip_if_no_pandas, user_message):
        """Should return pandas DataFrame."""
        import pandas as pd
        df = messages_to_dataframe([user_message])
        assert isinstance(df, pd.DataFrame)

    def test_columns(self, skip_if_no_pandas, user_message):
        """Should have expected columns."""
        df = messages_to_dataframe([user_message])
        assert "uuid" in df.columns
        assert "role" in df.columns
        assert "timestamp" in df.columns


class TestToolCallsToDataframe:
    """Tests for tool_calls_to_dataframe function."""

    @pytest.fixture
    def skip_if_no_pandas(self):
        pytest.importorskip("pandas")

    @pytest.fixture
    def tool_call(self, assistant_message_with_tool, user_message_with_tool_result):
        return ToolCall(
            tool_use=assistant_message_with_tool.tool_uses[0],
            tool_result=user_message_with_tool_result.tool_results[0],
            request_message=assistant_message_with_tool,
            response_message=user_message_with_tool_result
        )

    def test_returns_dataframe(self, skip_if_no_pandas, tool_call):
        """Should return pandas DataFrame."""
        import pandas as pd
        df = tool_calls_to_dataframe([tool_call])
        assert isinstance(df, pd.DataFrame)

    def test_columns(self, skip_if_no_pandas, tool_call):
        """Should have expected columns."""
        df = tool_calls_to_dataframe([tool_call])
        assert "tool_name" in df.columns
        assert "tool_category" in df.columns


class TestBashCommandsToDataframe:
    """Tests for bash_commands_to_dataframe function."""

    @pytest.fixture
    def skip_if_no_pandas(self):
        pytest.importorskip("pandas")

    @pytest.fixture
    def bash_tool_call(self, sample_datetime):
        tool_use = ToolUseBlock(id="bash-1", name="Bash", input={"command": "ls -la"})
        tool_result = ToolResultBlock(tool_use_id="bash-1", content="file1\nfile2")
        msg1 = Message(uuid="m1", parent_uuid=None, timestamp=sample_datetime,
                      role=MessageRole.ASSISTANT, content=[tool_use], session_id="test")
        msg2 = Message(uuid="m2", parent_uuid="m1", timestamp=sample_datetime,
                      role=MessageRole.USER, content=[tool_result], session_id="test")
        return ToolCall(tool_use=tool_use, tool_result=tool_result,
                       request_message=msg1, response_message=msg2)

    @pytest.fixture
    def read_tool_call(self, assistant_message_with_tool, user_message_with_tool_result):
        return ToolCall(
            tool_use=assistant_message_with_tool.tool_uses[0],
            tool_result=user_message_with_tool_result.tool_results[0],
            request_message=assistant_message_with_tool,
            response_message=user_message_with_tool_result
        )

    def test_filters_bash_only(self, skip_if_no_pandas, bash_tool_call, read_tool_call):
        """Should only include Bash tool calls."""
        df = bash_commands_to_dataframe([bash_tool_call, read_tool_call])
        assert len(df) == 1
        assert df.iloc[0]["command"] == "ls -la"

    def test_empty_when_no_bash(self, skip_if_no_pandas, read_tool_call):
        """Should return empty DataFrame if no Bash calls."""
        df = bash_commands_to_dataframe([read_tool_call])
        assert len(df) == 0


class TestFileOperationsToDataframe:
    """Tests for file_operations_to_dataframe function."""

    @pytest.fixture
    def skip_if_no_pandas(self):
        pytest.importorskip("pandas")

    @pytest.fixture
    def tool_call(self, assistant_message_with_tool, user_message_with_tool_result):
        return ToolCall(
            tool_use=assistant_message_with_tool.tool_uses[0],
            tool_result=user_message_with_tool_result.tool_results[0],
            request_message=assistant_message_with_tool,
            response_message=user_message_with_tool_result
        )

    def test_includes_read(self, skip_if_no_pandas, tool_call):
        """Should include Read operations."""
        df = file_operations_to_dataframe([tool_call])
        assert len(df) == 1
        assert df.iloc[0]["operation"] == "read"


# ============================================================================
# JSON Export Tests
# ============================================================================

class TestContentBlockToDict:
    """Tests for content_block_to_dict function."""

    def test_text_block(self, text_block):
        """TextBlock should serialize correctly."""
        d = content_block_to_dict(text_block)
        assert d["type"] == "text"
        assert d["text"] == "Sample text content"

    def test_tool_use_block(self, tool_use_block):
        """ToolUseBlock should serialize correctly."""
        d = content_block_to_dict(tool_use_block)
        assert d["type"] == "tool_use"
        assert d["name"] == "Read"
        assert "input" in d

    def test_tool_result_block(self, tool_result_block):
        """ToolResultBlock should serialize correctly."""
        d = content_block_to_dict(tool_result_block)
        assert d["type"] == "tool_result"
        assert "content" in d
        assert d["is_error"] is False


class TestMessageToDict:
    """Tests for message_to_dict function."""

    def test_serializes_message(self, user_message):
        """Message should serialize to dict."""
        d = message_to_dict(user_message)
        assert d["uuid"] == user_message.uuid
        assert d["role"] == "user"
        assert "timestamp" in d
        assert "content" in d

    def test_timestamp_iso_format(self, user_message):
        """Timestamp should be ISO format string."""
        d = message_to_dict(user_message)
        assert "T" in d["timestamp"]  # ISO format


class TestSessionToDict:
    """Tests for session_to_dict function."""

    def test_serializes_session(self, simple_session):
        """Session should serialize to dict."""
        d = session_to_dict(simple_session)
        assert d["session_id"] == simple_session.session_id
        assert "messages" in d
        assert "agents" in d

    def test_includes_agents(self, session_with_agents):
        """Should include agent data."""
        d = session_to_dict(session_with_agents)
        assert len(d["agents"]) > 0

    def test_empty_session(self, empty_session):
        """Empty session should serialize without errors."""
        d = session_to_dict(empty_session)
        assert d["session_id"] == empty_session.session_id
        assert d["start_time"] is None
        assert d["end_time"] is None


class TestToolCallToDict:
    """Tests for tool_call_to_dict function."""

    @pytest.fixture
    def tool_call(self, assistant_message_with_tool, user_message_with_tool_result):
        return ToolCall(
            tool_use=assistant_message_with_tool.tool_uses[0],
            tool_result=user_message_with_tool_result.tool_results[0],
            request_message=assistant_message_with_tool,
            response_message=user_message_with_tool_result
        )

    def test_serializes_tool_call(self, tool_call):
        """ToolCall should serialize to dict."""
        d = tool_call_to_dict(tool_call)
        assert d["tool_name"] == "Read"
        assert d["tool_category"] == "file_read"
        assert "timestamp" in d


class TestExportSessionsJson:
    """Tests for export_sessions_json function."""

    def test_writes_valid_json(self, simple_session, tmp_path):
        """Should write valid JSON file."""
        path = tmp_path / "sessions.json"
        export_sessions_json([simple_session], path)

        with open(path) as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert len(data) == 1

    def test_multiple_sessions(self, simple_session, session_with_agents, tmp_path):
        """Should write multiple sessions."""
        path = tmp_path / "sessions.json"
        export_sessions_json([simple_session, session_with_agents], path)

        with open(path) as f:
            data = json.load(f)
        assert len(data) == 2


class TestExportSessionsJsonl:
    """Tests for export_sessions_jsonl function."""

    def test_writes_jsonl(self, simple_session, tmp_path):
        """Should write JSONL file."""
        path = tmp_path / "sessions.jsonl"
        export_sessions_jsonl([simple_session], path)

        with open(path) as f:
            lines = f.readlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["session_id"] == simple_session.session_id

    def test_multiple_lines(self, simple_session, session_with_agents, tmp_path):
        """Should write one line per session."""
        path = tmp_path / "sessions.jsonl"
        export_sessions_jsonl([simple_session, session_with_agents], path)

        with open(path) as f:
            lines = f.readlines()
        assert len(lines) == 2


class TestExportToolCallsJson:
    """Tests for export_tool_calls_json function."""

    @pytest.fixture
    def tool_call(self, assistant_message_with_tool, user_message_with_tool_result):
        return ToolCall(
            tool_use=assistant_message_with_tool.tool_uses[0],
            tool_result=user_message_with_tool_result.tool_results[0],
            request_message=assistant_message_with_tool,
            response_message=user_message_with_tool_result
        )

    def test_writes_json(self, tool_call, tmp_path):
        """Should write valid JSON file."""
        path = tmp_path / "tool_calls.json"
        export_tool_calls_json([tool_call], path)

        with open(path) as f:
            data = json.load(f)
        assert len(data) == 1
        assert data[0]["tool_name"] == "Read"

    def test_empty_list(self, tmp_path):
        """Should write empty array for no tool calls."""
        path = tmp_path / "tool_calls.json"
        export_tool_calls_json([], path)

        with open(path) as f:
            data = json.load(f)
        assert data == []
