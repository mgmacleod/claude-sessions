"""Tests for claude_sessions.realtime.metrics module."""

from datetime import datetime, timezone

import pytest

from claude_sessions.realtime.metrics import (
    Counter,
    Gauge,
    Histogram,
    MetricsCollector,
)
from claude_sessions.realtime.events import (
    MessageEvent,
    ToolUseEvent,
    ToolResultEvent,
    ErrorEvent,
    SessionStartEvent,
    SessionEndEvent,
)
from claude_sessions.models import Message, MessageRole, TextBlock


@pytest.fixture
def sample_datetime():
    return datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)


class TestCounter:
    """Test Counter metric class."""

    def test_initial_value_zero(self):
        """Counter should start at zero."""
        counter = Counter("test_total", "Test counter")
        assert counter.get() == 0

    def test_inc_default(self):
        """inc() should increment by 1 by default."""
        counter = Counter("test_total")
        counter.inc()
        assert counter.get() == 1

    def test_inc_amount(self):
        """inc() should increment by specified amount."""
        counter = Counter("test_total")
        counter.inc(5)
        assert counter.get() == 5

    def test_inc_negative_raises(self):
        """inc() with negative amount should raise ValueError."""
        counter = Counter("test_total")
        with pytest.raises(ValueError, match="positive"):
            counter.inc(-1)

    def test_inc_with_labels(self):
        """inc() should support labels."""
        counter = Counter("test_total", label_names=("method", "status"))
        counter.inc(labels={"method": "GET", "status": "200"})
        counter.inc(labels={"method": "POST", "status": "201"})

        assert counter.get(labels={"method": "GET", "status": "200"}) == 1
        assert counter.get(labels={"method": "POST", "status": "201"}) == 1

    def test_get_all(self):
        """get_all() should return all label combinations."""
        counter = Counter("test_total", label_names=("type",))
        counter.inc(labels={"type": "a"})
        counter.inc(2, labels={"type": "b"})

        all_values = counter.get_all()
        assert len(all_values) == 2

    def test_reset(self):
        """reset() should clear all values."""
        counter = Counter("test_total")
        counter.inc(10)
        counter.reset()
        assert counter.get() == 0

    def test_to_prometheus_text(self):
        """to_prometheus_text() should produce valid Prometheus format."""
        counter = Counter("http_requests_total", "Total HTTP requests")
        counter.inc(5)

        text = counter.to_prometheus_text()

        assert "# HELP http_requests_total" in text
        assert "# TYPE http_requests_total counter" in text
        assert "http_requests_total 5" in text


class TestGauge:
    """Test Gauge metric class."""

    def test_initial_value_zero(self):
        """Gauge should start at zero."""
        gauge = Gauge("test_gauge")
        assert gauge.get() == 0

    def test_set(self):
        """set() should set the value."""
        gauge = Gauge("test_gauge")
        gauge.set(42)
        assert gauge.get() == 42

    def test_inc(self):
        """inc() should increment value."""
        gauge = Gauge("test_gauge")
        gauge.set(10)
        gauge.inc()
        assert gauge.get() == 11

    def test_inc_amount(self):
        """inc() should support custom amount."""
        gauge = Gauge("test_gauge")
        gauge.inc(5)
        assert gauge.get() == 5

    def test_dec(self):
        """dec() should decrement value."""
        gauge = Gauge("test_gauge")
        gauge.set(10)
        gauge.dec()
        assert gauge.get() == 9

    def test_dec_amount(self):
        """dec() should support custom amount."""
        gauge = Gauge("test_gauge")
        gauge.set(10)
        gauge.dec(5)
        assert gauge.get() == 5

    def test_reset(self):
        """reset() should clear all values."""
        gauge = Gauge("test_gauge")
        gauge.set(100)
        gauge.reset()
        assert gauge.get() == 0

    def test_to_prometheus_text(self):
        """to_prometheus_text() should produce valid Prometheus format."""
        gauge = Gauge("active_connections", "Active connections")
        gauge.set(42)

        text = gauge.to_prometheus_text()

        assert "# TYPE active_connections gauge" in text
        assert "active_connections 42" in text


class TestHistogram:
    """Test Histogram metric class."""

    def test_observe(self):
        """observe() should record values."""
        hist = Histogram("request_duration_seconds")
        hist.observe(0.5)
        hist.observe(1.5)
        hist.observe(2.5)

        assert hist.get_count() == 3

    def test_get_sum(self):
        """get_sum() should return sum of observations."""
        hist = Histogram("duration")
        hist.observe(1.0)
        hist.observe(2.0)
        hist.observe(3.0)

        assert hist.get_sum() == 6.0

    def test_bucket_distribution(self):
        """Observations should be distributed into buckets."""
        hist = Histogram("duration", buckets=(1.0, 5.0, 10.0))
        hist.observe(0.5)  # <= 1.0
        hist.observe(3.0)  # <= 5.0
        hist.observe(7.0)  # <= 10.0
        hist.observe(15.0)  # > 10.0 (inf bucket)

        buckets = hist.get_buckets()
        # Each bucket is cumulative
        assert buckets[1.0] >= 1
        assert buckets[5.0] >= 2
        assert buckets[10.0] >= 3

    def test_reset(self):
        """reset() should clear all values."""
        hist = Histogram("duration")
        hist.observe(1.0)
        hist.reset()

        assert hist.get_count() == 0
        assert hist.get_sum() == 0.0

    def test_to_prometheus_text(self):
        """to_prometheus_text() should produce valid Prometheus format."""
        hist = Histogram("request_duration_seconds", "Request latency", buckets=(0.1, 0.5, 1.0))
        hist.observe(0.25)

        text = hist.to_prometheus_text()

        assert "# TYPE request_duration_seconds histogram" in text
        assert "_bucket" in text
        assert "_count" in text
        assert "_sum" in text


class TestMetricsCollector:
    """Test MetricsCollector class."""

    @pytest.fixture
    def collector(self):
        """Create a fresh MetricsCollector."""
        return MetricsCollector()

    @pytest.fixture
    def message_event(self, sample_datetime):
        """Create a sample message event."""
        message = Message(
            uuid="msg-1",
            parent_uuid=None,
            timestamp=sample_datetime,
            role=MessageRole.USER,
            content=[TextBlock(text="Hello")],
            session_id="session-123"
        )
        return MessageEvent(
            timestamp=sample_datetime,
            session_id="session-123",
            message=message
        )

    @pytest.fixture
    def tool_use_event(self, sample_datetime):
        """Create a sample tool use event."""
        message = Message(
            uuid="msg-2",
            parent_uuid=None,
            timestamp=sample_datetime,
            role=MessageRole.ASSISTANT,
            content=[],
            session_id="session-123"
        )
        return ToolUseEvent(
            timestamp=sample_datetime,
            session_id="session-123",
            tool_name="Read",
            tool_category="file_read",
            tool_input={"file_path": "/test.py"},
            tool_use_id="toolu_123",
            message=message
        )

    @pytest.fixture
    def error_event(self, sample_datetime):
        """Create a sample error event."""
        return ErrorEvent(
            timestamp=sample_datetime,
            session_id="session-123",
            error_message="Parse error"
        )

    def test_handle_message_event(self, collector, message_event):
        """handle_event() should track message events."""
        collector.handle_event(message_event)

        # Check messages_total counter - note: session_id is truncated to 8 chars
        total = collector.messages_total.get(
            labels={"session_id": "session-", "role": "user"}
        )
        assert total == 1

    def test_handle_tool_use_event(self, collector, tool_use_event):
        """handle_event() should track tool use events."""
        collector.handle_event(tool_use_event)

        # Check tool_calls_total counter - note: session_id is truncated to 8 chars
        total = collector.tool_calls_total.get(
            labels={"session_id": "session-", "tool_name": "Read", "category": "file_read"}
        )
        assert total == 1

    def test_handle_error_event(self, collector, error_event):
        """handle_event() should track error events."""
        collector.handle_event(error_event)

        # Check errors_total counter - error_type is hardcoded as "parse_error"
        total = collector.errors_total.get(
            labels={"session_id": "session-", "error_type": "parse_error"}
        )
        assert total == 1

    def test_tool_usage_breakdown(self, collector, sample_datetime):
        """tool_usage_breakdown should aggregate by tool name."""
        message = Message(
            uuid="msg",
            parent_uuid=None,
            timestamp=sample_datetime,
            role=MessageRole.ASSISTANT,
            content=[],
            session_id="session-123"
        )

        # Add various tool uses
        for tool in ["Read", "Read", "Bash", "Write"]:
            event = ToolUseEvent(
                timestamp=sample_datetime,
                session_id="session-123",
                tool_name=tool,
                tool_category="other",
                tool_input={},
                tool_use_id=f"toolu_{tool}",
                message=message
            )
            collector.handle_event(event)

        breakdown = collector.tool_usage_breakdown

        assert breakdown["Read"] == 2
        assert breakdown["Bash"] == 1
        assert breakdown["Write"] == 1

    def test_to_prometheus_text(self, collector, message_event, tool_use_event):
        """to_prometheus_text() should produce valid output."""
        collector.handle_event(message_event)
        collector.handle_event(tool_use_event)

        text = collector.to_prometheus_text()

        # Default namespace is "claude_sessions"
        assert "claude_sessions_messages_total" in text
        assert "claude_sessions_tool_calls_total" in text

    def test_to_dict(self, collector, message_event):
        """to_dict() should serialize metrics."""
        collector.handle_event(message_event)

        data = collector.to_dict()

        assert "messages_total" in data
        assert "tool_calls_total" in data
        assert "errors_total" in data

    def test_reset(self, collector, message_event, tool_use_event):
        """reset() should clear all metrics."""
        collector.handle_event(message_event)
        collector.handle_event(tool_use_event)

        collector.reset()

        assert collector.messages_total.get() == 0


class TestMetricsCollectorRates:
    """Test rate calculation in MetricsCollector."""

    def test_messages_per_minute_initial(self):
        """Initial messages_per_minute should be 0."""
        collector = MetricsCollector()
        assert collector.messages_per_minute == 0.0

    def test_tools_per_minute_initial(self):
        """Initial tools_per_minute should be 0."""
        collector = MetricsCollector()
        assert collector.tools_per_minute == 0.0

    def test_error_rate_no_messages(self):
        """error_rate should be 0 when no messages."""
        collector = MetricsCollector()
        assert collector.error_rate == 0.0
