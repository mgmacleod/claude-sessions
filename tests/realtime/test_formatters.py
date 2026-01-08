"""Tests for claude_sessions.realtime.formatters module."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from claude_sessions.realtime.formatters import (
    OutputFormatter,
    PlainFormatter,
    JsonFormatter,
    CompactFormatter,
    get_formatter,
)
from claude_sessions.realtime.events import (
    MessageEvent,
    ToolUseEvent,
    ToolResultEvent,
    ErrorEvent,
    SessionStartEvent,
    SessionEndEvent,
)
from claude_sessions.models import Message, MessageRole, TextBlock


@pytest.fixture
def sample_datetime():
    return datetime(2024, 1, 15, 14, 32, 5, tzinfo=timezone.utc)


@pytest.fixture
def message_event(sample_datetime):
    """Create a sample user message event."""
    message = Message(
        uuid="msg-1",
        parent_uuid=None,
        timestamp=sample_datetime,
        role=MessageRole.USER,
        content=[TextBlock(text="Help me fix this bug")],
        session_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    )
    return MessageEvent(
        timestamp=sample_datetime,
        session_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        message=message
    )


@pytest.fixture
def assistant_message_event(sample_datetime):
    """Create a sample assistant message event."""
    message = Message(
        uuid="msg-2",
        parent_uuid="msg-1",
        timestamp=sample_datetime,
        role=MessageRole.ASSISTANT,
        content=[TextBlock(text="I'll help you debug that issue")],
        session_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    )
    return MessageEvent(
        timestamp=sample_datetime,
        session_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        message=message
    )


@pytest.fixture
def tool_use_event(sample_datetime):
    """Create a sample tool use event."""
    message = Message(
        uuid="msg-3",
        parent_uuid=None,
        timestamp=sample_datetime,
        role=MessageRole.ASSISTANT,
        content=[],
        session_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    )
    return ToolUseEvent(
        timestamp=sample_datetime,
        session_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        tool_name="Read",
        tool_category="file_read",
        tool_input={"file_path": "/path/to/file.py"},
        tool_use_id="toolu_123",
        message=message
    )


@pytest.fixture
def tool_result_event(sample_datetime):
    """Create a sample tool result event."""
    message = Message(
        uuid="msg-4",
        parent_uuid="msg-3",
        timestamp=sample_datetime,
        role=MessageRole.USER,
        content=[],
        session_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    )
    return ToolResultEvent(
        timestamp=sample_datetime,
        session_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        tool_use_id="toolu_123",
        content="def main():\n    print('Hello')",
        is_error=False,
        message=message
    )


@pytest.fixture
def error_event(sample_datetime):
    """Create a sample error event."""
    return ErrorEvent(
        timestamp=sample_datetime,
        session_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        error_message="Failed to parse JSON"
    )


@pytest.fixture
def session_start_event(sample_datetime):
    """Create a sample session start event."""
    return SessionStartEvent(
        timestamp=sample_datetime,
        session_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        project_slug="my-project",
        file_path=Path("/test/session.jsonl")
    )


class TestPlainFormatter:
    """Test PlainFormatter class."""

    def test_format_user_message(self, message_event):
        """PlainFormatter should format user messages."""
        formatter = PlainFormatter(use_color=False)
        output = formatter.format(message_event)

        assert "USER" in output
        assert "Help me fix this bug" in output
        assert "a1b2c3d4" in output  # Session ID prefix

    def test_format_assistant_message(self, assistant_message_event):
        """PlainFormatter should format assistant messages."""
        formatter = PlainFormatter(use_color=False)
        output = formatter.format(assistant_message_event)

        assert "ASSISTANT" in output
        assert "help you debug" in output

    def test_format_tool_use(self, tool_use_event):
        """PlainFormatter should format tool use events."""
        formatter = PlainFormatter(use_color=False)
        output = formatter.format(tool_use_event)

        assert "Read" in output
        assert "file_read" in output or "/path/to/file.py" in output

    def test_format_tool_result(self, tool_result_event):
        """PlainFormatter should format tool result events."""
        formatter = PlainFormatter(use_color=False)
        output = formatter.format(tool_result_event)

        # Should indicate success (not error)
        assert "error" not in output.lower() or "ok" in output.lower()

    def test_format_error(self, error_event):
        """PlainFormatter should format error events."""
        formatter = PlainFormatter(use_color=False)
        output = formatter.format(error_event)

        assert "ERROR" in output or "error" in output.lower()
        assert "parse JSON" in output.lower() or "Failed" in output

    def test_format_session_start(self, session_start_event):
        """PlainFormatter should format session start events."""
        formatter = PlainFormatter(use_color=False)
        output = formatter.format(session_start_event)

        assert "my-project" in output or "session" in output.lower()

    def test_truncate_long_text(self, sample_datetime):
        """PlainFormatter should truncate long messages."""
        long_text = "x" * 200
        message = Message(
            uuid="msg-1",
            parent_uuid=None,
            timestamp=sample_datetime,
            role=MessageRole.USER,
            content=[TextBlock(text=long_text)],
            session_id="a1b2c3d4-1234-5678-9abc-def012345678"
        )
        event = MessageEvent(
            timestamp=sample_datetime,
            session_id="a1b2c3d4-1234-5678-9abc-def012345678",
            message=message
        )

        formatter = PlainFormatter(use_color=False)
        output = formatter.format(event)

        # Should be truncated
        assert len(output) < 200 + 100  # Some overhead for formatting

    def test_color_disabled(self, message_event):
        """PlainFormatter with use_color=False should not include ANSI codes."""
        formatter = PlainFormatter(use_color=False)
        output = formatter.format(message_event)

        # No ANSI escape sequences
        assert "\033[" not in output


class TestJsonFormatter:
    """Test JsonFormatter class."""

    def test_format_produces_valid_json(self, message_event):
        """JsonFormatter should produce valid JSON."""
        formatter = JsonFormatter()
        output = formatter.format(message_event)

        # Should be parseable JSON
        data = json.loads(output)
        assert "event_type" in data
        assert data["event_type"] == "message"

    def test_format_message_event(self, message_event):
        """JsonFormatter should include message details."""
        formatter = JsonFormatter()
        output = formatter.format(message_event)
        data = json.loads(output)

        assert data["session_id"] == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        assert "timestamp" in data

    def test_format_tool_use_event(self, tool_use_event):
        """JsonFormatter should include tool details."""
        formatter = JsonFormatter()
        output = formatter.format(tool_use_event)
        data = json.loads(output)

        assert data["event_type"] == "tool_use"
        assert data["tool_name"] == "Read"

    def test_format_error_event(self, error_event):
        """JsonFormatter should include error details."""
        formatter = JsonFormatter()
        output = formatter.format(error_event)
        data = json.loads(output)

        assert data["event_type"] == "error"
        assert "error_message" in data

    def test_each_line_is_separate_json(self, message_event, tool_use_event):
        """Each formatted event should be a single JSON line (JSONL format)."""
        formatter = JsonFormatter()

        output1 = formatter.format(message_event)
        output2 = formatter.format(tool_use_event)

        # Each should be valid JSON on its own
        json.loads(output1)
        json.loads(output2)

        # No embedded newlines
        assert "\n" not in output1.strip()
        assert "\n" not in output2.strip()


class TestCompactFormatter:
    """Test CompactFormatter class."""

    def test_format_produces_compact_output(self, message_event):
        """CompactFormatter should produce compact pipe-separated output."""
        formatter = CompactFormatter()
        output = formatter.format(message_event)

        # Should contain pipe separators
        assert "|" in output

    def test_format_includes_key_info(self, message_event):
        """CompactFormatter should include essential information."""
        formatter = CompactFormatter()
        output = formatter.format(message_event)

        # Should include event type and session
        assert "message" in output.lower()

    def test_format_tool_use(self, tool_use_event):
        """CompactFormatter should format tool use compactly."""
        formatter = CompactFormatter()
        output = formatter.format(tool_use_event)

        assert "Read" in output or "tool" in output.lower()

    def test_single_line_output(self, message_event):
        """CompactFormatter should produce single-line output."""
        formatter = CompactFormatter()
        output = formatter.format(message_event)

        assert "\n" not in output.strip()


class TestGetFormatter:
    """Test get_formatter() factory function."""

    def test_get_plain_formatter(self):
        """get_formatter('plain') should return PlainFormatter."""
        formatter = get_formatter("plain")
        assert isinstance(formatter, PlainFormatter)

    def test_get_json_formatter(self):
        """get_formatter('json') should return JsonFormatter."""
        formatter = get_formatter("json")
        assert isinstance(formatter, JsonFormatter)

    def test_get_compact_formatter(self):
        """get_formatter('compact') should return CompactFormatter."""
        formatter = get_formatter("compact")
        assert isinstance(formatter, CompactFormatter)

    def test_get_formatter_with_color(self):
        """get_formatter() should pass use_color to PlainFormatter."""
        formatter = get_formatter("plain", use_color=False)
        assert isinstance(formatter, PlainFormatter)

    def test_get_formatter_unknown_raises(self):
        """get_formatter() with unknown name should raise ValueError."""
        with pytest.raises(ValueError):
            get_formatter("unknown")


class TestFormatterInheritance:
    """Test that formatters properly inherit from OutputFormatter."""

    def test_plain_formatter_is_output_formatter(self):
        """PlainFormatter should be an OutputFormatter."""
        assert issubclass(PlainFormatter, OutputFormatter)

    def test_json_formatter_is_output_formatter(self):
        """JsonFormatter should be an OutputFormatter."""
        assert issubclass(JsonFormatter, OutputFormatter)

    def test_compact_formatter_is_output_formatter(self):
        """CompactFormatter should be an OutputFormatter."""
        assert issubclass(CompactFormatter, OutputFormatter)
