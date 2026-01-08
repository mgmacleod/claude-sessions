"""Tests for claude_sessions.realtime.state module."""

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from claude_sessions.realtime.state import (
    FilePosition,
    WatcherState,
    StatePersistence,
)
from claude_sessions.realtime.tailer import JSONLTailer


class TestFilePosition:
    """Test FilePosition dataclass."""

    def test_from_tailer(self, tmp_path):
        """from_tailer() should capture tailer state."""
        file_path = tmp_path / "test.jsonl"
        file_path.write_text('{"test": true}\n')

        tailer = JSONLTailer(file_path)
        tailer.read_new()  # Advance position

        pos = FilePosition.from_tailer(tailer)

        assert pos.file_path == str(file_path.absolute())
        assert pos.position > 0
        assert pos.inode > 0

    def test_apply_to_tailer_success(self, tmp_path):
        """apply_to_tailer() should restore position when file unchanged."""
        file_path = tmp_path / "test.jsonl"
        content = '{"test": true}\n{"another": "entry"}\n'
        file_path.write_text(content)

        # Create tailer and advance it
        tailer1 = JSONLTailer(file_path)
        tailer1.read_new()
        pos = FilePosition.from_tailer(tailer1)

        # Create new tailer and restore position
        tailer2 = JSONLTailer(file_path)
        result = pos.apply_to_tailer(tailer2)

        assert result is True
        assert tailer2.position == pos.position

    def test_apply_to_tailer_truncated_file(self, tmp_path):
        """apply_to_tailer() should fail if file was truncated."""
        file_path = tmp_path / "test.jsonl"
        file_path.write_text('{"test": true}\n' * 100)

        tailer = JSONLTailer(file_path)
        tailer.read_new()
        pos = FilePosition.from_tailer(tailer)

        # Truncate the file
        file_path.write_text('{"new": "content"}\n')

        # Try to apply old position
        tailer2 = JSONLTailer(file_path)
        result = pos.apply_to_tailer(tailer2)

        assert result is False

    def test_apply_to_tailer_wrong_path(self, tmp_path):
        """apply_to_tailer() should fail if paths don't match."""
        file1 = tmp_path / "file1.jsonl"
        file2 = tmp_path / "file2.jsonl"
        file1.write_text('{"test": true}\n')
        file2.write_text('{"test": true}\n')

        tailer1 = JSONLTailer(file1)
        tailer1.read_new()
        pos = FilePosition.from_tailer(tailer1)

        tailer2 = JSONLTailer(file2)
        result = pos.apply_to_tailer(tailer2)

        assert result is False

    def test_to_dict_roundtrip(self, tmp_path):
        """to_dict() and from_dict() should roundtrip correctly."""
        file_path = tmp_path / "test.jsonl"
        file_path.write_text('{"test": true}\n')

        tailer = JSONLTailer(file_path)
        tailer.read_new()
        original = FilePosition.from_tailer(tailer)

        # Roundtrip through dict
        data = original.to_dict()
        restored = FilePosition.from_dict(data)

        assert restored.file_path == original.file_path
        assert restored.position == original.position
        assert restored.inode == original.inode


class TestWatcherState:
    """Test WatcherState dataclass."""

    def test_initial_state(self):
        """WatcherState should initialize empty."""
        state = WatcherState()
        assert len(state.file_positions) == 0

    def test_update_from_tailer(self, tmp_path):
        """update_from_tailer() should add/update file position."""
        file_path = tmp_path / "test.jsonl"
        file_path.write_text('{"test": true}\n')

        tailer = JSONLTailer(file_path)
        tailer.read_new()

        state = WatcherState()
        state.update_from_tailer(tailer)

        assert str(file_path.absolute()) in state.file_positions

    def test_apply_to_tailer(self, tmp_path):
        """apply_to_tailer() should restore from stored position."""
        file_path = tmp_path / "test.jsonl"
        file_path.write_text('{"test": true}\n{"second": "entry"}\n')

        # Create and advance first tailer
        tailer1 = JSONLTailer(file_path)
        tailer1.read_new()

        # Save state
        state = WatcherState()
        state.update_from_tailer(tailer1)

        # Create new tailer and restore
        tailer2 = JSONLTailer(file_path)
        result = state.apply_to_tailer(tailer2)

        assert result is True
        assert tailer2.position == tailer1.position

    def test_save_and_load(self, tmp_path):
        """save() and load() should persist state."""
        file_path = tmp_path / "test.jsonl"
        state_file = tmp_path / "state.json"
        file_path.write_text('{"test": true}\n')

        tailer = JSONLTailer(file_path)
        tailer.read_new()

        # Save state
        state1 = WatcherState()
        state1.update_from_tailer(tailer)
        state1.save(state_file)

        # Load state
        state2 = WatcherState.load(state_file)

        assert str(file_path.absolute()) in state2.file_positions
        pos = state2.file_positions[str(file_path.absolute())]
        assert pos.position == tailer.position

    def test_load_missing_file(self, tmp_path):
        """load() should return empty state for missing file."""
        state_file = tmp_path / "nonexistent.json"

        state = WatcherState.load(state_file)

        assert len(state.file_positions) == 0

    def test_load_invalid_json(self, tmp_path):
        """load() should return empty state for invalid JSON."""
        state_file = tmp_path / "invalid.json"
        state_file.write_text("not valid json")

        state = WatcherState.load(state_file)

        assert len(state.file_positions) == 0

    def test_prune_stale(self, tmp_path):
        """prune_stale() should remove old entries and entries for non-existent files."""
        state = WatcherState()

        # Create a real file that exists
        recent_file = tmp_path / "recent.jsonl"
        recent_file.write_text('{"test": true}\n')

        # Add an old position for a non-existent file (should be pruned)
        old_time = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        state.file_positions["/old/nonexistent.jsonl"] = FilePosition(
            file_path="/old/nonexistent.jsonl",
            position=100,
            inode=12345,
            last_modified=old_time
        )

        # Add a recent position for a file that exists (should NOT be pruned)
        recent_time = datetime.now(timezone.utc).isoformat()
        state.file_positions[str(recent_file)] = FilePosition(
            file_path=str(recent_file),
            position=200,
            inode=67890,
            last_modified=recent_time
        )

        # Prune entries older than 7 days OR for non-existent files
        removed_count = state.prune_stale(max_age=timedelta(days=7))

        # prune_stale returns an int (count of removed entries)
        assert removed_count == 1
        assert "/old/nonexistent.jsonl" not in state.file_positions
        assert str(recent_file) in state.file_positions

    def test_clear(self):
        """clear() should remove all positions."""
        state = WatcherState()
        state.file_positions["file1"] = FilePosition(
            file_path="file1", position=100, inode=1,
            last_modified=datetime.now(timezone.utc).isoformat()
        )
        state.file_positions["file2"] = FilePosition(
            file_path="file2", position=200, inode=2,
            last_modified=datetime.now(timezone.utc).isoformat()
        )

        state.clear()

        assert len(state.file_positions) == 0


class TestStatePersistence:
    """Test StatePersistence class."""

    def test_context_manager(self, tmp_path):
        """StatePersistence should work as context manager."""
        state_file = tmp_path / "state.json"
        file_path = tmp_path / "test.jsonl"
        file_path.write_text('{"test": true}\n')

        with StatePersistence(state_file) as persistence:
            assert persistence is not None
            # Must update from tailer to mark state as dirty
            tailer = JSONLTailer(file_path)
            tailer.read_new()
            persistence.update_from_tailer(tailer)

        # File should be created on exit (after dirty state is saved)
        assert state_file.exists()

    def test_save_now(self, tmp_path):
        """save_now() should immediately write state."""
        state_file = tmp_path / "state.json"
        file_path = tmp_path / "test.jsonl"
        file_path.write_text('{"test": true}\n')

        with StatePersistence(state_file) as persistence:
            tailer = JSONLTailer(file_path)
            tailer.read_new()
            persistence.update_from_tailer(tailer)
            persistence.save_now()

            # Should be saved
            assert state_file.exists()
            data = json.loads(state_file.read_text())
            assert "file_positions" in data

    def test_update_from_tailer(self, tmp_path):
        """update_from_tailer() should update internal state."""
        state_file = tmp_path / "state.json"
        file_path = tmp_path / "test.jsonl"
        file_path.write_text('{"test": true}\n')

        with StatePersistence(state_file) as persistence:
            tailer = JSONLTailer(file_path)
            tailer.read_new()
            persistence.update_from_tailer(tailer)

            # Check internal state
            assert str(file_path.absolute()) in persistence.state.file_positions

    def test_apply_to_tailer(self, tmp_path):
        """apply_to_tailer() should restore tailer position."""
        state_file = tmp_path / "state.json"
        file_path = tmp_path / "test.jsonl"
        file_path.write_text('{"test": true}\n{"second": "entry"}\n')

        # First run - save state
        with StatePersistence(state_file) as persistence:
            tailer1 = JSONLTailer(file_path)
            tailer1.read_new()
            persistence.update_from_tailer(tailer1)

        # Second run - restore state
        with StatePersistence(state_file) as persistence:
            tailer2 = JSONLTailer(file_path)
            result = persistence.apply_to_tailer(tailer2)

            assert result is True
            # Should be at end of file (no new entries to read)
            entries = tailer2.read_new()
            assert len(entries) == 0
