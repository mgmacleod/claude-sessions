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

## License

MIT
