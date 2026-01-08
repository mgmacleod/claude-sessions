# claude-sessions

Parse and analyze Claude Code session data from `~/.claude/`.

## Installation

```bash
cd ~/development/claude-sessions
pip install -e .

# With pandas support for DataFrame exports
pip install -e ".[pandas]"
```

## Quick Start

```python
from claude_sessions import ClaudeSessions

# Load all sessions
sessions = ClaudeSessions.load()
print(sessions.summary())

# Query recent sessions
recent = sessions.query().sort_by_date(descending=True).limit(10).to_list()

# Export to markdown
from claude_sessions.export import session_to_markdown
with open("transcript.md", "w") as f:
    f.write(session_to_markdown(recent[0]))
```

## Data Location

Claude Code stores session data in `~/.claude/`:

| Path | Content | Format |
|------|---------|--------|
| `projects/{slug}/*.jsonl` | Conversation logs | JSONL |
| `projects/{slug}/agent-*.jsonl` | Sub-agent (sidechain) logs | JSONL |
| `plans/*.md` | Implementation plans | Markdown |
| `todos/*.json` | Task lists | JSON |
| `stats-cache.json` | Usage statistics | JSON |

Project slugs encode the original path: `-home-username-project` → `/home/username/project`

---

## API Reference

### ClaudeSessions

Main entry point for loading and querying session data.

```python
from claude_sessions import ClaudeSessions

# Load from default ~/.claude
sessions = ClaudeSessions.load()

# Load from custom path
sessions = ClaudeSessions.load(base_path="/path/to/.claude")

# Load only specific projects (partial match)
sessions = ClaudeSessions.load(project_filter="myproject")

# Load single project directory
sessions = ClaudeSessions.load_project("/home/user/.claude/projects/-home-user-myproject")
```

#### Properties

| Property | Type | Description |
|----------|------|-------------|
| `projects` | `Dict[str, Project]` | All loaded projects by slug |
| `all_sessions` | `List[Session]` | All sessions across projects |
| `session_count` | `int` | Total session count |
| `project_count` | `int` | Total project count |
| `message_count` | `int` | Total messages across all sessions |
| `tool_call_count` | `int` | Total tool calls |

#### Methods

```python
# Get summary statistics
sessions.summary()
# {'projects': 5, 'sessions': 262, 'messages': 15956, ...}

# Create query builder
sessions.query()  # Returns SessionQuery

# Get specific session by ID
sessions.get_session("abc123-def456-...")

# Get specific project by slug
sessions.get_project("-home-user-myproject")

# Find projects by pattern
sessions.find_projects("myproject")  # Partial match
```

---

### SessionQuery

Fluent query interface for filtering and aggregating sessions.

```python
from datetime import datetime, timedelta

# Chain filters
results = (sessions.query()
    .by_project("myproject")           # Filter by project slug
    .by_date(start=datetime(2025,1,1)) # Filter by date range
    .with_tool("Bash")                 # Sessions using specific tool
    .with_agents()                     # Sessions with sub-agents
    .min_messages(10)                  # Minimum message count
    .sort_by_date(descending=True)     # Sort by start time
    .sort_by_messages(descending=True) # Sort by message count
    .limit(10)                         # Limit results
    .offset(5)                         # Skip first N
    .to_list())                        # Execute and return list

# Get first result
session = sessions.query().sort_by_date(descending=True).first()

# Iterate directly
for session in sessions.query().with_tool("Edit"):
    print(session.session_id)
```

#### Aggregations

```python
query = sessions.query()

query.count()              # Number of matching sessions
query.total_messages()     # Sum of messages
query.total_tool_calls()   # Sum of tool calls

# Usage statistics (returns Dict[str, int] sorted by frequency)
query.tool_usage_stats()      # {'Bash': 2077, 'Read': 1503, ...}
query.tool_category_stats()   # {'bash': 2077, 'file_read': 1503, ...}
query.model_usage_stats()     # {'claude-opus-4-5': 4817, ...}
query.project_stats()         # {'-home-user-proj': 50, ...}
```

#### Extraction

```python
# Get all messages from matching sessions
messages = sessions.query().by_project("myproject").all_messages()

# Get all tool calls
tool_calls = sessions.query().all_tool_calls()

# Filter with custom predicates
from claude_sessions.query import text_contains, tool_by_name

messages = sessions.query().filter_messages(text_contains("error"))
bash_calls = sessions.query().filter_tool_calls(tool_by_name("Bash"))
```

---

### Data Models

#### Session

A complete Claude Code session with main conversation and sub-agents.

```python
session.session_id      # UUID string
session.project_slug    # e.g., "-home-user-myproject"
session.main_thread     # Thread object
session.agents          # Dict[str, Agent] - sub-agents by ID
session.start_time      # datetime (UTC)
session.end_time        # datetime (UTC)
session.duration        # timedelta
session.message_count   # Total including agents
session.tool_call_count # Total including agents
session.cwd             # Working directory
session.git_branch      # Git branch if in repo
session.version         # Claude Code version

# Get all messages (main + agents) sorted by time
session.all_messages

# Get all tool calls (main + agents) sorted by time
session.all_tool_calls

# Get specific agent
agent = session.get_agent("a12bc34")
```

#### Thread

Ordered sequence of messages following `parentUuid` chain.

```python
thread.messages         # List[Message] in conversation order
thread.root             # First message (parentUuid=None)
thread.tool_calls       # List[ToolCall] - paired use/result

# Filter messages
thread.user_messages
thread.assistant_messages
thread.filter_by_role(MessageRole.USER)
thread.filter_by_tool("Read")  # Tool calls using Read
```

#### Message

A single message in a conversation.

```python
message.uuid            # Unique ID
message.parent_uuid     # Parent message ID (for threading)
message.timestamp       # datetime (UTC)
message.role            # MessageRole.USER or MessageRole.ASSISTANT
message.content         # List[ContentBlock]
message.session_id      # Parent session ID
message.agent_id        # Agent ID if sidechain, else None
message.is_sidechain    # True if from sub-agent
message.model           # e.g., "claude-opus-4-5-20251101"
message.cwd             # Working directory
message.git_branch      # Git branch

# Content helpers
message.text_content    # All text blocks concatenated
message.tool_uses       # List[ToolUseBlock]
message.tool_results    # List[ToolResultBlock]
message.has_tool_calls  # True if contains tool_use blocks
```

#### ContentBlock Types

```python
from claude_sessions import TextBlock, ToolUseBlock, ToolResultBlock

# TextBlock - plain text
block.text              # str

# ToolUseBlock - tool invocation by assistant
block.id                # "toolu_XXXXX..."
block.name              # "Bash", "Read", "Edit", etc.
block.input             # Dict[str, Any] - tool parameters
block.tool_category     # "bash", "file_read", "file_write", etc.

# ToolResultBlock - result returned to assistant
block.tool_use_id       # Links to ToolUseBlock.id
block.content           # str - output/result
block.is_error          # True if tool call failed
```

#### ToolCall

Paired tool invocation and result (spans two messages).

```python
tc.tool_use             # ToolUseBlock
tc.tool_result          # ToolResultBlock or None
tc.request_message      # Assistant message with tool_use
tc.response_message     # User message with tool_result
tc.tool_name            # e.g., "Bash"
tc.tool_category        # e.g., "bash"
tc.tool_input           # Dict - tool parameters
tc.result_content       # str or None
tc.is_error             # True if error
tc.timestamp            # datetime
tc.session_id           # Parent session
```

#### Agent

Sub-agent spawned by the Task tool.

```python
agent.agent_id          # Short ID, e.g., "a12bc34"
agent.session_id        # Parent session ID
agent.thread            # Thread object
agent.start_time        # datetime
agent.message_count     # int
agent.tool_calls        # List[ToolCall]
```

#### Project

Collection of sessions from one working directory.

```python
project.slug            # e.g., "-home-user-myproject"
project.path            # Filesystem path to project dir
project.sessions        # Dict[str, Session]
project.session_count   # int
project.project_path    # Decoded path: "/home/user/myproject"

# Get sessions in date range
project.sessions_by_date(start=datetime(2025,1,1))
```

---

## Export Functions

### Markdown

```python
from claude_sessions.export import session_to_markdown, export_session_markdown

# Get markdown string
md = session_to_markdown(
    session,
    include_tools=True,      # Include tool calls/results
    include_agents=True,     # Include sub-agent conversations
    include_metadata=False   # Include cwd/branch per message
)

# Write directly to file
export_session_markdown(session, Path("transcript.md"))
```

### DataFrames (requires pandas)

```python
from claude_sessions.export import (
    sessions_to_dataframe,
    messages_to_dataframe,
    tool_calls_to_dataframe,
    bash_commands_to_dataframe,
    file_operations_to_dataframe,
)

# Sessions overview
df = sessions_to_dataframe(sessions.all_sessions)
# Columns: session_id, project, start_time, end_time, duration_minutes,
#          message_count, tool_call_count, agent_count, cwd, git_branch, version

# Message-level data
df = messages_to_dataframe(session.all_messages)
# Columns: uuid, parent_uuid, session_id, agent_id, timestamp, role,
#          is_sidechain, text_length, tool_use_count, tool_result_count, model, cwd, git_branch

# Tool call data
df = tool_calls_to_dataframe(session.all_tool_calls)
# Columns: tool_id, tool_name, tool_category, timestamp, session_id,
#          agent_id, is_error, result_length

# Bash commands specifically
df = bash_commands_to_dataframe(tool_calls)
# Columns: timestamp, command, description, timeout, is_error, output, session_id

# File operations
df = file_operations_to_dataframe(tool_calls)
# Columns: timestamp, operation, file_path, session_id, is_error
```

### JSON

```python
from claude_sessions.export import (
    session_to_dict,
    export_sessions_json,
    export_sessions_jsonl,
    export_tool_calls_json,
)

# Convert to dict
data = session_to_dict(session)

# Export to JSON file
export_sessions_json(sessions_list, Path("sessions.json"))

# Export to JSONL (one session per line)
export_sessions_jsonl(sessions_list, Path("sessions.jsonl"))

# Export tool calls
export_tool_calls_json(tool_calls, Path("tools.json"))
```

---

## Raw Data Schema

### JSONL Message Entry

Each line in a session JSONL file has this structure:

```json
{
  "uuid": "abc123-...",
  "parentUuid": "def456-..." | null,
  "timestamp": "2025-01-05T20:19:25.839Z",
  "type": "user" | "assistant",
  "sessionId": "session-uuid",
  "agentId": "a12bc34" | null,
  "isSidechain": false,
  "cwd": "/home/user/project",
  "gitBranch": "main",
  "version": "2.0.74",
  "isMeta": false,
  "slug": "adjective-noun-word",
  "message": {
    "role": "user" | "assistant",
    "model": "claude-opus-4-5-20251101",
    "content": [...],
    "usage": {
      "input_tokens": 1234,
      "output_tokens": 567,
      "cache_read_input_tokens": 0,
      "cache_creation_input_tokens": 0
    }
  }
}
```

### Content Block Types

**Text:**
```json
{"type": "text", "text": "Hello, world!"}
```

**Tool Use (assistant):**
```json
{
  "type": "tool_use",
  "id": "toolu_01ABC...",
  "name": "Bash",
  "input": {
    "command": "ls -la",
    "description": "List files"
  }
}
```

**Tool Result (user):**
```json
{
  "type": "tool_result",
  "tool_use_id": "toolu_01ABC...",
  "content": "file1.txt\nfile2.txt",
  "is_error": false
}
```

### Tool Categories

| Category | Tools |
|----------|-------|
| `bash` | Bash, KillShell |
| `file_read` | Read |
| `file_write` | Write, Edit, NotebookEdit |
| `search` | Glob, Grep |
| `agent` | Task, TaskOutput |
| `planning` | TodoWrite, EnterPlanMode, ExitPlanMode |
| `web` | WebFetch, WebSearch |
| `interaction` | AskUserQuestion |
| `other` | Skill, other tools |

### Message Threading

Messages form a tree via `parentUuid`:

```
msg1 (parentUuid=null)      ← root
  └── msg2 (parentUuid=msg1.uuid)
        └── msg3 (parentUuid=msg2.uuid)
              └── msg4 (parentUuid=msg3.uuid)
```

Sub-agents have `isSidechain=true` and their own `agentId`.

---

## Examples

### Analyze Tool Usage Over Time

```python
from claude_sessions import ClaudeSessions
from claude_sessions.export import tool_calls_to_dataframe
import pandas as pd

sessions = ClaudeSessions.load()
calls = sessions.query().all_tool_calls()
df = tool_calls_to_dataframe(calls)

# Tools per day
df['date'] = df['timestamp'].dt.date
daily = df.groupby(['date', 'tool_name']).size().unstack(fill_value=0)
daily.plot(kind='area', figsize=(12, 6))
```

### Find All File Edits

```python
from claude_sessions.query import tool_by_name

edits = sessions.query().filter_tool_calls(tool_by_name("Edit"))
for tc in edits[:10]:
    path = tc.tool_input.get('file_path', '')
    print(f"{tc.timestamp}: {path}")
```

### Export Recent Session Transcripts

```python
from claude_sessions.export import export_session_markdown
from pathlib import Path

recent = sessions.query().sort_by_date(descending=True).limit(5).to_list()
for s in recent:
    filename = f"session_{s.session_id[:8]}.md"
    export_session_markdown(s, Path(filename))
```

### Search for Conversations About a Topic

```python
from claude_sessions.query import text_contains

messages = sessions.query().filter_messages(text_contains("authentication"))
for msg in messages[:5]:
    print(f"{msg.timestamp} [{msg.role.value}]: {msg.text_content[:100]}...")
```

---

## Realtime Monitoring

The `claude_sessions.realtime` module enables monitoring Claude Code sessions as they happen, emitting events for messages, tool calls, and session lifecycle changes.

### Quick Start

```python
from claude_sessions.realtime import SessionWatcher

watcher = SessionWatcher()

@watcher.on("message")
def on_message(event):
    print(f"{event.message.role}: {event.message.text_content[:80]}")

@watcher.on("tool_use")
def on_tool(event):
    print(f"  → {event.tool_name}")

watcher.start()  # Blocks until Ctrl+C
```

Or use the CLI:

```bash
# Install with realtime dependencies
pip install -e ".[realtime]"

# Watch all sessions
claude-sessions watch

# JSON output for piping
claude-sessions watch --format json | jq .
```

---

### Event Types

All events are immutable frozen dataclasses with these common attributes:

| Attribute | Type | Description |
|-----------|------|-------------|
| `timestamp` | `datetime` | When the event occurred |
| `session_id` | `str` | Session UUID |
| `event_type` | `str` | Event type string |
| `agent_id` | `str \| None` | Sub-agent ID if from sidechain |

#### Message Events

| Event | Description | Key Attributes |
|-------|-------------|----------------|
| `MessageEvent` | New message parsed | `message: Message` |
| `ToolUseEvent` | Tool invoked | `tool_name`, `tool_category`, `tool_input`, `tool_use_id` |
| `ToolResultEvent` | Tool result received | `tool_use_id`, `content`, `is_error` |
| `ToolCallCompletedEvent` | Tool use matched with result | `tool_call: ToolCall`, `tool_name`, `is_error`, `duration` |
| `ErrorEvent` | Parse error | `error_message`, `raw_entry` |

#### Session Lifecycle Events

| Event | Description | Key Attributes |
|-------|-------------|----------------|
| `SessionStartEvent` | New session file detected | `project_slug`, `file_path`, `cwd` |
| `SessionIdleEvent` | Session went idle | `idle_since: datetime` |
| `SessionResumeEvent` | Idle session became active | `idle_duration: timedelta` |
| `SessionEndEvent` | Session ended | `reason`, `idle_duration`, `message_count`, `tool_count` |

---

### SessionWatcher

High-level API for monitoring all sessions in `~/.claude/projects/`.

```python
from claude_sessions.realtime import SessionWatcher, WatcherConfig
from datetime import timedelta

# Custom configuration
config = WatcherConfig(
    poll_interval=0.5,                    # Check for changes every 500ms
    idle_timeout=timedelta(minutes=2),    # Mark idle after 2min inactivity
    end_timeout=timedelta(minutes=5),     # End session after 5min idle
    process_existing=True,                # Process existing files on startup
    emit_session_events=True,             # Emit session_start/end/idle events
)

watcher = SessionWatcher(config=config)

# Register handlers via decorator
@watcher.on("session_start")
def on_start(event):
    print(f"New session: {event.session_id[:8]} in {event.project_slug}")

@watcher.on("message")
def on_message(event):
    print(f"[{event.message.role}] {event.message.text_content[:100]}")

# Or register via method
def on_tool(event):
    print(f"Tool: {event.tool_name}")

watcher.on("tool_use", on_tool)

# Wildcard handler for all events
@watcher.on_any
def on_any(event):
    print(f"Event: {event.event_type}")

# Run methods
watcher.start()              # Block until Ctrl+C
watcher.run_for(seconds=60)  # Run for limited time
watcher.stop()               # Stop from another thread

# Context manager
with SessionWatcher() as watcher:
    watcher.run_for(10)
```

#### WatcherConfig Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `base_path` | `Path` | `~/.claude` | Base Claude directory |
| `poll_interval` | `float` | `0.5` | Seconds between file checks |
| `idle_timeout` | `timedelta` | `2 min` | Inactivity before session is idle |
| `end_timeout` | `timedelta` | `5 min` | Idle duration before session ends |
| `process_existing` | `bool` | `True` | Process existing files on startup |
| `emit_session_events` | `bool` | `True` | Emit lifecycle events |
| `truncate_inputs` | `bool` | `True` | Truncate large tool inputs |
| `max_input_length` | `int` | `1024` | Max input length when truncating |
| `state_file` | `Path` | `None` | Path for state persistence |
| `save_interval` | `timedelta` | `30 sec` | Auto-save interval |

---

### AsyncSessionWatcher

Async API for integration with asyncio applications.

```python
import asyncio
from claude_sessions.realtime import AsyncSessionWatcher

async def main():
    # Async iterator pattern
    async with AsyncSessionWatcher() as watcher:
        async for event in watcher.events():
            print(f"{event.event_type}: {event.session_id[:8]}")

asyncio.run(main())
```

Or with decorators (supports both sync and async handlers):

```python
async def main():
    watcher = AsyncSessionWatcher()

    @watcher.on("message")
    async def on_message(event):
        await process_message(event)

    @watcher.on("tool_use")
    def on_tool(event):  # Sync handler also works
        print(event.tool_name)

    await watcher.start()

asyncio.run(main())
```

---

### Live Sessions

Track mutable session state for tool call pairing and statistics.

```python
from claude_sessions.realtime import (
    SessionWatcher,
    LiveSessionConfig,
    RetentionPolicy,
)

# Enable live session tracking
watcher = SessionWatcher(live_sessions=True)

@watcher.on("tool_call_completed")
def on_complete(event):
    # Emitted when tool_use is matched with tool_result
    print(f"Tool {event.tool_name} completed, error={event.is_error}")
    if event.duration:
        print(f"  Duration: {event.duration}")

@watcher.on("session_end")
def on_end(event):
    session = watcher.live_sessions.get_session(event.session_id)
    if session:
        print(f"Session stats: {session.message_count} messages")
        # Convert to immutable Session for export
        immutable = session.to_session()
```

#### Retention Policies

Control memory usage for long-running sessions:

```python
# Keep all messages (default)
config = LiveSessionConfig(retention_policy=RetentionPolicy.FULL)

# Keep last 100 messages per thread
config = LiveSessionConfig(
    retention_policy=RetentionPolicy.SLIDING,
    max_messages=100,
)

# Only track counters, don't store messages
config = LiveSessionConfig(retention_policy=RetentionPolicy.NONE)

watcher = SessionWatcher(live_sessions=True, live_config=config)
```

#### LiveSession Properties

| Property | Type | Description |
|----------|------|-------------|
| `session_id` | `str` | Session UUID |
| `project_slug` | `str` | Project directory |
| `message_count` | `int` | Total messages |
| `tool_call_count` | `int` | Total tool calls |
| `start_time` | `datetime` | When session started |
| `last_activity` | `datetime` | Last event time |
| `is_idle` | `bool` | Currently idle |
| `to_session()` | `Session` | Convert to immutable |

---

### Filtering Events

Compose filters to selectively process events.

```python
from claude_sessions.realtime import SessionWatcher, filters, FilterPipeline

watcher = SessionWatcher()

# Filter functions return predicates
file_ops = filters.tool_category("file_read", "file_write")
my_project = filters.project("my-project")

# Combine with logical operators
combined = filters.and_(my_project, file_ops)

# Use with FilterPipeline for handler registration
pipeline = FilterPipeline(combined)

@pipeline.on("tool_use")
def on_file_op(event):
    print(f"File operation: {event.tool_name}")

# Route events through pipeline
@watcher.on_any
def route(event):
    pipeline.process(event)

watcher.start()
```

#### Available Filters

| Filter | Description | Example |
|--------|-------------|---------|
| `project(slug)` | Match project slug | `filters.project("myproj")` |
| `session(id)` | Match session ID | `filters.session("abc-123")` |
| `session_prefix(prefix)` | Match session ID prefix | `filters.session_prefix("abc")` |
| `event_type(*types)` | Match event types | `filters.event_type("message", "tool_use")` |
| `tool_name(*names)` | Match tool names | `filters.tool_name("Read", "Write")` |
| `tool_category(*cats)` | Match tool categories | `filters.tool_category("file_write")` |
| `agent()` | Match sub-agent events | `filters.agent()` |
| `main_thread()` | Match main thread only | `filters.main_thread()` |
| `has_error()` | Match error events/results | `filters.has_error()` |
| `role(role)` | Match message role | `filters.role("user")` |

#### Combinators

| Combinator | Description | Example |
|------------|-------------|---------|
| `and_(*filters)` | All filters must match | `filters.and_(f1, f2)` |
| `or_(*filters)` | Any filter must match | `filters.or_(f1, f2)` |
| `not_(filter)` | Invert filter | `filters.not_(f1)` |
| `always()` | Always matches | `filters.always()` |
| `never()` | Never matches | `filters.never()` |

---

### Metrics Collection

Track Prometheus-compatible metrics.

```python
from claude_sessions.realtime import SessionWatcher, MetricsCollector

watcher = SessionWatcher()
metrics = MetricsCollector()

# Route all events to metrics
watcher.on_any(metrics.handle_event)

# Access metrics
print(f"Total messages: {metrics.messages_total.get()}")
print(f"Messages/min: {metrics.messages_per_minute}")
print(f"Tool breakdown: {metrics.tool_usage_breakdown}")
print(f"Active sessions: {metrics.active_sessions.get()}")

# Export for Prometheus
print(metrics.to_prometheus_text())
```

#### Available Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `messages_total` | Counter | Total messages processed |
| `tool_calls_total` | Counter | Total tool invocations |
| `tool_errors_total` | Counter | Tool calls with errors |
| `session_starts_total` | Counter | Sessions started |
| `session_ends_total` | Counter | Sessions ended |
| `active_sessions` | Gauge | Currently active sessions |
| `tool_duration_seconds` | Histogram | Tool execution time distribution |

#### Properties

| Property | Type | Description |
|----------|------|-------------|
| `messages_per_minute` | `float` | Message rate |
| `tools_per_minute` | `float` | Tool call rate |
| `tool_usage_breakdown` | `Dict[str, int]` | Calls per tool |
| `error_rate` | `float` | Error ratio (0-1) |

#### Prometheus Server

Run a standalone HTTP server for metrics scraping:

```python
from claude_sessions.realtime import SessionWatcher, MetricsCollector, PrometheusServer

watcher = SessionWatcher()
metrics = MetricsCollector()
watcher.on_any(metrics.handle_event)

# Start HTTP server on port 9090
server = PrometheusServer(metrics, port=9090)
server.start()

print(f"Metrics available at {server.url}/metrics")
watcher.start()
```

---

### Webhooks

Send events to HTTP endpoints with batching and retry.

```python
from claude_sessions.realtime import SessionWatcher, WebhookDispatcher, WebhookConfig

watcher = SessionWatcher()

# Configure webhook
config = WebhookConfig(
    url="http://localhost:8080/events",
    headers={"Authorization": "Bearer token"},
    batch_size=10,           # Send in batches of 10
    batch_timeout=5.0,       # Or every 5 seconds
    max_retries=3,           # Retry failed requests
    retry_backoff=1.0,       # Exponential backoff base
)

dispatcher = WebhookDispatcher()
dispatcher.add_webhook(config)
dispatcher.start()

# Route events to webhook
watcher.on_any(dispatcher.handle_event)
watcher.start()
```

---

### State Persistence

Resume watching from where you left off after restart.

```python
from pathlib import Path
from claude_sessions.realtime import SessionWatcher, WatcherConfig

config = WatcherConfig(
    state_file=Path("~/.cache/claude-watcher-state.json").expanduser(),
    save_interval=timedelta(seconds=30),
)

watcher = SessionWatcher(config=config)
# State auto-saves periodically and restores on startup
watcher.start()
```

---

### CLI Reference

The `claude-sessions` command provides subcommands for monitoring:

#### watch

Monitor sessions in real-time:

```bash
# Basic usage
claude-sessions watch

# Filter by project
claude-sessions watch --project myproject

# Filter by tool category
claude-sessions watch --tool-category file_write --tool-category bash

# Filter by event type
claude-sessions watch --event-type message --event-type tool_use

# Output formats
claude-sessions watch --format plain   # Human-readable (default)
claude-sessions watch --format json    # JSON lines
claude-sessions watch --format compact # Minimal one-line

# With Prometheus metrics
claude-sessions watch --metrics --metrics-port 9090

# With webhooks
claude-sessions watch --webhook http://localhost:8080/events

# Resumable watching
claude-sessions watch --state-file ~/.cache/watcher-state.json
```

#### watch Options

| Option | Short | Description |
|--------|-------|-------------|
| `--project SLUG` | `-p` | Filter by project slug (partial match) |
| `--session ID` | `-s` | Filter by session ID (partial match) |
| `--tool NAME` | `-t` | Filter by tool name (repeatable) |
| `--tool-category CAT` | | Filter by category (repeatable) |
| `--event-type TYPE` | `-e` | Filter by event type (repeatable) |
| `--errors-only` | | Only show errors |
| `--format FMT` | `-f` | Output format: plain, json, compact |
| `--no-color` | | Disable colored output |
| `--quiet` | `-q` | Suppress headers/summaries |
| `--metrics` | | Enable Prometheus endpoint |
| `--metrics-port PORT` | | Metrics port (default: 9090) |
| `--webhook URL` | | Send events to webhook (repeatable) |
| `--state-file PATH` | | Enable state persistence |

#### metrics

Run a standalone Prometheus metrics server:

```bash
claude-sessions metrics --port 9090
```

---

## License

MIT
