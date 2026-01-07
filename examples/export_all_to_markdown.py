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
import re
import sys
from pathlib import Path

from claude_sessions import ClaudeSessions, Session, MessageRole
from claude_sessions.export import export_session_markdown


def session_to_filename(session: Session, max_length: int = 40) -> str:
    """
    Generate a human-readable filename from a session.

    Uses the first user message to create a kebab-case slug,
    prefixed with the date and session ID snippet.

    Example: 2025-01-05_a1b2c3d4_help-me-fix-the-login-bug.md
    """
    # Date prefix
    if session.start_time:
        date_str = session.start_time.strftime("%Y-%m-%d")
    else:
        date_str = "unknown"

    # Session ID snippet for uniqueness
    session_prefix = session.session_id[:8]

    # Extract first user message text
    slug = ""
    for msg in session.main_thread.messages:
        if msg.role == MessageRole.USER and msg.text_content:
            text = msg.text_content.strip()
            # Strip XML-style metadata tags (e.g., <ide_opened_file>...</ide_opened_file>)
            text = re.sub(r'<[^>]+>[^<]*</[^>]+>', '', text).strip()
            if not text:
                continue  # Skip messages that are only metadata
            # Convert to kebab-case slug
            # Lowercase, replace non-alphanumeric with hyphens, collapse multiple hyphens
            slug = text.lower()
            slug = re.sub(r'[^a-z0-9]+', '-', slug)
            slug = re.sub(r'-+', '-', slug)
            slug = slug.strip('-')
            # Truncate to max_length, avoiding mid-word cuts
            if len(slug) > max_length:
                slug = slug[:max_length].rsplit('-', 1)[0]
            break

    if slug:
        return f"{date_str}_{session_prefix}_{slug}.md"
    else:
        return f"{date_str}_{session_prefix}.md"


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
        "-m", "--include-metadata",
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
            filename = session_to_filename(session)
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
