"""Session watcher for realtime monitoring of Claude Code sessions.

This module provides the SessionWatcher class for monitoring the ~/.claude/projects/
directory and emitting events as new sessions appear and messages are added.

Example usage:
    from claude_sessions.realtime import SessionWatcher

    watcher = SessionWatcher()

    @watcher.on("session_start")
    def on_start(event):
        print(f"New session: {event.session_id[:8]}")

    @watcher.on("message")
    def on_message(event):
        print(f"{event.message.role}: {event.message.text_content[:80]}")

    watcher.start()  # Blocks until Ctrl+C
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .live import LiveSessionConfig, LiveSessionManager

from .emitter import EventEmitter
from .events import (
    SessionEndEvent,
    SessionEventType,
    SessionIdleEvent,
    SessionResumeEvent,
    SessionStartEvent,
    ToolCallCompletedEvent,
)
from .parser import IncrementalParser
from .tailer import JSONLTailer

# Try to import watchdog, but allow running without it
try:
    from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent
    from watchdog.observers import Observer

    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    FileSystemEventHandler = object  # type: ignore
    Observer = None  # type: ignore

logger = logging.getLogger(__name__)


@dataclass
class WatcherConfig:
    """Configuration for SessionWatcher.

    Attributes:
        base_path: Base Claude directory (default: ~/.claude)
        poll_interval: How often to check for changes in seconds
        idle_timeout: Duration before session considered idle
        end_timeout: Duration after idle before session considered ended
        process_existing: Whether to process existing files on startup
        emit_session_events: Whether to emit session start/end/idle events
        truncate_inputs: Whether to truncate large tool inputs
        max_input_length: Max length for tool input truncation
    """

    base_path: Path = field(default_factory=lambda: Path.home() / ".claude")
    poll_interval: float = 0.5
    idle_timeout: timedelta = field(default_factory=lambda: timedelta(minutes=2))
    end_timeout: timedelta = field(default_factory=lambda: timedelta(minutes=5))
    process_existing: bool = True
    emit_session_events: bool = True
    truncate_inputs: bool = True
    max_input_length: int = 1024

    @property
    def projects_path(self) -> Path:
        """Path to projects directory."""
        return self.base_path / "projects"


@dataclass
class TrackedSession:
    """Internal state for a tracked session.

    Tracks file position, activity timestamps, and statistics
    for session lifecycle management.
    """

    session_id: str
    project_slug: str
    file_path: Path
    tailer: JSONLTailer

    # Timestamps
    discovered_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    last_activity: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    # State
    is_idle: bool = False
    idle_since: Optional[datetime] = None
    is_ended: bool = False

    # Counters
    message_count: int = 0
    tool_count: int = 0

    # First message metadata
    cwd: Optional[str] = None

    # Related agent files
    agent_files: Dict[str, JSONLTailer] = field(default_factory=dict)

    def update_activity(self) -> bool:
        """Mark session as active.

        Returns:
            True if session was previously idle (resumed), False otherwise.
        """
        was_idle = self.is_idle

        self.last_activity = datetime.now(timezone.utc)
        self.is_idle = False
        self.idle_since = None

        return was_idle

    def check_idle(self, timeout: timedelta) -> bool:
        """Check if session has become idle.

        Args:
            timeout: Duration after which session is considered idle.

        Returns:
            True if session just became idle, False otherwise.
        """
        if self.is_idle or self.is_ended:
            return False

        now = datetime.now(timezone.utc)
        if now - self.last_activity > timeout:
            self.is_idle = True
            self.idle_since = self.last_activity
            return True
        return False

    def check_ended(self, end_timeout: timedelta) -> bool:
        """Check if idle session should be considered ended.

        Args:
            end_timeout: Duration after idle before session is ended.

        Returns:
            True if session just ended, False otherwise.
        """
        if self.is_ended or not self.is_idle:
            return False

        if self.idle_since is None:
            return False

        now = datetime.now(timezone.utc)
        if now - self.idle_since > end_timeout:
            self.is_ended = True
            return True
        return False


class SessionFileHandler(FileSystemEventHandler):
    """Handle file system events for session files."""

    def __init__(self, watcher: "SessionWatcher"):
        super().__init__()
        self._watcher = watcher

    def on_created(self, event: Any) -> None:
        if event.is_directory:
            return
        if event.src_path.endswith(".jsonl"):
            self._watcher._queue_file_event("created", Path(event.src_path))

    def on_modified(self, event: Any) -> None:
        if event.is_directory:
            return
        if event.src_path.endswith(".jsonl"):
            self._watcher._queue_file_event("modified", Path(event.src_path))


class SessionWatcher:
    """Monitors Claude session directories for changes.

    Provides a high-level API for watching session files and emitting
    events. Integrates watchdog file monitoring with the existing
    tailer/parser/emitter infrastructure.

    Example (callback style):
        watcher = SessionWatcher()

        @watcher.on("session_start")
        def on_start(event):
            print(f"New session: {event.session_id}")

        @watcher.on("message")
        def on_message(event):
            print(f"{event.message.role}: {event.message.text_content[:80]}")

        watcher.start()  # Blocking

    Example (context manager):
        with SessionWatcher() as watcher:
            @watcher.on("message")
            def handle(event):
                print(event)

            watcher.run_for(seconds=60)

    Example (with live session state):
        watcher = SessionWatcher(live_sessions=True)

        @watcher.on("session_end")
        def on_end(event):
            session = watcher.live_sessions.get_session(event.session_id)
            if session:
                immutable = session.to_session()
                print(f"Session had {session.message_count} messages")
    """

    def __init__(
        self,
        config: Optional[WatcherConfig] = None,
        live_sessions: bool = False,
        live_config: Optional["LiveSessionConfig"] = None,
    ):
        """Initialize the session watcher.

        Args:
            config: Configuration options (uses defaults if None)
            live_sessions: If True, enable live session state tracking.
                When enabled, the watcher maintains a LiveSessionManager
                that accumulates message history and pairs tool calls.
            live_config: Configuration for live sessions. Only used if
                live_sessions=True. Uses defaults if None.
        """
        self._config = config or WatcherConfig()
        self._emitter = EventEmitter()
        self._parser = IncrementalParser(
            truncate_inputs=self._config.truncate_inputs,
            max_input_length=self._config.max_input_length,
        )

        # Tracked sessions by session_id
        self._sessions: Dict[str, TrackedSession] = {}

        # File path to session_id mapping
        self._file_to_session: Dict[Path, str] = {}

        # Live session management (optional)
        self._live_manager: Optional["LiveSessionManager"] = None
        if live_sessions:
            from .live import LiveSessionManager
            self._live_manager = LiveSessionManager(default_config=live_config)

        # Watchdog components
        self._observer: Optional[Any] = None
        self._handler: Optional[SessionFileHandler] = None

        # Thread safety
        self._lock = threading.Lock()
        self._pending_files: List[Tuple[str, Path]] = []

        # State
        self._running = False
        self._stop_event = threading.Event()
        self._background_thread: Optional[threading.Thread] = None

    # --- Public API ---

    def on(
        self, event_type: str, handler: Optional[Callable[[SessionEventType], None]] = None
    ) -> Callable:
        """Register an event handler (decorator or direct call).

        Args:
            event_type: Event type to handle ("message", "tool_use", etc.)
            handler: Handler function (optional for decorator use)

        Returns:
            Handler or decorator
        """
        return self._emitter.on(event_type, handler)

    def on_any(self, handler: Callable[[SessionEventType], None]) -> Callable:
        """Register handler for all events.

        Args:
            handler: Handler function to receive all events.

        Returns:
            The handler function.
        """
        return self._emitter.on_any(handler)

    def off(self, event_type: str, handler: Callable) -> bool:
        """Unregister a handler.

        Args:
            event_type: Event type the handler was registered for.
            handler: Handler function to remove.

        Returns:
            True if handler was found and removed.
        """
        return self._emitter.off(event_type, handler)

    @property
    def live_sessions(self) -> Optional["LiveSessionManager"]:
        """Access the live session manager.

        Returns:
            LiveSessionManager if live_sessions=True was passed to __init__,
            None otherwise.

        Example:
            watcher = SessionWatcher(live_sessions=True)
            watcher.start_background()

            # Later...
            session = watcher.live_sessions.get_session("abc-123")
            if session:
                print(f"Messages: {session.message_count}")
        """
        return self._live_manager

    def start(self) -> None:
        """Start watching for sessions (blocking).

        This method blocks until stop() is called or KeyboardInterrupt.
        """
        self._start_watching()
        try:
            while not self._stop_event.is_set():
                self._poll_cycle()
                self._stop_event.wait(self._config.poll_interval)
        finally:
            self._stop_watching()

    def start_background(self) -> None:
        """Start watching in a background thread.

        Returns immediately. Use stop() to terminate.
        """
        self._start_watching()
        self._background_thread = threading.Thread(
            target=self._background_loop,
            daemon=True,
        )
        self._background_thread.start()

    def stop(self) -> None:
        """Stop watching for sessions."""
        self._stop_event.set()
        if self._background_thread is not None:
            self._background_thread.join(timeout=5.0)
            self._background_thread = None
        self._stop_watching()

    def run_for(self, seconds: float) -> None:
        """Run watcher for a limited duration.

        Args:
            seconds: How long to run.
        """
        self._start_watching()
        deadline = time.time() + seconds
        try:
            while time.time() < deadline and not self._stop_event.is_set():
                self._poll_cycle()
                remaining = deadline - time.time()
                wait_time = min(self._config.poll_interval, max(0, remaining))
                if wait_time > 0:
                    self._stop_event.wait(wait_time)
        finally:
            self._stop_watching()

    def get_active_sessions(self) -> List[str]:
        """Get list of active (non-ended) session IDs."""
        with self._lock:
            return [
                sid
                for sid, ts in self._sessions.items()
                if not ts.is_ended
            ]

    def get_session_stats(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get statistics for a tracked session.

        Args:
            session_id: The session ID to look up.

        Returns:
            Dictionary with session statistics, or None if not found.
        """
        with self._lock:
            ts = self._sessions.get(session_id)
            if ts is None:
                return None
            return {
                "session_id": ts.session_id,
                "project_slug": ts.project_slug,
                "message_count": ts.message_count,
                "tool_count": ts.tool_count,
                "is_idle": ts.is_idle,
                "is_ended": ts.is_ended,
                "last_activity": ts.last_activity,
                "cwd": ts.cwd,
            }

    @property
    def config(self) -> WatcherConfig:
        """Get the watcher configuration."""
        return self._config

    # --- Context Manager ---

    def __enter__(self) -> "SessionWatcher":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        self.stop()
        return False

    # --- Internal Methods ---

    def _queue_file_event(self, action: str, path: Path) -> None:
        """Queue a file event from watchdog thread for processing.

        Args:
            action: "created" or "modified"
            path: Path to the file.
        """
        with self._lock:
            self._pending_files.append((action, path))

    def _start_watching(self) -> None:
        """Initialize file watching."""
        if self._running:
            return

        self._running = True
        self._stop_event.clear()

        # Set up watchdog if available
        projects_path = self._config.projects_path
        if WATCHDOG_AVAILABLE and projects_path.exists():
            try:
                self._handler = SessionFileHandler(self)
                self._observer = Observer()
                self._observer.schedule(
                    self._handler,
                    str(projects_path),
                    recursive=True,
                )
                self._observer.start()
                logger.debug("Started watchdog observer on %s", projects_path)
            except Exception as e:
                logger.warning("Failed to start watchdog, using polling only: %s", e)
                self._observer = None
                self._handler = None
        elif not WATCHDOG_AVAILABLE:
            logger.debug("watchdog not available, using polling only")

        # Discover existing sessions
        if self._config.process_existing:
            self._discover_existing_sessions()

    def _stop_watching(self) -> None:
        """Clean up file watching."""
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5.0)
            self._observer = None
        self._handler = None
        self._running = False

    def _background_loop(self) -> None:
        """Background thread main loop."""
        try:
            while not self._stop_event.is_set():
                self._poll_cycle()
                self._stop_event.wait(self._config.poll_interval)
        except Exception as e:
            logger.exception("Error in background loop: %s", e)

    def _poll_cycle(self) -> None:
        """Single poll iteration - process pending events, read new data, check timeouts."""
        # Process pending file events from watchdog
        self._process_pending_file_events()

        # Read new data from all tracked sessions
        with self._lock:
            sessions = list(self._sessions.items())

        for session_id, tracked in sessions:
            if tracked.is_ended:
                continue
            self._process_session_updates(tracked)

        # Check for idle/end timeouts
        self._check_timeouts()

    def _process_pending_file_events(self) -> None:
        """Process file events queued from watchdog."""
        with self._lock:
            pending = list(self._pending_files)
            self._pending_files.clear()

        for action, path in pending:
            try:
                if action == "created":
                    self._handle_file_created(path)
                elif action == "modified":
                    self._handle_file_modified(path)
            except Exception as e:
                logger.warning("Error processing file event %s %s: %s", action, path, e)

    def _discover_existing_sessions(self) -> None:
        """Scan for existing session files on startup."""
        projects_path = self._config.projects_path
        if not projects_path.exists():
            logger.debug("Projects path does not exist: %s", projects_path)
            return

        for project_dir in projects_path.iterdir():
            if not project_dir.is_dir():
                continue

            project_slug = project_dir.name

            for jsonl_file in project_dir.glob("*.jsonl"):
                # Skip agent files - they'll be associated with sessions
                if jsonl_file.stem.startswith("agent-"):
                    continue

                session_id = jsonl_file.stem
                with self._lock:
                    if session_id not in self._sessions:
                        self._track_session(session_id, project_slug, jsonl_file)

    def _handle_file_created(self, file_path: Path) -> None:
        """Handle new file creation."""
        try:
            project_slug = file_path.parent.name
        except Exception:
            return

        filename = file_path.stem

        if filename.startswith("agent-"):
            # Agent file - associate with parent session
            self._handle_agent_file(file_path, project_slug)
        else:
            # Main session file
            session_id = filename
            with self._lock:
                if session_id not in self._sessions:
                    self._track_session(session_id, project_slug, file_path)

    def _handle_file_modified(self, file_path: Path) -> None:
        """Handle file modification."""
        with self._lock:
            session_id = self._file_to_session.get(file_path)
            if session_id:
                tracked = self._sessions.get(session_id)
                if tracked and not tracked.is_ended:
                    # Will be processed in next poll cycle
                    pass

    def _track_session(
        self,
        session_id: str,
        project_slug: str,
        file_path: Path,
    ) -> TrackedSession:
        """Start tracking a new session.

        Note: Must be called with self._lock held.
        """
        tailer = JSONLTailer(file_path)

        tracked = TrackedSession(
            session_id=session_id,
            project_slug=project_slug,
            file_path=file_path,
            tailer=tailer,
        )

        self._sessions[session_id] = tracked
        self._file_to_session[file_path] = session_id

        # Emit session start event
        if self._config.emit_session_events:
            self._emitter.emit(
                SessionStartEvent(
                    timestamp=datetime.now(timezone.utc),
                    session_id=session_id,
                    project_slug=project_slug,
                    file_path=file_path,
                )
            )

        # Process initial content (release lock temporarily)
        # We need to release lock to avoid deadlock during event emission
        self._lock.release()
        try:
            self._process_session_updates(tracked)
            # Look for associated agent files
            self._discover_agent_files(tracked)
        finally:
            self._lock.acquire()

        return tracked

    def _handle_agent_file(self, file_path: Path, project_slug: str) -> None:
        """Associate an agent file with its parent session."""
        # Read first entry to get session_id
        tailer = JSONLTailer(file_path)
        entries = tailer.read_new()

        if not entries:
            return

        session_id = entries[0].get("sessionId")
        if not session_id:
            return

        with self._lock:
            tracked = self._sessions.get(session_id)
            if tracked:
                agent_id = file_path.stem  # "agent-{short_id}"
                tracked.agent_files[agent_id] = tailer

        # Process the entries we already read
        if tracked:
            for entry in entries:
                self._process_entry(tracked, entry)

    def _discover_agent_files(self, tracked: TrackedSession) -> None:
        """Find existing agent files for a session."""
        project_dir = tracked.file_path.parent

        for agent_file in project_dir.glob("agent-*.jsonl"):
            if agent_file.stem in tracked.agent_files:
                continue

            # Check if it belongs to this session
            tailer = JSONLTailer(agent_file)
            entries = tailer.read_new()

            if entries and entries[0].get("sessionId") == tracked.session_id:
                tracked.agent_files[agent_file.stem] = tailer
                for entry in entries:
                    self._process_entry(tracked, entry)

    def _process_session_updates(self, tracked: TrackedSession) -> None:
        """Read and process new entries from a session."""
        had_activity = False

        # Read main session file
        try:
            for entry in tracked.tailer.read_new():
                self._process_entry(tracked, entry)
                had_activity = True
        except Exception as e:
            logger.warning(
                "Error reading session file %s: %s", tracked.file_path, e
            )

        # Read agent files
        for agent_id, tailer in list(tracked.agent_files.items()):
            try:
                for entry in tailer.read_new():
                    self._process_entry(tracked, entry)
                    had_activity = True
            except Exception as e:
                logger.warning("Error reading agent file %s: %s", agent_id, e)

        # Update activity if we had new data
        if had_activity:
            was_idle = tracked.update_activity()

            # Emit resume event if coming back from idle
            if was_idle and tracked.idle_since:
                idle_duration = datetime.now(timezone.utc) - tracked.idle_since
                self._emitter.emit(
                    SessionResumeEvent(
                        timestamp=datetime.now(timezone.utc),
                        session_id=tracked.session_id,
                        idle_duration=idle_duration,
                    )
                )

    def _process_entry(self, tracked: TrackedSession, entry: Dict[str, Any]) -> None:
        """Process a single JSONL entry."""
        events = self._parser.parse_entry(entry)

        for event in events:
            # Update counters
            if event.event_type == "message":
                tracked.message_count += 1
                # Capture cwd from first message
                if tracked.cwd is None and hasattr(event, "message"):
                    tracked.cwd = getattr(event.message, "cwd", None)
            elif event.event_type == "tool_use":
                tracked.tool_count += 1

            # Route to live manager if enabled
            if self._live_manager is not None:
                completed_tool_call = self._live_manager.handle_event(event)

                # Emit ToolCallCompletedEvent when a tool call is paired
                if completed_tool_call is not None:
                    self._emitter.emit(
                        ToolCallCompletedEvent(
                            timestamp=datetime.now(timezone.utc),
                            session_id=tracked.session_id,
                            tool_call=completed_tool_call,
                            agent_id=getattr(event, "agent_id", None),
                        )
                    )

            # Emit the event
            self._emitter.emit(event)

    def _check_timeouts(self) -> None:
        """Check all sessions for idle/end timeouts."""
        with self._lock:
            sessions = list(self._sessions.items())

        for session_id, tracked in sessions:
            if tracked.is_ended:
                continue

            # Check for new idle
            if tracked.check_idle(self._config.idle_timeout):
                if self._config.emit_session_events and tracked.idle_since:
                    self._emitter.emit(
                        SessionIdleEvent(
                            timestamp=datetime.now(timezone.utc),
                            session_id=session_id,
                            idle_since=tracked.idle_since,
                        )
                    )

            # Check for end (after idle)
            if tracked.check_ended(self._config.end_timeout):
                if self._config.emit_session_events:
                    idle_duration = None
                    if tracked.idle_since:
                        idle_duration = datetime.now(timezone.utc) - tracked.idle_since

                    self._emitter.emit(
                        SessionEndEvent(
                            timestamp=datetime.now(timezone.utc),
                            session_id=session_id,
                            reason="idle_timeout",
                            idle_duration=idle_duration,
                            message_count=tracked.message_count,
                            tool_count=tracked.tool_count,
                        )
                    )
