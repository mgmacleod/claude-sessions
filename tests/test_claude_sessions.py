"""Tests for claude_sessions.__init__ (ClaudeSessions class)."""

import pytest
from pathlib import Path

from claude_sessions import (
    ClaudeSessions,
    Session, Project, Message, ToolCall,
    SessionQuery,
)

# Constants from conftest
SAMPLE_SESSION_ID = "abc12345-1234-5678-9abc-def012345678"


class TestClaudeSessionsLoad:
    """Tests for ClaudeSessions.load() class method."""

    def test_load_from_custom_path(self, mock_project_directory_with_sessions):
        """Should load from custom base_path."""
        cs = ClaudeSessions.load(base_path=mock_project_directory_with_sessions)
        assert cs.project_count >= 1

    def test_load_with_project_filter(self, mock_project_directory_with_sessions):
        """Should filter projects by slug."""
        cs = ClaudeSessions.load(
            base_path=mock_project_directory_with_sessions,
            project_filter="mgm"
        )
        assert cs.project_count >= 1

    def test_load_with_no_match_filter(self, mock_project_directory_with_sessions):
        """Should return empty with non-matching filter."""
        cs = ClaudeSessions.load(
            base_path=mock_project_directory_with_sessions,
            project_filter="nonexistent"
        )
        assert cs.project_count == 0

    def test_load_string_path(self, mock_project_directory_with_sessions):
        """Should accept string path."""
        cs = ClaudeSessions.load(base_path=str(mock_project_directory_with_sessions))
        assert isinstance(cs, ClaudeSessions)


class TestClaudeSessionsLoadProject:
    """Tests for ClaudeSessions.load_project() class method."""

    def test_load_single_project(self, mock_project_directory_with_sessions):
        """Should load a single project."""
        project_path = mock_project_directory_with_sessions / "projects" / "-home-mgm-project"
        cs = ClaudeSessions.load_project(project_path)
        assert cs.project_count == 1

    def test_load_project_string_path(self, mock_project_directory_with_sessions):
        """Should accept string path."""
        project_path = str(mock_project_directory_with_sessions / "projects" / "-home-mgm-project")
        cs = ClaudeSessions.load_project(project_path)
        assert cs.project_count == 1


class TestClaudeSessionsProperties:
    """Tests for ClaudeSessions properties."""

    @pytest.fixture
    def claude_sessions(self, mock_project_directory_with_sessions):
        """Create ClaudeSessions instance."""
        return ClaudeSessions.load(base_path=mock_project_directory_with_sessions)

    def test_projects(self, claude_sessions):
        """projects should return dict of projects."""
        assert isinstance(claude_sessions.projects, dict)
        assert len(claude_sessions.projects) >= 1

    def test_all_sessions(self, claude_sessions):
        """all_sessions should return list of all sessions."""
        sessions = claude_sessions.all_sessions
        assert isinstance(sessions, list)
        assert len(sessions) >= 1

    def test_all_sessions_cached(self, claude_sessions):
        """all_sessions should be cached."""
        sessions1 = claude_sessions.all_sessions
        sessions2 = claude_sessions.all_sessions
        assert sessions1 is sessions2


class TestClaudeSessionsQuery:
    """Tests for ClaudeSessions.query() method."""

    @pytest.fixture
    def claude_sessions(self, mock_project_directory_with_sessions):
        return ClaudeSessions.load(base_path=mock_project_directory_with_sessions)

    def test_returns_session_query(self, claude_sessions):
        """query() should return SessionQuery."""
        q = claude_sessions.query()
        assert isinstance(q, SessionQuery)

    def test_query_contains_all_sessions(self, claude_sessions):
        """Query should contain all sessions."""
        q = claude_sessions.query()
        assert len(q) == claude_sessions.session_count


class TestClaudeSessionsGetSession:
    """Tests for ClaudeSessions.get_session() method."""

    @pytest.fixture
    def claude_sessions(self, mock_project_directory_with_sessions):
        return ClaudeSessions.load(base_path=mock_project_directory_with_sessions)

    def test_get_existing_session(self, claude_sessions):
        """Should return session by ID."""
        # Get first session ID
        session_id = list(claude_sessions.all_sessions)[0].session_id
        session = claude_sessions.get_session(session_id)
        assert session is not None
        assert session.session_id == session_id

    def test_get_nonexistent_session(self, claude_sessions):
        """Should return None for unknown ID."""
        session = claude_sessions.get_session("nonexistent-id")
        assert session is None


class TestClaudeSessionsGetProject:
    """Tests for ClaudeSessions.get_project() method."""

    @pytest.fixture
    def claude_sessions(self, mock_project_directory_with_sessions):
        return ClaudeSessions.load(base_path=mock_project_directory_with_sessions)

    def test_get_existing_project(self, claude_sessions):
        """Should return project by slug."""
        project = claude_sessions.get_project("-home-mgm-project")
        assert project is not None

    def test_get_nonexistent_project(self, claude_sessions):
        """Should return None for unknown slug."""
        project = claude_sessions.get_project("nonexistent")
        assert project is None


class TestClaudeSessionsFindProjects:
    """Tests for ClaudeSessions.find_projects() method."""

    @pytest.fixture
    def claude_sessions(self, mock_project_directory_with_sessions):
        return ClaudeSessions.load(base_path=mock_project_directory_with_sessions)

    def test_find_matching(self, claude_sessions):
        """Should find projects matching pattern."""
        projects = claude_sessions.find_projects("mgm")
        assert len(projects) >= 1

    def test_find_no_match(self, claude_sessions):
        """Should return empty for no match."""
        projects = claude_sessions.find_projects("xyz123")
        assert len(projects) == 0

    def test_find_case_insensitive(self, claude_sessions):
        """Should be case insensitive."""
        projects = claude_sessions.find_projects("MGM")
        assert len(projects) >= 1


class TestClaudeSessionsStatistics:
    """Tests for ClaudeSessions statistics properties."""

    @pytest.fixture
    def claude_sessions(self, mock_project_directory_with_sessions):
        return ClaudeSessions.load(base_path=mock_project_directory_with_sessions)

    def test_session_count(self, claude_sessions):
        """session_count should match all_sessions length."""
        assert claude_sessions.session_count == len(claude_sessions.all_sessions)

    def test_project_count(self, claude_sessions):
        """project_count should match projects length."""
        assert claude_sessions.project_count == len(claude_sessions.projects)

    def test_message_count(self, claude_sessions):
        """message_count should sum session message counts."""
        expected = sum(s.message_count for s in claude_sessions.all_sessions)
        assert claude_sessions.message_count == expected

    def test_tool_call_count(self, claude_sessions):
        """tool_call_count should sum session tool counts."""
        expected = sum(s.tool_call_count for s in claude_sessions.all_sessions)
        assert claude_sessions.tool_call_count == expected


class TestClaudeSessionsSummary:
    """Tests for ClaudeSessions.summary() method."""

    @pytest.fixture
    def claude_sessions(self, mock_project_directory_with_sessions):
        return ClaudeSessions.load(base_path=mock_project_directory_with_sessions)

    def test_summary_keys(self, claude_sessions):
        """summary() should have expected keys."""
        s = claude_sessions.summary()
        expected_keys = [
            'projects', 'sessions', 'messages', 'tool_calls',
            'sessions_with_agents', 'total_agents'
        ]
        for key in expected_keys:
            assert key in s

    def test_summary_values(self, claude_sessions):
        """summary() values should match properties."""
        s = claude_sessions.summary()
        assert s['projects'] == claude_sessions.project_count
        assert s['sessions'] == claude_sessions.session_count
        assert s['messages'] == claude_sessions.message_count


class TestClaudeSessionsDunderMethods:
    """Tests for ClaudeSessions __repr__ and __len__."""

    @pytest.fixture
    def claude_sessions(self, mock_project_directory_with_sessions):
        return ClaudeSessions.load(base_path=mock_project_directory_with_sessions)

    def test_repr(self, claude_sessions):
        """__repr__ should include counts."""
        r = repr(claude_sessions)
        assert "ClaudeSessions" in r
        assert "projects" in r
        assert "sessions" in r

    def test_len(self, claude_sessions):
        """__len__ should return session_count."""
        assert len(claude_sessions) == claude_sessions.session_count


class TestClaudeSessionsEmpty:
    """Tests for empty ClaudeSessions."""

    def test_empty_instance(self):
        """Empty instance should have zero counts."""
        cs = ClaudeSessions({})
        assert cs.project_count == 0
        assert cs.session_count == 0
        assert cs.message_count == 0
        assert cs.tool_call_count == 0

    def test_empty_query(self):
        """Empty instance query should be empty."""
        cs = ClaudeSessions({})
        q = cs.query()
        assert len(q) == 0

    def test_empty_get_session(self):
        """Empty instance should return None for get_session."""
        cs = ClaudeSessions({})
        assert cs.get_session("any-id") is None

    def test_empty_get_project(self):
        """Empty instance should return None for get_project."""
        cs = ClaudeSessions({})
        assert cs.get_project("any-slug") is None

    def test_empty_find_projects(self):
        """Empty instance should return empty list for find_projects."""
        cs = ClaudeSessions({})
        assert cs.find_projects("any") == []

    def test_empty_summary(self):
        """Empty instance summary should have zero values."""
        cs = ClaudeSessions({})
        s = cs.summary()
        assert s['projects'] == 0
        assert s['sessions'] == 0
        assert s['messages'] == 0
        assert s['tool_calls'] == 0
        assert s['sessions_with_agents'] == 0
        assert s['total_agents'] == 0
