"""The setup page's local server: standard library only.

Safety, since this page can save keys, install programs and spend money:
- it listens on 127.0.0.1 only, so no other computer can reach it;
- every API call needs the token printed in the address this process opens,
  sent back as an X-BMID-Token header (a custom header, so another website
  cannot forge the request from someone's browser);
- the Host header must be this address (blocks DNS-rebinding tricks), and a
  POST from any other Origin is refused;
- keys go into the password store and only ever come back redacted;
- only the files in static/ are served, with a Content-Security-Policy that
  allows nothing from elsewhere.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
import traceback
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

STATIC = Path(__file__).with_name("static")
FILES = {"/": ("index.html", "text/html"), "/app.css": ("app.css", "text/css"),
         "/app.js": ("app.js", "text/javascript")}
CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")


@dataclass
class Job:
    """A slow task (install, download, speed test) the page follows by polling."""
    id: str
    kind: str
    status: str = "running"           # running | done | failed
    message: str = ""
    done: int = 0
    total: int = 0
    result: dict = field(default_factory=dict)
    error: str = ""


class Jobs:
    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, kind: str, work: Callable[[Job], dict | None]) -> Job:
        """Run `work(job)` in the background; one job of each kind at a time."""
        with self._lock:
            for job in self._jobs.values():
                if job.kind == kind and job.status == "running":
                    return job
            job = Job(id=uuid.uuid4().hex[:12], kind=kind)
            self._jobs[job.id] = job

        def run():
            try:
                job.result = work(job) or {}
                job.status = "done"
            except Exception as exc:
                job.error = str(exc) or type(exc).__name__
                job.status = "failed"

        threading.Thread(target=run, daemon=True, name=f"job-{kind}").start()
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def busy(self) -> bool:
        return any(j.status == "running" for j in self._jobs.values())


class HTTPError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class App:
    def __init__(self, port: int = 0):
        from .api import ROUTES

        self.token = secrets.token_urlsafe(24)
        self.jobs = Jobs()
        self.routes = ROUTES
        self.last_seen = time.monotonic()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), _handler_for(self))
        self.port = self.httpd.server_address[1]

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/?t={self.token}"

    def allowed_hosts(self) -> set[str]:
        return {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}

    def serve(self, idle_minutes: float = 15.0) -> None:
        """Serve until Quit is pressed, or the page has been closed for a while and no
        job is running."""
        def watch():
            while True:
                time.sleep(15)
                idle = time.monotonic() - self.last_seen
                if idle > idle_minutes * 60 and not self.jobs.busy():
                    self.stop()
                    return

        if idle_minutes:
            threading.Thread(target=watch, daemon=True).start()
        self.httpd.serve_forever(poll_interval=0.5)

    def stop(self) -> None:
        threading.Thread(target=self.httpd.shutdown, daemon=True).start()


def _handler_for(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "BetterMarkItDown"
        sys_version = ""

        def log_message(self, *_args):        # quiet: the page shows what matters
            pass

        # -- plumbing ------------------------------------------------------------------
        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", CSP)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: dict) -> None:
            self._send(status, json.dumps(payload).encode(), "application/json")

        def _check(self, method: str) -> None:
            if self.headers.get("Host", "") not in app.allowed_hosts():
                raise HTTPError(403, "Unexpected address.")
            if method == "POST":
                origin = self.headers.get("Origin")
                if origin and origin not in {f"http://{h}" for h in app.allowed_hosts()}:
                    raise HTTPError(403, "Requests from other sites are refused.")

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length > 1_000_000:
                raise HTTPError(413, "Too large.")
            if not length:
                return {}
            if "application/json" not in self.headers.get("Content-Type", ""):
                raise HTTPError(415, "JSON only.")
            try:
                data = json.loads(self.rfile.read(length))
            except ValueError:
                raise HTTPError(400, "Not valid JSON.") from None
            if not isinstance(data, dict):
                raise HTTPError(400, "Expected a JSON object.")
            return data

        def _handle(self, method: str) -> None:
            try:
                self._check(method)
                parsed = urlparse(self.path)
                if method == "GET" and parsed.path in FILES:
                    return self._static(parsed)
                if not parsed.path.startswith("/api/"):
                    raise HTTPError(404, "Not found.")
                if not secrets.compare_digest(self.headers.get("X-BMID-Token", ""), app.token):
                    raise HTTPError(403, "Open this page from BetterMarkItDown itself.")
                app.last_seen = time.monotonic()
                route, arg = parsed.path, None
                if route.startswith("/api/jobs/"):
                    route, arg = "/api/jobs/", route.removeprefix("/api/jobs/")
                handler = app.routes.get((method, route))
                if handler is None:
                    raise HTTPError(404, "Not found.")
                query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
                body = self._body() if method == "POST" else query
                if arg is not None:
                    body["id"] = arg
                self._json(200, handler(app, body))
            except HTTPError as exc:
                self._json(exc.status, {"error": str(exc)})
            except ValueError as exc:            # a bad choice sent by the page
                self._json(400, {"error": str(exc)})
            except Exception as exc:
                traceback.print_exc()
                self._json(500, {"error": f"Something went wrong: {exc}"})

        def _static(self, parsed) -> None:
            if parsed.path == "/" and not secrets.compare_digest(
                    parse_qs(parsed.query).get("t", [""])[0], app.token):
                self._send(403, b"<p>Open BetterMarkItDown from its icon, or run "
                                b"<code>bettermarkitdown app</code>.</p>", "text/html")
                return
            name, kind = FILES[parsed.path]
            body = (STATIC / name).read_bytes()
            if name == "index.html":
                body = body.replace(b"__TOKEN__", app.token.encode())
            self._send(200, body, kind)

        def do_GET(self):  # noqa: N802 - the http.server API
            self._handle("GET")

        def do_POST(self):  # noqa: N802
            self._handle("POST")

    return Handler


def job_json(job: Job) -> dict:
    return asdict(job)
