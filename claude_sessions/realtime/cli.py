#!/usr/bin/env python3
"""Command-line interface for claude-sessions realtime monitoring.

This module provides the `claude-sessions` CLI with subcommands for
watching sessions in real-time and exposing Prometheus metrics.

Usage:
    claude-sessions watch [options]    # Monitor sessions
    claude-sessions metrics [options]  # Start metrics server only

Examples:
    # Watch all sessions with default output
    claude-sessions watch

    # Watch with filters
    claude-sessions watch --project myproject --tool-category file_write

    # JSON output for piping
    claude-sessions watch --format json | jq .

    # With Prometheus metrics
    claude-sessions watch --metrics --metrics-port 9090

    # With webhooks
    claude-sessions watch --webhook http://localhost:8080/events
"""

import argparse
import logging
import signal
import sys
from datetime import timedelta
from pathlib import Path
from typing import Callable, List, Optional

from .events import SessionEventType
from .formatters import get_formatter, OutputFormatter

logger = logging.getLogger(__name__)


def create_parser() -> argparse.ArgumentParser:
    """Create the main argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="claude-sessions",
        description="Parse and monitor Claude Code sessions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  claude-sessions watch                    Watch all sessions
  claude-sessions watch --format json      Output as JSON lines
  claude-sessions watch --project myproj   Filter by project
  claude-sessions watch --metrics          Enable Prometheus metrics
  claude-sessions metrics                  Run metrics server only
        """,
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (-v for info, -vv for debug)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Watch subcommand
    watch_parser = subparsers.add_parser(
        "watch",
        help="Monitor sessions in real-time",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_watch_arguments(watch_parser)

    # Metrics subcommand
    metrics_parser = subparsers.add_parser(
        "metrics",
        help="Start Prometheus metrics server only",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_metrics_arguments(metrics_parser)

    return parser


def _add_watch_arguments(parser: argparse.ArgumentParser) -> None:
    """Add arguments for the watch subcommand."""
    # Filter options
    filter_group = parser.add_argument_group("filters")
    filter_group.add_argument(
        "--project",
        "-p",
        metavar="SLUG",
        help="Filter by project slug (partial match)",
    )
    filter_group.add_argument(
        "--session",
        "-s",
        metavar="ID",
        help="Filter by session ID (partial match)",
    )
    filter_group.add_argument(
        "--tool",
        "-t",
        action="append",
        metavar="NAME",
        help="Filter by tool name (can specify multiple)",
    )
    filter_group.add_argument(
        "--tool-category",
        action="append",
        choices=[
            "bash",
            "file_read",
            "file_write",
            "search",
            "agent",
            "planning",
            "web",
            "interaction",
        ],
        metavar="CAT",
        help="Filter by tool category (bash, file_read, file_write, search, agent, planning, web, interaction)",
    )
    filter_group.add_argument(
        "--event-type",
        "-e",
        action="append",
        choices=[
            "message",
            "tool_use",
            "tool_result",
            "tool_call_completed",
            "session_start",
            "session_end",
            "session_idle",
            "session_resume",
            "error",
        ],
        metavar="TYPE",
        help="Filter by event type",
    )
    filter_group.add_argument(
        "--errors-only",
        action="store_true",
        help="Only show error events and tool errors",
    )

    # Output options
    output_group = parser.add_argument_group("output")
    output_group.add_argument(
        "--format",
        "-f",
        choices=["plain", "json", "compact"],
        default="plain",
        help="Output format (default: plain)",
    )
    output_group.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colored output",
    )
    output_group.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress non-event output (headers, summaries)",
    )

    # Metrics options
    metrics_group = parser.add_argument_group("metrics")
    metrics_group.add_argument(
        "--metrics",
        action="store_true",
        help="Enable metrics collection and Prometheus endpoint",
    )
    metrics_group.add_argument(
        "--metrics-port",
        type=int,
        default=9090,
        help="Port for Prometheus metrics endpoint (default: 9090)",
    )
    metrics_group.add_argument(
        "--metrics-host",
        default="127.0.0.1",
        help="Host for Prometheus metrics endpoint (default: 127.0.0.1)",
    )
    metrics_group.add_argument(
        "--show-metrics-summary",
        action="store_true",
        help="Show metrics summary on exit",
    )

    # Webhook options
    webhook_group = parser.add_argument_group("webhooks")
    webhook_group.add_argument(
        "--webhook",
        action="append",
        metavar="URL",
        help="Send events to webhook URL (can specify multiple)",
    )
    webhook_group.add_argument(
        "--webhook-batch-size",
        type=int,
        default=10,
        help="Batch events before sending (default: 10)",
    )
    webhook_group.add_argument(
        "--webhook-batch-timeout",
        type=float,
        default=5.0,
        help="Max seconds to wait before sending batch (default: 5.0)",
    )
    webhook_group.add_argument(
        "--webhook-header",
        action="append",
        metavar="KEY=VALUE",
        help="Add HTTP header to webhook requests",
    )

    # Watcher configuration
    config_group = parser.add_argument_group("configuration")
    config_group.add_argument(
        "--base-path",
        type=Path,
        help="Override ~/.claude base directory",
    )
    config_group.add_argument(
        "--poll-interval",
        type=float,
        default=0.5,
        help="Poll interval in seconds (default: 0.5)",
    )
    config_group.add_argument(
        "--idle-timeout",
        type=float,
        default=120.0,
        help="Idle timeout in seconds before session marked idle (default: 120)",
    )
    config_group.add_argument(
        "--end-timeout",
        type=float,
        default=300.0,
        help="Timeout in seconds before idle session marked ended (default: 300)",
    )
    config_group.add_argument(
        "--state-file",
        type=Path,
        help="File to persist watcher state for resume capability",
    )


def _add_metrics_arguments(parser: argparse.ArgumentParser) -> None:
    """Add arguments for the metrics subcommand."""
    parser.add_argument(
        "--port",
        type=int,
        default=9090,
        help="Port to listen on (default: 9090)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Address to bind to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--base-path",
        type=Path,
        help="Override ~/.claude base directory",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.5,
        help="Poll interval in seconds (default: 0.5)",
    )


def build_filter(args) -> Optional[Callable[[SessionEventType], bool]]:
    """Build a combined filter from CLI arguments.

    Args:
        args: Parsed CLI arguments

    Returns:
        Filter function or None if no filters specified
    """
    # Import here to avoid circular imports and allow optional watchdog
    from . import filters

    filter_list: List[Callable[[SessionEventType], bool]] = []

    if args.project:
        filter_list.append(filters.project(args.project))

    if args.session:
        filter_list.append(filters.session(args.session))

    if args.tool:
        filter_list.append(filters.tool_name(*args.tool))

    if args.tool_category:
        filter_list.append(filters.tool_category(*args.tool_category))

    if args.event_type:
        filter_list.append(filters.event_type(*args.event_type))

    if args.errors_only:
        filter_list.append(filters.has_error())

    if not filter_list:
        return None

    if len(filter_list) == 1:
        return filter_list[0]

    return filters.and_(*filter_list)


def parse_webhook_headers(header_args: Optional[List[str]]) -> dict:
    """Parse webhook header arguments into a dictionary.

    Args:
        header_args: List of "KEY=VALUE" strings

    Returns:
        Dictionary of header name to value
    """
    if not header_args:
        return {}

    headers = {}
    for header in header_args:
        if "=" in header:
            key, value = header.split("=", 1)
            headers[key.strip()] = value.strip()
        else:
            logger.warning("Invalid header format (expected KEY=VALUE): %s", header)

    return headers


def cmd_watch(args) -> int:
    """Execute the watch subcommand.

    Args:
        args: Parsed CLI arguments

    Returns:
        Exit code (0 for success)
    """
    # Import realtime components (may fail if watchdog not installed)
    try:
        from .watcher import SessionWatcher, WatcherConfig
        from .metrics import MetricsCollector
    except ImportError as e:
        print(f"Error: Missing dependency - {e}", file=sys.stderr)
        print("Install with: pip install claude-sessions[realtime]", file=sys.stderr)
        return 1

    # Build configuration
    config_kwargs = {
        "poll_interval": args.poll_interval,
        "idle_timeout": timedelta(seconds=args.idle_timeout),
        "end_timeout": timedelta(seconds=args.end_timeout),
    }

    if args.base_path:
        config_kwargs["base_path"] = args.base_path

    if args.state_file:
        config_kwargs["state_file"] = args.state_file

    config = WatcherConfig(**config_kwargs)
    watcher = SessionWatcher(config)

    # Set up formatter
    formatter = get_formatter(args.format, use_color=not args.no_color)

    # Build filter
    event_filter = build_filter(args)

    # Set up metrics if enabled
    metrics = None
    prometheus_server = None
    if args.metrics:
        metrics = MetricsCollector()
        watcher.on_any(metrics.handle_event)

        # Start Prometheus server
        try:
            from .prometheus_server import PrometheusServer

            prometheus_server = PrometheusServer(
                metrics,
                host=args.metrics_host,
                port=args.metrics_port,
            )
            prometheus_server.start()
            if not args.quiet:
                print(f"Prometheus metrics available at {prometheus_server.url}")
        except ImportError:
            logger.warning("Prometheus server not available")

    # Set up webhooks if configured
    webhook_dispatcher = None
    if args.webhook:
        try:
            from .webhook import WebhookDispatcher, WebhookConfig

            webhook_dispatcher = WebhookDispatcher()
            headers = parse_webhook_headers(args.webhook_header)

            for url in args.webhook:
                webhook_config = WebhookConfig(
                    url=url,
                    headers=headers,
                    event_filter=event_filter,  # Apply same filter to webhooks
                    batch_size=args.webhook_batch_size,
                    batch_timeout=args.webhook_batch_timeout,
                )
                webhook_dispatcher.add_webhook(webhook_config)

            watcher.on_any(webhook_dispatcher.handle_event)
            webhook_dispatcher.start()

            if not args.quiet:
                print(f"Sending events to {len(args.webhook)} webhook(s)")
        except ImportError as e:
            logger.warning("Webhook dispatcher not available: %s", e)

    # Set up output handler
    @watcher.on_any
    def handle_event(event: SessionEventType) -> None:
        # Apply filter if configured
        if event_filter and not event_filter(event):
            return

        output = formatter.format(event)
        print(output)
        sys.stdout.flush()

    # Print startup message
    if not args.quiet:
        print("=" * 60)
        print("Watching Claude Code sessions...")
        print(f"  Poll interval: {args.poll_interval}s")
        print(f"  Idle timeout: {args.idle_timeout}s")
        if event_filter:
            print("  Filters: active")
        print("Press Ctrl+C to stop")
        print("=" * 60)

    # Handle shutdown gracefully
    def shutdown(signum, frame):
        if not args.quiet:
            print("\nShutting down...")
        watcher.stop()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Start watching
    try:
        watcher.start()
    except KeyboardInterrupt:
        pass
    finally:
        # Clean up
        if webhook_dispatcher:
            webhook_dispatcher.stop()
        if prometheus_server:
            prometheus_server.stop()

        # Show metrics summary if requested
        if metrics and args.show_metrics_summary:
            print("\n" + "=" * 60)
            print("Metrics Summary:")
            print(f"  Total messages: {metrics.messages_total.get()}")
            print(f"  Total tool calls: {metrics.tool_calls_total.get()}")
            print(f"  Total errors: {metrics.errors_total.get()}")
            print(f"  Messages/minute: {metrics.messages_per_minute:.1f}")
            print("=" * 60)

    return 0


def cmd_metrics(args) -> int:
    """Execute the metrics subcommand.

    Starts a Prometheus metrics server that watches sessions in the
    background and exposes metrics at /metrics.

    Args:
        args: Parsed CLI arguments

    Returns:
        Exit code (0 for success)
    """
    try:
        from .watcher import SessionWatcher, WatcherConfig
        from .metrics import MetricsCollector
        from .prometheus_server import PrometheusServer
    except ImportError as e:
        print(f"Error: Missing dependency - {e}", file=sys.stderr)
        print("Install with: pip install claude-sessions[realtime]", file=sys.stderr)
        return 1

    # Build configuration
    config_kwargs = {"poll_interval": args.poll_interval}
    if args.base_path:
        config_kwargs["base_path"] = args.base_path

    config = WatcherConfig(**config_kwargs)
    watcher = SessionWatcher(config)
    metrics = MetricsCollector()

    # Route events to metrics
    watcher.on_any(metrics.handle_event)

    # Start Prometheus server
    server = PrometheusServer(metrics, host=args.host, port=args.port)
    server.start()

    print("=" * 60)
    print(f"Prometheus metrics server running")
    print(f"  URL: {server.url}")
    print(f"  Health: http://{args.host}:{args.port}/health")
    print("Press Ctrl+C to stop")
    print("=" * 60)

    # Handle shutdown
    def shutdown(signum, frame):
        print("\nShutting down...")
        watcher.stop()
        server.stop()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Start watching (this blocks)
    try:
        watcher.start()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()

    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """Main entry point for CLI.

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:])

    Returns:
        Exit code
    """
    parser = create_parser()
    args = parser.parse_args(argv)

    # Configure logging based on verbosity
    if args.verbose >= 2:
        log_level = logging.DEBUG
    elif args.verbose >= 1:
        log_level = logging.INFO
    else:
        log_level = logging.WARNING

    logging.basicConfig(
        level=log_level,
        format="%(levelname)s: %(message)s",
    )

    # Dispatch to subcommand
    if args.command == "watch":
        return cmd_watch(args)
    elif args.command == "metrics":
        return cmd_metrics(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
