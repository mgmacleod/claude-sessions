"""Shared pytest fixtures for claude-sessions tests."""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict
import pytest

from claude_sessions.models import (
    TextBlock, ToolUseBlock, ToolResultBlock,
    Message, MessageRole, ToolCall, Thread, Agent, Session, Project
)


# Sample UUIDs for consistent testing
SAMPLE_SESSION_ID = "abc12345-1234-5678-9abc-def012345678"
SAMPLE_UUID_1 = "msg-11111111-1111-1111-1111-111111111111"
SAMPLE_UUID_2 = "msg-22222222-2222-2222-2222-222222222222"
SAMPLE_UUID_3 = "msg-33333333-3333-3333-3333-333333333333"
SAMPLE_TOOL_USE_ID = "toolu_01ABC123DEF456"
SAMPLE_AGENT_ID = "agent-99999999-9999-9999-9999-999999999999"


@pytest.fixture
def sample_timestamp() -> str:
    """Return a sample ISO timestamp string."""
    return "2024-01-15T10:30:00.000Z"


@pytest.fixture
def sample_datetime() -> datetime:
    """Return a sample datetime object."""
    return datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)


@pytest.fixture
def sample_user_message_entry() -> Dict[str, Any]:
    """Valid JSONL entry for a user message."""
    return {
        "type": "user",
        "uuid": SAMPLE_UUID_1,
        "parentUuid": None,
        "timestamp": "2024-01-15T10:30:00.000Z",
        "sessionId": SAMPLE_SESSION_ID,
        "cwd": "/home/user/project",
        "gitBranch": "main",
        "version": "1.0.0",
        "message": {
            "role": "user",
            "content": "Hello, can you help me with my code?"
        }
    }


@pytest.fixture
def sample_assistant_message_entry() -> Dict[str, Any]:
    """Valid JSONL entry for an assistant message without tools."""
    return {
        "type": "assistant",
        "uuid": SAMPLE_UUID_2,
        "parentUuid": SAMPLE_UUID_1,
        "timestamp": "2024-01-15T10:30:05.000Z",
        "sessionId": SAMPLE_SESSION_ID,
        "message": {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Sure, I'd be happy to help!"}
            ],
            "model": "claude-sonnet-4-20250514",
            "usage": {"input_tokens": 100, "output_tokens": 50}
        }
    }


@pytest.fixture
def sample_tool_use_entry() -> Dict[str, Any]:
    """Valid JSONL entry for an assistant message with tool use."""
    return {
        "type": "assistant",
        "uuid": SAMPLE_UUID_2,
        "parentUuid": SAMPLE_UUID_1,
        "timestamp": "2024-01-15T10:30:05.000Z",
        "sessionId": SAMPLE_SESSION_ID,
        "message": {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Let me read that file for you."},
                {
                    "type": "tool_use",
                    "id": SAMPLE_TOOL_USE_ID,
                    "name": "Read",
                    "input": {"file_path": "/home/user/project/main.py"}
                }
            ],
            "model": "claude-sonnet-4-20250514"
        }
    }


@pytest.fixture
def sample_tool_result_entry() -> Dict[str, Any]:
    """Valid JSONL entry for a user message with tool result."""
    return {
        "type": "user",
        "uuid": SAMPLE_UUID_3,
        "parentUuid": SAMPLE_UUID_2,
        "timestamp": "2024-01-15T10:30:06.000Z",
        "sessionId": SAMPLE_SESSION_ID,
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": SAMPLE_TOOL_USE_ID,
                    "content": "def main():\n    print('Hello')"
                }
            ]
        }
    }


@pytest.fixture
def sample_tool_result_error_entry() -> Dict[str, Any]:
    """Valid JSONL entry for a tool result with error."""
    return {
        "type": "user",
        "uuid": SAMPLE_UUID_3,
        "parentUuid": SAMPLE_UUID_2,
        "timestamp": "2024-01-15T10:30:06.000Z",
        "sessionId": SAMPLE_SESSION_ID,
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": SAMPLE_TOOL_USE_ID,
                    "content": "Error: File not found",
                    "is_error": True
                }
            ]
        }
    }


@pytest.fixture
def sample_agent_message_entry() -> Dict[str, Any]:
    """Valid JSONL entry for an agent (sub-agent) message."""
    return {
        "type": "assistant",
        "uuid": SAMPLE_UUID_2,
        "parentUuid": SAMPLE_UUID_1,
        "timestamp": "2024-01-15T10:30:05.000Z",
        "sessionId": SAMPLE_SESSION_ID,
        "agentId": SAMPLE_AGENT_ID,
        "isSidechain": True,
        "message": {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Agent response here."}
            ]
        }
    }


@pytest.fixture
def sample_queue_operation_entry() -> Dict[str, Any]:
    """Non-message JSONL entry (should be skipped)."""
    return {
        "type": "queue-operation",
        "sessionId": SAMPLE_SESSION_ID,
        "operation": "clear"
    }


@pytest.fixture
def temp_jsonl_file(tmp_path):
    """Factory fixture to create temporary JSONL files with content."""
    def _create_jsonl(entries: list, filename: str = "session.jsonl") -> Path:
        file_path = tmp_path / filename
        with open(file_path, "w") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")
        return file_path
    return _create_jsonl


@pytest.fixture
def mock_session_directory(tmp_path):
    """Create a mock ~/.claude/projects/ directory structure."""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    # Create a sample project
    project_dir = projects_dir / "my-project"
    project_dir.mkdir()

    return tmp_path


@pytest.fixture
def mock_session_file(mock_session_directory, sample_user_message_entry, sample_tool_use_entry, sample_tool_result_entry):
    """Create a mock session file with sample entries."""
    project_dir = mock_session_directory / "projects" / "my-project"
    session_file = project_dir / f"{SAMPLE_SESSION_ID}.jsonl"

    entries = [
        sample_user_message_entry,
        sample_tool_use_entry,
        sample_tool_result_entry
    ]

    with open(session_file, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")

    return session_file


# Helper constants for tests
@pytest.fixture
def session_id():
    """Return the sample session ID."""
    return SAMPLE_SESSION_ID


@pytest.fixture
def tool_use_id():
    """Return the sample tool use ID."""
    return SAMPLE_TOOL_USE_ID


@pytest.fixture
def agent_id():
    """Return the sample agent ID."""
    return SAMPLE_AGENT_ID


# ============================================================================
# Content Block Fixtures
# ============================================================================

@pytest.fixture
def text_block():
    """Create a simple TextBlock."""
    return TextBlock(text="Sample text content")


@pytest.fixture
def tool_use_block():
    """Create a ToolUseBlock for Read tool."""
    return ToolUseBlock(
        id=SAMPLE_TOOL_USE_ID,
        name="Read",
        input={"file_path": "/home/user/project/main.py"}
    )


@pytest.fixture
def tool_result_block():
    """Create a successful ToolResultBlock."""
    return ToolResultBlock(
        tool_use_id=SAMPLE_TOOL_USE_ID,
        content="def main():\n    print('Hello')",
        is_error=False
    )


@pytest.fixture
def tool_result_error_block():
    """Create an error ToolResultBlock."""
    return ToolResultBlock(
        tool_use_id=SAMPLE_TOOL_USE_ID,
        content="Error: File not found",
        is_error=True
    )


# ============================================================================
# Message Fixtures
# ============================================================================

@pytest.fixture
def user_message(sample_datetime):
    """Create a user Message object."""
    return Message(
        uuid=SAMPLE_UUID_1,
        parent_uuid=None,
        timestamp=sample_datetime,
        role=MessageRole.USER,
        content=[TextBlock(text="Hello, can you help me?")],
        session_id=SAMPLE_SESSION_ID,
        cwd="/home/user/project",
        git_branch="main",
        version="1.0.0"
    )


@pytest.fixture
def assistant_message(sample_datetime):
    """Create an assistant Message object."""
    return Message(
        uuid=SAMPLE_UUID_2,
        parent_uuid=SAMPLE_UUID_1,
        timestamp=sample_datetime + timedelta(seconds=5),
        role=MessageRole.ASSISTANT,
        content=[TextBlock(text="Sure, I can help!")],
        session_id=SAMPLE_SESSION_ID,
        model="claude-sonnet-4-20250514"
    )


@pytest.fixture
def assistant_message_with_tool(sample_datetime, tool_use_block):
    """Create an assistant Message with tool use."""
    return Message(
        uuid=SAMPLE_UUID_2,
        parent_uuid=SAMPLE_UUID_1,
        timestamp=sample_datetime + timedelta(seconds=5),
        role=MessageRole.ASSISTANT,
        content=[
            TextBlock(text="Let me read that file."),
            tool_use_block
        ],
        session_id=SAMPLE_SESSION_ID,
        model="claude-sonnet-4-20250514"
    )


@pytest.fixture
def user_message_with_tool_result(sample_datetime, tool_result_block):
    """Create a user Message with tool result."""
    return Message(
        uuid=SAMPLE_UUID_3,
        parent_uuid=SAMPLE_UUID_2,
        timestamp=sample_datetime + timedelta(seconds=6),
        role=MessageRole.USER,
        content=[tool_result_block],
        session_id=SAMPLE_SESSION_ID
    )


@pytest.fixture
def agent_message(sample_datetime):
    """Create an agent (sidechain) Message."""
    return Message(
        uuid=SAMPLE_UUID_2,
        parent_uuid=SAMPLE_UUID_1,
        timestamp=sample_datetime,
        role=MessageRole.ASSISTANT,
        content=[TextBlock(text="Agent response")],
        session_id=SAMPLE_SESSION_ID,
        agent_id=SAMPLE_AGENT_ID,
        is_sidechain=True
    )


# ============================================================================
# Thread Fixtures
# ============================================================================

@pytest.fixture
def simple_thread(user_message, assistant_message):
    """Create a simple two-message thread."""
    return Thread(messages=[user_message, assistant_message])


@pytest.fixture
def thread_with_tool_calls(user_message, assistant_message_with_tool, user_message_with_tool_result):
    """Create a thread with tool call and result."""
    return Thread(messages=[
        user_message,
        assistant_message_with_tool,
        user_message_with_tool_result
    ])


@pytest.fixture
def empty_thread():
    """Create an empty thread."""
    return Thread(messages=[])


# ============================================================================
# Session Fixtures
# ============================================================================

@pytest.fixture
def simple_session(simple_thread):
    """Create a simple Session without agents."""
    return Session(
        session_id=SAMPLE_SESSION_ID,
        project_slug="-home-mgm-project",
        main_thread=simple_thread,
        cwd="/home/mgm/project",
        git_branch="main",
        version="1.0.0"
    )


@pytest.fixture
def session_with_agents(thread_with_tool_calls, sample_datetime):
    """Create a Session with agents."""
    agent_thread = Thread(messages=[
        Message(
            uuid="agent-msg-1",
            parent_uuid=None,
            timestamp=sample_datetime,
            role=MessageRole.ASSISTANT,
            content=[TextBlock(text="Agent response")],
            session_id=SAMPLE_SESSION_ID,
            agent_id=SAMPLE_AGENT_ID,
            is_sidechain=True
        )
    ])
    agent = Agent(
        agent_id=SAMPLE_AGENT_ID,
        session_id=SAMPLE_SESSION_ID,
        thread=agent_thread
    )
    return Session(
        session_id=SAMPLE_SESSION_ID,
        project_slug="-home-mgm-project",
        main_thread=thread_with_tool_calls,
        agents={SAMPLE_AGENT_ID: agent}
    )


@pytest.fixture
def empty_session():
    """Create an empty Session."""
    return Session(
        session_id=SAMPLE_SESSION_ID,
        project_slug="-home-mgm-project",
        main_thread=Thread(messages=[])
    )


# ============================================================================
# Project Fixtures
# ============================================================================

@pytest.fixture
def simple_project(simple_session):
    """Create a Project with one session."""
    return Project(
        slug="-home-mgm-project",
        path="/path/to/project",
        sessions={SAMPLE_SESSION_ID: simple_session}
    )


@pytest.fixture
def empty_project():
    """Create an empty Project."""
    return Project(
        slug="-home-mgm-project",
        path="/path/to/project",
        sessions={}
    )


@pytest.fixture
def multi_session_project(sample_datetime):
    """Create a Project with multiple sessions for query testing."""
    sessions = {}
    for i in range(5):
        session_id = f"session-{i:03d}"
        thread = Thread(messages=[
            Message(
                uuid=f"msg-{i}-1",
                parent_uuid=None,
                timestamp=sample_datetime + timedelta(days=i),
                role=MessageRole.USER,
                content=[TextBlock(text=f"User message {i}")],
                session_id=session_id
            ),
            Message(
                uuid=f"msg-{i}-2",
                parent_uuid=f"msg-{i}-1",
                timestamp=sample_datetime + timedelta(days=i, seconds=5),
                role=MessageRole.ASSISTANT,
                content=[
                    TextBlock(text=f"Assistant message {i}"),
                    ToolUseBlock(
                        id=f"toolu_{i}",
                        name=["Read", "Bash", "Write", "Glob", "Task"][i % 5],
                        input={"test": "value"}
                    )
                ],
                session_id=session_id,
                model="claude-sonnet-4-20250514"
            )
        ])
        sessions[session_id] = Session(
            session_id=session_id,
            project_slug="-home-mgm-project",
            main_thread=thread
        )
    return Project(
        slug="-home-mgm-project",
        path="/path/to/project",
        sessions=sessions
    )


# ============================================================================
# JSONL File Fixtures for Parser Testing
# ============================================================================

@pytest.fixture
def jsonl_with_empty_lines(tmp_path):
    """Create JSONL file with empty lines."""
    file_path = tmp_path / "empty_lines.jsonl"
    content = '{"type": "user", "uuid": "1"}\n\n{"type": "assistant", "uuid": "2"}\n   \n'
    file_path.write_text(content)
    return file_path


@pytest.fixture
def jsonl_with_invalid_json(tmp_path):
    """Create JSONL file with invalid JSON."""
    file_path = tmp_path / "invalid.jsonl"
    content = '{"type": "user", "uuid": "1"}\nnot valid json\n{"type": "assistant", "uuid": "2"}\n'
    file_path.write_text(content)
    return file_path


@pytest.fixture
def mock_project_directory_with_sessions(tmp_path, sample_user_message_entry, sample_agent_message_entry):
    """Create a complete mock project directory with multiple sessions."""
    projects_dir = tmp_path / "projects"
    project_dir = projects_dir / "-home-mgm-project"
    project_dir.mkdir(parents=True)

    # Session 1 - main file
    session1_id = "session-001"
    session1_file = project_dir / f"{session1_id}.jsonl"
    entry1 = sample_user_message_entry.copy()
    entry1["sessionId"] = session1_id
    session1_file.write_text(json.dumps(entry1) + "\n")

    # Session 2 - main file + agent file
    session2_id = "session-002"
    session2_file = project_dir / f"{session2_id}.jsonl"
    entry2 = sample_user_message_entry.copy()
    entry2["sessionId"] = session2_id
    session2_file.write_text(json.dumps(entry2) + "\n")

    # Agent file for session 2
    agent_file = project_dir / "agent-abc123.jsonl"
    agent_entry = sample_agent_message_entry.copy()
    agent_entry["sessionId"] = session2_id
    agent_file.write_text(json.dumps(agent_entry) + "\n")

    return tmp_path
