"""Realtime session monitoring and event streaming.

This module provides components for tailing Claude Code session files
and emitting events as new messages and tool calls appear.

Example usage (low-level):
    from claude_sessions.realtime import JSONLTailer, IncrementalParser, EventEmitter

    tailer = JSONLTailer(session_file)
    parser = IncrementalParser()
    emitter = EventEmitter()

    @emitter.on("message")
    def on_message(event):
        print(f"{event.message.role}: {event.message.text_content[:80]}")

    for entry in tailer.read_new():
        for event in parser.parse_entry(entry):
            emitter.emit(event)

Example usage (high-level with SessionWatcher):
    from claude_sessions.realtime import SessionWatcher

    watcher = SessionWatcher()

    @watcher.on("session_start")
    def on_start(event):
        print(f"New session: {event.session_id[:8]}")

    @watcher.on("message")
    def on_message(event):
        print(f"{event.message.role}: {event.message.text_content[:80]}")

    watcher.start()  # Blocks until Ctrl+C
"""

from .events import (
    SessionEvent,
    MessageEvent,
    ToolUseEvent,
    ToolResultEvent,
    ErrorEvent,
    SessionStartEvent,
    SessionEndEvent,
    SessionIdleEvent,
    SessionResumeEvent,
    ToolCallCompletedEvent,
    SessionEventType,
    truncate_tool_input,
)
from .tailer import JSONLTailer, TailerState, MultiFileTailer
from .parser import IncrementalParser
from .emitter import EventEmitter
from .watcher import SessionWatcher, WatcherConfig, TrackedSession
from .live import (
    LiveSession,
    LiveSessionManager,
    LiveSessionConfig,
    RetentionPolicy,
)

__all__ = [
    # Event types
    "SessionEvent",
    "MessageEvent",
    "ToolUseEvent",
    "ToolResultEvent",
    "ErrorEvent",
    "SessionStartEvent",
    "SessionEndEvent",
    "SessionIdleEvent",
    "SessionResumeEvent",
    "ToolCallCompletedEvent",
    "SessionEventType",
    # Utilities
    "truncate_tool_input",
    # Core components
    "JSONLTailer",
    "TailerState",
    "MultiFileTailer",
    "IncrementalParser",
    "EventEmitter",
    # Session watcher (Phase 2)
    "SessionWatcher",
    "WatcherConfig",
    "TrackedSession",
    # Live state management (Phase 3)
    "LiveSession",
    "LiveSessionManager",
    "LiveSessionConfig",
    "RetentionPolicy",
]
