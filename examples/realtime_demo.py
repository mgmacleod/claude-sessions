#!/usr/bin/env python3
"""Demo: Realtime session monitoring.

This script demonstrates the realtime API by reading events from
session files and printing them in a formatted way.

Usage:
    # Watch all sessions (high-level API using SessionWatcher)
    python realtime_demo.py --watch-all

    # Process a specific session file (low-level API)
    python realtime_demo.py /path/to/session.jsonl

    # Find and process the most recent session
    python realtime_demo.py --latest

    # Watch a specific file for new events
    python realtime_demo.py --latest --watch
"""

import argparse
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# Add parent directory to path for development
sys.path.insert(0, str(Path(__file__).parent.parent))

from claude_sessions.realtime import (
    JSONLTailer,
    IncrementalParser,
    EventEmitter,
    MessageEvent,
    ToolUseEvent,
    ToolResultEvent,
    ErrorEvent,
    SessionWatcher,
    WatcherConfig,
    SessionStartEvent,
    SessionEndEvent,
    SessionIdleEvent,
    SessionResumeEvent,
)


def find_latest_session() -> Optional[Path]:
    """Find the most recently modified session file."""
    claude_dir = Path.home() / ".claude" / "projects"

    if not claude_dir.exists():
        return None

    # Find all JSONL files
    session_files = list(claude_dir.glob("**/*.jsonl"))

    if not session_files:
        return None

    # Return the most recently modified
    return max(session_files, key=lambda p: p.stat().st_mtime)


def format_timestamp(ts: datetime) -> str:
    """Format timestamp for display."""
    return ts.strftime("%H:%M:%S")


def truncate_text(text: str, max_length: int = 80) -> str:
    """Truncate text for display."""
    text = text.replace("\n", " ").strip()
    if len(text) > max_length:
        return text[:max_length - 3] + "..."
    return text


def run_watch_all(poll_interval: float = 0.5, idle_timeout: float = 120.0):
    """Watch all sessions using the high-level SessionWatcher API."""
    config = WatcherConfig(
        poll_interval=poll_interval,
        idle_timeout=timedelta(seconds=idle_timeout),
        end_timeout=timedelta(seconds=idle_timeout * 2.5),
    )
    watcher = SessionWatcher(config)

    # Track stats per session
    stats: dict = {}

    def get_stats(session_id: str) -> dict:
        if session_id not in stats:
            stats[session_id] = {
                "messages": 0,
                "tool_uses": 0,
                "tool_results": 0,
                "errors": 0,
            }
        return stats[session_id]

    @watcher.on("session_start")
    def on_session_start(event: SessionStartEvent):
        print(f"\n{'='*60}")
        print(f"SESSION STARTED: {event.session_id[:8]}")
        print(f"  Project: {event.project_slug}")
        print(f"  File: {event.file_path.name}")
        print(f"{'='*60}")

    @watcher.on("session_idle")
    def on_session_idle(event: SessionIdleEvent):
        s = get_stats(event.session_id)
        print(f"\n  [Session {event.session_id[:8]} is now idle]")
        print(f"    Messages: {s['messages']}, Tools: {s['tool_uses']}")

    @watcher.on("session_resume")
    def on_session_resume(event: SessionResumeEvent):
        idle_secs = event.idle_duration.total_seconds()
        print(f"\n  [Session {event.session_id[:8]} resumed after {idle_secs:.0f}s]")

    @watcher.on("session_end")
    def on_session_end(event: SessionEndEvent):
        print(f"\n{'='*60}")
        print(f"SESSION ENDED: {event.session_id[:8]}")
        print(f"  Reason: {event.reason}")
        print(f"  Messages: {event.message_count}, Tools: {event.tool_count}")
        print(f"{'='*60}")
        stats.pop(event.session_id, None)

    @watcher.on("message")
    def on_message(event: MessageEvent):
        get_stats(event.session_id)["messages"] += 1
        role = event.message.role.value.upper()
        text = truncate_text(event.message.text_content)
        agent_prefix = f"[{event.agent_id[:8]}] " if event.agent_id else ""
        session_prefix = f"[{event.session_id[:8]}] "

        print(f"\n[{format_timestamp(event.timestamp)}] {session_prefix}{agent_prefix}{role}:")
        if text:
            print(f"  {text}")

    @watcher.on("tool_use")
    def on_tool_use(event: ToolUseEvent):
        get_stats(event.session_id)["tool_uses"] += 1
        agent_prefix = f"[{event.agent_id[:8]}] " if event.agent_id else ""

        # Format tool-specific info
        details = ""
        if event.tool_name == "Bash":
            cmd = event.tool_input.get("command", "")
            details = f": {truncate_text(cmd, 60)}"
        elif event.tool_name in ("Read", "Write", "Edit"):
            path = event.tool_input.get("file_path", "")
            details = f": {path}"
        elif event.tool_name == "Grep":
            pattern = event.tool_input.get("pattern", "")
            details = f": /{pattern}/"
        elif event.tool_name == "Task":
            desc = event.tool_input.get("description", "")
            details = f": {desc}"

        print(f"  {agent_prefix}-> {event.tool_name} ({event.tool_category}){details}")

    @watcher.on("tool_result")
    def on_tool_result(event: ToolResultEvent):
        get_stats(event.session_id)["tool_results"] += 1
        if event.is_error:
            print(f"     ERROR: {truncate_text(event.content, 60)}")

    @watcher.on("error")
    def on_error(event: ErrorEvent):
        get_stats(event.session_id)["errors"] += 1
        print(f"\n  PARSE ERROR: {event.error_message}")

    print(f"\n{'='*60}")
    print("Watching all Claude Code sessions...")
    print(f"Poll interval: {poll_interval}s, Idle timeout: {idle_timeout}s")
    print("Press Ctrl+C to stop")
    print(f"{'='*60}")

    try:
        watcher.start()
    except KeyboardInterrupt:
        print("\n\nStopped.")

    # Print final summary
    if stats:
        print(f"\n{'='*60}")
        print("Active sessions at exit:")
        for session_id, s in stats.items():
            print(f"  {session_id[:8]}: {s['messages']} msgs, {s['tool_uses']} tools")
        print(f"{'='*60}")


def run_single_file(session_file: Path, watch: bool = False, poll_interval: float = 0.5):
    """Process a single session file using the low-level API."""
    # Set up components
    tailer = JSONLTailer(session_file)
    incremental_parser = IncrementalParser()
    emitter = EventEmitter()

    # Track stats
    stats = {"messages": 0, "tool_uses": 0, "tool_results": 0, "errors": 0}

    @emitter.on("message")
    def on_message(event: MessageEvent):
        stats["messages"] += 1
        role = event.message.role.value.upper()
        text = truncate_text(event.message.text_content)
        agent_prefix = f"[{event.agent_id[:8]}] " if event.agent_id else ""

        print(f"\n[{format_timestamp(event.timestamp)}] {agent_prefix}{role}:")
        if text:
            print(f"  {text}")

    @emitter.on("tool_use")
    def on_tool_use(event: ToolUseEvent):
        stats["tool_uses"] += 1
        agent_prefix = f"[{event.agent_id[:8]}] " if event.agent_id else ""

        # Format tool-specific info
        details = ""
        if event.tool_name == "Bash":
            cmd = event.tool_input.get("command", "")
            details = f": {truncate_text(cmd, 60)}"
        elif event.tool_name in ("Read", "Write", "Edit"):
            path = event.tool_input.get("file_path", "")
            details = f": {path}"
        elif event.tool_name == "Grep":
            pattern = event.tool_input.get("pattern", "")
            details = f": /{pattern}/"
        elif event.tool_name == "Task":
            desc = event.tool_input.get("description", "")
            details = f": {desc}"

        print(f"  {agent_prefix}-> {event.tool_name} ({event.tool_category}){details}")

    @emitter.on("tool_result")
    def on_tool_result(event: ToolResultEvent):
        stats["tool_results"] += 1
        if event.is_error:
            print(f"     ERROR: {truncate_text(event.content, 60)}")

    @emitter.on("error")
    def on_error(event: ErrorEvent):
        stats["errors"] += 1
        print(f"\n  PARSE ERROR: {event.error_message}")

    # Process events
    print(f"\n{'='*60}")
    print(f"Session: {session_file.name}")
    print(f"{'='*60}")

    def process_new_entries():
        """Process any new entries from the file."""
        entries = tailer.read_new()
        for entry in entries:
            events = incremental_parser.parse_entry(entry)
            emitter.emit_all(events)
        return len(entries)

    # Initial read
    process_new_entries()

    # Watch mode
    if watch:
        print(f"\n{'='*60}")
        print("Watching for new events... (Ctrl+C to stop)")
        print(f"{'='*60}")

        try:
            while True:
                new_count = process_new_entries()
                if new_count == 0:
                    time.sleep(poll_interval)
        except KeyboardInterrupt:
            print("\n\nStopped.")

    # Print summary
    print(f"\n{'='*60}")
    print("Summary:")
    print(f"  Messages:     {stats['messages']}")
    print(f"  Tool uses:    {stats['tool_uses']}")
    print(f"  Tool results: {stats['tool_results']}")
    print(f"  Errors:       {stats['errors']}")
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(
        description="Demo realtime session monitoring"
    )
    parser.add_argument(
        "file",
        nargs="?",
        help="Path to session JSONL file"
    )
    parser.add_argument(
        "--latest",
        action="store_true",
        help="Use the most recent session file"
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Watch for new events (poll every 0.5s)"
    )
    parser.add_argument(
        "--watch-all",
        action="store_true",
        help="Watch all sessions using SessionWatcher (high-level API)"
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.5,
        help="Poll interval in seconds (default: 0.5)"
    )
    parser.add_argument(
        "--idle-timeout",
        type=float,
        default=120.0,
        help="Idle timeout in seconds for --watch-all (default: 120)"
    )

    args = parser.parse_args()

    # High-level API: watch all sessions
    if args.watch_all:
        run_watch_all(
            poll_interval=args.poll_interval,
            idle_timeout=args.idle_timeout,
        )
        return

    # Low-level API: process a single file
    if args.file:
        session_file = Path(args.file)
    elif args.latest:
        session_file = find_latest_session()
        if session_file is None:
            print("No session files found in ~/.claude/projects/")
            sys.exit(1)
        print(f"Using: {session_file}")
    else:
        parser.print_help()
        sys.exit(1)

    if not session_file.exists():
        print(f"File not found: {session_file}")
        sys.exit(1)

    run_single_file(
        session_file,
        watch=args.watch,
        poll_interval=args.poll_interval,
    )


if __name__ == "__main__":
    main()
