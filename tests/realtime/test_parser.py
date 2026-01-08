"""Tests for claude_sessions.realtime.parser module."""

import pytest

from claude_sessions.realtime.parser import IncrementalParser
from claude_sessions.realtime.events import (
    MessageEvent,
    ToolUseEvent,
    ToolResultEvent,
    ErrorEvent,
)


@pytest.fixture
def parser():
    """Create a fresh IncrementalParser instance."""
    return IncrementalParser()


@pytest.fixture
def parser_no_truncate():
    """Create a parser that doesn't truncate inputs."""
    return IncrementalParser(truncate_inputs=False)


class TestParseEntry:
    """Test parse_entry() method."""

    def test_user_message_produces_message_event(self, parser, sample_user_message_entry):
        """User message should produce a single MessageEvent."""
        events = parser.parse_entry(sample_user_message_entry)

        assert len(events) == 1
        assert isinstance(events[0], MessageEvent)
        assert events[0].message.role.value == "user"
        assert events[0].session_id == sample_user_message_entry["sessionId"]

    def test_assistant_message_produces_message_event(self, parser, sample_assistant_message_entry):
        """Assistant message should produce a MessageEvent."""
        events = parser.parse_entry(sample_assistant_message_entry)

        assert len(events) == 1
        assert isinstance(events[0], MessageEvent)
        assert events[0].message.role.value == "assistant"

    def test_tool_use_produces_multiple_events(self, parser, sample_tool_use_entry):
        """Assistant message with tool use should produce MessageEvent + ToolUseEvent."""
        events = parser.parse_entry(sample_tool_use_entry)

        assert len(events) == 2
        assert isinstance(events[0], MessageEvent)
        assert isinstance(events[1], ToolUseEvent)

        tool_event = events[1]
        assert tool_event.tool_name == "Read"
        assert tool_event.tool_category == "file_read"
        assert tool_event.tool_input == {"file_path": "/home/user/project/main.py"}

    def test_tool_result_produces_tool_result_event(self, parser, sample_tool_result_entry):
        """User message with tool result should produce MessageEvent + ToolResultEvent."""
        events = parser.parse_entry(sample_tool_result_entry)

        assert len(events) == 2
        assert isinstance(events[0], MessageEvent)
        assert isinstance(events[1], ToolResultEvent)

        result_event = events[1]
        assert result_event.tool_use_id == sample_tool_result_entry["message"]["content"][0]["tool_use_id"]
        assert result_event.is_error is False

    def test_tool_result_error(self, parser, sample_tool_result_error_entry):
        """Tool result with error should have is_error=True."""
        events = parser.parse_entry(sample_tool_result_error_entry)

        assert len(events) == 2
        result_event = events[1]
        assert isinstance(result_event, ToolResultEvent)
        assert result_event.is_error is True

    def test_non_message_entry_skipped(self, parser, sample_queue_operation_entry):
        """Non-message entries (like queue-operation) should return empty list."""
        events = parser.parse_entry(sample_queue_operation_entry)
        assert events == []

    def test_agent_message_has_agent_id(self, parser, sample_agent_message_entry):
        """Agent messages should have agent_id set."""
        events = parser.parse_entry(sample_agent_message_entry)

        assert len(events) >= 1
        assert events[0].agent_id == sample_agent_message_entry["agentId"]

    def test_message_event_includes_metadata(self, parser, sample_user_message_entry):
        """MessageEvent should include cwd, git_branch, version from entry."""
        events = parser.parse_entry(sample_user_message_entry)

        message = events[0].message
        assert message.cwd == "/home/user/project"
        assert message.git_branch == "main"
        assert message.version == "1.0.0"


class TestInputTruncation:
    """Test input truncation behavior."""

    def test_long_tool_input_truncated(self, parser):
        """Long tool inputs should be truncated."""
        long_content = "x" * 2000
        entry = {
            "type": "assistant",
            "uuid": "test-uuid",
            "timestamp": "2024-01-15T10:30:00.000Z",
            "sessionId": "test-session",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_123",
                        "name": "Write",
                        "input": {"file_path": "/test.py", "content": long_content}
                    }
                ]
            }
        }

        events = parser.parse_entry(entry)
        tool_event = events[1]

        # Content should be truncated
        assert len(tool_event.tool_input["content"]) < 2000
        assert "...[truncated]" in tool_event.tool_input["content"]

    def test_truncation_disabled(self, parser_no_truncate):
        """With truncate_inputs=False, inputs should not be truncated."""
        long_content = "x" * 2000
        entry = {
            "type": "assistant",
            "uuid": "test-uuid",
            "timestamp": "2024-01-15T10:30:00.000Z",
            "sessionId": "test-session",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_123",
                        "name": "Write",
                        "input": {"file_path": "/test.py", "content": long_content}
                    }
                ]
            }
        }

        events = parser_no_truncate.parse_entry(entry)
        tool_event = events[1]

        # Content should NOT be truncated
        assert len(tool_event.tool_input["content"]) == 2000

    def test_tool_result_content_truncated(self, parser):
        """Long tool result content should be truncated."""
        long_result = "x" * 2000
        entry = {
            "type": "user",
            "uuid": "test-uuid",
            "timestamp": "2024-01-15T10:30:00.000Z",
            "sessionId": "test-session",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_123",
                        "content": long_result
                    }
                ]
            }
        }

        events = parser.parse_entry(entry)
        result_event = events[1]

        assert len(result_event.content) < 2000
        assert "...[truncated]" in result_event.content


class TestErrorHandling:
    """Test error handling and graceful parsing."""

    def test_missing_fields_parsed_with_defaults(self, parser):
        """Missing fields should be handled gracefully with defaults."""
        # Parser is lenient - missing fields get default values
        minimal_entry = {
            "type": "user",
            "sessionId": "test-session",
        }

        events = parser.parse_entry(minimal_entry)

        # Should still produce a MessageEvent with default values
        assert len(events) == 1
        assert isinstance(events[0], MessageEvent)
        assert events[0].session_id == "test-session"

    def test_non_message_type_returns_empty(self, parser):
        """Non-message types (queue-operation, etc.) should return empty list."""
        # queue-operation entries should be skipped
        non_message_entry = {
            "type": "queue-operation",
            "sessionId": "test-session",
            "operation": "clear"
        }

        events = parser.parse_entry(non_message_entry)

        assert len(events) == 0

    def test_unknown_type_returns_empty(self, parser):
        """Unknown entry types should return empty list."""
        unknown_entry = {
            "type": "unknown-type",
            "sessionId": "test-session"
        }

        events = parser.parse_entry(unknown_entry)

        assert len(events) == 0


class TestParseRawLine:
    """Test parse_raw_line() method."""

    def test_valid_json_parsed(self, parser, sample_user_message_entry):
        """Valid JSON line should be parsed."""
        import json
        line = json.dumps(sample_user_message_entry)

        events = parser.parse_raw_line(line)

        assert len(events) == 1
        assert isinstance(events[0], MessageEvent)

    def test_invalid_json_produces_error(self, parser):
        """Invalid JSON should produce ErrorEvent."""
        events = parser.parse_raw_line("not valid json")

        assert len(events) == 1
        assert isinstance(events[0], ErrorEvent)
        assert "JSON parse error" in events[0].error_message

    def test_empty_line_returns_empty(self, parser):
        """Empty line should return empty list."""
        assert parser.parse_raw_line("") == []
        assert parser.parse_raw_line("   ") == []
        assert parser.parse_raw_line("\n") == []


class TestMultipleToolBlocks:
    """Test parsing messages with multiple tool use/result blocks."""

    def test_multiple_tool_uses(self, parser):
        """Message with multiple tool uses should produce multiple ToolUseEvents."""
        entry = {
            "type": "assistant",
            "uuid": "test-uuid",
            "timestamp": "2024-01-15T10:30:00.000Z",
            "sessionId": "test-session",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "I'll read both files."},
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "Read",
                        "input": {"file_path": "/file1.py"}
                    },
                    {
                        "type": "tool_use",
                        "id": "toolu_2",
                        "name": "Read",
                        "input": {"file_path": "/file2.py"}
                    }
                ]
            }
        }

        events = parser.parse_entry(entry)

        # 1 MessageEvent + 2 ToolUseEvents
        assert len(events) == 3
        assert isinstance(events[0], MessageEvent)
        assert isinstance(events[1], ToolUseEvent)
        assert isinstance(events[2], ToolUseEvent)

        assert events[1].tool_use_id == "toolu_1"
        assert events[2].tool_use_id == "toolu_2"

    def test_multiple_tool_results(self, parser):
        """Message with multiple tool results should produce multiple ToolResultEvents."""
        entry = {
            "type": "user",
            "uuid": "test-uuid",
            "timestamp": "2024-01-15T10:30:00.000Z",
            "sessionId": "test-session",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_1",
                        "content": "result 1"
                    },
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_2",
                        "content": "result 2"
                    }
                ]
            }
        }

        events = parser.parse_entry(entry)

        # 1 MessageEvent + 2 ToolResultEvents
        assert len(events) == 3
        assert isinstance(events[0], MessageEvent)
        assert isinstance(events[1], ToolResultEvent)
        assert isinstance(events[2], ToolResultEvent)


class TestToolCategories:
    """Test that tool categories are correctly assigned."""

    @pytest.mark.parametrize("tool_name,expected_category", [
        ("Read", "file_read"),
        ("Write", "file_write"),
        ("Edit", "file_write"),
        ("Bash", "bash"),
        ("Glob", "search"),
        ("Grep", "search"),
        ("Task", "agent"),
        ("WebFetch", "web"),
        ("TodoWrite", "planning"),
        ("AskUserQuestion", "interaction"),
        ("UnknownTool", "other"),
    ])
    def test_tool_category_mapping(self, parser, tool_name, expected_category):
        """Tool names should map to correct categories."""
        entry = {
            "type": "assistant",
            "uuid": "test-uuid",
            "timestamp": "2024-01-15T10:30:00.000Z",
            "sessionId": "test-session",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_123",
                        "name": tool_name,
                        "input": {}
                    }
                ]
            }
        }

        events = parser.parse_entry(entry)
        tool_event = events[1]

        assert tool_event.tool_category == expected_category
