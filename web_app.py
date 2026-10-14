"""Serve the network monitor as a small, standard-library web application."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
from urllib.parse import urlparse

from network_monitor import Monitor, NetworkChecker, NetworkLogger, SystemInfo


BASE_DIR = Path(__file__).resolve().parent
PAGE_PATH = BASE_DIR / "templates" / "index.html"
CHECKER = NetworkChecker()
LOGGER = NetworkLogger()
MONITOR = Monitor(CHECKER, LOGGER)
STATE_LOCK = threading.Lock()
CHECK_LOCK = threading.Lock()
LATEST_RESULT = None


def make_json_safe(result):
    """Convert a check result's datetime into text so JSON can encode it."""
    output = dict(result)
    output["timestamp"] = result["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
    return output


class MonitorRequestHandler(BaseHTTPRequestHandler):
    """Handle the web page and its small JSON API."""

    server_version = "NetworkMonitor/1.0"

    def do_GET(self):
        """Return the home page or one of the read-only dashboard APIs."""
        path = urlparse(self.path).path
        if path == "/":
            self._send_page()
        elif path == "/healthz":
            self._send_json({"ok": True})
        elif path == "/api/system-info":
            information = SystemInfo.collect()
            information["mac_address"] = "Not exposed by the hosted demo"
            self._send_json({"system": information})
        elif path == "/api/logs":
            entries, error = LOGGER.get_last_entries(10)
            self._send_json({"entries": [entry.rstrip() for entry in entries], "error": error})
        elif path == "/api/status":
            with STATE_LOCK:
                result = make_json_safe(LATEST_RESULT) if LATEST_RESULT else None
                summary = MONITOR.summary()
            self._send_json({"result": result, "summary": summary})
        else:
            self._send_json({"error": "Not found"}, status=404)

    def do_POST(self):
        """Run a connectivity check when the browser asks for one."""
        if urlparse(self.path).path != "/api/check":
            self._send_json({"error": "Not found"}, status=404)
            return
        if not CHECK_LOCK.acquire(blocking=False):
            self._send_json(
                {"error": "A network check is already running. Try again shortly."},
                status=429,
            )
            return

        try:
            result = CHECKER.run_all_checks()
            log_error = LOGGER.log_result(result)
            with STATE_LOCK:
                global LATEST_RESULT
                LATEST_RESULT = result
                MONITOR.record_result(result)
                summary = MONITOR.summary()
            self._send_json(
                {
                    "result": make_json_safe(result),
                    "summary": summary,
                    "log_error": log_error,
                }
            )
        except Exception as error:
            self._send_json(
                {"error": "The network check failed: {}".format(error)},
                status=500,
            )
        finally:
            CHECK_LOCK.release()

    def _send_page(self):
        """Read and return the browser dashboard HTML."""
        try:
            page = PAGE_PATH.read_bytes()
        except OSError as error:
            self._send_json(
                {"error": "Could not load dashboard page: {}".format(error)},
                status=500,
            )
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(page)

    def _send_json(self, payload, status=200):
        """Serialize a response and send it with the correct JSON headers."""
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format_string, *args):
        """Keep routine browser requests out of the hosting service logs."""
        return


def create_server(host="127.0.0.1", port=8000):
    """Create a threaded HTTP server for local runs and automated checks."""
    return ThreadingHTTPServer((host, port), MonitorRequestHandler)


def main():
    """Start the web server on the port supplied by the cloud host or local user."""
    port = int(os.environ.get("PORT", "8000"))
    server = create_server(host="0.0.0.0", port=port)
    print("Network Monitor web app listening on port {}".format(port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping the web server.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
