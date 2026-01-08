"""HTTP server for Prometheus metrics scraping.

This module provides a simple HTTP server that exposes MetricsCollector
metrics in Prometheus text format at the /metrics endpoint.

Example usage:
    from claude_sessions.realtime import MetricsCollector
    from claude_sessions.realtime.prometheus_server import PrometheusServer

    metrics = MetricsCollector()
    server = PrometheusServer(metrics, port=9090)
    server.start()

    # Metrics available at http://localhost:9090/metrics
    # curl http://localhost:9090/metrics

    server.stop()

The server can also be used as a context manager:
    with PrometheusServer(metrics, port=9090) as server:
        print(f"Metrics at {server.url}")
        # ... do work ...
"""

import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional, Type

from .metrics import MetricsCollector

logger = logging.getLogger(__name__)


class MetricsHandler(BaseHTTPRequestHandler):
    """HTTP request handler for Prometheus metrics.

    Serves:
        GET /metrics - Prometheus text format metrics
        GET /health  - Health check endpoint
        GET /        - Index page with links
    """

    # Set at class level by PrometheusServer
    metrics_collector: Optional[MetricsCollector] = None

    def do_GET(self) -> None:
        """Handle GET requests."""
        if self.path == "/metrics":
            self._serve_metrics()
        elif self.path == "/health":
            self._serve_health()
        elif self.path == "/":
            self._serve_index()
        else:
            self.send_error(404, "Not Found")

    def _serve_metrics(self) -> None:
        """Serve Prometheus metrics."""
        if self.metrics_collector is None:
            self.send_error(503, "Metrics not available")
            return

        try:
            content = self.metrics_collector.to_prometheus_text()
        except Exception as e:
            logger.exception("Error generating metrics")
            self.send_error(500, f"Error generating metrics: {e}")
            return

        content_bytes = content.encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(content_bytes)))
        self.end_headers()
        self.wfile.write(content_bytes)

    def _serve_health(self) -> None:
        """Serve health check endpoint."""
        content = '{"status": "ok"}'
        content_bytes = content.encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content_bytes)))
        self.end_headers()
        self.wfile.write(content_bytes)

    def _serve_index(self) -> None:
        """Serve index page with links."""
        content = """<!DOCTYPE html>
<html>
<head>
    <title>Claude Sessions Metrics</title>
    <style>
        body { font-family: sans-serif; margin: 40px; }
        a { color: #0066cc; }
        ul { list-style-type: none; padding: 0; }
        li { margin: 10px 0; }
    </style>
</head>
<body>
    <h1>Claude Sessions Metrics</h1>
    <p>Prometheus metrics for Claude Code session monitoring.</p>
    <ul>
        <li><a href="/metrics">/metrics</a> - Prometheus metrics endpoint</li>
        <li><a href="/health">/health</a> - Health check</li>
    </ul>
</body>
</html>"""

        content_bytes = content.encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content_bytes)))
        self.end_headers()
        self.wfile.write(content_bytes)

    def log_message(self, format: str, *args) -> None:
        """Override to use Python logging instead of stderr."""
        logger.debug("%s - %s", self.address_string(), format % args)


class PrometheusServer:
    """HTTP server for Prometheus metrics.

    Exposes metrics collected by MetricsCollector at the /metrics endpoint
    in Prometheus text format. Runs in a background thread.

    Attributes:
        url: URL of the metrics endpoint

    Example:
        metrics = MetricsCollector()
        server = PrometheusServer(metrics, port=9090)
        server.start()

        # Metrics available at http://localhost:9090/metrics
        print(f"Scrape from: {server.url}")

        # ... run your application ...

        server.stop()

    As context manager:
        with PrometheusServer(metrics) as server:
            print(server.url)
            # ... do work ...
    """

    def __init__(
        self,
        metrics: MetricsCollector,
        host: str = "127.0.0.1",
        port: int = 9090,
    ):
        """Initialize the Prometheus server.

        Args:
            metrics: MetricsCollector to expose
            host: Address to bind to (default: localhost only)
            port: Port to listen on (default: 9090)
        """
        self._metrics = metrics
        self._host = host
        self._port = port
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def url(self) -> str:
        """URL for the metrics endpoint."""
        return f"http://{self._host}:{self._port}/metrics"

    def start(self) -> None:
        """Start the HTTP server in a background thread.

        The server runs as a daemon thread, so it will be automatically
        terminated when the main program exits. Call stop() for graceful
        shutdown.
        """
        if self._server is not None:
            logger.warning("Server already running")
            return

        # Create handler class with metrics reference
        # We create a new class to avoid sharing state between server instances
        handler_class: Type[MetricsHandler] = type(
            "MetricsHandlerWithCollector",
            (MetricsHandler,),
            {"metrics_collector": self._metrics},
        )

        try:
            self._server = HTTPServer((self._host, self._port), handler_class)
        except OSError as e:
            logger.error("Failed to start server on %s:%d - %s", self._host, self._port, e)
            raise

        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="prometheus-metrics-server",
            daemon=True,
        )
        self._thread.start()

        logger.info(
            "Prometheus metrics server started on %s:%d",
            self._host,
            self._port,
        )

    def stop(self) -> None:
        """Stop the HTTP server gracefully.

        Shuts down the server and waits for the background thread to finish.
        Safe to call multiple times.
        """
        if self._server is None:
            return

        logger.debug("Shutting down metrics server")
        self._server.shutdown()
        self._server.server_close()
        self._server = None

        if self._thread is not None:
            self._thread.join(timeout=5.0)
            if self._thread.is_alive():
                logger.warning("Server thread did not terminate cleanly")
            self._thread = None

        logger.info("Prometheus metrics server stopped")

    def __enter__(self) -> "PrometheusServer":
        """Context manager entry - starts the server."""
        self.start()
        return self

    def __exit__(self, *args) -> None:
        """Context manager exit - stops the server."""
        self.stop()
