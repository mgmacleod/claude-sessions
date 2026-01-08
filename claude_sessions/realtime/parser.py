"""Incremental parsing for realtime session monitoring.

This module provides the IncrementalParser class for parsing individual
JSONL entries into events without requiring full session context.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..models import (
    Message,
    MessageRole,
    ToolUseBlock,
    ToolResultBlock,
    TOOL_CATEGORIES,
)
from ..parser import parse_content_block, parse_timestamp
from .events import (
    SessionEventType,
    MessageEvent,
    ToolUseEvent,
    ToolResultEvent,
    ErrorEvent,
    truncate_tool_input,
)


class IncrementalParser:
    """Parses individual JSONL entries into session events.

    Unlike the batch parser which builds complete sessions, this parser
    processes entries one at a time and emits events immediately.

    Example:
        >>> parser = IncrementalParser()
        >>> for entry in jsonl_entries:
        ...     events = parser.parse_entry(entry)
        ...     for event in events:
        ...         handle_event(event)
    """

    def __init__(self, truncate_inputs: bool = True, max_input_length: int = 1024):
        """Initialize the parser.

        Args:
            truncate_inputs: Whether to truncate large tool inputs
            max_input_length: Maximum length for tool input strings
        """
        self.truncate_inputs = truncate_inputs
        self.max_input_length = max_input_length

    def parse_entry(self, entry: Dict[str, Any]) -> List[SessionEventType]:
        """Parse a JSONL entry into events.

        A single entry may produce multiple events:
        - One MessageEvent for the message itself
        - One ToolUseEvent for each tool invocation (assistant messages)
        - One ToolResultEvent for each tool result (user messages)

        Args:
            entry: Parsed JSON dict from JSONL line

        Returns:
            List of events (may be empty for non-message entries)
        """
        events: List[SessionEventType] = []

        try:
            message = self._parse_message(entry)
            if message is None:
                # Non-message entry (queue-operation, etc.) - skip
                return events

            # Emit the message event
            events.append(
                MessageEvent(
                    timestamp=message.timestamp,
                    session_id=message.session_id,
                    message=message,
                    agent_id=message.agent_id,
                )
            )

            # Emit tool events
            events.extend(self._extract_tool_events(message))

        except Exception as e:
            # Emit error event for parse failures
            session_id = entry.get("sessionId", "")
            agent_id = entry.get("agentId")

            events.append(
                ErrorEvent(
                    timestamp=datetime.now(timezone.utc),
                    session_id=session_id,
                    error_message=f"Parse error: {e}",
                    raw_entry=str(entry)[:1024],  # Truncate raw entry
                    agent_id=agent_id,
                )
            )

        return events

    def _parse_message(self, entry: Dict[str, Any]) -> Optional[Message]:
        """Parse a JSONL entry into a Message object.

        This reuses logic from the batch parser but is called per-entry.

        Args:
            entry: Parsed JSON dict

        Returns:
            Message object, or None for non-message entries
        """
        msg_type = entry.get("type")

        if msg_type not in ("user", "assistant"):
            return None

        raw_message = entry.get("message", {})
        raw_content = raw_message.get("content", [])

        # Handle string content (plain text user message)
        if isinstance(raw_content, str):
            from ..models import TextBlock
            content = [TextBlock(text=raw_content)]
        elif isinstance(raw_content, list):
            content = [parse_content_block(c) for c in raw_content]
        else:
            content = []

        # Extract usage stats from assistant messages
        usage = None
        if msg_type == "assistant" and "usage" in raw_message:
            usage = raw_message["usage"]

        return Message(
            uuid=entry.get("uuid", ""),
            parent_uuid=entry.get("parentUuid"),
            timestamp=parse_timestamp(entry.get("timestamp", "")),
            role=MessageRole(raw_message.get("role", msg_type)),
            content=content,
            session_id=entry.get("sessionId", ""),
            agent_id=entry.get("agentId"),
            is_sidechain=entry.get("isSidechain", False),
            cwd=entry.get("cwd"),
            git_branch=entry.get("gitBranch"),
            version=entry.get("version"),
            model=raw_message.get("model"),
            request_id=entry.get("requestId"),
            is_meta=entry.get("isMeta", False),
            slug=entry.get("slug"),
            tool_use_result=entry.get("toolUseResult"),
            todos=entry.get("todos"),
            usage=usage,
        )

    def _extract_tool_events(self, message: Message) -> List[SessionEventType]:
        """Extract tool use and result events from a message.

        Args:
            message: Parsed Message object

        Returns:
            List of ToolUseEvent and ToolResultEvent objects
        """
        events: List[SessionEventType] = []

        for block in message.content:
            if isinstance(block, ToolUseBlock):
                # Truncate tool input if configured
                tool_input = block.input
                if self.truncate_inputs:
                    tool_input = truncate_tool_input(tool_input, self.max_input_length)

                events.append(
                    ToolUseEvent(
                        timestamp=message.timestamp,
                        session_id=message.session_id,
                        tool_name=block.name,
                        tool_category=TOOL_CATEGORIES.get(block.name, "other"),
                        tool_input=tool_input,
                        tool_use_id=block.id,
                        message=message,
                        agent_id=message.agent_id,
                    )
                )

            elif isinstance(block, ToolResultBlock):
                # Truncate result content
                content = block.content
                if self.truncate_inputs and len(content) > self.max_input_length:
                    content = content[: self.max_input_length] + "...[truncated]"

                events.append(
                    ToolResultEvent(
                        timestamp=message.timestamp,
                        session_id=message.session_id,
                        tool_use_id=block.tool_use_id,
                        content=content,
                        is_error=block.is_error,
                        message=message,
                        agent_id=message.agent_id,
                    )
                )

        return events

    def parse_raw_line(self, line: str) -> List[SessionEventType]:
        """Parse a raw JSONL line into events.

        This is a convenience method that handles JSON parsing and
        emits ErrorEvent for malformed JSON.

        Args:
            line: Raw JSONL line string

        Returns:
            List of events (includes ErrorEvent if JSON is invalid)
        """
        import json

        line = line.strip()
        if not line:
            return []

        try:
            entry = json.loads(line)
            return self.parse_entry(entry)
        except json.JSONDecodeError as e:
            return [
                ErrorEvent(
                    timestamp=datetime.now(timezone.utc),
                    session_id="",
                    error_message=f"JSON parse error: {e}",
                    raw_entry=line[:1024],
                )
            ]
