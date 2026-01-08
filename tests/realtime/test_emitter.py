"""Tests for claude_sessions.realtime.emitter module."""

from datetime import datetime, timezone

import pytest

from claude_sessions.realtime.emitter import EventEmitter
from claude_sessions.realtime.events import (
    MessageEvent,
    ToolUseEvent,
    ErrorEvent,
)
from claude_sessions.models import Message, MessageRole, TextBlock


@pytest.fixture
def emitter():
    """Create a fresh EventEmitter instance."""
    return EventEmitter()


@pytest.fixture
def sample_message_event(sample_datetime, session_id):
    """Create a sample MessageEvent for testing."""
    message = Message(
        uuid="test-uuid",
        parent_uuid=None,
        timestamp=sample_datetime,
        role=MessageRole.USER,
        content=[TextBlock(text="Hello")],
        session_id=session_id
    )
    return MessageEvent(
        timestamp=sample_datetime,
        session_id=session_id,
        message=message
    )


@pytest.fixture
def sample_tool_use_event(sample_datetime, session_id):
    """Create a sample ToolUseEvent for testing."""
    message = Message(
        uuid="test-uuid",
        parent_uuid=None,
        timestamp=sample_datetime,
        role=MessageRole.ASSISTANT,
        content=[],
        session_id=session_id
    )
    return ToolUseEvent(
        timestamp=sample_datetime,
        session_id=session_id,
        tool_name="Read",
        tool_category="file_read",
        tool_input={"file_path": "/test.py"},
        tool_use_id="toolu_123",
        message=message
    )


@pytest.fixture
def sample_error_event(sample_datetime, session_id):
    """Create a sample ErrorEvent for testing."""
    return ErrorEvent(
        timestamp=sample_datetime,
        session_id=session_id,
        error_message="Test error"
    )


class TestHandlerRegistration:
    """Test handler registration methods."""

    def test_on_as_decorator(self, emitter, sample_message_event):
        """on() should work as a decorator."""
        received = []

        @emitter.on("message")
        def handler(event):
            received.append(event)

        emitter.emit(sample_message_event)
        assert len(received) == 1
        assert received[0] is sample_message_event

    def test_on_as_direct_call(self, emitter, sample_message_event):
        """on() should work as a direct method call."""
        received = []

        def handler(event):
            received.append(event)

        emitter.on("message", handler)

        emitter.emit(sample_message_event)
        assert len(received) == 1

    def test_on_returns_handler(self, emitter):
        """on() should return the handler function."""
        def handler(event):
            pass

        result = emitter.on("message", handler)
        assert result is handler

    def test_off_removes_handler(self, emitter, sample_message_event):
        """off() should remove a registered handler."""
        received = []

        def handler(event):
            received.append(event)

        emitter.on("message", handler)
        result = emitter.off("message", handler)

        assert result is True
        emitter.emit(sample_message_event)
        assert len(received) == 0

    def test_off_returns_false_for_unknown_handler(self, emitter):
        """off() should return False if handler not found."""
        def handler(event):
            pass

        result = emitter.off("message", handler)
        assert result is False

    def test_on_any_receives_all_events(self, emitter, sample_message_event, sample_tool_use_event):
        """on_any() handler should receive all event types."""
        received = []

        @emitter.on_any
        def handler(event):
            received.append(event)

        emitter.emit(sample_message_event)
        emitter.emit(sample_tool_use_event)

        assert len(received) == 2
        assert received[0] is sample_message_event
        assert received[1] is sample_tool_use_event

    def test_off_any_removes_wildcard_handler(self, emitter, sample_message_event):
        """off_any() should remove a wildcard handler."""
        received = []

        def handler(event):
            received.append(event)

        emitter.on_any(handler)
        result = emitter.off_any(handler)

        assert result is True
        emitter.emit(sample_message_event)
        assert len(received) == 0


class TestEventDispatch:
    """Test event dispatch behavior."""

    def test_emit_dispatches_to_correct_type(self, emitter, sample_message_event, sample_tool_use_event):
        """emit() should only dispatch to handlers for that event type."""
        message_received = []
        tool_received = []

        @emitter.on("message")
        def msg_handler(event):
            message_received.append(event)

        @emitter.on("tool_use")
        def tool_handler(event):
            tool_received.append(event)

        emitter.emit(sample_message_event)

        assert len(message_received) == 1
        assert len(tool_received) == 0

    def test_emit_returns_handler_count(self, emitter, sample_message_event):
        """emit() should return the number of handlers called."""
        @emitter.on("message")
        def handler1(event):
            pass

        @emitter.on("message")
        def handler2(event):
            pass

        count = emitter.emit(sample_message_event)
        assert count == 2

    def test_emit_counts_wildcard_handlers(self, emitter, sample_message_event):
        """emit() should count both type-specific and wildcard handlers."""
        @emitter.on("message")
        def specific(event):
            pass

        @emitter.on_any
        def wildcard(event):
            pass

        count = emitter.emit(sample_message_event)
        assert count == 2

    def test_emit_all_processes_multiple_events(self, emitter, sample_message_event, sample_tool_use_event):
        """emit_all() should process all events and return total handler calls."""
        received = []

        @emitter.on_any
        def handler(event):
            received.append(event)

        total = emitter.emit_all([sample_message_event, sample_tool_use_event])

        assert len(received) == 2
        assert total == 2


class TestExceptionHandling:
    """Test that handler exceptions don't crash the emitter."""

    def test_handler_exception_isolated(self, emitter, sample_message_event):
        """Exception in one handler should not affect others."""
        received = []

        @emitter.on("message")
        def bad_handler(event):
            raise ValueError("Handler error")

        @emitter.on("message")
        def good_handler(event):
            received.append(event)

        # Should not raise
        count = emitter.emit(sample_message_event)

        # Good handler should still be called
        assert len(received) == 1
        # Count reflects only successfully completed handlers
        assert count == 1


class TestClearHandlers:
    """Test handler clearing functionality."""

    def test_clear_specific_type(self, emitter):
        """clear() with type should only clear handlers for that type."""
        @emitter.on("message")
        def msg_handler(event):
            pass

        @emitter.on("tool_use")
        def tool_handler(event):
            pass

        emitter.clear("message")

        assert not emitter.has_handlers("message")
        assert emitter.has_handlers("tool_use")

    def test_clear_all(self, emitter):
        """clear() without args should clear all handlers."""
        @emitter.on("message")
        def msg_handler(event):
            pass

        @emitter.on("tool_use")
        def tool_handler(event):
            pass

        @emitter.on_any
        def wildcard(event):
            pass

        emitter.clear()

        assert emitter.handler_count == 0


class TestHandlerCount:
    """Test handler counting functionality."""

    def test_handler_count_empty(self, emitter):
        """handler_count should be 0 initially."""
        assert emitter.handler_count == 0

    def test_handler_count_increments(self, emitter):
        """handler_count should track registered handlers."""
        @emitter.on("message")
        def handler1(event):
            pass

        @emitter.on("message")
        def handler2(event):
            pass

        @emitter.on_any
        def wildcard(event):
            pass

        assert emitter.handler_count == 3

    def test_has_handlers_true(self, emitter):
        """has_handlers() should return True when handlers exist."""
        @emitter.on("message")
        def handler(event):
            pass

        assert emitter.has_handlers("message") is True

    def test_has_handlers_false(self, emitter):
        """has_handlers() should return False when no handlers exist."""
        assert emitter.has_handlers("message") is False

    def test_has_handlers_with_wildcard(self, emitter):
        """has_handlers() should consider wildcard handlers."""
        @emitter.on_any
        def wildcard(event):
            pass

        # Even though no specific "message" handler, wildcard counts
        assert emitter.has_handlers("message") is True
