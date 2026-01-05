"""Data models for Claude Code session parsing."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, List, Dict, Any, Tuple, Union


class MessageRole(Enum):
    """Role of a message sender."""
    USER = "user"
    ASSISTANT = "assistant"


class ContentBlockType(Enum):
    """Type of content block in a message."""
    TEXT = "text"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"


# Tool categorization for analysis
TOOL_CATEGORIES = {
    'Read': 'file_read',
    'Write': 'file_write',
    'Edit': 'file_write',
    'NotebookEdit': 'file_write',
    'Bash': 'bash',
    'Glob': 'search',
    'Grep': 'search',
    'Task': 'agent',
    'TaskOutput': 'agent',
    'TodoWrite': 'planning',
    'WebFetch': 'web',
    'WebSearch': 'web',
    'AskUserQuestion': 'interaction',
    'EnterPlanMode': 'planning',
    'ExitPlanMode': 'planning',
    'KillShell': 'bash',
    'Skill': 'other',
}


@dataclass(frozen=True)
class TextBlock:
    """Plain text content block."""
    text: str
    type: ContentBlockType = field(default=ContentBlockType.TEXT, repr=False)


@dataclass(frozen=True)
class ToolUseBlock:
    """Tool invocation by assistant."""
    id: str              # toolu_XXXXX
    name: str            # Tool name: Read, Bash, Glob, etc.
    input: Dict[str, Any]
    type: ContentBlockType = field(default=ContentBlockType.TOOL_USE, repr=False)

    @property
    def tool_category(self) -> str:
        """Categorize tool: file_read, file_write, bash, search, etc."""
        return TOOL_CATEGORIES.get(self.name, 'other')


@dataclass(frozen=True)
class ToolResultBlock:
    """Tool result returned to assistant."""
    tool_use_id: str     # Links back to ToolUseBlock.id
    content: str         # Result content (may be truncated)
    is_error: bool = False
    type: ContentBlockType = field(default=ContentBlockType.TOOL_RESULT, repr=False)


ContentBlock = Union[TextBlock, ToolUseBlock, ToolResultBlock]


@dataclass
class Message:
    """A single message in a Claude Code conversation."""
    uuid: str
    parent_uuid: Optional[str]
    timestamp: datetime
    role: MessageRole
    content: List[ContentBlock]

    # Session context
    session_id: str
    agent_id: Optional[str] = None
    is_sidechain: bool = False

    # Environment context
    cwd: Optional[str] = None
    git_branch: Optional[str] = None
    version: Optional[str] = None

    # Metadata
    model: Optional[str] = None
    request_id: Optional[str] = None
    is_meta: bool = False
    slug: Optional[str] = None

    # Tool result metadata (for user messages)
    tool_use_result: Optional[Dict[str, Any]] = None
    todos: Optional[List[Dict]] = None

    # Usage stats (for assistant messages)
    usage: Optional[Dict[str, Any]] = None

    @property
    def text_content(self) -> str:
        """Extract all text content, concatenated."""
        return "\n".join(
            block.text for block in self.content
            if isinstance(block, TextBlock)
        )

    @property
    def tool_uses(self) -> List[ToolUseBlock]:
        """Extract all tool use blocks."""
        return [b for b in self.content if isinstance(b, ToolUseBlock)]

    @property
    def tool_results(self) -> List[ToolResultBlock]:
        """Extract all tool result blocks."""
        return [b for b in self.content if isinstance(b, ToolResultBlock)]

    @property
    def has_tool_calls(self) -> bool:
        """True if message contains tool_use blocks."""
        return any(isinstance(b, ToolUseBlock) for b in self.content)

    def __repr__(self) -> str:
        text_preview = self.text_content[:50] + "..." if len(self.text_content) > 50 else self.text_content
        return f"Message({self.role.value}, {self.timestamp.isoformat()}, {repr(text_preview)})"


@dataclass
class ToolCall:
    """
    A complete tool call: tool_use from assistant + tool_result from user.
    Spans two sequential messages in the thread.
    """
    tool_use: ToolUseBlock
    tool_result: Optional[ToolResultBlock]
    request_message: Message
    response_message: Optional[Message]

    @property
    def tool_name(self) -> str:
        return self.tool_use.name

    @property
    def tool_category(self) -> str:
        return self.tool_use.tool_category

    @property
    def tool_input(self) -> Dict[str, Any]:
        return self.tool_use.input

    @property
    def result_content(self) -> Optional[str]:
        return self.tool_result.content if self.tool_result else None

    @property
    def is_error(self) -> bool:
        return self.tool_result.is_error if self.tool_result else False

    @property
    def timestamp(self) -> datetime:
        return self.request_message.timestamp

    @property
    def session_id(self) -> str:
        return self.request_message.session_id

    def __repr__(self) -> str:
        status = "error" if self.is_error else "ok"
        return f"ToolCall({self.tool_name}, {status}, {self.timestamp.isoformat()})"


@dataclass
class Thread:
    """
    A linear sequence of messages connected by parentUuid.
    Represents a conversation flow (may include branches).
    """
    messages: List[Message] = field(default_factory=list)

    @property
    def root(self) -> Optional[Message]:
        """First message (parentUuid is None)."""
        for msg in self.messages:
            if msg.parent_uuid is None:
                return msg
        return self.messages[0] if self.messages else None

    @property
    def tool_calls(self) -> List[ToolCall]:
        """
        Extract all tool calls, pairing tool_use with subsequent tool_result.
        Deduplicates by tool_use.id (keeps first occurrence).
        """
        calls = []
        seen_tool_ids: set = set()
        pending: Dict[str, Tuple[ToolUseBlock, Message]] = {}

        for msg in self.messages:
            # Collect tool_use blocks from assistant
            if msg.role == MessageRole.ASSISTANT:
                for block in msg.content:
                    if isinstance(block, ToolUseBlock):
                        # Skip duplicates (same tool ID seen before)
                        if block.id in seen_tool_ids:
                            continue
                        seen_tool_ids.add(block.id)
                        pending[block.id] = (block, msg)

            # Match tool_result blocks from user
            elif msg.role == MessageRole.USER:
                for block in msg.content:
                    if isinstance(block, ToolResultBlock):
                        if block.tool_use_id in pending:
                            use, req_msg = pending.pop(block.tool_use_id)
                            calls.append(ToolCall(
                                tool_use=use,
                                tool_result=block,
                                request_message=req_msg,
                                response_message=msg
                            ))

        # Remaining unmatched tool_use (incomplete calls)
        for tool_id, (use, req_msg) in pending.items():
            calls.append(ToolCall(
                tool_use=use,
                tool_result=None,
                request_message=req_msg,
                response_message=None
            ))

        return sorted(calls, key=lambda c: c.timestamp)

    def filter_by_role(self, role: MessageRole) -> List[Message]:
        """Filter messages by role."""
        return [m for m in self.messages if m.role == role]

    def filter_by_tool(self, tool_name: str) -> List[ToolCall]:
        """Filter tool calls by tool name."""
        return [c for c in self.tool_calls if c.tool_name == tool_name]

    @property
    def user_messages(self) -> List[Message]:
        """All user messages."""
        return self.filter_by_role(MessageRole.USER)

    @property
    def assistant_messages(self) -> List[Message]:
        """All assistant messages."""
        return self.filter_by_role(MessageRole.ASSISTANT)

    def __len__(self) -> int:
        return len(self.messages)

    def __repr__(self) -> str:
        return f"Thread({len(self.messages)} messages, {len(self.tool_calls)} tool calls)"


@dataclass
class Agent:
    """
    A sub-agent (sidechain) spawned by the Task tool.
    Has its own conversation thread but shares session context.
    """
    agent_id: str
    session_id: str
    thread: Thread

    # Task that spawned this agent (if captured)
    spawn_prompt: Optional[str] = None
    subagent_type: Optional[str] = None

    @property
    def start_time(self) -> Optional[datetime]:
        root = self.thread.root
        return root.timestamp if root else None

    @property
    def message_count(self) -> int:
        return len(self.thread.messages)

    @property
    def tool_calls(self) -> List[ToolCall]:
        return self.thread.tool_calls

    def __repr__(self) -> str:
        return f"Agent({self.agent_id}, {self.message_count} messages)"


@dataclass
class Session:
    """
    A complete Claude Code session.
    Contains main thread + any sidechain agents.
    """
    session_id: str
    project_slug: str

    # Main conversation
    main_thread: Thread

    # Sub-agents (sidechains)
    agents: Dict[str, Agent] = field(default_factory=dict)

    # Metadata from first message
    cwd: Optional[str] = None
    git_branch: Optional[str] = None
    version: Optional[str] = None
    slug: Optional[str] = None

    # Non-message entries (queue-operation, file-history-snapshot)
    metadata_entries: List[Dict] = field(default_factory=list)

    @property
    def start_time(self) -> Optional[datetime]:
        root = self.main_thread.root
        return root.timestamp if root else None

    @property
    def end_time(self) -> Optional[datetime]:
        all_msgs = self.all_messages
        return max(m.timestamp for m in all_msgs) if all_msgs else None

    @property
    def all_messages(self) -> List[Message]:
        """All messages including sidechains, sorted by timestamp."""
        msgs = list(self.main_thread.messages)
        for agent in self.agents.values():
            msgs.extend(agent.thread.messages)
        return sorted(msgs, key=lambda m: m.timestamp)

    @property
    def all_tool_calls(self) -> List[ToolCall]:
        """All tool calls including sidechains."""
        calls = list(self.main_thread.tool_calls)
        for agent in self.agents.values():
            calls.extend(agent.thread.tool_calls)
        return sorted(calls, key=lambda c: c.timestamp)

    @property
    def duration(self) -> Optional[timedelta]:
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return None

    @property
    def message_count(self) -> int:
        return len(self.all_messages)

    @property
    def tool_call_count(self) -> int:
        return len(self.all_tool_calls)

    def get_agent(self, agent_id: str) -> Optional[Agent]:
        return self.agents.get(agent_id)

    def __repr__(self) -> str:
        agents_str = f", {len(self.agents)} agents" if self.agents else ""
        return f"Session({self.session_id[:8]}..., {self.message_count} messages{agents_str})"


@dataclass
class Project:
    """
    A Claude Code project containing multiple sessions.
    Corresponds to a directory in ~/.claude/projects/
    """
    slug: str
    path: str
    sessions: Dict[str, Session] = field(default_factory=dict)

    @property
    def project_path(self) -> Optional[str]:
        """Decode original project path from slug."""
        # "-home-mgm-foo" -> "/home/mgm/foo"
        if not self.slug.startswith("-"):
            return None
        return self.slug.replace("-", "/")

    @property
    def session_count(self) -> int:
        return len(self.sessions)

    def sessions_by_date(self,
                         start: Optional[datetime] = None,
                         end: Optional[datetime] = None) -> List[Session]:
        """Get sessions within a date range, sorted by start time."""
        result = []
        for session in self.sessions.values():
            ts = session.start_time
            if ts is None:
                continue
            if start and ts < start:
                continue
            if end and ts > end:
                continue
            result.append(session)
        return sorted(result, key=lambda s: s.start_time or datetime.min)

    def __repr__(self) -> str:
        return f"Project({self.slug}, {self.session_count} sessions)"
