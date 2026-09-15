"""Local read-only audit API. No tool dispatch or approval endpoints."""
import argparse
import json
import os
import stat
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .redaction import redact


def read_events(path, verdict="", action=""):
    # Read a bounded tail; a partial first/last line is skipped.
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return []
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("Audit file is not a regular file")
        start = max(0, info.st_size - 2_000_000)
        stream.seek(start)
        data = stream.read(2_000_000)
    lines = data.splitlines()
    if start and lines:
        lines = lines[1:]
    events = []
    for line in lines:
        try:
            event = json.loads(line)
            if type(event) is not dict:
                continue
            decision = event.get("decision") or {}
            if verdict and decision.get("verdict") != verdict:
                continue
            if action and event.get("action", decision.get("action")) != action:
                continue
            events.append(redact(event))
        except (ValueError, TypeError, AttributeError):
            continue
    return events[-500:][::-1]


def make_handler(path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            # Protect against browser DNS rebinding; no permissive CORS headers.
            expected_host = f"127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host") != expected_host or self.headers.get("Origin") is not None:
                self.send_error(403)
                return
            p = urlsplit(self.path)
            if p.path != "/events":
                self.send_error(404)
                return
            query = parse_qs(p.query)
            try:
                data = read_events(path, query.get("verdict", [""])[0], query.get("action", [""])[0])
                body = json.dumps({"events": data, "limit": 500, "read_only": True}).encode()
            except Exception:
                self.send_error(500, "Audit read failed")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass  # Do not echo untrusted URLs into terminal logs.

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, default=Path(".webcloner/events.jsonl"))
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    path = args.audit.absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        parser.error("Audit path must not contain symlinks")
    server = HTTPServer(("127.0.0.1", args.port), make_handler(path))
    print(f"Read-only audit API: http://127.0.0.1:{args.port}/events")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
