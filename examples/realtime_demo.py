#!/usr/bin/env python3
"""Demo: Realtime session monitoring.

This script demonstrates the realtime API by reading events from
a session file and printing them in a formatted way.

Usage:
    # Process a specific session file
    python realtime_demo.py /path/to/session.jsonl

    # Find and process the most recent session
    python realtime_demo.py --latest

    # Watch for new events (poll mode)
    python realtime_demo.py --latest --watch
"""

import argparse
import sys
import time
from datetime import datetime
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
        "--poll-interval",
        type=float,
        default=0.5,
        help="Poll interval in seconds (default: 0.5)"
    )

    args = parser.parse_args()

    # Determine which file to use
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
    if args.watch:
        print(f"\n{'='*60}")
        print(f"Watching for new events... (Ctrl+C to stop)")
        print(f"{'='*60}")

        try:
            while True:
                new_count = process_new_entries()
                if new_count == 0:
                    time.sleep(args.poll_interval)
        except KeyboardInterrupt:
            print("\n\nStopped.")

    # Print summary
    print(f"\n{'='*60}")
    print(f"Summary:")
    print(f"  Messages:     {stats['messages']}")
    print(f"  Tool uses:    {stats['tool_uses']}")
    print(f"  Tool results: {stats['tool_results']}")
    print(f"  Errors:       {stats['errors']}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
