#!/usr/bin/env python3
"""Example: Send Claude Code session events to Slack.

This example demonstrates sending filtered session events to a Slack
webhook. Only errors and session completions are sent to avoid noise.

Usage:
    export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."
    python slack_webhook.py

The webhook sends Slack Block Kit formatted messages that look like:

    :warning: Error in session a1b2c3d4
    Parse error: Unexpected token...

    :checkered_flag: Session ended
    Session: `a1b2c3d4`
    Messages: 42, Tools: 15

To set up a Slack webhook:
1. Go to https://api.slack.com/apps
2. Create a new app or select existing
3. Enable "Incoming Webhooks"
4. Create a webhook for your channel
5. Copy the webhook URL
"""

import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Add parent directory for development
sys.path.insert(0, str(Path(__file__).parent.parent))

from claude_sessions.realtime import SessionWatcher, filters
from claude_sessions.realtime.events import SessionEventType


def format_slack_message(event: SessionEventType) -> dict | None:
    """Format an event as a Slack Block Kit message.

    Args:
        event: The session event to format

    Returns:
        Slack Block Kit payload or None if event shouldn't be sent
    """
    if event.event_type == "error":
        return {
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f":warning: *Error in session {event.session_id[:8]}*\n"
                            f"```{event.error_message[:500]}```"
                        ),
                    },
                }
            ]
        }

    elif event.event_type == "tool_result" and event.is_error:
        return {
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f":x: *Tool error in session {event.session_id[:8]}*\n"
                            f"```{event.content[:500]}```"
                        ),
                    },
                }
            ]
        }

    elif event.event_type == "session_end":
        emoji = ":white_check_mark:" if event.reason == "idle_timeout" else ":checkered_flag:"
        return {
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"{emoji} *Session ended*\n"
                            f"Session: `{event.session_id[:8]}`\n"
                            f"Reason: {event.reason}\n"
                            f"Messages: {event.message_count}, Tools: {event.tool_count}"
                        ),
                    },
                }
            ]
        }

    elif event.event_type == "session_start":
        return {
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f":rocket: *New session started*\n"
                            f"Session: `{event.session_id[:8]}`\n"
                            f"Project: {event.project_slug}"
                        ),
                    },
                }
            ]
        }

    return None


def send_to_slack(webhook_url: str, payload: dict) -> bool:
    """Send a payload to a Slack webhook.

    Args:
        webhook_url: Slack webhook URL
        payload: Slack message payload

    Returns:
        True if successful, False otherwise
    """
    try:
        req = Request(
            webhook_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=10) as response:
            return response.status == 200
    except (HTTPError, URLError, TimeoutError) as e:
        print(f"Failed to send to Slack: {e}", file=sys.stderr)
        return False


def main():
    # Get Slack webhook URL from environment
    slack_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not slack_url:
        print("Error: Set SLACK_WEBHOOK_URL environment variable")
        print()
        print("To get a webhook URL:")
        print("1. Go to https://api.slack.com/apps")
        print("2. Create/select app -> Incoming Webhooks")
        print("3. Create webhook for your channel")
        sys.exit(1)

    # Create watcher
    watcher = SessionWatcher()

    # Define which events to send
    # Only send: errors, tool errors, session start/end
    event_filter = filters.or_(
        filters.event_type("error"),
        filters.event_type("session_start"),
        filters.event_type("session_end"),
        filters.has_error(),  # Includes tool_result with is_error=True
    )

    # Track stats
    stats = {"sent": 0, "skipped": 0, "failed": 0}

    @watcher.on_any
    def handle_event(event: SessionEventType) -> None:
        # Apply filter
        if not event_filter(event):
            stats["skipped"] += 1
            return

        # Format for Slack
        payload = format_slack_message(event)
        if payload is None:
            stats["skipped"] += 1
            return

        # Send to Slack
        if send_to_slack(slack_url, payload):
            stats["sent"] += 1
            print(f"Sent {event.event_type} to Slack")
        else:
            stats["failed"] += 1

    print("=" * 60)
    print("Slack Webhook Integration")
    print(f"Sending to: {slack_url[:50]}...")
    print("Events: errors, session_start, session_end")
    print("Press Ctrl+C to stop")
    print("=" * 60)

    try:
        watcher.start()
    except KeyboardInterrupt:
        print()

    print()
    print("=" * 60)
    print("Summary:")
    print(f"  Sent: {stats['sent']}")
    print(f"  Skipped: {stats['skipped']}")
    print(f"  Failed: {stats['failed']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
