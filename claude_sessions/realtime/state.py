"""State persistence for resumable session watching.

This module provides functionality to save and restore tailer positions,
enabling the watcher to resume from where it left off after a restart.

Example usage:
    from claude_sessions.realtime import SessionWatcher, WatcherConfig, WatcherState

    # Enable state persistence
    config = WatcherConfig(
        state_file=Path("~/.claude/watcher_state.json").expanduser()
    )

    watcher = SessionWatcher(config=config)
    watcher.start()  # Will resume from saved positions

    # State is automatically saved on stop and periodically
"""

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .tailer import TailerState, JSONLTailer

logger = logging.getLogger(__name__)


@dataclass
class FilePosition:
    """Serializable file position state.

    Stores the information needed to resume tailing a file from a
    specific position.

    Attributes:
        file_path: Absolute path to the file
        position: Byte position in the file
        inode: File inode for rotation detection
        last_modified: When this position was last updated
    """

    file_path: str
    position: int
    inode: int
    last_modified: str  # ISO format datetime

    @classmethod
    def from_tailer(cls, tailer: "JSONLTailer") -> "FilePosition":
        """Create a FilePosition from a JSONLTailer.

        Args:
            tailer: The tailer to capture state from

        Returns:
            FilePosition with current tailer state
        """
        return cls(
            file_path=str(tailer.state.file_path.absolute()),
            position=tailer.state.position,
            inode=tailer.state.inode,
            last_modified=datetime.now(timezone.utc).isoformat(),
        )

    def apply_to_tailer(self, tailer: "JSONLTailer") -> bool:
        """Apply this position to a tailer.

        Only applies if the file path matches and the file hasn't been
        rotated (same inode) or truncated (size >= position).

        Args:
            tailer: The tailer to restore state to

        Returns:
            True if state was applied, False if file changed
        """
        # Verify file path matches
        if str(tailer.state.file_path.absolute()) != self.file_path:
            return False

        try:
            stat = os.stat(tailer.state.file_path)

            # Check if file was rotated (inode changed)
            if stat.st_ino != self.inode:
                logger.debug(
                    "File %s was rotated (inode %d -> %d), starting fresh",
                    self.file_path,
                    self.inode,
                    stat.st_ino,
                )
                return False

            # Check if file was truncated
            if stat.st_size < self.position:
                logger.debug(
                    "File %s was truncated (%d < %d), starting fresh",
                    self.file_path,
                    stat.st_size,
                    self.position,
                )
                return False

            # Safe to restore position
            tailer.state.position = self.position
            tailer.state.inode = self.inode
            logger.debug(
                "Restored position %d for %s",
                self.position,
                self.file_path,
            )
            return True

        except OSError as e:
            logger.warning("Error checking file %s: %s", self.file_path, e)
            return False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FilePosition":
        """Create from dict (e.g., loaded from JSON)."""
        return cls(
            file_path=data["file_path"],
            position=data["position"],
            inode=data["inode"],
            last_modified=data.get("last_modified", datetime.now(timezone.utc).isoformat()),
        )


@dataclass
class WatcherState:
    """Persistent state for the session watcher.

    Stores file positions and metadata for resumable watching.

    Attributes:
        file_positions: Dict mapping file paths to their positions
        last_saved: When the state was last saved
        version: State format version for compatibility
    """

    file_positions: Dict[str, FilePosition] = field(default_factory=dict)
    last_saved: Optional[str] = None  # ISO format datetime
    version: int = 1

    def save(self, path: Path) -> None:
        """Save state to a JSON file.

        Creates parent directories if needed. Uses atomic write
        (write to temp, then rename) to prevent corruption.

        Args:
            path: Path to save the state file
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        self.last_saved = datetime.now(timezone.utc).isoformat()

        data = {
            "version": self.version,
            "last_saved": self.last_saved,
            "file_positions": {
                fp: pos.to_dict() for fp, pos in self.file_positions.items()
            },
        }

        # Atomic write
        temp_path = path.with_suffix(".tmp")
        try:
            with open(temp_path, "w") as f:
                json.dump(data, f, indent=2)
            temp_path.replace(path)
            logger.debug("Saved watcher state to %s", path)
        except Exception as e:
            logger.warning("Failed to save watcher state: %s", e)
            if temp_path.exists():
                temp_path.unlink()
            raise

    @classmethod
    def load(cls, path: Path) -> "WatcherState":
        """Load state from a JSON file.

        Args:
            path: Path to the state file

        Returns:
            Loaded WatcherState, or empty state if file doesn't exist

        Raises:
            ValueError: If state file format is incompatible
        """
        path = Path(path)

        if not path.exists():
            logger.debug("No state file found at %s, starting fresh", path)
            return cls()

        try:
            with open(path) as f:
                data = json.load(f)

            version = data.get("version", 1)
            if version > cls.version:
                raise ValueError(
                    f"State file version {version} is newer than supported {cls.version}"
                )

            file_positions = {
                fp: FilePosition.from_dict(pos_data)
                for fp, pos_data in data.get("file_positions", {}).items()
            }

            state = cls(
                file_positions=file_positions,
                last_saved=data.get("last_saved"),
                version=version,
            )

            logger.debug(
                "Loaded watcher state from %s (%d positions)",
                path,
                len(file_positions),
            )
            return state

        except json.JSONDecodeError as e:
            logger.warning("Corrupt state file %s: %s", path, e)
            return cls()
        except Exception as e:
            logger.warning("Error loading state file %s: %s", path, e)
            return cls()

    def update_from_tailer(self, tailer: "JSONLTailer") -> None:
        """Update state with current tailer position.

        Args:
            tailer: The tailer to capture state from
        """
        file_path = str(tailer.state.file_path.absolute())
        self.file_positions[file_path] = FilePosition.from_tailer(tailer)

    def apply_to_tailer(self, tailer: "JSONLTailer") -> bool:
        """Apply saved position to a tailer if available.

        Args:
            tailer: The tailer to restore state to

        Returns:
            True if state was applied, False otherwise
        """
        file_path = str(tailer.state.file_path.absolute())
        position = self.file_positions.get(file_path)

        if position is None:
            return False

        return position.apply_to_tailer(tailer)

    def prune_stale(self, max_age: timedelta = timedelta(days=7)) -> int:
        """Remove positions for files that no longer exist or are stale.

        Args:
            max_age: Maximum age for position entries

        Returns:
            Number of entries removed
        """
        now = datetime.now(timezone.utc)
        to_remove = []

        for file_path, position in self.file_positions.items():
            # Check if file exists
            if not Path(file_path).exists():
                to_remove.append(file_path)
                continue

            # Check age
            try:
                last_modified = datetime.fromisoformat(position.last_modified)
                if now - last_modified > max_age:
                    to_remove.append(file_path)
            except (ValueError, TypeError):
                pass

        for file_path in to_remove:
            del self.file_positions[file_path]

        if to_remove:
            logger.debug("Pruned %d stale position entries", len(to_remove))

        return len(to_remove)

    def clear(self) -> None:
        """Clear all saved positions."""
        self.file_positions.clear()
        self.last_saved = None

    def __len__(self) -> int:
        """Number of saved file positions."""
        return len(self.file_positions)

    def __repr__(self) -> str:
        return f"WatcherState({len(self.file_positions)} positions)"


class StatePersistence:
    """Manages periodic saving of watcher state.

    Handles automatic saving on an interval and on shutdown.
    Thread-safe for use with background watchers.

    Example:
        persistence = StatePersistence(
            state_file=Path("state.json"),
            save_interval=timedelta(seconds=30),
        )

        persistence.start()

        # Update state as files are processed
        persistence.update_from_tailer(tailer)

        # State is auto-saved periodically
        persistence.stop()  # Final save on stop
    """

    def __init__(
        self,
        state_file: Path,
        save_interval: timedelta = timedelta(seconds=30),
        load_existing: bool = True,
    ):
        """Initialize persistence manager.

        Args:
            state_file: Path to save/load state
            save_interval: How often to auto-save
            load_existing: Whether to load existing state on init
        """
        self._state_file = Path(state_file)
        self._save_interval = save_interval
        self._lock = threading.RLock()

        # Load or create state
        if load_existing:
            self._state = WatcherState.load(self._state_file)
        else:
            self._state = WatcherState()

        # Background save thread
        self._stop_event = threading.Event()
        self._save_thread: Optional[threading.Thread] = None
        self._dirty = False

    @property
    def state(self) -> WatcherState:
        """Access the current state."""
        return self._state

    def start(self) -> None:
        """Start periodic saving."""
        if self._save_thread is not None:
            return

        self._stop_event.clear()
        self._save_thread = threading.Thread(
            target=self._save_loop,
            daemon=True,
        )
        self._save_thread.start()
        logger.debug("Started state persistence thread")

    def stop(self) -> None:
        """Stop periodic saving and do a final save."""
        self._stop_event.set()

        if self._save_thread is not None:
            self._save_thread.join(timeout=5.0)
            self._save_thread = None

        # Final save
        self._save_if_dirty()
        logger.debug("Stopped state persistence thread")

    def update_from_tailer(self, tailer: "JSONLTailer") -> None:
        """Update state with tailer position.

        Args:
            tailer: Tailer to capture state from
        """
        with self._lock:
            self._state.update_from_tailer(tailer)
            self._dirty = True

    def apply_to_tailer(self, tailer: "JSONLTailer") -> bool:
        """Apply saved position to tailer.

        Args:
            tailer: Tailer to restore

        Returns:
            True if position was restored
        """
        with self._lock:
            return self._state.apply_to_tailer(tailer)

    def save_now(self) -> None:
        """Force an immediate save."""
        with self._lock:
            self._state.save(self._state_file)
            self._dirty = False

    def _save_if_dirty(self) -> None:
        """Save if there are unsaved changes."""
        with self._lock:
            if self._dirty:
                try:
                    self._state.save(self._state_file)
                    self._dirty = False
                except Exception as e:
                    logger.warning("Failed to save state: %s", e)

    def _save_loop(self) -> None:
        """Background thread for periodic saving."""
        while not self._stop_event.is_set():
            self._stop_event.wait(self._save_interval.total_seconds())
            if not self._stop_event.is_set():
                self._save_if_dirty()

    def __enter__(self) -> "StatePersistence":
        self.start()
        return self

    def __exit__(self, *args: Any) -> None:
        self.stop()
