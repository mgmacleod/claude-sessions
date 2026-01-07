#!/usr/bin/env python3
"""
Export all Claude Code conversations to Markdown files.

This script demonstrates using the claude-sessions library to export
all conversations to human-readable markdown format, organized by project.

Usage:
    python export_all_to_markdown.py
    python export_all_to_markdown.py -o ./my_exports
    python export_all_to_markdown.py --project myproject --no-tools
"""

import argparse
import sys
from pathlib import Path

from claude_sessions import ClaudeSessions
from claude_sessions.export import export_session_markdown


def main():
    parser = argparse.ArgumentParser(
        description="Export Claude Code conversations to Markdown files."
    )
    parser.add_argument(
        "-o", "--output-dir",
        type=Path,
        default=Path("./claude_exports"),
        help="Output directory for exported files (default: ./claude_exports)"
    )
    parser.add_argument(
        "-p", "--project",
        type=str,
        default=None,
        help="Filter to projects containing this string"
    )
    parser.add_argument(
        "--no-tools",
        action="store_true",
        help="Exclude tool calls from output"
    )
    parser.add_argument(
        "--no-agents",
        action="store_true",
        help="Exclude sub-agent conversations from output"
    )
    parser.add_argument(
        "--include-metadata",
        action="store_true",
        help="Include working directory and git branch per message"
    )

    args = parser.parse_args()

    # Load sessions
    print("Loading sessions from ~/.claude ...")
    sessions = ClaudeSessions.load(project_filter=args.project)

    if sessions.session_count == 0:
        print("No sessions found.")
        sys.exit(0)

    print(f"Found {sessions.session_count} sessions across {sessions.project_count} projects")

    # Create output directory
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Export settings
    include_tools = not args.no_tools
    include_agents = not args.no_agents

    # Track statistics
    exported_count = 0
    skipped_count = 0

    # Export each session, organized by project
    for project in sessions.projects.values():
        # Create project subdirectory
        project_dir = args.output_dir / project.slug
        project_dir.mkdir(exist_ok=True)

        for session in project.sessions.values():
            # Generate filename: {session_id_prefix}_{date}.md
            if session.start_time:
                date_str = session.start_time.strftime("%Y-%m-%d")
            else:
                date_str = "unknown"

            filename = f"{session.session_id[:8]}_{date_str}.md"
            output_path = project_dir / filename

            try:
                export_session_markdown(
                    session,
                    output_path,
                    include_tools=include_tools,
                    include_agents=include_agents,
                    include_metadata=args.include_metadata
                )
                exported_count += 1
            except Exception as e:
                print(f"  Error exporting {session.session_id}: {e}")
                skipped_count += 1

    print(f"\nExported {exported_count} sessions to {args.output_dir}")
    if skipped_count > 0:
        print(f"Skipped {skipped_count} sessions due to errors")


if __name__ == "__main__":
    main()
