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

Example usage (async with AsyncSessionWatcher):
    import asyncio
    from claude_sessions.realtime import AsyncSessionWatcher

    async def main():
        async with AsyncSessionWatcher() as watcher:
            async for event in watcher.events():
                print(f"{event.event_type}: {event.session_id[:8]}")

    asyncio.run(main())

Example usage (with filters and metrics):
    from claude_sessions.realtime import SessionWatcher, MetricsCollector, filters

    watcher = SessionWatcher()
    metrics = MetricsCollector()

    # Route all events to metrics
    watcher.on_any(metrics.handle_event)

    # Filter for file operations
    file_ops = filters.FilterPipeline(
        filters.tool_category("file_read", "file_write")
    )

    @file_ops.on("tool_use")
    def on_file_tool(event):
        print(f"File: {event.tool_name}")

    @watcher.on_any
    def route(event):
        file_ops.process(event)

    watcher.start()
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

# Phase 4: Advanced features
from .async_watcher import AsyncSessionWatcher
from . import filters
from .filters import FilterPipeline, EventFilter
from .metrics import (
    MetricsCollector,
    Counter,
    Gauge,
    Histogram,
)
from .state import (
    WatcherState,
    FilePosition,
    StatePersistence,
)

# Phase 5: Integrations
from .formatters import (
    OutputFormatter,
    PlainFormatter,
    JsonFormatter,
    CompactFormatter,
    get_formatter,
)
from .prometheus_server import PrometheusServer
from .webhook import (
    WebhookDispatcher,
    WebhookConfig,
    WebhookPayload,
    serialize_event,
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
    # Async watcher (Phase 4)
    "AsyncSessionWatcher",
    # Filters (Phase 4)
    "filters",
    "FilterPipeline",
    "EventFilter",
    # Metrics (Phase 4)
    "MetricsCollector",
    "Counter",
    "Gauge",
    "Histogram",
    # State persistence (Phase 4)
    "WatcherState",
    "FilePosition",
    "StatePersistence",
    # Formatters (Phase 5)
    "OutputFormatter",
    "PlainFormatter",
    "JsonFormatter",
    "CompactFormatter",
    "get_formatter",
    # Prometheus server (Phase 5)
    "PrometheusServer",
    # Webhook dispatcher (Phase 5)
    "WebhookDispatcher",
    "WebhookConfig",
    "WebhookPayload",
    "serialize_event",
]
