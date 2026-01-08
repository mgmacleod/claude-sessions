"""Tests for claude_sessions.realtime.tailer module."""

import json
import os
from pathlib import Path

import pytest

from claude_sessions.realtime.tailer import JSONLTailer, MultiFileTailer, TailerState


class TestTailerState:
    """Test TailerState dataclass."""

    def test_initial_state(self, tmp_path):
        """TailerState should initialize with defaults."""
        state = TailerState(file_path=tmp_path / "test.jsonl")

        assert state.position == 0
        assert state.inode == 0
        assert state.line_buffer == ""

    def test_reset(self, tmp_path):
        """reset() should clear position and buffer."""
        state = TailerState(
            file_path=tmp_path / "test.jsonl",
            position=100,
            line_buffer="partial"
        )

        state.reset()

        assert state.position == 0
        assert state.line_buffer == ""


class TestJSONLTailer:
    """Test JSONLTailer class."""

    def test_read_new_empty_file(self, tmp_path):
        """read_new() should return empty list for empty file."""
        file_path = tmp_path / "empty.jsonl"
        file_path.touch()

        tailer = JSONLTailer(file_path)
        entries = tailer.read_new()

        assert entries == []

    def test_read_new_single_entry(self, tmp_path):
        """read_new() should parse a single JSON line."""
        file_path = tmp_path / "single.jsonl"
        entry = {"type": "user", "message": "hello"}
        file_path.write_text(json.dumps(entry) + "\n")

        tailer = JSONLTailer(file_path)
        entries = tailer.read_new()

        assert len(entries) == 1
        assert entries[0] == entry

    def test_read_new_multiple_entries(self, tmp_path):
        """read_new() should parse multiple JSON lines."""
        file_path = tmp_path / "multi.jsonl"
        entries = [
            {"type": "user", "id": 1},
            {"type": "assistant", "id": 2},
            {"type": "user", "id": 3}
        ]
        file_path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

        tailer = JSONLTailer(file_path)
        result = tailer.read_new()

        assert len(result) == 3
        assert result == entries

    def test_read_new_incremental(self, tmp_path):
        """read_new() should only return new entries on subsequent calls."""
        file_path = tmp_path / "incremental.jsonl"
        entry1 = {"type": "user", "id": 1}
        file_path.write_text(json.dumps(entry1) + "\n")

        tailer = JSONLTailer(file_path)

        # First read
        result1 = tailer.read_new()
        assert len(result1) == 1

        # Second read - no new data
        result2 = tailer.read_new()
        assert result2 == []

        # Append more data
        entry2 = {"type": "assistant", "id": 2}
        with open(file_path, "a") as f:
            f.write(json.dumps(entry2) + "\n")

        # Third read - only new entry
        result3 = tailer.read_new()
        assert len(result3) == 1
        assert result3[0] == entry2

    def test_read_new_empty_on_no_change(self, tmp_path):
        """read_new() should return empty list when file unchanged."""
        file_path = tmp_path / "unchanged.jsonl"
        file_path.write_text(json.dumps({"test": True}) + "\n")

        tailer = JSONLTailer(file_path)
        tailer.read_new()  # First read

        # Multiple subsequent reads with no changes
        assert tailer.read_new() == []
        assert tailer.read_new() == []

    def test_read_all_from_start(self, tmp_path):
        """read_all() should read entire file from beginning."""
        file_path = tmp_path / "all.jsonl"
        entries = [{"id": i} for i in range(5)]
        file_path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

        tailer = JSONLTailer(file_path)
        tailer.read_new()  # Advance position

        # read_all should reset and read everything
        result = tailer.read_all()
        assert len(result) == 5

    def test_reset_position(self, tmp_path):
        """reset() should reset position to beginning."""
        file_path = tmp_path / "reset.jsonl"
        entries = [{"id": i} for i in range(3)]
        file_path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

        tailer = JSONLTailer(file_path)
        tailer.read_new()
        assert tailer.position > 0

        tailer.reset()
        assert tailer.position == 0

        # Should read all entries again
        result = tailer.read_new()
        assert len(result) == 3

    def test_partial_line_buffering(self, tmp_path):
        """Tailer should buffer incomplete lines."""
        file_path = tmp_path / "partial.jsonl"
        file_path.write_text('{"complete": true}\n{"partial":')

        tailer = JSONLTailer(file_path)
        entries = tailer.read_new()

        # Only complete line should be returned
        assert len(entries) == 1
        assert entries[0] == {"complete": True}
        assert tailer.has_pending_data

        # Complete the partial line
        with open(file_path, "a") as f:
            f.write(' "value"}\n')

        entries = tailer.read_new()
        assert len(entries) == 1
        assert entries[0] == {"partial": "value"}
        assert not tailer.has_pending_data

    def test_malformed_json_skipped(self, tmp_path):
        """Malformed JSON lines should be skipped."""
        file_path = tmp_path / "malformed.jsonl"
        content = '{"valid": 1}\nnot valid json\n{"valid": 2}\n'
        file_path.write_text(content)

        tailer = JSONLTailer(file_path)
        entries = tailer.read_new()

        # Only valid entries returned
        assert len(entries) == 2
        assert entries[0] == {"valid": 1}
        assert entries[1] == {"valid": 2}

    def test_empty_lines_skipped(self, tmp_path):
        """Empty lines should be skipped."""
        file_path = tmp_path / "empty_lines.jsonl"
        content = '{"id": 1}\n\n\n{"id": 2}\n'
        file_path.write_text(content)

        tailer = JSONLTailer(file_path)
        entries = tailer.read_new()

        assert len(entries) == 2

    def test_file_truncation_detection(self, tmp_path):
        """Tailer should detect file truncation and reset."""
        file_path = tmp_path / "truncate.jsonl"

        # Write initial content
        entries = [{"id": i} for i in range(10)]
        file_path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

        tailer = JSONLTailer(file_path)
        tailer.read_new()
        old_position = tailer.position

        # Truncate the file (write less content)
        file_path.write_text(json.dumps({"new": True}) + "\n")

        # Position should reset on next read
        entries = tailer.read_new()
        assert tailer.position < old_position
        assert len(entries) == 1
        assert entries[0] == {"new": True}

    def test_unicode_handling(self, tmp_path):
        """Tailer should handle UTF-8 content."""
        file_path = tmp_path / "unicode.jsonl"
        entry = {"message": "Hello 世界 🌍 émoji"}
        file_path.write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")

        tailer = JSONLTailer(file_path)
        entries = tailer.read_new()

        assert len(entries) == 1
        assert entries[0]["message"] == "Hello 世界 🌍 émoji"

    def test_tail_iterator(self, tmp_path):
        """tail() should yield entries as an iterator."""
        file_path = tmp_path / "tail.jsonl"
        entries = [{"id": i} for i in range(3)]
        file_path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

        tailer = JSONLTailer(file_path)
        result = list(tailer.tail())

        assert len(result) == 3

    def test_file_path_property(self, tmp_path):
        """file_path property should return the file path."""
        file_path = tmp_path / "test.jsonl"
        file_path.touch()

        tailer = JSONLTailer(file_path)
        assert tailer.file_path == file_path

    def test_position_property(self, tmp_path):
        """position property should return current byte position."""
        file_path = tmp_path / "position.jsonl"
        content = json.dumps({"test": True}) + "\n"
        file_path.write_text(content)

        tailer = JSONLTailer(file_path)
        assert tailer.position == 0

        tailer.read_new()
        assert tailer.position == len(content.encode("utf-8"))


class TestMultiFileTailer:
    """Test MultiFileTailer class."""

    def test_init_with_files(self, tmp_path):
        """MultiFileTailer should initialize with given files."""
        file1 = tmp_path / "file1.jsonl"
        file2 = tmp_path / "file2.jsonl"
        file1.touch()
        file2.touch()

        tailer = MultiFileTailer([file1, file2])

        assert len(tailer.file_paths) == 2
        assert file1 in tailer.file_paths
        assert file2 in tailer.file_paths

    def test_add_file(self, tmp_path):
        """add_file() should add a new file to tail."""
        file1 = tmp_path / "file1.jsonl"
        file2 = tmp_path / "file2.jsonl"
        file1.touch()
        file2.touch()

        tailer = MultiFileTailer([file1])
        tailer.add_file(file2)

        assert len(tailer.file_paths) == 2

    def test_add_file_duplicate_ignored(self, tmp_path):
        """add_file() should ignore duplicates."""
        file1 = tmp_path / "file1.jsonl"
        file1.touch()

        tailer = MultiFileTailer([file1])
        tailer.add_file(file1)  # Add same file again

        assert len(tailer.file_paths) == 1

    def test_remove_file(self, tmp_path):
        """remove_file() should remove a file from tailing."""
        file1 = tmp_path / "file1.jsonl"
        file2 = tmp_path / "file2.jsonl"
        file1.touch()
        file2.touch()

        tailer = MultiFileTailer([file1, file2])
        tailer.remove_file(file1)

        assert len(tailer.file_paths) == 1
        assert file1 not in tailer.file_paths

    def test_read_new_from_multiple_files(self, tmp_path):
        """read_new() should return entries from all files with paths."""
        file1 = tmp_path / "file1.jsonl"
        file2 = tmp_path / "file2.jsonl"

        file1.write_text(json.dumps({"source": "file1"}) + "\n")
        file2.write_text(json.dumps({"source": "file2"}) + "\n")

        tailer = MultiFileTailer([file1, file2])
        results = tailer.read_new()

        assert len(results) == 2

        # Results are tuples of (path, entry)
        paths = [r[0] for r in results]
        entries = [r[1] for r in results]

        assert file1 in paths
        assert file2 in paths
        assert {"source": "file1"} in entries
        assert {"source": "file2"} in entries

    def test_reset_all_files(self, tmp_path):
        """reset() should reset all tailers."""
        file1 = tmp_path / "file1.jsonl"
        file2 = tmp_path / "file2.jsonl"

        file1.write_text(json.dumps({"id": 1}) + "\n")
        file2.write_text(json.dumps({"id": 2}) + "\n")

        tailer = MultiFileTailer([file1, file2])
        tailer.read_new()  # Advance positions

        tailer.reset()

        # Should read all entries again
        results = tailer.read_new()
        assert len(results) == 2
