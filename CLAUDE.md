# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**claude-sessions** is a Python library for parsing and analyzing Claude Code session data stored in `~/.claude/`. It provides data models, a fluent query API, and export capabilities for conversation sessions including sub-agents.

## Development Commands

```bash
# Install in editable mode
pip install -e .

# Install with pandas support (for DataFrame exports)
pip install -e ".[pandas]"
```

Note: No test framework or linting is currently configured.

## Architecture

### Module Structure

- **models.py** - Immutable dataclasses defining the data hierarchy
- **parser.py** - JSONL parsing and session reconstruction
- **query.py** - Fluent query builder and filter predicates
- **export.py** - Markdown, DataFrame, and JSON export functions

### Data Model Hierarchy

```
ClaudeSessions (entry point)
  └── Project (one per working directory)
        └── Session (complete conversation)
              ├── main_thread (Thread)
              │     └── messages (Message[])
              │           └── content (ContentBlock[])
              └── agents (Dict[str, Agent]) - sub-agents from Task tool
                    └── thread (Thread)
```

### Key Design Patterns

1. **Frozen Dataclasses** - All data models are immutable (TextBlock, ToolUseBlock, ToolResultBlock)
2. **Fluent Query Interface** - SessionQuery supports method chaining: `.by_project().with_tool().limit().to_list()`
3. **Tree Traversal** - Messages linked via `parentUuid`, built into ordered Thread using BFS
4. **Tool Pairing** - ToolCall pairs a ToolUseBlock (request) with its ToolResultBlock (response)

### Data Flow

```
~/.claude/projects/{slug}/*.jsonl
        ↓
parse_message() → Message objects
        ↓
build_thread() → ordered Thread (BFS via parentUuid)
        ↓
build_session() → Session (main thread + agents dict)
        ↓
load_all_projects() → ClaudeSessions
```

### Tool Categories

The query module categorizes Claude Code tools:
- **bash**: Bash, KillShell
- **file_read**: Read
- **file_write**: Write, Edit, NotebookEdit
- **search**: Glob, Grep
- **agent**: Task, TaskOutput
- **planning**: TodoWrite, EnterPlanMode, ExitPlanMode
- **web**: WebFetch, WebSearch
- **interaction**: AskUserQuestion

## Dependencies

- **Core**: Python 3.10+ stdlib only (no external dependencies)
- **Optional**: pandas>=2.0 for DataFrame exports
