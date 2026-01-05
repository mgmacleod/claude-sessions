"""
Claude Sessions - Parse and analyze Claude Code session data.

Usage:
    from claude_sessions import ClaudeSessions

    # Load all sessions
    sessions = ClaudeSessions.load()

    # Query sessions
    recent = sessions.query().by_date(start=datetime(2025, 1, 1)).to_list()

    # Export to markdown
    from claude_sessions.export import session_to_markdown
    md = session_to_markdown(recent[0])

    # Export to DataFrame
    from claude_sessions.export import sessions_to_dataframe
    df = sessions_to_dataframe(recent)
"""

from pathlib import Path
from typing import Optional, List, Dict

from .models import (
    Message, MessageRole, ContentBlock, TextBlock, ToolUseBlock, ToolResultBlock,
    ToolCall, Thread, Agent, Session, Project
)
from .parser import load_all_projects, load_project
from .query import SessionQuery


__version__ = "0.1.0"

__all__ = [
    # Main class
    "ClaudeSessions",
    # Models
    "Message",
    "MessageRole",
    "ContentBlock",
    "TextBlock",
    "ToolUseBlock",
    "ToolResultBlock",
    "ToolCall",
    "Thread",
    "Agent",
    "Session",
    "Project",
    # Query
    "SessionQuery",
]


class ClaudeSessions:
    """
    Main entry point for loading and querying Claude Code sessions.

    Example:
        # Load from default ~/.claude location
        sessions = ClaudeSessions.load()

        # Query sessions
        recent = sessions.query().by_date(start=datetime(2025, 1, 1)).to_list()

        # Get specific session
        session = sessions.get_session("abc123-...")

        # Get statistics
        stats = sessions.query().tool_usage_stats()
    """

    def __init__(self, projects: Dict[str, Project]):
        self._projects = projects
        self._all_sessions: Optional[List[Session]] = None

    @classmethod
    def load(
        cls,
        base_path: Optional[Path] = None,
        project_filter: Optional[str] = None
    ) -> 'ClaudeSessions':
        """
        Load all sessions from Claude Code data directory.

        Args:
            base_path: Override default ~/.claude location
            project_filter: Only load projects containing this string in slug

        Returns:
            ClaudeSessions instance with loaded data
        """
        if base_path is not None and isinstance(base_path, str):
            base_path = Path(base_path)

        projects = load_all_projects(base_path)

        if project_filter:
            projects = {
                slug: proj for slug, proj in projects.items()
                if project_filter.lower() in slug.lower()
            }

        return cls(projects)

    @classmethod
    def load_project(cls, project_path: Path) -> 'ClaudeSessions':
        """
        Load a single project directory.

        Args:
            project_path: Path to project directory in ~/.claude/projects/

        Returns:
            ClaudeSessions instance with single project loaded
        """
        if isinstance(project_path, str):
            project_path = Path(project_path)

        project = load_project(project_path)
        return cls({project.slug: project})

    @property
    def projects(self) -> Dict[str, Project]:
        """All loaded projects."""
        return self._projects

    @property
    def all_sessions(self) -> List[Session]:
        """All sessions across all projects."""
        if self._all_sessions is None:
            self._all_sessions = [
                s for p in self._projects.values()
                for s in p.sessions.values()
            ]
        return self._all_sessions

    def query(self) -> SessionQuery:
        """
        Create a query builder for sessions.

        Returns:
            SessionQuery instance for fluent filtering
        """
        return SessionQuery(self.all_sessions)

    def get_session(self, session_id: str) -> Optional[Session]:
        """
        Get a specific session by ID.

        Args:
            session_id: The session UUID

        Returns:
            Session if found, None otherwise
        """
        for project in self._projects.values():
            if session_id in project.sessions:
                return project.sessions[session_id]
        return None

    def get_project(self, slug: str) -> Optional[Project]:
        """
        Get a specific project by slug.

        Args:
            slug: Project slug (e.g., "-home-mgm-development-myproject")

        Returns:
            Project if found, None otherwise
        """
        return self._projects.get(slug)

    def find_projects(self, pattern: str) -> List[Project]:
        """
        Find projects matching a pattern.

        Args:
            pattern: Substring to match in project slug

        Returns:
            List of matching projects
        """
        return [
            p for p in self._projects.values()
            if pattern.lower() in p.slug.lower()
        ]

    # ========================================================================
    # Summary Statistics
    # ========================================================================

    @property
    def session_count(self) -> int:
        """Total number of sessions."""
        return len(self.all_sessions)

    @property
    def project_count(self) -> int:
        """Total number of projects."""
        return len(self._projects)

    @property
    def message_count(self) -> int:
        """Total messages across all sessions."""
        return sum(s.message_count for s in self.all_sessions)

    @property
    def tool_call_count(self) -> int:
        """Total tool calls across all sessions."""
        return sum(s.tool_call_count for s in self.all_sessions)

    def summary(self) -> Dict[str, any]:
        """
        Get a summary of loaded data.

        Returns:
            Dict with counts and statistics
        """
        sessions = self.all_sessions
        return {
            'projects': self.project_count,
            'sessions': self.session_count,
            'messages': self.message_count,
            'tool_calls': self.tool_call_count,
            'sessions_with_agents': sum(1 for s in sessions if s.agents),
            'total_agents': sum(len(s.agents) for s in sessions),
        }

    def __repr__(self) -> str:
        return f"ClaudeSessions({self.project_count} projects, {self.session_count} sessions)"

    def __len__(self) -> int:
        return self.session_count
