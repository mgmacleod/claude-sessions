"""Export functions for Claude Code sessions."""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from .models import (
    Message, MessageRole, Session, ToolCall, ContentBlock,
    TextBlock, ToolUseBlock, ToolResultBlock
)


# ============================================================================
# Markdown Export
# ============================================================================

def message_to_markdown(
    msg: Message,
    include_tools: bool = True,
    include_metadata: bool = False
) -> str:
    """Convert a message to Markdown format."""
    lines = []

    # Header with role and timestamp
    role_label = "User" if msg.role == MessageRole.USER else "Assistant"
    ts = msg.timestamp.strftime("%Y-%m-%d %H:%M:%S")

    header = f"### {role_label}"
    if msg.model:
        # Extract short model name
        model_short = msg.model.split("-")[1] if "-" in msg.model else msg.model
        header += f" ({model_short})"
    header += f" — {ts}"

    if msg.agent_id:
        header += f" [Agent: {msg.agent_id}]"

    lines.append(header)
    lines.append("")

    if include_metadata and (msg.cwd or msg.git_branch):
        meta_parts = []
        if msg.cwd:
            meta_parts.append(f"cwd: `{msg.cwd}`")
        if msg.git_branch:
            meta_parts.append(f"branch: `{msg.git_branch}`")
        lines.append(f"*{' | '.join(meta_parts)}*")
        lines.append("")

    for block in msg.content:
        if isinstance(block, TextBlock):
            text = block.text.strip()
            if text:
                lines.append(text)
                lines.append("")

        elif isinstance(block, ToolUseBlock) and include_tools:
            lines.append(f"**🔧 {block.name}**")
            # Format input based on tool type
            if block.name == "Bash":
                cmd = block.input.get("command", "")
                lines.append("```bash")
                lines.append(cmd)
                lines.append("```")
            elif block.name in ("Read", "Write", "Edit"):
                path = block.input.get("file_path", "")
                lines.append(f"`{path}`")
                if block.name == "Edit":
                    old = block.input.get("old_string", "")[:100]
                    new = block.input.get("new_string", "")[:100]
                    lines.append(f"  - old: `{old}...`")
                    lines.append(f"  - new: `{new}...`")
            elif block.name in ("Glob", "Grep"):
                pattern = block.input.get("pattern", "")
                lines.append(f"Pattern: `{pattern}`")
            elif block.name == "Task":
                prompt = block.input.get("prompt", "")[:200]
                subagent = block.input.get("subagent_type", "")
                lines.append(f"Type: {subagent}")
                lines.append(f"Prompt: {prompt}...")
            else:
                # Generic JSON display
                lines.append("```json")
                lines.append(json.dumps(block.input, indent=2)[:500])
                lines.append("```")
            lines.append("")

        elif isinstance(block, ToolResultBlock) and include_tools:
            status = "❌ Error" if block.is_error else "✓"
            lines.append(f"**Result** {status}")
            content = block.content[:1000]
            if len(block.content) > 1000:
                content += "\n... [truncated]"
            lines.append("```")
            lines.append(content)
            lines.append("```")
            lines.append("")

    return "\n".join(lines)


def thread_to_markdown(
    messages: List[Message],
    include_tools: bool = True,
    include_metadata: bool = False
) -> str:
    """Convert a list of messages to Markdown."""
    parts = []
    for msg in messages:
        parts.append(message_to_markdown(msg, include_tools, include_metadata))
    return "\n---\n\n".join(parts)


def session_to_markdown(
    session: Session,
    include_tools: bool = True,
    include_agents: bool = True,
    include_metadata: bool = False
) -> str:
    """Export a session to Markdown transcript."""
    lines = []

    # Header
    lines.append(f"# Session: {session.session_id}")
    lines.append("")

    # Metadata table
    lines.append("| Property | Value |")
    lines.append("|----------|-------|")
    if session.start_time:
        lines.append(f"| Start | {session.start_time.strftime('%Y-%m-%d %H:%M:%S')} |")
    if session.end_time:
        lines.append(f"| End | {session.end_time.strftime('%Y-%m-%d %H:%M:%S')} |")
    if session.duration:
        dur_mins = session.duration.total_seconds() / 60
        lines.append(f"| Duration | {dur_mins:.1f} minutes |")
    lines.append(f"| Messages | {session.message_count} |")
    lines.append(f"| Tool Calls | {session.tool_call_count} |")
    lines.append(f"| Project | `{session.project_slug}` |")
    if session.cwd:
        lines.append(f"| Working Dir | `{session.cwd}` |")
    if session.git_branch:
        lines.append(f"| Git Branch | `{session.git_branch}` |")
    if session.agents:
        lines.append(f"| Sub-Agents | {len(session.agents)} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Main thread
    lines.append("## Conversation")
    lines.append("")
    lines.append(thread_to_markdown(
        session.main_thread.messages,
        include_tools,
        include_metadata
    ))

    # Agents
    if include_agents and session.agents:
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("## Sub-Agents")
        lines.append("")

        for agent_id, agent in sorted(session.agents.items()):
            lines.append(f"### Agent: {agent_id}")
            lines.append(f"*{agent.message_count} messages*")
            lines.append("")
            lines.append(thread_to_markdown(
                agent.thread.messages,
                include_tools,
                include_metadata
            ))
            lines.append("")

    return "\n".join(lines)


def export_session_markdown(session: Session, path: Path, **kwargs) -> None:
    """Export session to a Markdown file."""
    md = session_to_markdown(session, **kwargs)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(md)


# ============================================================================
# DataFrame Export (pandas)
# ============================================================================

def sessions_to_dataframe(sessions: List[Session]):
    """
    Export sessions summary to DataFrame.
    Requires pandas to be installed.
    """
    try:
        import pandas as pd
    except ImportError:
        raise ImportError("pandas is required for DataFrame export. Install with: pip install pandas")

    records = []
    for s in sessions:
        records.append({
            'session_id': s.session_id,
            'project': s.project_slug,
            'start_time': s.start_time,
            'end_time': s.end_time,
            'duration_minutes': s.duration.total_seconds() / 60 if s.duration else None,
            'message_count': s.message_count,
            'tool_call_count': s.tool_call_count,
            'agent_count': len(s.agents),
            'cwd': s.cwd,
            'git_branch': s.git_branch,
            'version': s.version,
        })
    return pd.DataFrame(records)


def messages_to_dataframe(messages: List[Message]):
    """Export messages to DataFrame."""
    try:
        import pandas as pd
    except ImportError:
        raise ImportError("pandas is required for DataFrame export.")

    records = []
    for m in messages:
        records.append({
            'uuid': m.uuid,
            'parent_uuid': m.parent_uuid,
            'session_id': m.session_id,
            'agent_id': m.agent_id,
            'timestamp': m.timestamp,
            'role': m.role.value,
            'is_sidechain': m.is_sidechain,
            'text_length': len(m.text_content),
            'tool_use_count': len(m.tool_uses),
            'tool_result_count': len(m.tool_results),
            'model': m.model,
            'cwd': m.cwd,
            'git_branch': m.git_branch,
        })
    return pd.DataFrame(records)


def tool_calls_to_dataframe(tool_calls: List[ToolCall]):
    """Export tool calls to DataFrame."""
    try:
        import pandas as pd
    except ImportError:
        raise ImportError("pandas is required for DataFrame export.")

    records = []
    for tc in tool_calls:
        records.append({
            'tool_id': tc.tool_use.id,
            'tool_name': tc.tool_name,
            'tool_category': tc.tool_category,
            'timestamp': tc.timestamp,
            'session_id': tc.session_id,
            'agent_id': tc.request_message.agent_id,
            'is_error': tc.is_error,
            'result_length': len(tc.result_content) if tc.result_content else 0,
        })
    return pd.DataFrame(records)


def bash_commands_to_dataframe(tool_calls: List[ToolCall]):
    """Extract Bash commands with their outputs."""
    try:
        import pandas as pd
    except ImportError:
        raise ImportError("pandas is required for DataFrame export.")

    records = []
    for tc in tool_calls:
        if tc.tool_name != 'Bash':
            continue
        records.append({
            'timestamp': tc.timestamp,
            'command': tc.tool_input.get('command', ''),
            'description': tc.tool_input.get('description', ''),
            'timeout': tc.tool_input.get('timeout'),
            'is_error': tc.is_error,
            'output': tc.result_content,
            'session_id': tc.session_id,
        })
    return pd.DataFrame(records)


def file_operations_to_dataframe(tool_calls: List[ToolCall]):
    """Extract file read/write operations."""
    try:
        import pandas as pd
    except ImportError:
        raise ImportError("pandas is required for DataFrame export.")

    records = []
    for tc in tool_calls:
        if tc.tool_name not in ('Read', 'Write', 'Edit'):
            continue
        records.append({
            'timestamp': tc.timestamp,
            'operation': tc.tool_name.lower(),
            'file_path': tc.tool_input.get('file_path', ''),
            'session_id': tc.session_id,
            'is_error': tc.is_error,
        })
    return pd.DataFrame(records)


# ============================================================================
# JSON Export
# ============================================================================

def content_block_to_dict(block: ContentBlock) -> Dict[str, Any]:
    """Convert content block to JSON-serializable dict."""
    if isinstance(block, TextBlock):
        return {'type': 'text', 'text': block.text}
    elif isinstance(block, ToolUseBlock):
        return {
            'type': 'tool_use',
            'id': block.id,
            'name': block.name,
            'input': block.input
        }
    elif isinstance(block, ToolResultBlock):
        return {
            'type': 'tool_result',
            'tool_use_id': block.tool_use_id,
            'content': block.content,
            'is_error': block.is_error
        }
    return {}


def message_to_dict(msg: Message) -> Dict[str, Any]:
    """Convert message to JSON-serializable dict."""
    return {
        'uuid': msg.uuid,
        'parent_uuid': msg.parent_uuid,
        'timestamp': msg.timestamp.isoformat(),
        'role': msg.role.value,
        'content': [content_block_to_dict(b) for b in msg.content],
        'session_id': msg.session_id,
        'agent_id': msg.agent_id,
        'is_sidechain': msg.is_sidechain,
        'model': msg.model,
        'cwd': msg.cwd,
        'git_branch': msg.git_branch,
    }


def session_to_dict(session: Session) -> Dict[str, Any]:
    """Convert session to JSON-serializable dict."""
    return {
        'session_id': session.session_id,
        'project_slug': session.project_slug,
        'start_time': session.start_time.isoformat() if session.start_time else None,
        'end_time': session.end_time.isoformat() if session.end_time else None,
        'duration_seconds': session.duration.total_seconds() if session.duration else None,
        'cwd': session.cwd,
        'git_branch': session.git_branch,
        'version': session.version,
        'message_count': session.message_count,
        'tool_call_count': session.tool_call_count,
        'messages': [message_to_dict(m) for m in session.main_thread.messages],
        'agents': {
            agent_id: {
                'agent_id': agent.agent_id,
                'message_count': agent.message_count,
                'messages': [message_to_dict(m) for m in agent.thread.messages]
            }
            for agent_id, agent in session.agents.items()
        }
    }


def tool_call_to_dict(tc: ToolCall) -> Dict[str, Any]:
    """Convert tool call to JSON-serializable dict."""
    return {
        'tool_id': tc.tool_use.id,
        'tool_name': tc.tool_name,
        'tool_category': tc.tool_category,
        'timestamp': tc.timestamp.isoformat(),
        'input': tc.tool_input,
        'result': tc.result_content,
        'is_error': tc.is_error,
        'session_id': tc.session_id,
        'agent_id': tc.request_message.agent_id,
    }


def export_sessions_json(sessions: List[Session], path: Path) -> None:
    """Export sessions to JSON file."""
    data = [session_to_dict(s) for s in sessions]
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)


def export_sessions_jsonl(sessions: List[Session], path: Path) -> None:
    """Export sessions to JSONL file (one session per line)."""
    with open(path, 'w', encoding='utf-8') as f:
        for session in sessions:
            f.write(json.dumps(session_to_dict(session)) + '\n')


def export_tool_calls_json(tool_calls: List[ToolCall], path: Path) -> None:
    """Export tool calls to JSON file."""
    data = [tool_call_to_dict(tc) for tc in tool_calls]
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
