"""Prometheus-compatible metrics for realtime session monitoring.

This module provides metric types (Counter, Gauge, Histogram) that follow
Prometheus conventions, enabling easy integration with monitoring systems.

Example usage:
    from claude_sessions.realtime import SessionWatcher, MetricsCollector

    watcher = SessionWatcher()
    metrics = MetricsCollector()

    # Route all events to metrics collector
    watcher.on_any(metrics.handle_event)

    # Access metrics
    print(f"Total messages: {metrics.messages_total.get()}")
    print(f"Messages/min: {metrics.messages_per_minute}")
    print(f"Tool breakdown: {metrics.tool_usage_breakdown}")

    # Export for Prometheus scraping
    print(metrics.to_prometheus_text())

    watcher.start()
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Any, Callable, Dict, List, Optional, Tuple

from .events import SessionEventType


# --- Prometheus-Compatible Metric Types ---


class Counter:
    """A monotonically increasing counter metric.

    Counters are used to track cumulative values that only go up,
    like total requests or total errors.

    Supports labels for multi-dimensional metrics.

    Example:
        counter = Counter("requests_total", "Total HTTP requests")
        counter.inc()  # Increment by 1
        counter.inc(5, labels={"method": "GET"})  # Increment by 5 with label
    """

    def __init__(self, name: str, description: str = "", label_names: Tuple[str, ...] = ()):
        """Initialize the counter.

        Args:
            name: Metric name (should follow Prometheus naming conventions)
            description: Human-readable description
            label_names: Names of labels this counter supports
        """
        self.name = name
        self.description = description
        self.label_names = label_names
        self._values: Dict[Tuple[str, ...], float] = defaultdict(float)
        self._lock = RLock()

    def inc(self, amount: float = 1.0, labels: Optional[Dict[str, str]] = None) -> None:
        """Increment the counter.

        Args:
            amount: Amount to increment by (must be positive)
            labels: Label values as a dict

        Raises:
            ValueError: If amount is negative
        """
        if amount < 0:
            raise ValueError("Counter can only be incremented by positive values")

        label_key = self._make_label_key(labels)
        with self._lock:
            self._values[label_key] += amount

    def get(self, labels: Optional[Dict[str, str]] = None) -> float:
        """Get the current counter value.

        Args:
            labels: Label values to query

        Returns:
            Current counter value for the given labels
        """
        label_key = self._make_label_key(labels)
        with self._lock:
            return self._values[label_key]

    def get_all(self) -> Dict[Tuple[str, ...], float]:
        """Get all counter values with their label combinations.

        Returns:
            Dict mapping label tuples to values
        """
        with self._lock:
            return dict(self._values)

    def reset(self) -> None:
        """Reset all counter values to zero."""
        with self._lock:
            self._values.clear()

    def _make_label_key(self, labels: Optional[Dict[str, str]]) -> Tuple[str, ...]:
        """Convert labels dict to a hashable tuple."""
        if labels is None or not self.label_names:
            return ()
        return tuple(labels.get(name, "") for name in self.label_names)

    def to_prometheus_text(self) -> str:
        """Export in Prometheus text format."""
        lines = []
        if self.description:
            lines.append(f"# HELP {self.name} {self.description}")
        lines.append(f"# TYPE {self.name} counter")

        with self._lock:
            for label_key, value in self._values.items():
                if label_key:
                    label_str = ",".join(
                        f'{name}="{val}"'
                        for name, val in zip(self.label_names, label_key)
                        if val
                    )
                    lines.append(f"{self.name}{{{label_str}}} {value}")
                else:
                    lines.append(f"{self.name} {value}")

        return "\n".join(lines)


class Gauge:
    """A metric that can go up or down.

    Gauges are used for values that can increase and decrease,
    like current active connections or temperature.

    Supports labels for multi-dimensional metrics.

    Example:
        gauge = Gauge("active_sessions", "Currently active sessions")
        gauge.set(10)
        gauge.inc()  # Now 11
        gauge.dec(5)  # Now 6
    """

    def __init__(self, name: str, description: str = "", label_names: Tuple[str, ...] = ()):
        """Initialize the gauge.

        Args:
            name: Metric name
            description: Human-readable description
            label_names: Names of labels this gauge supports
        """
        self.name = name
        self.description = description
        self.label_names = label_names
        self._values: Dict[Tuple[str, ...], float] = defaultdict(float)
        self._lock = RLock()

    def set(self, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """Set the gauge to a specific value.

        Args:
            value: Value to set
            labels: Label values
        """
        label_key = self._make_label_key(labels)
        with self._lock:
            self._values[label_key] = value

    def inc(self, amount: float = 1.0, labels: Optional[Dict[str, str]] = None) -> None:
        """Increment the gauge.

        Args:
            amount: Amount to increment by
            labels: Label values
        """
        label_key = self._make_label_key(labels)
        with self._lock:
            self._values[label_key] += amount

    def dec(self, amount: float = 1.0, labels: Optional[Dict[str, str]] = None) -> None:
        """Decrement the gauge.

        Args:
            amount: Amount to decrement by
            labels: Label values
        """
        label_key = self._make_label_key(labels)
        with self._lock:
            self._values[label_key] -= amount

    def get(self, labels: Optional[Dict[str, str]] = None) -> float:
        """Get the current gauge value.

        Args:
            labels: Label values to query

        Returns:
            Current gauge value
        """
        label_key = self._make_label_key(labels)
        with self._lock:
            return self._values[label_key]

    def get_all(self) -> Dict[Tuple[str, ...], float]:
        """Get all gauge values with their label combinations."""
        with self._lock:
            return dict(self._values)

    def reset(self) -> None:
        """Reset all gauge values to zero."""
        with self._lock:
            self._values.clear()

    def _make_label_key(self, labels: Optional[Dict[str, str]]) -> Tuple[str, ...]:
        """Convert labels dict to a hashable tuple."""
        if labels is None or not self.label_names:
            return ()
        return tuple(labels.get(name, "") for name in self.label_names)

    def to_prometheus_text(self) -> str:
        """Export in Prometheus text format."""
        lines = []
        if self.description:
            lines.append(f"# HELP {self.name} {self.description}")
        lines.append(f"# TYPE {self.name} gauge")

        with self._lock:
            for label_key, value in self._values.items():
                if label_key:
                    label_str = ",".join(
                        f'{name}="{val}"'
                        for name, val in zip(self.label_names, label_key)
                        if val
                    )
                    lines.append(f"{self.name}{{{label_str}}} {value}")
                else:
                    lines.append(f"{self.name} {value}")

        return "\n".join(lines)


# Default histogram buckets for durations in seconds
DEFAULT_DURATION_BUCKETS = (
    0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, float("inf")
)


class Histogram:
    """A histogram metric for observing value distributions.

    Histograms are used to track distributions of values,
    like request durations or response sizes.

    Supports labels for multi-dimensional metrics.

    Example:
        hist = Histogram("request_duration_seconds", "Request duration")
        hist.observe(0.25)  # 250ms request
        hist.observe(1.5)   # 1.5s request
    """

    def __init__(
        self,
        name: str,
        description: str = "",
        label_names: Tuple[str, ...] = (),
        buckets: Tuple[float, ...] = DEFAULT_DURATION_BUCKETS,
    ):
        """Initialize the histogram.

        Args:
            name: Metric name
            description: Human-readable description
            label_names: Names of labels this histogram supports
            buckets: Upper bounds for histogram buckets
        """
        self.name = name
        self.description = description
        self.label_names = label_names
        self.buckets = tuple(sorted(buckets))

        # Per-label-key: bucket counts, sum, and count
        self._bucket_counts: Dict[Tuple[str, ...], Dict[float, int]] = defaultdict(
            lambda: {b: 0 for b in self.buckets}
        )
        self._sums: Dict[Tuple[str, ...], float] = defaultdict(float)
        self._counts: Dict[Tuple[str, ...], int] = defaultdict(int)
        self._lock = RLock()

    def observe(self, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """Observe a value.

        Args:
            value: The value to observe
            labels: Label values
        """
        label_key = self._make_label_key(labels)
        with self._lock:
            self._sums[label_key] += value
            self._counts[label_key] += 1

            # Increment buckets (cumulative)
            for bucket in self.buckets:
                if value <= bucket:
                    self._bucket_counts[label_key][bucket] += 1

    def get_buckets(
        self, labels: Optional[Dict[str, str]] = None
    ) -> Dict[float, int]:
        """Get bucket counts for given labels.

        Args:
            labels: Label values to query

        Returns:
            Dict mapping bucket upper bounds to cumulative counts
        """
        label_key = self._make_label_key(labels)
        with self._lock:
            if label_key in self._bucket_counts:
                return dict(self._bucket_counts[label_key])
            return {b: 0 for b in self.buckets}

    def get_sum(self, labels: Optional[Dict[str, str]] = None) -> float:
        """Get the sum of all observed values.

        Args:
            labels: Label values to query

        Returns:
            Sum of observed values
        """
        label_key = self._make_label_key(labels)
        with self._lock:
            return self._sums[label_key]

    def get_count(self, labels: Optional[Dict[str, str]] = None) -> int:
        """Get the count of observations.

        Args:
            labels: Label values to query

        Returns:
            Number of observations
        """
        label_key = self._make_label_key(labels)
        with self._lock:
            return self._counts[label_key]

    def reset(self) -> None:
        """Reset all histogram data."""
        with self._lock:
            self._bucket_counts.clear()
            self._sums.clear()
            self._counts.clear()

    def _make_label_key(self, labels: Optional[Dict[str, str]]) -> Tuple[str, ...]:
        """Convert labels dict to a hashable tuple."""
        if labels is None or not self.label_names:
            return ()
        return tuple(labels.get(name, "") for name in self.label_names)

    def to_prometheus_text(self) -> str:
        """Export in Prometheus text format."""
        lines = []
        if self.description:
            lines.append(f"# HELP {self.name} {self.description}")
        lines.append(f"# TYPE {self.name} histogram")

        with self._lock:
            for label_key in set(
                list(self._bucket_counts.keys())
                + list(self._sums.keys())
                + list(self._counts.keys())
            ):
                base_labels = ""
                if label_key:
                    base_labels = ",".join(
                        f'{name}="{val}"'
                        for name, val in zip(self.label_names, label_key)
                        if val
                    )

                # Bucket lines
                for bucket, count in self._bucket_counts.get(
                    label_key, {b: 0 for b in self.buckets}
                ).items():
                    le = "+Inf" if bucket == float("inf") else str(bucket)
                    if base_labels:
                        lines.append(
                            f'{self.name}_bucket{{{base_labels},le="{le}"}} {count}'
                        )
                    else:
                        lines.append(f'{self.name}_bucket{{le="{le}"}} {count}')

                # Sum and count
                if base_labels:
                    lines.append(
                        f"{self.name}_sum{{{base_labels}}} {self._sums.get(label_key, 0)}"
                    )
                    lines.append(
                        f"{self.name}_count{{{base_labels}}} {self._counts.get(label_key, 0)}"
                    )
                else:
                    lines.append(f"{self.name}_sum {self._sums.get(label_key, 0)}")
                    lines.append(f"{self.name}_count {self._counts.get(label_key, 0)}")

        return "\n".join(lines)


# --- Rate Tracking ---


@dataclass
class _RateWindow:
    """Sliding window for rate calculations."""

    window_size: timedelta
    timestamps: List[float] = field(default_factory=list)

    def add(self) -> None:
        """Add a timestamp for the current time."""
        now = time.time()
        self.timestamps.append(now)
        self._prune(now)

    def _prune(self, now: float) -> None:
        """Remove timestamps outside the window."""
        cutoff = now - self.window_size.total_seconds()
        self.timestamps = [t for t in self.timestamps if t >= cutoff]

    def rate_per_minute(self) -> float:
        """Calculate the rate per minute."""
        now = time.time()
        self._prune(now)

        if not self.timestamps:
            return 0.0

        window_seconds = self.window_size.total_seconds()
        return (len(self.timestamps) / window_seconds) * 60


# --- MetricsCollector ---


class MetricsCollector:
    """Collects and aggregates metrics from session events.

    Provides Prometheus-compatible metrics for monitoring Claude Code
    session activity. Can be used as an event handler with SessionWatcher.

    Metrics collected:
        - claude_sessions_messages_total: Counter of messages by session/role
        - claude_sessions_tool_calls_total: Counter of tool calls by name/category
        - claude_sessions_errors_total: Counter of errors
        - claude_sessions_active_sessions: Gauge of currently active sessions
        - claude_sessions_tool_duration_seconds: Histogram of tool durations

    Example:
        watcher = SessionWatcher()
        metrics = MetricsCollector()

        watcher.on_any(metrics.handle_event)
        watcher.start_background()

        # Access metrics
        print(metrics.messages_per_minute)
        print(metrics.tool_usage_breakdown)
        print(metrics.to_prometheus_text())
    """

    def __init__(
        self,
        window_size: timedelta = timedelta(minutes=5),
        namespace: str = "claude_sessions",
    ):
        """Initialize the metrics collector.

        Args:
            window_size: Time window for rate calculations
            namespace: Prefix for metric names
        """
        self._lock = RLock()
        self._window_size = window_size
        self._namespace = namespace

        # Track active sessions
        self._active_session_ids: set = set()
        self._session_start_times: Dict[str, datetime] = {}

        # Rate tracking
        self._message_rate = _RateWindow(window_size)
        self._tool_rate = _RateWindow(window_size)
        self._error_rate = _RateWindow(window_size)

        # Prometheus-compatible metrics
        self.messages_total = Counter(
            f"{namespace}_messages_total",
            "Total messages processed",
            label_names=("session_id", "role"),
        )

        self.tool_calls_total = Counter(
            f"{namespace}_tool_calls_total",
            "Total tool calls",
            label_names=("session_id", "tool_name", "category"),
        )

        self.errors_total = Counter(
            f"{namespace}_errors_total",
            "Total errors",
            label_names=("session_id", "error_type"),
        )

        self.active_sessions = Gauge(
            f"{namespace}_active_sessions",
            "Currently active sessions",
        )

        self.tool_duration_seconds = Histogram(
            f"{namespace}_tool_duration_seconds",
            "Tool call duration in seconds",
            label_names=("tool_name",),
        )

        self.session_duration_seconds = Histogram(
            f"{namespace}_session_duration_seconds",
            "Session duration in seconds",
            label_names=(),
            buckets=(60, 300, 600, 1800, 3600, 7200, 14400, float("inf")),
        )

    def handle_event(self, event: SessionEventType) -> None:
        """Process an event and update metrics.

        This method is compatible with watcher.on_any() for easy integration.

        Args:
            event: The session event to process
        """
        event_type = getattr(event, "event_type", None)
        session_id = getattr(event, "session_id", "")

        with self._lock:
            if event_type == "message":
                self._handle_message(event, session_id)
            elif event_type == "tool_use":
                self._handle_tool_use(event, session_id)
            elif event_type == "tool_result":
                self._handle_tool_result(event, session_id)
            elif event_type == "tool_call_completed":
                self._handle_tool_call_completed(event, session_id)
            elif event_type == "error":
                self._handle_error(event, session_id)
            elif event_type == "session_start":
                self._handle_session_start(event, session_id)
            elif event_type == "session_end":
                self._handle_session_end(event, session_id)

    def _handle_message(self, event: SessionEventType, session_id: str) -> None:
        """Handle a message event."""
        self._message_rate.add()

        role = "unknown"
        if hasattr(event, "message"):
            msg_role = getattr(event.message, "role", None)
            if msg_role:
                role = msg_role.value if hasattr(msg_role, "value") else str(msg_role)

        self.messages_total.inc(
            labels={"session_id": session_id[:8], "role": role}
        )

        # Track as active session
        if session_id and session_id not in self._active_session_ids:
            self._active_session_ids.add(session_id)
            self.active_sessions.set(len(self._active_session_ids))

    def _handle_tool_use(self, event: SessionEventType, session_id: str) -> None:
        """Handle a tool use event."""
        self._tool_rate.add()

        tool_name = getattr(event, "tool_name", "unknown")
        category = getattr(event, "tool_category", "other")

        self.tool_calls_total.inc(
            labels={
                "session_id": session_id[:8],
                "tool_name": tool_name,
                "category": category,
            }
        )

    def _handle_tool_result(self, event: SessionEventType, session_id: str) -> None:
        """Handle a tool result event."""
        if getattr(event, "is_error", False):
            self._error_rate.add()
            self.errors_total.inc(
                labels={"session_id": session_id[:8], "error_type": "tool_error"}
            )

    def _handle_tool_call_completed(
        self, event: SessionEventType, session_id: str
    ) -> None:
        """Handle a completed tool call event with duration."""
        duration = getattr(event, "duration", None)
        if duration is not None:
            tool_name = getattr(event, "tool_name", "unknown")
            self.tool_duration_seconds.observe(
                duration.total_seconds(),
                labels={"tool_name": tool_name},
            )

    def _handle_error(self, event: SessionEventType, session_id: str) -> None:
        """Handle an error event."""
        self._error_rate.add()
        self.errors_total.inc(
            labels={"session_id": session_id[:8], "error_type": "parse_error"}
        )

    def _handle_session_start(self, event: SessionEventType, session_id: str) -> None:
        """Handle session start."""
        self._active_session_ids.add(session_id)
        self._session_start_times[session_id] = datetime.now(timezone.utc)
        self.active_sessions.set(len(self._active_session_ids))

    def _handle_session_end(self, event: SessionEventType, session_id: str) -> None:
        """Handle session end."""
        self._active_session_ids.discard(session_id)
        self.active_sessions.set(len(self._active_session_ids))

        # Record session duration
        start_time = self._session_start_times.pop(session_id, None)
        if start_time:
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            self.session_duration_seconds.observe(duration)

    # --- Convenience Accessors ---

    @property
    def messages_per_minute(self) -> float:
        """Current message rate per minute."""
        with self._lock:
            return self._message_rate.rate_per_minute()

    @property
    def tools_per_minute(self) -> float:
        """Current tool call rate per minute."""
        with self._lock:
            return self._tool_rate.rate_per_minute()

    @property
    def errors_per_minute(self) -> float:
        """Current error rate per minute."""
        with self._lock:
            return self._error_rate.rate_per_minute()

    @property
    def tool_usage_breakdown(self) -> Dict[str, int]:
        """Breakdown of tool usage by tool name.

        Returns:
            Dict mapping tool names to total call counts
        """
        result: Dict[str, int] = defaultdict(int)
        for label_key, count in self.tool_calls_total.get_all().items():
            if len(label_key) >= 2:
                tool_name = label_key[1]  # (session_id, tool_name, category)
                result[tool_name] += int(count)
        return dict(result)

    @property
    def error_rate(self) -> float:
        """Error rate as a fraction of total events.

        Returns:
            Ratio of errors to total messages (0.0 to 1.0)
        """
        total_messages = sum(self.messages_total.get_all().values())
        total_errors = sum(self.errors_total.get_all().values())

        if total_messages == 0:
            return 0.0
        return total_errors / total_messages

    @property
    def active_session_count(self) -> int:
        """Number of currently active sessions."""
        with self._lock:
            return len(self._active_session_ids)

    # --- Export ---

    def to_prometheus_text(self) -> str:
        """Export all metrics in Prometheus text format.

        Returns:
            String in Prometheus exposition format, ready for scraping
        """
        sections = [
            self.messages_total.to_prometheus_text(),
            self.tool_calls_total.to_prometheus_text(),
            self.errors_total.to_prometheus_text(),
            self.active_sessions.to_prometheus_text(),
            self.tool_duration_seconds.to_prometheus_text(),
            self.session_duration_seconds.to_prometheus_text(),
        ]
        return "\n\n".join(s for s in sections if s)

    def to_dict(self) -> Dict[str, Any]:
        """Export metrics as a JSON-serializable dictionary.

        Returns:
            Dict with all metric values
        """
        return {
            "messages_total": sum(self.messages_total.get_all().values()),
            "tool_calls_total": sum(self.tool_calls_total.get_all().values()),
            "errors_total": sum(self.errors_total.get_all().values()),
            "active_sessions": self.active_session_count,
            "messages_per_minute": self.messages_per_minute,
            "tools_per_minute": self.tools_per_minute,
            "errors_per_minute": self.errors_per_minute,
            "error_rate": self.error_rate,
            "tool_usage_breakdown": self.tool_usage_breakdown,
        }

    def reset(self) -> None:
        """Reset all metrics to initial state."""
        with self._lock:
            self._active_session_ids.clear()
            self._session_start_times.clear()
            self._message_rate = _RateWindow(self._window_size)
            self._tool_rate = _RateWindow(self._window_size)
            self._error_rate = _RateWindow(self._window_size)

            self.messages_total.reset()
            self.tool_calls_total.reset()
            self.errors_total.reset()
            self.active_sessions.reset()
            self.tool_duration_seconds.reset()
            self.session_duration_seconds.reset()

    def __repr__(self) -> str:
        return (
            f"MetricsCollector("
            f"active={self.active_session_count}, "
            f"msgs/min={self.messages_per_minute:.1f}, "
            f"tools/min={self.tools_per_minute:.1f})"
        )
