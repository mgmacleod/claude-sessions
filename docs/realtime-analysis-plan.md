# Realtime Analysis & Feedback - Design Plan

## Overview

This document outlines a plan to extend the `claude-sessions` library with realtime analysis and feedback capabilities. The goal is to enable monitoring, analyzing, and responding to Claude Code sessions as they happen.

## Use Cases

### 1. Session Monitoring Dashboard
- Watch active sessions in real-time
- Display live message stream, tool usage, and progress
- Show token usage and cost estimates as they accumulate

### 2. Automated Feedback/Alerts
- Detect patterns that warrant attention (errors, long-running commands, security concerns)
- Trigger notifications or callbacks when specific events occur
- Log session activity for compliance/audit purposes

### 3. Session Metrics & Analytics
- Real-time aggregation of tool usage patterns
- Track session duration, message rates, error rates
- Build live dashboards for team visibility

### 4. Integration Hooks
- Pipe session events to external systems (Slack, logging, metrics)
- Build custom tooling on top of the event stream
- Enable programmatic responses to session events

### 5. Enhanced Human-AI Collaboration Interfaces
- Build richer UIs that augment the terminal experience
- Provide real-time visibility into Claude's "thinking" and tool usage
- Enable human intervention points (pause, redirect, approve)
- Support collaborative workflows where humans and AI work in tandem
- Create shared workspaces with live session state

**Example applications:**
- **Approval gates**: Pause before destructive operations (file deletes, git push)
- **Context injection**: Human can add notes/context mid-session
- **Pair programming UI**: Side-by-side view of what Claude is doing
- **Teaching mode**: Instructor watches student's Claude session in real-time
- **Team visibility**: Dashboard showing all active Claude sessions across a team

### 6. Context Engineering Research
- Study how context accumulates and influences AI behavior
- Analyze prompt patterns and their effectiveness
- Research optimal context window utilization
- Investigate how tool results shape subsequent responses
- Build datasets for context optimization research

**Research capabilities:**
- **Context snapshots**: Capture full context state at any message
- **Token accounting**: Track input/output tokens in real-time
- **Context compression analysis**: Study what gets summarized and when
- **Tool influence mapping**: How do tool results affect next actions?
- **Prompt effectiveness metrics**: Correlate prompt patterns with outcomes
- **A/B testing infrastructure**: Compare different prompting strategies
- **Conversation trajectory analysis**: Study how sessions evolve over time

---

## Architecture Design

### Current State (Batch Processing)

```
JSONL Files ─→ load_all_projects() ─→ ClaudeSessions (immutable)
                                            │
                                            ├── .query() → SessionQuery → Results
                                            └── export functions
```

### Proposed Addition (Realtime Processing)

```
┌─────────────────────────────────────────────────────────────────────┐
│                        SessionWatcher                                │
│  (monitors ~/.claude/projects/ for changes)                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   FileWatcher ───→ JSONLTailer ───→ MessageParser ───→ EventEmitter │
│   (inotify/poll)   (tail -f style)   (incremental)    (callbacks)   │
│                                                                      │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │    Event Handlers    │
                    ├──────────────────────┤
                    │ • on_message         │
                    │ • on_tool_use        │
                    │ • on_tool_result     │
                    │ • on_session_start   │
                    │ • on_session_end     │
                    │ • on_agent_spawn     │
                    │ • on_error           │
                    └──────────────────────┘
```

---

## Core Components

### 1. `watcher.py` - File System Monitoring

```python
@dataclass
class WatcherConfig:
    """Configuration for the session watcher."""
    base_path: Path = Path.home() / ".claude"
    poll_interval: float = 0.5  # seconds
    use_inotify: bool = True    # fall back to polling if unavailable

class SessionWatcher:
    """Monitors Claude session directories for changes."""

    def __init__(self, config: WatcherConfig = None):
        ...

    def start(self) -> None:
        """Start watching for file changes."""

    def stop(self) -> None:
        """Stop watching."""

    def on_file_change(self, callback: Callable[[Path, ChangeType], None]) -> None:
        """Register callback for file changes."""
```

**Implementation options:**
- **watchdog** library (cross-platform, robust)
- **inotify** (Linux-native, lower latency)
- **polling** fallback (universal compatibility)

### 2. `tailer.py` - JSONL File Tailing

```python
@dataclass
class TailerState:
    """Tracks position in a JSONL file."""
    file_path: Path
    position: int = 0
    inode: int = 0  # detect file rotation

class JSONLTailer:
    """Tails a JSONL file, yielding new entries as they appear."""

    def __init__(self, file_path: Path):
        ...

    def tail(self) -> Iterator[dict]:
        """Yield new JSON entries since last read."""

    def reset(self) -> None:
        """Reset to beginning of file."""

    @property
    def position(self) -> int:
        """Current byte position in file."""
```

**Key considerations:**
- Handle partial line writes (buffer incomplete JSON)
- Detect file truncation/rotation
- Persist position for resumability

### 3. `stream.py` - Event Stream Processing

```python
class SessionEvent(Protocol):
    """Base protocol for all session events."""
    timestamp: datetime
    session_id: str
    event_type: str

@dataclass(frozen=True)
class MessageEvent:
    """Emitted when a new message is parsed."""
    timestamp: datetime
    session_id: str
    event_type: str = "message"
    message: Message

@dataclass(frozen=True)
class ToolUseEvent:
    """Emitted when a tool is invoked."""
    timestamp: datetime
    session_id: str
    event_type: str = "tool_use"
    tool_name: str
    tool_input: dict
    tool_use_id: str
    message: Message

@dataclass(frozen=True)
class ToolResultEvent:
    """Emitted when a tool result is received."""
    timestamp: datetime
    session_id: str
    event_type: str = "tool_result"
    tool_use_id: str
    content: str
    is_error: bool
    message: Message
    # Paired with original tool_use if available
    tool_use: Optional[ToolUseBlock] = None

@dataclass(frozen=True)
class SessionStartEvent:
    """Emitted when a new session is detected."""
    timestamp: datetime
    session_id: str
    event_type: str = "session_start"
    project_slug: str
    cwd: Optional[str]

@dataclass(frozen=True)
class AgentSpawnEvent:
    """Emitted when a sub-agent is spawned via Task tool."""
    timestamp: datetime
    session_id: str
    event_type: str = "agent_spawn"
    agent_id: str
    subagent_type: str
    prompt: str
```

### 4. `emitter.py` - Event Dispatcher

```python
EventType = Literal[
    "message", "tool_use", "tool_result",
    "session_start", "session_end", "agent_spawn", "error"
]

class EventEmitter:
    """Dispatches session events to registered handlers."""

    def on(self, event_type: EventType, handler: Callable[[SessionEvent], None]) -> None:
        """Register a handler for an event type."""

    def off(self, event_type: EventType, handler: Callable) -> None:
        """Unregister a handler."""

    def emit(self, event: SessionEvent) -> None:
        """Dispatch an event to all registered handlers."""

    def on_any(self, handler: Callable[[SessionEvent], None]) -> None:
        """Register a handler for all events."""
```

### 5. `live.py` - Live Session State

```python
@dataclass
class LiveSession:
    """Mutable representation of an in-progress session."""
    session_id: str
    project_slug: str
    messages: list[Message]
    agents: dict[str, list[Message]]
    pending_tool_calls: dict[str, ToolUseBlock]  # awaiting results
    start_time: datetime
    last_activity: datetime

    # Computed properties
    @property
    def message_count(self) -> int: ...

    @property
    def tool_call_count(self) -> int: ...

    @property
    def duration(self) -> timedelta: ...

    @property
    def is_idle(self) -> bool:
        """No activity for > threshold."""

    def to_session(self) -> Session:
        """Convert to immutable Session for export/query."""

class LiveSessionManager:
    """Manages collection of active sessions."""

    def get_session(self, session_id: str) -> Optional[LiveSession]: ...
    def get_active_sessions(self) -> list[LiveSession]: ...
    def prune_idle(self, threshold: timedelta) -> list[str]: ...
```

---

## Integration Patterns

### Pattern 1: Simple Callback

```python
from claude_sessions.realtime import SessionWatcher

watcher = SessionWatcher()

@watcher.on("message")
def handle_message(event: MessageEvent):
    print(f"[{event.session_id[:8]}] {event.message.role}: {event.message.text_content[:100]}")

@watcher.on("tool_use")
def handle_tool(event: ToolUseEvent):
    print(f"  → Using tool: {event.tool_name}")

watcher.start()  # blocking, or use watcher.start_async()
```

### Pattern 2: Async/Await

```python
import asyncio
from claude_sessions.realtime import AsyncSessionWatcher

async def main():
    watcher = AsyncSessionWatcher()

    async for event in watcher.events():
        match event.event_type:
            case "message":
                await process_message(event)
            case "tool_use":
                await log_tool_use(event)
            case "error":
                await alert_on_error(event)

asyncio.run(main())
```

### Pattern 3: Filter Pipeline

```python
from claude_sessions.realtime import SessionWatcher, filters

watcher = SessionWatcher()

# Only watch specific project
project_filter = filters.project("my-project")

# Only care about certain tools
tool_filter = filters.tool_category("file_write")

# Combine filters
pipeline = watcher.pipe(project_filter, tool_filter)

@pipeline.on("tool_use")
def handle_file_write(event):
    log_file_modification(event.tool_input)
```

### Pattern 4: Metrics Collection

```python
from claude_sessions.realtime import SessionWatcher, MetricsCollector

watcher = SessionWatcher()
metrics = MetricsCollector()

watcher.pipe(metrics)

# Access live metrics
print(metrics.active_sessions)
print(metrics.messages_per_minute)
print(metrics.tool_usage_breakdown)
print(metrics.error_rate)
```

---

## Implementation Phases

### Phase 1: Core Infrastructure
- [ ] `JSONLTailer` - tail JSONL files for new entries
- [ ] `IncrementalParser` - parse entries without full session context
- [ ] `EventEmitter` - basic event dispatch system
- [ ] Basic event types: `MessageEvent`, `ToolUseEvent`, `ToolResultEvent`

### Phase 2: File Watching
- [ ] `SessionWatcher` - monitor directory for changes
- [ ] File discovery and tracking
- [ ] Handle file creation, modification, rotation
- [ ] `SessionStartEvent`, `SessionEndEvent` detection

### Phase 3: Live State Management
- [ ] `LiveSession` - mutable session representation
- [ ] `LiveSessionManager` - track active sessions
- [ ] Tool call pairing (match use → result)
- [ ] Agent message routing

### Phase 4: Advanced Features
- [ ] Async API (`AsyncSessionWatcher`)
- [ ] Filter pipeline API
- [ ] Built-in `MetricsCollector`
- [ ] Session idle detection and cleanup
- [ ] Resumable watching (persist tailer positions)

### Phase 5: Integrations
- [ ] CLI command: `claude-sessions watch`
- [ ] Webhook dispatcher
- [ ] Prometheus metrics exporter
- [ ] Example integrations (Slack, logging)

---

## Technical Considerations

### Thread Safety
- File watching likely runs in background thread
- Event handlers should be thread-safe or dispatch to main thread
- Consider `asyncio` as primary async model

### Memory Management
- Don't accumulate unbounded message history
- Configurable retention window for `LiveSession`
- Option to disable full message storage (events only)

### Performance
- Minimize file system operations
- Batch small reads (don't read byte-by-byte)
- Consider memory-mapped file access for large sessions
- Debounce rapid file changes

### Error Handling
- Malformed JSON lines (log and skip)
- Missing parent references (buffer orphan messages)
- File access errors (retry with backoff)
- Handler exceptions (isolate, don't crash watcher)

### Testing Strategy
- Mock file system for unit tests
- Integration tests with real JSONL files
- Stress tests with rapid file writes
- Test file rotation scenarios

---

## Dependencies

**Core (required):**
- `watchdog` - cross-platform file system monitoring (robust, well-maintained)

**Recommended:**
- `psutil` - process detection for session end detection

**Optional enhancements:**
- `aiofiles` - async file operations (if needed for high-throughput)
- `prometheus_client` - metrics export
- `httpx` - webhook delivery
- `rich` - enhanced CLI output for the `watch` command

---

## Design Decisions

### 1. Dual Sync/Async API ✓

We'll support both synchronous and asynchronous APIs to cover different use cases:

**Sync API** - Simple scripts, CLI tools, quick prototypes:
```python
watcher = SessionWatcher()

@watcher.on("message")
def handle(event):
    print(event)

watcher.start()  # blocks
```

**Async API** - Web servers, complex applications, high concurrency:
```python
async def main():
    watcher = AsyncSessionWatcher()
    async for event in watcher.events():
        await handle(event)
```

**Implementation approach:**
- Core implementation is async-native (using `asyncio`)
- Sync API is a thin wrapper that runs the async code in an event loop
- Shared event types and core logic between both APIs
- `watchdog` library handles the file system layer (supports both modes)

### 2. Immutability Strategy ✓

- `LiveSession` is mutable (necessary for accumulating state)
- `.to_session()` produces an immutable `Session` snapshot
- Events themselves remain immutable (frozen dataclasses)
- This mirrors the pattern used by many reactive frameworks

### 3. Session End Detection

This is genuinely tricky since there's no explicit "session ended" marker. Proposed multi-signal approach:

**Heuristics (configurable):**
| Signal | Detection Method | Confidence |
|--------|-----------------|------------|
| Idle timeout | No new messages for N minutes (default: 5) | Medium |
| Explicit goodbye | User message contains "bye", "done", "exit" | Low |
| Process exit | Claude Code process no longer running | High |
| File unchanged | File mtime stable + no Claude processes | High |

**Implementation:**
```python
@dataclass
class SessionEndConfig:
    idle_timeout: timedelta = timedelta(minutes=5)
    check_process: bool = True  # requires psutil
    emit_on_idle: bool = True   # emit SessionEndEvent on timeout

class LiveSession:
    last_activity: datetime

    @property
    def is_idle(self) -> bool:
        return datetime.now() - self.last_activity > self.config.idle_timeout

    @property
    def is_definitely_ended(self) -> bool:
        """Check if Claude Code process is still running for this session."""
        # Use psutil to check for claude processes with matching session
```

**Events:**
- `SessionIdleEvent` - Emitted when session goes idle (may resume)
- `SessionEndEvent` - Emitted when session is definitively ended
- `SessionResumeEvent` - Emitted if an idle session becomes active again

### 4. Remaining Open Questions

1. **Scope of "realtime"?**
   - Sub-second latency acceptable? (Probably yes for most use cases)
   - Polling at 100-500ms is simpler and sufficient
   - True streaming only needed for very specialized applications

2. **Multi-process safety?**
   - Multiple watchers on same files - read-only, so safe
   - No file locking needed (we only read)
   - Each watcher maintains its own position cursors

---

## Context Engineering Research Support

The realtime API enables powerful context engineering research by providing hooks into the live context as it evolves.

### Context Snapshot API

```python
@dataclass
class ContextSnapshot:
    """Captures the full context state at a point in time."""
    timestamp: datetime
    session_id: str
    message_index: int

    # Token accounting
    estimated_context_tokens: int
    input_tokens_total: int
    output_tokens_total: int

    # Message history
    messages: list[Message]
    system_prompt_hash: str  # detect system prompt changes

    # Active state
    pending_tool_calls: list[ToolUseBlock]
    active_agents: list[str]

    # Derived metrics
    @property
    def context_utilization(self) -> float:
        """Estimated % of context window used."""

    @property
    def tool_result_token_ratio(self) -> float:
        """What % of context is tool results vs conversation."""

class ContextTracker:
    """Tracks context evolution throughout a session."""

    def __init__(self, session_id: str):
        self.snapshots: list[ContextSnapshot] = []

    def on_message(self, event: MessageEvent) -> ContextSnapshot:
        """Capture snapshot after each message."""

    def get_trajectory(self) -> ContextTrajectory:
        """Analyze how context evolved over the session."""

    def detect_summarization(self) -> list[SummarizationEvent]:
        """Detect when context was likely summarized/compressed."""
```

### Research Event Types

```python
@dataclass(frozen=True)
class ContextGrowthEvent:
    """Emitted when context grows significantly."""
    timestamp: datetime
    session_id: str
    tokens_added: int
    source: Literal["user", "assistant", "tool_result"]
    cumulative_tokens: int

@dataclass(frozen=True)
class SummarizationEvent:
    """Emitted when context compression is detected."""
    timestamp: datetime
    session_id: str
    tokens_before: int
    tokens_after: int
    compression_ratio: float

@dataclass(frozen=True)
class ToolInfluenceEvent:
    """Tracks how tool results influence subsequent responses."""
    timestamp: datetime
    session_id: str
    tool_call: ToolCall
    result_tokens: int
    next_assistant_message: Message
    # Analysis
    result_referenced: bool  # Did assistant reference the result?
    influence_score: float   # How much did result shape response?
```

### Research Utilities

```python
class PromptPatternAnalyzer:
    """Analyze patterns in user prompts and their effectiveness."""

    def extract_patterns(self, messages: list[Message]) -> list[PromptPattern]:
        """Identify common prompt structures."""

    def correlate_with_outcomes(
        self,
        patterns: list[PromptPattern],
        outcomes: list[SessionOutcome]
    ) -> PatternEffectivenessReport:
        """Which prompt patterns lead to better outcomes?"""

class ConversationTrajectoryAnalyzer:
    """Study how conversations evolve over time."""

    def classify_trajectory(self, session: Session) -> TrajectoryType:
        """Classify: linear, exploratory, iterative, stuck, etc."""

    def detect_pivots(self, session: Session) -> list[PivotPoint]:
        """Find moments where conversation direction changed."""

    def measure_progress(self, session: Session) -> ProgressMetrics:
        """Quantify progress toward apparent goal."""
```

### Example: Context Research Script

```python
#!/usr/bin/env python3
"""Research script: Analyze context utilization patterns."""

from claude_sessions.realtime import SessionWatcher, ContextTracker
from claude_sessions.research import ContextAnalyzer

watcher = SessionWatcher()
trackers: dict[str, ContextTracker] = {}
analyzer = ContextAnalyzer()

@watcher.on("session_start")
def on_start(event):
    trackers[event.session_id] = ContextTracker(event.session_id)

@watcher.on("message")
def on_message(event):
    tracker = trackers.get(event.session_id)
    if tracker:
        snapshot = tracker.on_message(event)

        # Log context growth
        print(f"Context: {snapshot.estimated_context_tokens:,} tokens "
              f"({snapshot.context_utilization:.1%} utilized)")

        # Detect if we're approaching context limits
        if snapshot.context_utilization > 0.8:
            print("⚠️  Context utilization high - summarization likely soon")

@watcher.on("session_end")
def on_end(event):
    tracker = trackers.pop(event.session_id, None)
    if tracker:
        trajectory = tracker.get_trajectory()
        report = analyzer.analyze(trajectory)
        report.save(f"context_analysis_{event.session_id[:8]}.json")

watcher.start()
```

---

## Example: Complete Monitoring Script

```python
#!/usr/bin/env python3
"""Example: Real-time Claude Code session monitor."""

from datetime import datetime
from claude_sessions.realtime import SessionWatcher, LiveSessionManager

def main():
    watcher = SessionWatcher()
    sessions = LiveSessionManager()

    @watcher.on("session_start")
    def on_start(event):
        print(f"\n{'='*60}")
        print(f"Session started: {event.session_id}")
        print(f"Project: {event.project_slug}")
        print(f"{'='*60}\n")

    @watcher.on("message")
    def on_message(event):
        session = sessions.get_session(event.session_id)
        role = event.message.role.value.upper()
        text = event.message.text_content[:200]

        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {role}: {text}")

        if session:
            print(f"  (messages: {session.message_count}, "
                  f"tools: {session.tool_call_count})")

    @watcher.on("tool_use")
    def on_tool(event):
        print(f"  → {event.tool_name}", end="")
        if event.tool_name == "Bash":
            cmd = event.tool_input.get("command", "")[:50]
            print(f": {cmd}")
        elif event.tool_name in ("Read", "Write", "Edit"):
            path = event.tool_input.get("file_path", "")
            print(f": {path}")
        else:
            print()

    @watcher.on("tool_result")
    def on_result(event):
        if event.is_error:
            print(f"  ✗ Tool error: {event.content[:100]}")

    @watcher.on("error")
    def on_error(event):
        print(f"\n⚠️  Error: {event.message}\n")

    print("Watching for Claude Code sessions... (Ctrl+C to stop)")
    try:
        watcher.start()
    except KeyboardInterrupt:
        print("\nStopped.")

if __name__ == "__main__":
    main()
```

---

## Example: Human-AI Collaboration Interface

```python
#!/usr/bin/env python3
"""Example: Approval gate for destructive operations."""

from claude_sessions.realtime import AsyncSessionWatcher
from claude_sessions.collaboration import ApprovalGate
import asyncio

# Define patterns that require human approval
DANGEROUS_PATTERNS = [
    {"tool": "Bash", "command_contains": ["rm -rf", "git push --force", "DROP TABLE"]},
    {"tool": "Write", "path_contains": [".env", "credentials", "secret"]},
    {"tool": "Bash", "command_contains": ["sudo"]},
]

async def main():
    watcher = AsyncSessionWatcher()
    gate = ApprovalGate(patterns=DANGEROUS_PATTERNS)

    async for event in watcher.events():
        if event.event_type == "tool_use":
            if gate.requires_approval(event):
                print(f"\n🚨 APPROVAL REQUIRED 🚨")
                print(f"Tool: {event.tool_name}")
                print(f"Input: {event.tool_input}")
                print(f"Session: {event.session_id[:8]}")

                # In a real implementation, this would:
                # - Send notification (Slack, desktop, etc.)
                # - Wait for approval via UI/API
                # - Optionally inject a response back to Claude

                # For now, just log it
                gate.log_pending(event)

asyncio.run(main())
```

---

## Example: Live Dashboard Data Provider

```python
#!/usr/bin/env python3
"""Example: WebSocket server providing live session data for a dashboard."""

from claude_sessions.realtime import AsyncSessionWatcher, LiveSessionManager
import asyncio
import json
from websockets import serve

sessions = LiveSessionManager()
connected_clients: set = set()

async def broadcast(data: dict):
    """Send update to all connected dashboard clients."""
    if connected_clients:
        message = json.dumps(data)
        await asyncio.gather(*[client.send(message) for client in connected_clients])

async def watch_sessions():
    """Watch for session events and broadcast to clients."""
    watcher = AsyncSessionWatcher()

    async for event in watcher.events():
        sessions.update(event)

        await broadcast({
            "type": event.event_type,
            "session_id": event.session_id,
            "timestamp": event.timestamp.isoformat(),
            "data": event.to_dict(),
            "stats": {
                "active_sessions": len(sessions.get_active()),
                "total_messages": sessions.total_message_count,
                "total_tool_calls": sessions.total_tool_call_count,
            }
        })

async def handle_client(websocket):
    """Handle a dashboard client connection."""
    connected_clients.add(websocket)
    try:
        # Send current state on connect
        await websocket.send(json.dumps({
            "type": "init",
            "sessions": [s.to_dict() for s in sessions.get_active()]
        }))
        # Keep connection alive
        async for message in websocket:
            pass  # Handle client commands if needed
    finally:
        connected_clients.remove(websocket)

async def main():
    async with serve(handle_client, "localhost", 8765):
        await watch_sessions()

asyncio.run(main())
```

---

## Next Steps

1. **Review this plan** - Gather feedback on architecture and priorities
2. **Prototype Phase 1** - Build `JSONLTailer` and basic event emission
3. **Validate with real sessions** - Test against live Claude Code usage
4. **Iterate on API design** - Refine based on practical usage patterns
5. **Build example applications** - Monitor script, dashboard, research tools
6. **Document and release** - API docs, examples, PyPI package update
