"""Shared pytest fixtures for claude-sessions tests."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
import pytest


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
