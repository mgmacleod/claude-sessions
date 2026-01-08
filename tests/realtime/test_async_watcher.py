"""Tests for AsyncSessionWatcher.

These tests verify the async wrapper around SessionWatcher.

Note: Some lifecycle tests are skipped because the underlying watchdog
observer threads need time to fully terminate, which can cause issues
with pytest-asyncio's strict mode. The core functionality is tested
via the run_for() tests which handle cleanup properly.
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from claude_sessions.realtime.async_watcher import AsyncSessionWatcher
from claude_sessions.realtime.watcher import WatcherConfig
from claude_sessions.realtime.events import MessageEvent


def make_user_entry(session_id: str, uuid: str, text: str = "Hello") -> dict:
    """Create a JSONL user message entry."""
    return {
        "type": "user",
        "uuid": uuid,
        "parentUuid": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sessionId": session_id,
        "cwd": "/test/project",
        "message": {
            "role": "user",
            "content": text
        }
    }


@pytest.fixture
def mock_claude_dir(tmp_path):
    """Create a mock ~/.claude directory structure."""
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    return tmp_path


@pytest.fixture
def watcher_config(mock_claude_dir):
    """Create a WatcherConfig pointing to mock directory."""
    return WatcherConfig(
        base_path=mock_claude_dir,
        poll_interval=0.1,
        idle_timeout=timedelta(seconds=1),
        end_timeout=timedelta(seconds=2),
        emit_session_events=True,
        process_existing=True,  # Must be True to discover files created before watcher starts
    )


class TestAsyncSessionWatcherBasics:
    """Basic AsyncSessionWatcher tests."""

    @pytest.mark.asyncio
    async def test_initialization(self, watcher_config):
        """AsyncSessionWatcher should initialize correctly."""
        watcher = AsyncSessionWatcher(config=watcher_config)
        assert watcher is not None
        assert not watcher.is_running

    @pytest.mark.asyncio
    async def test_handler_registration(self, watcher_config):
        """Handler registration should work before starting."""
        watcher = AsyncSessionWatcher(config=watcher_config)
        received = []

        @watcher.on("message")
        def handler(event):
            received.append(event)

        assert watcher.handler_count == 1

    @pytest.mark.asyncio
    async def test_off_removes_handler(self, watcher_config):
        """off() should remove a registered handler."""
        watcher = AsyncSessionWatcher(config=watcher_config)

        def handler(event):
            pass

        watcher.on("message", handler)
        assert watcher.handler_count == 1

        result = watcher.off("message", handler)
        assert result is True
        assert watcher.handler_count == 0

    @pytest.mark.asyncio
    async def test_on_any_wildcard(self, watcher_config):
        """on_any() should register wildcard handler."""
        watcher = AsyncSessionWatcher(config=watcher_config)

        @watcher.on_any
        def handler(event):
            pass

        assert watcher.handler_count == 1

    @pytest.mark.asyncio
    async def test_off_any_removes_wildcard(self, watcher_config):
        """off_any() should remove wildcard handler."""
        watcher = AsyncSessionWatcher(config=watcher_config)

        def handler(event):
            pass

        watcher.on_any(handler)
        result = watcher.off_any(handler)
        assert result is True
        assert watcher.handler_count == 0


class TestAsyncDecoratorHandlers:
    """Test decorator-style handler registration."""

    @pytest.mark.asyncio
    async def test_sync_handler_decorator(self, mock_claude_dir, watcher_config):
        """Sync handlers should work with @watcher.on()."""
        project_dir = mock_claude_dir / "projects" / "test-project"
        project_dir.mkdir(parents=True)

        session_id = "test-session-12345678"
        session_file = project_dir / f"{session_id}.jsonl"
        session_file.write_text(
            json.dumps(make_user_entry(session_id, "msg-1")) + "\n"
        )

        watcher = AsyncSessionWatcher(config=watcher_config)
        received = []

        @watcher.on("message")
        def handler(event):
            received.append(event)

        await watcher.run_for(0.3)

        assert len(received) >= 1

    @pytest.mark.asyncio
    async def test_async_handler_decorator(self, mock_claude_dir, watcher_config):
        """Async handlers should work with @watcher.on()."""
        project_dir = mock_claude_dir / "projects" / "test-project"
        project_dir.mkdir(parents=True)

        session_id = "test-session-12345678"
        session_file = project_dir / f"{session_id}.jsonl"
        session_file.write_text(
            json.dumps(make_user_entry(session_id, "msg-1")) + "\n"
        )

        watcher = AsyncSessionWatcher(config=watcher_config)
        received = []

        @watcher.on("message")
        async def handler(event):
            await asyncio.sleep(0.01)  # Simulate async work
            received.append(event)

        await watcher.run_for(0.3)

        assert len(received) >= 1


class TestAsyncRunFor:
    """Test run_for() which handles cleanup properly."""

    @pytest.mark.asyncio
    async def test_run_for_duration(self, watcher_config):
        """run_for() should run for specified duration."""
        watcher = AsyncSessionWatcher(config=watcher_config)

        import time
        start = time.time()
        await watcher.run_for(0.2)
        elapsed = time.time() - start

        assert elapsed >= 0.15  # Allow some tolerance
        assert not watcher.is_running

    @pytest.mark.asyncio
    async def test_run_for_discovers_session(self, mock_claude_dir, watcher_config):
        """run_for() should discover and process sessions."""
        project_dir = mock_claude_dir / "projects" / "test-project"
        project_dir.mkdir(parents=True)

        session_id = "test-session-12345678"
        session_file = project_dir / f"{session_id}.jsonl"
        session_file.write_text(
            json.dumps(make_user_entry(session_id, "msg-1")) + "\n"
        )

        watcher = AsyncSessionWatcher(config=watcher_config)
        received = []

        @watcher.on_any
        def handler(event):
            received.append(event)

        await watcher.run_for(0.3)

        # Should have received events
        assert len(received) >= 1


class TestAsyncProperties:
    """Test async watcher properties."""

    @pytest.mark.asyncio
    async def test_handler_count(self, watcher_config):
        """handler_count should track registered handlers."""
        watcher = AsyncSessionWatcher(config=watcher_config)

        @watcher.on("message")
        def h1(event):
            pass

        @watcher.on("tool_use")
        async def h2(event):
            pass

        assert watcher.handler_count == 2

    @pytest.mark.asyncio
    async def test_config_property(self, watcher_config):
        """config property should return configuration."""
        watcher = AsyncSessionWatcher(config=watcher_config)
        assert watcher.config == watcher_config

    @pytest.mark.asyncio
    async def test_live_sessions_disabled_by_default(self, watcher_config):
        """live_sessions should be None when not enabled."""
        watcher = AsyncSessionWatcher(config=watcher_config)
        assert watcher.live_sessions is None

    @pytest.mark.asyncio
    async def test_repr(self, watcher_config):
        """__repr__ should show status."""
        watcher = AsyncSessionWatcher(config=watcher_config)
        assert "stopped" in repr(watcher)
        assert "0 handlers" in repr(watcher)


class TestAsyncErrorHandling:
    """Test async error handling."""

    @pytest.mark.asyncio
    async def test_handler_exception_isolated(self, mock_claude_dir, watcher_config):
        """Handler exceptions should not crash the watcher."""
        project_dir = mock_claude_dir / "projects" / "test-project"
        project_dir.mkdir(parents=True)

        session_id = "test-session-12345678"
        session_file = project_dir / f"{session_id}.jsonl"
        session_file.write_text(
            json.dumps(make_user_entry(session_id, "msg-1")) + "\n"
        )

        watcher = AsyncSessionWatcher(config=watcher_config)
        good_received = []

        @watcher.on("message")
        async def bad_handler(event):
            raise ValueError("Handler error")

        @watcher.on("message")
        async def good_handler(event):
            good_received.append(event)

        # Should not crash
        await watcher.run_for(0.3)

        # Good handler should still be called
        assert len(good_received) >= 1
