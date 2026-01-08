#!/usr/bin/env python3
"""Example: Structured logging of Claude Code session events.

This example outputs session events as JSON lines suitable for ingestion
into log aggregation systems like Elasticsearch, Datadog, or Splunk.

Usage:
    # Output to stdout (pipe to jq for pretty printing)
    python structured_logging.py | jq .

    # Output to file
    python structured_logging.py >> claude_sessions.log

    # With filtering
    python structured_logging.py --tools-only

Output format:
    {
        "@timestamp": "2024-01-15T14:32:05.123456+00:00",
        "logger": "claude-sessions",
        "level": "info",
        "event_type": "message",
        "session_id": "abc123...",
        "role": "user",
        "text": "Help me fix this bug..."
    }

This format is compatible with:
- Elasticsearch (ELK stack) - @timestamp field
- Datadog - standard JSON log format
- Splunk - auto-extracted fields
- CloudWatch Logs Insights - JSON parsing
- Grafana Loki - JSON labels
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add parent directory for development
sys.path.insert(0, str(Path(__file__).parent.parent))

from claude_sessions.realtime import SessionWatcher, filters
from claude_sessions.realtime.formatters import JsonFormatter
from claude_sessions.realtime.events import SessionEventType


def enrich_log_entry(event: SessionEventType, base_data: dict) -> dict:
    """Enrich a log entry with standard logging fields.

    Args:
        event: The session event
        base_data: Base serialized event data from JsonFormatter

    Returns:
        Enriched log entry with standard logging fields
    """
    # Determine log level based on event type
    if event.event_type == "error":
        level = "error"
    elif event.event_type == "tool_result" and event.is_error:
        level = "warning"
    elif event.event_type in ("session_start", "session_end"):
        level = "info"
    else:
        level = "debug"

    # Build enriched entry
    entry = {
        # Standard logging fields (at top for visibility)
        "@timestamp": datetime.now(timezone.utc).isoformat(),
        "logger": "claude-sessions",
        "level": level,
        # Event data
        **base_data,
    }

    # Add service context
    entry["service"] = {
        "name": "claude-sessions",
        "type": "session-monitor",
    }

    return entry


def main():
    parser = argparse.ArgumentParser(
        description="Output Claude Code session events as structured logs"
    )
    parser.add_argument(
        "--tools-only",
        action="store_true",
        help="Only log tool_use and tool_result events",
    )
    parser.add_argument(
        "--errors-only",
        action="store_true",
        help="Only log error events",
    )
    parser.add_argument(
        "--min-level",
        choices=["debug", "info", "warning", "error"],
        default="debug",
        help="Minimum log level to output (default: debug)",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON (for debugging, not recommended for production)",
    )

    args = parser.parse_args()

    # Build filter based on arguments
    filter_list = []
    if args.tools_only:
        filter_list.append(filters.event_type("tool_use", "tool_result"))
    if args.errors_only:
        filter_list.append(filters.has_error())

    event_filter = None
    if filter_list:
        event_filter = filters.and_(*filter_list) if len(filter_list) > 1 else filter_list[0]

    # Level filtering
    level_order = {"debug": 0, "info": 1, "warning": 2, "error": 3}
    min_level_num = level_order[args.min_level]

    # Set up formatter
    formatter = JsonFormatter()

    # Create watcher
    watcher = SessionWatcher()

    # Log startup
    startup_log = {
        "@timestamp": datetime.now(timezone.utc).isoformat(),
        "logger": "claude-sessions",
        "level": "info",
        "message": "Session monitoring started",
        "filters": {
            "tools_only": args.tools_only,
            "errors_only": args.errors_only,
            "min_level": args.min_level,
        },
    }
    print(json.dumps(startup_log))
    sys.stdout.flush()

    @watcher.on_any
    def log_event(event: SessionEventType) -> None:
        # Apply event filter if configured
        if event_filter and not event_filter(event):
            return

        # Get base serialized data
        base_data = json.loads(formatter.format(event))

        # Enrich with logging fields
        log_entry = enrich_log_entry(event, base_data)

        # Apply level filter
        event_level = level_order.get(log_entry["level"], 0)
        if event_level < min_level_num:
            return

        # Output
        if args.pretty:
            print(json.dumps(log_entry, indent=2, default=str))
        else:
            print(json.dumps(log_entry, default=str))
        sys.stdout.flush()

    try:
        watcher.start()
    except KeyboardInterrupt:
        pass

    # Log shutdown
    shutdown_log = {
        "@timestamp": datetime.now(timezone.utc).isoformat(),
        "logger": "claude-sessions",
        "level": "info",
        "message": "Session monitoring stopped",
    }
    print(json.dumps(shutdown_log))


if __name__ == "__main__":
    main()
