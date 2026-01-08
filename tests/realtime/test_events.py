"""Tests for claude_sessions.realtime.events module."""

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from claude_sessions.realtime.events import (
    MessageEvent,
    ToolUseEvent,
    ToolResultEvent,
    ErrorEvent,
    SessionStartEvent,
    SessionEndEvent,
    SessionIdleEvent,
    SessionResumeEvent,
    ToolCallCompletedEvent,
    truncate_tool_input,
)
from claude_sessions.models import Message, MessageRole, TextBlock, ToolUseBlock, ToolResultBlock, ToolCall


class TestEventImmutability:
    """Test that all event types are immutable (frozen dataclasses)."""

    def test_message_event_is_frozen(self, sample_datetime, session_id):
        """MessageEvent should be immutable."""
        message = Message(
            uuid="test-uuid",
            parent_uuid=None,
            timestamp=sample_datetime,
            role=MessageRole.USER,
            content=[TextBlock(text="Hello")],
            session_id=session_id
        )
        event = MessageEvent(
            timestamp=sample_datetime,
            session_id=session_id,
            message=message
        )
        with pytest.raises(FrozenInstanceError):
            event.session_id = "new-id"

    def test_tool_use_event_is_frozen(self, sample_datetime, session_id):
        """ToolUseEvent should be immutable."""
        message = Message(
            uuid="test-uuid",
            parent_uuid=None,
            timestamp=sample_datetime,
            role=MessageRole.ASSISTANT,
            content=[],
            session_id=session_id
        )
        event = ToolUseEvent(
            timestamp=sample_datetime,
            session_id=session_id,
            tool_name="Read",
            tool_category="file_read",
            tool_input={"file_path": "/test.py"},
            tool_use_id="toolu_123",
            message=message
        )
        with pytest.raises(FrozenInstanceError):
            event.tool_name = "Write"

    def test_error_event_is_frozen(self, sample_datetime, session_id):
        """ErrorEvent should be immutable."""
        event = ErrorEvent(
            timestamp=sample_datetime,
            session_id=session_id,
            error_message="Test error"
        )
        with pytest.raises(FrozenInstanceError):
            event.error_message = "New error"

    def test_session_start_event_is_frozen(self, sample_datetime, session_id):
        """SessionStartEvent should be immutable."""
        event = SessionStartEvent(
            timestamp=sample_datetime,
            session_id=session_id,
            project_slug="my-project",
            file_path=Path("/test/session.jsonl")
        )
        with pytest.raises(FrozenInstanceError):
            event.project_slug = "other-project"


class TestEventAttributes:
    """Test that events have required protocol attributes."""

    def test_message_event_has_required_attrs(self, sample_datetime, session_id):
        """MessageEvent should have all protocol attributes."""
        message = Message(
            uuid="test-uuid",
            parent_uuid=None,
            timestamp=sample_datetime,
            role=MessageRole.USER,
            content=[TextBlock(text="Hello")],
            session_id=session_id
        )
        event = MessageEvent(
            timestamp=sample_datetime,
            session_id=session_id,
            message=message
        )

        assert event.timestamp == sample_datetime
        assert event.session_id == session_id
        assert event.event_type == "message"
        assert event.agent_id is None

    def test_tool_use_event_has_required_attrs(self, sample_datetime, session_id):
        """ToolUseEvent should have all protocol attributes."""
        message = Message(
            uuid="test-uuid",
            parent_uuid=None,
            timestamp=sample_datetime,
            role=MessageRole.ASSISTANT,
            content=[],
            session_id=session_id
        )
        event = ToolUseEvent(
            timestamp=sample_datetime,
            session_id=session_id,
            tool_name="Read",
            tool_category="file_read",
            tool_input={"file_path": "/test.py"},
            tool_use_id="toolu_123",
            message=message,
            agent_id="agent-123"
        )

        assert event.timestamp == sample_datetime
        assert event.session_id == session_id
        assert event.event_type == "tool_use"
        assert event.agent_id == "agent-123"

    def test_session_end_event_attributes(self, sample_datetime, session_id):
        """SessionEndEvent should have reason and optional fields."""
        event = SessionEndEvent(
            timestamp=sample_datetime,
            session_id=session_id,
            reason="idle_timeout",
            idle_duration=timedelta(minutes=5),
            message_count=10,
            tool_count=5
        )

        assert event.reason == "idle_timeout"
        assert event.idle_duration == timedelta(minutes=5)
        assert event.message_count == 10
        assert event.tool_count == 5


class TestToolCallCompletedEvent:
    """Test ToolCallCompletedEvent properties."""

    def test_tool_name_property(self, sample_datetime, session_id):
        """ToolCallCompletedEvent should expose tool_name."""
        tool_use = ToolUseBlock(
            id="toolu_123",
            name="Read",
            input={"file_path": "/test.py"}
        )
        tool_result = ToolResultBlock(
            tool_use_id="toolu_123",
            content="file content",
            is_error=False
        )
        request_msg = Message(
            uuid="msg-1",
            parent_uuid=None,
            timestamp=sample_datetime,
            role=MessageRole.ASSISTANT,
            content=[tool_use],
            session_id=session_id
        )
        response_msg = Message(
            uuid="msg-2",
            parent_uuid="msg-1",
            timestamp=sample_datetime,
            role=MessageRole.USER,
            content=[tool_result],
            session_id=session_id
        )
        tool_call = ToolCall(
            tool_use=tool_use,
            tool_result=tool_result,
            request_message=request_msg,
            response_message=response_msg
        )

        event = ToolCallCompletedEvent(
            timestamp=sample_datetime,
            session_id=session_id,
            tool_call=tool_call
        )

        assert event.tool_name == "Read"

    def test_is_error_property(self, sample_datetime, session_id):
        """ToolCallCompletedEvent should expose is_error."""
        tool_use = ToolUseBlock(
            id="toolu_123",
            name="Bash",
            input={"command": "ls"}
        )
        tool_result = ToolResultBlock(
            tool_use_id="toolu_123",
            content="command failed",
            is_error=True
        )
        request_msg = Message(
            uuid="msg-1",
            parent_uuid=None,
            timestamp=sample_datetime,
            role=MessageRole.ASSISTANT,
            content=[tool_use],
            session_id=session_id
        )
        response_msg = Message(
            uuid="msg-2",
            parent_uuid="msg-1",
            timestamp=sample_datetime,
            role=MessageRole.USER,
            content=[tool_result],
            session_id=session_id
        )
        tool_call = ToolCall(
            tool_use=tool_use,
            tool_result=tool_result,
            request_message=request_msg,
            response_message=response_msg
        )

        event = ToolCallCompletedEvent(
            timestamp=sample_datetime,
            session_id=session_id,
            tool_call=tool_call
        )

        assert event.is_error is True

    def test_duration_property_with_messages(self, sample_datetime, session_id):
        """ToolCallCompletedEvent should calculate duration from messages."""
        tool_use = ToolUseBlock(
            id="toolu_123",
            name="Read",
            input={"file_path": "/test.py"}
        )
        tool_result = ToolResultBlock(
            tool_use_id="toolu_123",
            content="content",
            is_error=False
        )

        request_msg = Message(
            uuid="msg-1",
            parent_uuid=None,
            timestamp=sample_datetime,
            role=MessageRole.ASSISTANT,
            content=[tool_use],
            session_id=session_id
        )
        response_msg = Message(
            uuid="msg-2",
            parent_uuid="msg-1",
            timestamp=sample_datetime + timedelta(seconds=5),
            role=MessageRole.USER,
            content=[tool_result],
            session_id=session_id
        )

        tool_call = ToolCall(
            tool_use=tool_use,
            tool_result=tool_result,
            request_message=request_msg,
            response_message=response_msg
        )

        event = ToolCallCompletedEvent(
            timestamp=sample_datetime,
            session_id=session_id,
            tool_call=tool_call
        )

        assert event.duration == timedelta(seconds=5)

    def test_duration_property_without_response_message(self, sample_datetime, session_id):
        """ToolCallCompletedEvent.duration should be None without response_message."""
        tool_use = ToolUseBlock(
            id="toolu_123",
            name="Read",
            input={"file_path": "/test.py"}
        )
        tool_result = ToolResultBlock(
            tool_use_id="toolu_123",
            content="content",
            is_error=False
        )
        request_msg = Message(
            uuid="msg-1",
            parent_uuid=None,
            timestamp=sample_datetime,
            role=MessageRole.ASSISTANT,
            content=[tool_use],
            session_id=session_id
        )
        tool_call = ToolCall(
            tool_use=tool_use,
            tool_result=tool_result,
            request_message=request_msg,
            response_message=None  # No response message
        )

        event = ToolCallCompletedEvent(
            timestamp=sample_datetime,
            session_id=session_id,
            tool_call=tool_call
        )

        assert event.duration is None


class TestTruncateToolInput:
    """Test the truncate_tool_input utility function."""

    def test_short_string_unchanged(self):
        """Short strings should not be truncated."""
        result = truncate_tool_input({"key": "short"}, max_length=100)
        assert result == {"key": "short"}

    def test_long_string_truncated(self):
        """Long strings should be truncated with marker."""
        long_str = "x" * 200
        result = truncate_tool_input({"key": long_str}, max_length=100)
        assert result["key"] == "x" * 100 + "...[truncated]"

    def test_nested_dict_truncated(self):
        """Nested dicts should have strings truncated recursively."""
        data = {"outer": {"inner": "x" * 200}}
        result = truncate_tool_input(data, max_length=50)
        assert result["outer"]["inner"] == "x" * 50 + "...[truncated]"

    def test_list_with_strings_truncated(self):
        """Lists with long strings should have them truncated."""
        data = {"items": ["short", "x" * 200]}
        result = truncate_tool_input(data, max_length=50)
        assert result["items"][0] == "short"
        assert result["items"][1] == "x" * 50 + "...[truncated]"

    def test_list_with_dicts_truncated(self):
        """Lists with dicts containing long strings should be truncated."""
        data = {"items": [{"content": "x" * 200}]}
        result = truncate_tool_input(data, max_length=50)
        assert result["items"][0]["content"] == "x" * 50 + "...[truncated]"

    def test_non_string_values_unchanged(self):
        """Non-string values should be preserved."""
        data = {"number": 42, "boolean": True, "null": None}
        result = truncate_tool_input(data, max_length=10)
        assert result == {"number": 42, "boolean": True, "null": None}

    def test_empty_dict(self):
        """Empty dict should return empty dict."""
        result = truncate_tool_input({})
        assert result == {}

    def test_default_max_length(self):
        """Default max_length should be 1024."""
        data = {"key": "x" * 2000}
        result = truncate_tool_input(data)
        assert len(result["key"]) == 1024 + len("...[truncated]")
