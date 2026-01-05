"""JSONL parsing and session building for Claude Code data."""

import json
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Dict, Any, List, Optional, Tuple

from .models import (
    Message, MessageRole, ContentBlock, TextBlock, ToolUseBlock, ToolResultBlock,
    Thread, Agent, Session, Project
)


# Use timezone-aware min datetime for consistent comparisons
DATETIME_MIN = datetime.min.replace(tzinfo=timezone.utc)


def parse_timestamp(ts: str) -> datetime:
    """Parse ISO-8601 timestamp string to datetime (always UTC)."""
    if not ts:
        return DATETIME_MIN
    # Handle various ISO formats
    ts = ts.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(ts)
        # Ensure timezone-aware
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        # Fallback for unusual formats
        return DATETIME_MIN


def iter_jsonl(path: Path) -> Iterator[Dict[str, Any]]:
    """Iterate over lines in a JSONL file, yielding parsed dicts."""
    with open(path, 'r', encoding='utf-8') as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                warnings.warn(f"{path}:{line_no}: JSON parse error: {e}")
                continue


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Load entire JSONL file into memory."""
    return list(iter_jsonl(path))


def parse_content_block(raw: Any) -> ContentBlock:
    """Parse a content block from raw JSON."""
    if isinstance(raw, str):
        return TextBlock(text=raw)

    if not isinstance(raw, dict):
        return TextBlock(text=str(raw))

    block_type = raw.get("type")

    if block_type == "text":
        return TextBlock(text=raw.get("text", ""))

    elif block_type == "tool_use":
        return ToolUseBlock(
            id=raw.get("id", ""),
            name=raw.get("name", ""),
            input=raw.get("input", {})
        )

    elif block_type == "tool_result":
        content = raw.get("content", "")
        # Handle content as list of text blocks
        if isinstance(content, list):
            texts = []
            for c in content:
                if isinstance(c, dict):
                    texts.append(c.get("text", ""))
                elif isinstance(c, str):
                    texts.append(c)
            content = "\n".join(texts)
        return ToolResultBlock(
            tool_use_id=raw.get("tool_use_id", ""),
            content=content,
            is_error=raw.get("is_error", False)
        )

    else:
        # Unknown block type - treat as text
        return TextBlock(text=str(raw))


def parse_message(entry: Dict[str, Any]) -> Optional[Message]:
    """
    Parse a JSONL entry into a Message object.
    Returns None for non-message entries (queue-operation, etc).
    """
    msg_type = entry.get("type")

    if msg_type not in ("user", "assistant"):
        return None

    raw_message = entry.get("message", {})
    raw_content = raw_message.get("content", [])

    # Handle string content (plain text user message)
    if isinstance(raw_content, str):
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


def build_thread(messages: List[Message]) -> Thread:
    """
    Build a thread from messages using parentUuid linkage.
    Messages are ordered by following parent chain from roots.
    """
    if not messages:
        return Thread(messages=[])

    # Index by UUID
    by_uuid: Dict[str, Message] = {m.uuid: m for m in messages}

    # Find children of each message
    children: Dict[Optional[str], List[Message]] = {}
    for msg in messages:
        children.setdefault(msg.parent_uuid, []).append(msg)

    # BFS from roots to build ordered list
    ordered: List[Message] = []
    roots = children.get(None, [])

    # Sort roots by timestamp
    queue = sorted(roots, key=lambda m: m.timestamp)

    while queue:
        msg = queue.pop(0)
        ordered.append(msg)

        # Add children sorted by timestamp
        msg_children = children.get(msg.uuid, [])
        msg_children.sort(key=lambda m: m.timestamp)
        queue = msg_children + queue  # DFS-like to maintain thread order

    # Include any orphaned messages (parent not found)
    seen = {m.uuid for m in ordered}
    orphans = [m for m in messages if m.uuid not in seen]
    if orphans:
        orphans.sort(key=lambda m: m.timestamp)
        ordered.extend(orphans)

    return Thread(messages=ordered)


def discover_session_files(project_path: Path) -> Dict[str, List[Path]]:
    """
    Discover all session and agent files in a project directory.
    Returns: {session_id: [files...]}

    Session files are named by UUID: {uuid}.jsonl
    Agent files are named: agent-{short_id}.jsonl
    """
    sessions: Dict[str, List[Path]] = {}
    agent_files: List[Tuple[Path, Optional[str]]] = []

    for jsonl_file in project_path.glob("*.jsonl"):
        name = jsonl_file.stem

        if name.startswith("agent-"):
            # Agent file - defer session assignment
            # Read first line to get session_id
            session_id = None
            try:
                for entry in iter_jsonl(jsonl_file):
                    session_id = entry.get("sessionId")
                    if session_id:
                        break
            except Exception:
                pass
            agent_files.append((jsonl_file, session_id))
        else:
            # Main session file (UUID filename)
            session_id = name
            sessions.setdefault(session_id, []).insert(0, jsonl_file)

    # Assign agent files to sessions
    for agent_file, session_id in agent_files:
        if session_id:
            sessions.setdefault(session_id, []).append(agent_file)

    return sessions


def build_session(
    session_id: str,
    project_slug: str,
    files: List[Path]
) -> Session:
    """
    Build a complete Session from JSONL files.
    Handles main session file + agent sidechain files.
    """
    main_messages: List[Message] = []
    agent_messages: Dict[str, List[Message]] = {}
    metadata_entries: List[Dict] = []

    session_meta: Dict[str, Any] = {}

    for file_path in files:
        try:
            for entry in iter_jsonl(file_path):
                entry_type = entry.get("type")

                # Collect non-message entries
                if entry_type in ("queue-operation", "file-history-snapshot"):
                    metadata_entries.append(entry)
                    continue

                # Parse message
                msg = parse_message(entry)
                if msg is None:
                    continue

                # Capture session-level metadata from first message
                if not session_meta:
                    session_meta = {
                        "cwd": msg.cwd,
                        "git_branch": msg.git_branch,
                        "version": msg.version,
                        "slug": msg.slug,
                    }

                # Route to main thread or agent
                if msg.agent_id and msg.is_sidechain:
                    agent_messages.setdefault(msg.agent_id, []).append(msg)
                else:
                    main_messages.append(msg)

        except Exception as e:
            warnings.warn(f"Error reading {file_path}: {e}")
            continue

    # Build threads
    main_thread = build_thread(main_messages)

    agents = {}
    for agent_id, msgs in agent_messages.items():
        thread = build_thread(msgs)
        agents[agent_id] = Agent(
            agent_id=agent_id,
            session_id=session_id,
            thread=thread
        )

    return Session(
        session_id=session_id,
        project_slug=project_slug,
        main_thread=main_thread,
        agents=agents,
        metadata_entries=metadata_entries,
        cwd=session_meta.get("cwd"),
        git_branch=session_meta.get("git_branch"),
        version=session_meta.get("version"),
        slug=session_meta.get("slug"),
    )


def load_project(project_path: Path) -> Project:
    """Load all sessions from a project directory."""
    slug = project_path.name
    session_files = discover_session_files(project_path)

    sessions = {}
    for session_id, files in session_files.items():
        try:
            session = build_session(session_id, slug, files)
            sessions[session_id] = session
        except Exception as e:
            warnings.warn(f"Failed to load session {session_id}: {e}")

    return Project(
        slug=slug,
        path=str(project_path),
        sessions=sessions
    )


def load_all_projects(base_path: Optional[Path] = None) -> Dict[str, Project]:
    """
    Load all projects from Claude Code data directory.

    Args:
        base_path: Override default ~/.claude location
    """
    if base_path is None:
        base_path = Path.home() / ".claude"

    projects_dir = base_path / "projects"
    if not projects_dir.exists():
        return {}

    projects = {}
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        try:
            project = load_project(project_dir)
            projects[project.slug] = project
        except Exception as e:
            warnings.warn(f"Failed to load project {project_dir.name}: {e}")

    return projects
