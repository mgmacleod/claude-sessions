"""Tests for claude_sessions.parser module."""

import json
import pytest
import warnings
from datetime import datetime, timezone, timedelta
from pathlib import Path

from claude_sessions.parser import (
    DATETIME_MIN,
    parse_timestamp,
    iter_jsonl,
    load_jsonl,
    parse_content_block,
    parse_message,
    build_thread,
    discover_session_files,
    build_session,
    load_project,
    load_all_projects,
)
from claude_sessions.models import (
    TextBlock, ToolUseBlock, ToolResultBlock,
    MessageRole, Thread, Message
)

# Constants from conftest
SAMPLE_SESSION_ID = "abc12345-1234-5678-9abc-def012345678"
SAMPLE_UUID_1 = "msg-11111111-1111-1111-1111-111111111111"


class TestParseTimestamp:
    """Tests for parse_timestamp function."""

    def test_iso_with_z_suffix(self):
        """Should parse ISO timestamp with Z suffix."""
        ts = parse_timestamp("2024-01-15T10:30:00.000Z")
        assert ts.year == 2024
        assert ts.month == 1
        assert ts.day == 15
        assert ts.hour == 10
        assert ts.minute == 30
        assert ts.tzinfo is not None

    def test_iso_with_timezone_offset(self):
        """Should parse ISO timestamp with +HH:MM timezone."""
        ts = parse_timestamp("2024-01-15T10:30:00+05:00")
        assert ts.tzinfo is not None

    def test_empty_string(self):
        """Empty string should return DATETIME_MIN."""
        ts = parse_timestamp("")
        assert ts == DATETIME_MIN

    def test_invalid_format(self):
        """Invalid format should return DATETIME_MIN."""
        ts = parse_timestamp("not-a-date")
        assert ts == DATETIME_MIN

    def test_naive_datetime_gets_utc(self):
        """Naive datetime should be converted to UTC."""
        ts = parse_timestamp("2024-01-15T10:30:00")
        assert ts.tzinfo == timezone.utc

    @pytest.mark.parametrize("ts_str,expected_valid", [
        ("2024-01-15T10:30:00.000Z", True),
        ("2024-01-15T10:30:00+00:00", True),
        ("2024-01-15T10:30:00+05:30", True),
        ("2024-01-15T10:30:00", True),
        ("", False),
        ("invalid", False),
    ])
    def test_various_formats(self, ts_str, expected_valid):
        """Test various timestamp formats."""
        result = parse_timestamp(ts_str)
        if expected_valid:
            assert result != DATETIME_MIN
        else:
            assert result == DATETIME_MIN


class TestIterJsonl:
    """Tests for iter_jsonl function."""

    def test_valid_jsonl(self, temp_jsonl_file, sample_user_message_entry):
        """Should yield parsed dicts for valid JSONL."""
        file_path = temp_jsonl_file([sample_user_message_entry])
        entries = list(iter_jsonl(file_path))
        assert len(entries) == 1
        assert entries[0]["type"] == "user"

    def test_empty_lines_skipped(self, jsonl_with_empty_lines):
        """Empty lines should be skipped."""
        entries = list(iter_jsonl(jsonl_with_empty_lines))
        assert len(entries) == 2

    def test_invalid_json_warning(self, jsonl_with_invalid_json):
        """Invalid JSON should emit warning and continue."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            entries = list(iter_jsonl(jsonl_with_invalid_json))
            assert len(entries) == 2  # Should skip invalid line
            assert len(w) == 1
            assert "JSON parse error" in str(w[0].message)

    def test_empty_file(self, tmp_path):
        """Empty file should yield nothing."""
        file_path = tmp_path / "empty.jsonl"
        file_path.write_text("")
        entries = list(iter_jsonl(file_path))
        assert len(entries) == 0


class TestLoadJsonl:
    """Tests for load_jsonl function."""

    def test_loads_all_entries(self, temp_jsonl_file, sample_user_message_entry, sample_assistant_message_entry):
        """Should load all entries into list."""
        file_path = temp_jsonl_file([sample_user_message_entry, sample_assistant_message_entry])
        entries = load_jsonl(file_path)
        assert len(entries) == 2


class TestParseContentBlock:
    """Tests for parse_content_block function."""

    def test_string_content(self):
        """String content should become TextBlock."""
        block = parse_content_block("Hello world")
        assert isinstance(block, TextBlock)
        assert block.text == "Hello world"

    def test_text_dict(self):
        """Dict with type=text should become TextBlock."""
        raw = {"type": "text", "text": "Sample text"}
        block = parse_content_block(raw)
        assert isinstance(block, TextBlock)
        assert block.text == "Sample text"

    def test_text_dict_missing_text(self):
        """Text dict without text key should use empty string."""
        raw = {"type": "text"}
        block = parse_content_block(raw)
        assert isinstance(block, TextBlock)
        assert block.text == ""

    def test_tool_use_dict(self):
        """Dict with type=tool_use should become ToolUseBlock."""
        raw = {
            "type": "tool_use",
            "id": "toolu_123",
            "name": "Read",
            "input": {"file_path": "/test.py"}
        }
        block = parse_content_block(raw)
        assert isinstance(block, ToolUseBlock)
        assert block.id == "toolu_123"
        assert block.name == "Read"
        assert block.input == {"file_path": "/test.py"}

    def test_tool_use_missing_fields(self):
        """Tool use dict with missing fields should use defaults."""
        raw = {"type": "tool_use"}
        block = parse_content_block(raw)
        assert isinstance(block, ToolUseBlock)
        assert block.id == ""
        assert block.name == ""
        assert block.input == {}

    def test_tool_result_string_content(self):
        """Tool result with string content."""
        raw = {
            "type": "tool_result",
            "tool_use_id": "toolu_123",
            "content": "result text"
        }
        block = parse_content_block(raw)
        assert isinstance(block, ToolResultBlock)
        assert block.content == "result text"
        assert block.is_error is False

    def test_tool_result_list_content(self):
        """Tool result with list of text blocks."""
        raw = {
            "type": "tool_result",
            "tool_use_id": "toolu_123",
            "content": [
                {"type": "text", "text": "line 1"},
                "line 2"
            ]
        }
        block = parse_content_block(raw)
        assert isinstance(block, ToolResultBlock)
        assert "line 1" in block.content
        assert "line 2" in block.content

    def test_tool_result_error(self):
        """Tool result with is_error=True."""
        raw = {
            "type": "tool_result",
            "tool_use_id": "toolu_123",
            "content": "Error occurred",
            "is_error": True
        }
        block = parse_content_block(raw)
        assert block.is_error is True

    def test_unknown_type(self):
        """Unknown block type should become TextBlock with str(raw)."""
        raw = {"type": "unknown", "data": "something"}
        block = parse_content_block(raw)
        assert isinstance(block, TextBlock)

    def test_non_dict_non_string(self):
        """Non-dict, non-string should become TextBlock with str()."""
        block = parse_content_block(12345)
        assert isinstance(block, TextBlock)
        assert block.text == "12345"


class TestParseMessage:
    """Tests for parse_message function."""

    def test_user_message(self, sample_user_message_entry):
        """Should parse user message entry."""
        msg = parse_message(sample_user_message_entry)
        assert msg is not None
        assert msg.role == MessageRole.USER
        assert msg.session_id == sample_user_message_entry["sessionId"]
        assert msg.cwd == "/home/user/project"

    def test_assistant_message(self, sample_assistant_message_entry):
        """Should parse assistant message entry."""
        msg = parse_message(sample_assistant_message_entry)
        assert msg is not None
        assert msg.role == MessageRole.ASSISTANT
        assert msg.model == "claude-sonnet-4-20250514"

    def test_non_message_returns_none(self, sample_queue_operation_entry):
        """Non-message entry should return None."""
        msg = parse_message(sample_queue_operation_entry)
        assert msg is None

    def test_string_content(self, sample_user_message_entry):
        """String content should be wrapped in TextBlock."""
        # sample_user_message_entry has string content
        msg = parse_message(sample_user_message_entry)
        assert len(msg.content) == 1
        assert isinstance(msg.content[0], TextBlock)

    def test_list_content(self, sample_assistant_message_entry):
        """List content should be parsed as blocks."""
        msg = parse_message(sample_assistant_message_entry)
        assert len(msg.content) == 1
        assert isinstance(msg.content[0], TextBlock)

    def test_tool_use_content(self, sample_tool_use_entry):
        """Tool use content should become ToolUseBlock."""
        msg = parse_message(sample_tool_use_entry)
        assert len(msg.content) == 2
        assert isinstance(msg.content[1], ToolUseBlock)

    def test_tool_result_content(self, sample_tool_result_entry):
        """Tool result content should become ToolResultBlock."""
        msg = parse_message(sample_tool_result_entry)
        assert len(msg.content) == 1
        assert isinstance(msg.content[0], ToolResultBlock)

    def test_agent_message_metadata(self, sample_agent_message_entry):
        """Agent message should have agent_id and is_sidechain."""
        msg = parse_message(sample_agent_message_entry)
        assert msg.agent_id == sample_agent_message_entry["agentId"]
        assert msg.is_sidechain is True

    def test_usage_extraction(self, sample_assistant_message_entry):
        """Assistant message should extract usage stats."""
        msg = parse_message(sample_assistant_message_entry)
        assert msg.usage is not None
        assert msg.usage["input_tokens"] == 100

    def test_missing_uuid(self):
        """Missing UUID should use empty string."""
        entry = {
            "type": "user",
            "message": {"role": "user", "content": "test"},
            "sessionId": "test"
        }
        msg = parse_message(entry)
        assert msg.uuid == ""

    def test_missing_timestamp(self):
        """Missing timestamp should use DATETIME_MIN."""
        entry = {
            "type": "user",
            "uuid": "test",
            "message": {"role": "user", "content": "test"},
            "sessionId": "test"
        }
        msg = parse_message(entry)
        assert msg.timestamp == DATETIME_MIN


class TestBuildThread:
    """Tests for build_thread function."""

    def test_empty_messages(self):
        """Empty list should return empty thread."""
        thread = build_thread([])
        assert len(thread.messages) == 0

    def test_single_message(self, user_message):
        """Single message should be in thread."""
        thread = build_thread([user_message])
        assert len(thread.messages) == 1
        assert thread.root == user_message

    def test_ordered_by_parent(self, user_message, assistant_message):
        """Messages should be ordered by parent chain."""
        # Pass in wrong order
        thread = build_thread([assistant_message, user_message])
        # Should be reordered: user first, then assistant
        assert thread.messages[0].parent_uuid is None
        assert thread.messages[1].parent_uuid == user_message.uuid

    def test_orphaned_messages(self, sample_datetime):
        """Orphaned messages should be appended at end."""
        root = Message(
            uuid="root",
            parent_uuid=None,
            timestamp=sample_datetime,
            role=MessageRole.USER,
            content=[],
            session_id="test"
        )
        orphan = Message(
            uuid="orphan",
            parent_uuid="nonexistent",  # Parent doesn't exist
            timestamp=sample_datetime + timedelta(seconds=1),
            role=MessageRole.USER,
            content=[],
            session_id="test"
        )
        thread = build_thread([orphan, root])
        assert len(thread.messages) == 2
        assert thread.messages[0] == root
        assert thread.messages[1] == orphan

    def test_timestamp_ordering(self, sample_datetime):
        """Messages with same parent should be ordered by timestamp."""
        parent = Message(
            uuid="parent",
            parent_uuid=None,
            timestamp=sample_datetime,
            role=MessageRole.USER,
            content=[],
            session_id="test"
        )
        child1 = Message(
            uuid="child1",
            parent_uuid="parent",
            timestamp=sample_datetime + timedelta(seconds=2),
            role=MessageRole.ASSISTANT,
            content=[],
            session_id="test"
        )
        child2 = Message(
            uuid="child2",
            parent_uuid="parent",
            timestamp=sample_datetime + timedelta(seconds=1),
            role=MessageRole.ASSISTANT,
            content=[],
            session_id="test"
        )
        # Pass out of order
        thread = build_thread([child1, parent, child2])
        # Should be: parent, child2, child1 (by timestamp)
        assert thread.messages[0].uuid == "parent"
        assert thread.messages[1].uuid == "child2"
        assert thread.messages[2].uuid == "child1"


class TestDiscoverSessionFiles:
    """Tests for discover_session_files function."""

    def test_main_session_files(self, mock_project_directory_with_sessions):
        """Should discover main session files."""
        project_path = mock_project_directory_with_sessions / "projects" / "-home-mgm-project"
        files = discover_session_files(project_path)
        assert "session-001" in files
        assert "session-002" in files

    def test_agent_files_assigned(self, mock_project_directory_with_sessions):
        """Agent files should be assigned to correct session."""
        project_path = mock_project_directory_with_sessions / "projects" / "-home-mgm-project"
        files = discover_session_files(project_path)
        # session-002 should have agent file
        assert len(files.get("session-002", [])) == 2

    def test_empty_directory(self, tmp_path):
        """Empty directory should return empty dict."""
        files = discover_session_files(tmp_path)
        assert files == {}


class TestBuildSession:
    """Tests for build_session function."""

    def test_builds_main_thread(self, mock_session_file):
        """Should build main thread from session file."""
        session = build_session(
            SAMPLE_SESSION_ID,
            "my-project",
            [mock_session_file]
        )
        assert session.session_id == SAMPLE_SESSION_ID
        assert len(session.main_thread.messages) > 0

    def test_metadata_captured(self, mock_session_file):
        """Session metadata should be captured from first message."""
        session = build_session(
            SAMPLE_SESSION_ID,
            "my-project",
            [mock_session_file]
        )
        assert session.cwd == "/home/user/project"
        assert session.git_branch == "main"


class TestLoadProject:
    """Tests for load_project function."""

    def test_loads_all_sessions(self, mock_project_directory_with_sessions):
        """Should load all sessions in project."""
        project_path = mock_project_directory_with_sessions / "projects" / "-home-mgm-project"
        project = load_project(project_path)
        assert project.slug == "-home-mgm-project"
        assert project.session_count >= 1


class TestLoadAllProjects:
    """Tests for load_all_projects function."""

    def test_loads_all_projects(self, mock_project_directory_with_sessions):
        """Should load all projects from base path."""
        projects = load_all_projects(mock_project_directory_with_sessions)
        assert "-home-mgm-project" in projects

    def test_nonexistent_path(self, tmp_path):
        """Nonexistent projects directory should return empty dict."""
        projects = load_all_projects(tmp_path)
        assert projects == {}

    def test_default_path_used(self):
        """Should use ~/.claude by default (may be empty)."""
        # This tests that default path doesn't raise
        projects = load_all_projects()
        assert isinstance(projects, dict)
