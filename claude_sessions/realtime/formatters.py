"""Output formatters for CLI events.

This module provides formatters to convert session events into various
output formats: human-readable plain text, JSON lines, and compact summaries.

Example usage:
    from claude_sessions.realtime.formatters import PlainFormatter

    formatter = PlainFormatter(use_color=True)
    print(formatter.format(event))
"""

import json
import sys
from abc import ABC, abstractmethod
from dataclasses import asdict
from datetime import datetime
from typing import Any, Dict

from .events import SessionEventType


class OutputFormatter(ABC):
    """Base class for event formatters."""

    @abstractmethod
    def format(self, event: SessionEventType) -> str:
        """Format an event for output.

        Args:
            event: The event to format

        Returns:
            Formatted string representation
        """
        pass


class PlainFormatter(OutputFormatter):
    """Human-readable plain text output with optional colors.

    Produces formatted output suitable for terminal display, with
    optional ANSI color codes for better readability.

    Example output:
        [14:32:05] [a1b2c3d4] USER: Help me fix this bug
        [14:32:06] [a1b2c3d4] -> Read (file_read): /path/to/file.py
        [14:32:06] [a1b2c3d4]    <- ok
    """

    COLORS = {
        "reset": "\033[0m",
        "bold": "\033[1m",
        "dim": "\033[2m",
        "red": "\033[31m",
        "green": "\033[32m",
        "yellow": "\033[33m",
        "blue": "\033[34m",
        "magenta": "\033[35m",
        "cyan": "\033[36m",
        "white": "\033[37m",
    }

    def __init__(self, use_color: bool = True):
        """Initialize the formatter.

        Args:
            use_color: Whether to use ANSI color codes. Auto-detected
                      based on terminal if True.
        """
        # Auto-detect color support
        if use_color:
            self._use_color = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
        else:
            self._use_color = False

    def _color(self, name: str, text: str) -> str:
        """Apply color to text if colors are enabled."""
        if not self._use_color:
            return text
        return f"{self.COLORS.get(name, '')}{text}{self.COLORS['reset']}"

    def _truncate(self, text: str, max_length: int = 80) -> str:
        """Truncate text and replace newlines."""
        text = text.replace("\n", " ").strip()
        if len(text) > max_length:
            return text[: max_length - 3] + "..."
        return text

    def format(self, event: SessionEventType) -> str:
        """Format an event as human-readable text."""
        ts = event.timestamp.strftime("%H:%M:%S")
        sid = event.session_id[:8]
        agent_prefix = f"[{event.agent_id[:8]}] " if event.agent_id else ""

        if event.event_type == "message":
            role = event.message.role.value.upper()
            text = self._truncate(event.message.text_content)
            role_color = "green" if role == "USER" else "blue"
            return (
                f"[{ts}] [{sid}] {agent_prefix}"
                f"{self._color(role_color, role)}: {text}"
            )

        elif event.event_type == "tool_use":
            tool_info = f"{event.tool_name} ({event.tool_category})"
            details = self._format_tool_details(event)
            return (
                f"[{ts}] [{sid}] {agent_prefix}"
                f"{self._color('cyan', '->')} {tool_info}{details}"
            )

        elif event.event_type == "tool_result":
            if event.is_error:
                status = self._color("red", "ERROR")
                content = f": {self._truncate(event.content, 60)}"
            else:
                status = self._color("dim", "ok")
                content = ""
            return f"[{ts}] [{sid}] {agent_prefix}   <- {status}{content}"

        elif event.event_type == "tool_call_completed":
            duration_ms = (
                event.duration.total_seconds() * 1000 if event.duration else 0
            )
            status = self._color("red", "ERROR") if event.is_error else "ok"
            return (
                f"[{ts}] [{sid}] {agent_prefix}   "
                f"{self._color('dim', f'[{event.tool_name} completed in {duration_ms:.0f}ms: {status}]')}"
            )

        elif event.event_type == "session_start":
            header = "=" * 60
            return (
                f"\n{self._color('bold', header)}\n"
                f"SESSION STARTED: {event.session_id[:8]}\n"
                f"  Project: {event.project_slug}\n"
                f"  File: {event.file_path.name}\n"
                f"{self._color('bold', header)}"
            )

        elif event.event_type == "session_end":
            header = "=" * 60
            return (
                f"\n{self._color('bold', header)}\n"
                f"SESSION ENDED: {event.session_id[:8]}\n"
                f"  Reason: {event.reason}\n"
                f"  Messages: {event.message_count}, Tools: {event.tool_count}\n"
                f"{self._color('bold', header)}"
            )

        elif event.event_type == "session_idle":
            return (
                f"[{ts}] [{sid}] "
                f"{self._color('yellow', '[Session is now idle]')}"
            )

        elif event.event_type == "session_resume":
            idle_secs = event.idle_duration.total_seconds()
            return (
                f"[{ts}] [{sid}] "
                f"{self._color('green', f'[Session resumed after {idle_secs:.0f}s]')}"
            )

        elif event.event_type == "error":
            return (
                f"[{ts}] [{sid}] {agent_prefix}"
                f"{self._color('red', 'ERROR')}: {event.error_message}"
            )

        else:
            return f"[{ts}] [{sid}] {event.event_type}"

    def _format_tool_details(self, event) -> str:
        """Format tool-specific details."""
        tool_input = event.tool_input

        if event.tool_name == "Bash":
            cmd = tool_input.get("command", "")
            return f": {self._truncate(cmd, 60)}"
        elif event.tool_name in ("Read", "Write", "Edit"):
            path = tool_input.get("file_path", "")
            return f": {path}"
        elif event.tool_name == "Grep":
            pattern = tool_input.get("pattern", "")
            return f": /{pattern}/"
        elif event.tool_name == "Glob":
            pattern = tool_input.get("pattern", "")
            return f": {pattern}"
        elif event.tool_name == "Task":
            desc = tool_input.get("description", "")
            return f": {desc}"

        return ""


class JsonFormatter(OutputFormatter):
    """JSON output formatter (one event per line, JSONL format).

    Produces newline-delimited JSON suitable for piping to tools like
    jq, or ingestion into log aggregation systems.

    Example output:
        {"event_type": "message", "timestamp": "2024-01-15T14:32:05", ...}
    """

    def format(self, event: SessionEventType) -> str:
        """Format an event as a JSON line."""
        data = self._serialize(event)
        return json.dumps(data, default=str, ensure_ascii=False)

    def _serialize(self, event: SessionEventType) -> Dict[str, Any]:
        """Serialize event to dictionary."""
        result: Dict[str, Any] = {
            "event_type": event.event_type,
            "timestamp": event.timestamp.isoformat(),
            "session_id": event.session_id,
        }

        if event.agent_id:
            result["agent_id"] = event.agent_id

        # Type-specific serialization
        if event.event_type == "message":
            result["role"] = event.message.role.value
            result["text"] = event.message.text_content
            result["has_tool_calls"] = event.message.has_tool_calls
        elif event.event_type == "tool_use":
            result["tool_name"] = event.tool_name
            result["tool_category"] = event.tool_category
            result["tool_use_id"] = event.tool_use_id
            result["tool_input"] = event.tool_input
        elif event.event_type == "tool_result":
            result["tool_use_id"] = event.tool_use_id
            result["is_error"] = event.is_error
            result["content_preview"] = event.content[:500] if event.content else ""
        elif event.event_type == "tool_call_completed":
            result["tool_name"] = event.tool_name
            result["tool_use_id"] = event.tool_use_id
            result["is_error"] = event.is_error
            if event.duration:
                result["duration_ms"] = event.duration.total_seconds() * 1000
        elif event.event_type == "session_start":
            result["project_slug"] = event.project_slug
            result["file_path"] = str(event.file_path)
        elif event.event_type == "session_end":
            result["reason"] = event.reason
            result["message_count"] = event.message_count
            result["tool_count"] = event.tool_count
        elif event.event_type == "session_idle":
            pass  # No additional fields
        elif event.event_type == "session_resume":
            result["idle_duration_seconds"] = event.idle_duration.total_seconds()
        elif event.event_type == "error":
            result["error_message"] = event.error_message

        return result


class CompactFormatter(OutputFormatter):
    """Single-line compact output.

    Produces minimal output with pipe-separated fields, useful for
    quick scanning or when space is limited.

    Example output:
        14:32:05 | a1b2c3d4 | message | user | Help me fix...
        14:32:06 | a1b2c3d4 | tool_use | Read
    """

    def format(self, event: SessionEventType) -> str:
        """Format an event as a compact single line."""
        ts = event.timestamp.strftime("%H:%M:%S")
        sid = event.session_id[:8]

        parts = [ts, sid, event.event_type]

        if event.event_type == "message":
            parts.append(event.message.role.value)
            text = event.message.text_content[:40].replace("\n", " ")
            parts.append(text)
        elif event.event_type == "tool_use":
            parts.append(event.tool_name)
            parts.append(event.tool_category)
        elif event.event_type == "tool_result":
            parts.append("error" if event.is_error else "ok")
        elif event.event_type == "tool_call_completed":
            parts.append(event.tool_name)
            if event.duration:
                parts.append(f"{event.duration.total_seconds() * 1000:.0f}ms")
            parts.append("error" if event.is_error else "ok")
        elif event.event_type == "session_start":
            parts.append(event.project_slug)
        elif event.event_type == "session_end":
            parts.append(event.reason)
            parts.append(f"{event.message_count}msg")
        elif event.event_type == "session_idle":
            pass
        elif event.event_type == "session_resume":
            parts.append(f"{event.idle_duration.total_seconds():.0f}s")
        elif event.event_type == "error":
            parts.append(event.error_message[:40])

        return " | ".join(parts)


def get_formatter(name: str, use_color: bool = True) -> OutputFormatter:
    """Get a formatter by name.

    Args:
        name: Formatter name ("plain", "json", or "compact")
        use_color: Whether to use colors (for plain formatter)

    Returns:
        OutputFormatter instance

    Raises:
        ValueError: If formatter name is unknown
    """
    formatters = {
        "plain": lambda: PlainFormatter(use_color=use_color),
        "json": JsonFormatter,
        "compact": CompactFormatter,
    }

    if name not in formatters:
        raise ValueError(f"Unknown formatter: {name}. Choose from: {list(formatters.keys())}")

    return formatters[name]()
