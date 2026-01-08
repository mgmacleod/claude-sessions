"""JSONL file tailing for realtime session monitoring.

This module provides the JSONLTailer class for incrementally reading
new entries from JSONL files as they are appended.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, List, Optional, Tuple


@dataclass
class TailerState:
    """Tracks position in a JSONL file for incremental reading.

    Attributes:
        file_path: Path to the JSONL file being tailed
        position: Current byte position in the file
        inode: File inode for detecting rotation/truncation
        line_buffer: Incomplete line from previous read
    """

    file_path: Path
    position: int = 0
    inode: int = 0
    line_buffer: str = ""

    def reset(self) -> None:
        """Reset state to beginning of file."""
        self.position = 0
        self.line_buffer = ""


class JSONLTailer:
    """Tails a JSONL file, yielding new entries as they appear.

    This class provides incremental reading of JSONL files, handling:
    - Partial line writes (buffering incomplete JSON)
    - File truncation/rotation detection via inode
    - Graceful handling of malformed JSON

    Example:
        >>> tailer = JSONLTailer(Path("session.jsonl"))
        >>> for entry in tailer.read_new():
        ...     print(entry.get("type"))
        >>> # Later, read more new entries
        >>> for entry in tailer.read_new():
        ...     print(entry.get("type"))
    """

    def __init__(self, file_path: Path):
        """Initialize tailer for the given file.

        Args:
            file_path: Path to the JSONL file to tail
        """
        self.state = TailerState(file_path=Path(file_path))
        self._update_inode()

    def _update_inode(self) -> None:
        """Update stored inode from current file."""
        try:
            stat = os.stat(self.state.file_path)
            self.state.inode = stat.st_ino
        except OSError:
            self.state.inode = 0

    def _check_rotation(self) -> bool:
        """Check if file has been rotated or truncated.

        Returns:
            True if file was rotated/truncated and state was reset
        """
        try:
            stat = os.stat(self.state.file_path)
            current_inode = stat.st_ino
            current_size = stat.st_size

            # Inode changed = file was rotated
            if current_inode != self.state.inode:
                self.state.reset()
                self.state.inode = current_inode
                return True

            # Size shrunk = file was truncated
            if current_size < self.state.position:
                self.state.reset()
                return True

            return False
        except OSError:
            return False

    def _read_bytes(self) -> bytes:
        """Read new bytes from file starting at current position.

        Returns:
            New bytes read from file, or empty bytes on error
        """
        try:
            with open(self.state.file_path, "rb") as f:
                f.seek(self.state.position)
                return f.read()
        except OSError:
            return b""

    def _parse_lines(self, data: bytes) -> Tuple[List[dict], str]:
        """Parse complete JSON lines from data.

        Args:
            data: Raw bytes read from file

        Returns:
            Tuple of (parsed entries, remaining incomplete line)
        """
        # Decode and prepend any buffered partial line
        try:
            text = self.state.line_buffer + data.decode("utf-8")
        except UnicodeDecodeError:
            # Try with error handling
            text = self.state.line_buffer + data.decode("utf-8", errors="replace")

        lines = text.split("\n")
        entries: List[dict] = []

        # Last element is incomplete line (or empty if text ends with \n)
        incomplete = lines[-1]
        complete_lines = lines[:-1]

        for line in complete_lines:
            line = line.strip()
            if not line:
                continue

            try:
                entry = json.loads(line)
                entries.append(entry)
            except json.JSONDecodeError:
                # Skip malformed lines - caller can handle via ErrorEvent
                pass

        return entries, incomplete

    def read_new(self) -> List[dict]:
        """Read and parse any new entries since last read.

        This is a non-blocking read that returns immediately with
        any new entries, or an empty list if no new data.

        Returns:
            List of parsed JSON entries (may be empty)
        """
        # Check for rotation/truncation first
        self._check_rotation()

        # Read new bytes
        data = self._read_bytes()
        if not data:
            return []

        # Parse complete lines
        entries, incomplete = self._parse_lines(data)

        # Update state
        self.state.position += len(data)
        self.state.line_buffer = incomplete

        return entries

    def tail(self) -> Iterator[dict]:
        """Yield new entries as they appear (single pass).

        This is equivalent to read_new() but returns an iterator.
        For continuous watching, call read_new() in a loop with
        appropriate sleep intervals.

        Yields:
            Parsed JSON entries
        """
        for entry in self.read_new():
            yield entry

    def read_all(self) -> List[dict]:
        """Read all entries from beginning of file.

        Resets position to start and reads entire file.

        Returns:
            List of all parsed JSON entries
        """
        self.reset()
        return self.read_new()

    def reset(self) -> None:
        """Reset to beginning of file."""
        self.state.reset()
        self._update_inode()

    @property
    def position(self) -> int:
        """Current byte position in file."""
        return self.state.position

    @property
    def file_path(self) -> Path:
        """Path to the file being tailed."""
        return self.state.file_path

    @property
    def has_pending_data(self) -> bool:
        """Whether there's buffered incomplete data."""
        return bool(self.state.line_buffer)


class MultiFileTailer:
    """Tails multiple JSONL files simultaneously.

    Useful for watching a session's main file and agent sidechain files.

    Example:
        >>> tailer = MultiFileTailer([main_file, agent_file1, agent_file2])
        >>> for file_path, entry in tailer.read_new():
        ...     print(f"{file_path.name}: {entry.get('type')}")
    """

    def __init__(self, file_paths: List[Path]):
        """Initialize tailers for all given files.

        Args:
            file_paths: List of paths to JSONL files to tail
        """
        self._tailers = {path: JSONLTailer(path) for path in file_paths}

    def add_file(self, file_path: Path) -> None:
        """Add a new file to tail.

        Args:
            file_path: Path to JSONL file to add
        """
        if file_path not in self._tailers:
            self._tailers[file_path] = JSONLTailer(file_path)

    def remove_file(self, file_path: Path) -> None:
        """Remove a file from tailing.

        Args:
            file_path: Path to remove
        """
        self._tailers.pop(file_path, None)

    def read_new(self) -> List[Tuple[Path, dict]]:
        """Read new entries from all files.

        Returns:
            List of (file_path, entry) tuples
        """
        results: List[Tuple[Path, dict]] = []

        for file_path, tailer in self._tailers.items():
            for entry in tailer.read_new():
                results.append((file_path, entry))

        return results

    def reset(self) -> None:
        """Reset all tailers to beginning of their files."""
        for tailer in self._tailers.values():
            tailer.reset()

    @property
    def file_paths(self) -> List[Path]:
        """List of files being tailed."""
        return list(self._tailers.keys())
