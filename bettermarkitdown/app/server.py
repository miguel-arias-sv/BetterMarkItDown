"""The setup page's local server: standard library only.

Safety, since this page can save keys, install programs and spend money:
- it listens on 127.0.0.1 only, so no other computer can reach it;
- every API call needs the token printed in the address this process opens,
  sent back as an X-BMID-Token header (a custom header, so another website
  cannot forge the request from someone's browser). Only GETs that the browser
  makes by itself (a page image, a download link) may carry it as ?t= instead,
  and those change nothing;
- the Host header must be this address (blocks DNS-rebinding tricks), and a
  POST from any other Origin is refused;
- keys go into the password store and only ever come back redacted;
- only the files in static/ are served, with a Content-Security-Policy that
  allows nothing from elsewhere. KaTeX sizes formulas with style attributes, so
  those are allowed; <style> elements and inline scripts are not.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, fields
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

STATIC = Path(__file__).with_name("static")
TYPES = {".html": "text/html", ".css": "text/css", ".js": "text/javascript",
         ".woff2": "font/woff2"}
# Every servable file, found once: "/" is the page, the rest by their path in static/.
FILES = {"/": "index.html"} | {
    "/" + p.relative_to(STATIC).as_posix(): p.relative_to(STATIC).as_posix()
    for p in sorted(STATIC.rglob("*")) if p.suffix in TYPES and p.name != "index.html"}
CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; "
       "style-src-attr 'unsafe-inline'; script-src 'self'; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
MAX_JSON = 16 * 1024 ** 2         # a long page of Markdown, saved from the editor
MAX_DRAIN = 64 * 1024 ** 2        # past this, a refused request's body is not read


class _Body:
    """The request body, counting what is left of it."""
    def __init__(self, rfile, length: int):
        self.rfile, self.left = rfile, length

    def read(self, n: int = -1) -> bytes:
        n = self.left if n < 0 else min(n, self.left)
        data = self.rfile.read(n) if n > 0 else b""
        self.left -= len(data)
        return data


@dataclass
class Job:
    """A slow task (install, download, speed test, conversion) the page follows by
    polling. The page cannot use server-sent events: EventSource sends no custom
    header, so it could not carry the token."""
    id: str
    kind: str
    status: str = "running"           # running | done | failed
    message: str = ""
    done: int = 0
    total: int = 0
    result: dict = field(default_factory=dict)
    error: str = ""
    info: dict = field(default_factory=dict)       # live details, e.g. a conversion's ETA
    abort: threading.Event = field(default_factory=threading.Event, repr=False)


class Jobs:
    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, kind: str, work: Callable[[Job], dict | None]) -> Job:
        """Run `work(job)` in the background; one job of each kind at a time."""
        with self._lock:
            running = self.running(kind)
            if running:
                return running
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

    def running(self, kind: str) -> Job | None:
        return next((j for j in self._jobs.values()
                     if j.kind == kind and j.status == "running"), None)

    def busy(self) -> bool:
        return any(j.status == "running" for j in self._jobs.values())


class HTTPError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@dataclass
class Response:
    """A handler's reply that is not JSON: a page image, a download."""
    body: bytes
    content_type: str
    filename: str = ""                 # set: the browser saves it instead of showing it


def route(raw_body: bool = False, token_in_query: bool = False):
    """Mark a handler: `raw_body` gets the request's bytes as a stream (a file being
    added) instead of JSON; `token_in_query` is a GET the browser makes by itself,
    from an <img> or a download link, which cannot send the token header."""
    def mark(handler):
        handler.raw_body = raw_body
        handler.token_in_query = token_in_query
        return handler
    return mark


class App:
    def __init__(self, port: int = 0):
        from .api import ROUTES
        from .workspace import ROUTES as WORKSPACE

        self.token = secrets.token_urlsafe(24)
        self.jobs = Jobs()
        self.routes = {**ROUTES, **WORKSPACE}
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
        stream: _Body | None = None

        def log_message(self, *_args):        # quiet: the page shows what matters
            pass

        # -- plumbing ------------------------------------------------------------------
        def _send(self, status: int, body: bytes, content_type: str,
                  filename: str = "") -> None:
            self._discard_body()
            self.send_response(status)
            text = content_type.startswith("text/") or content_type == "application/json"
            self.send_header("Content-Type", content_type + ("; charset=utf-8" if text else ""))
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", CSP)
            if filename:
                ascii_name = filename.encode("ascii", "replace").decode().replace('"', "'")
                self.send_header("Content-Disposition",
                                 f"attachment; filename=\"{ascii_name}\"; "
                                 f"filename*=UTF-8''{quote(filename, safe='')}")
            self.end_headers()
            self.wfile.write(body)

        def _discard_body(self) -> None:
            """Read what the request sent and nobody used, before answering. Windows
            resets a connection closed with unread bytes in it, and the client then
            sees a network error instead of this reply: a refused POST, say."""
            if self.stream is None or not self.stream.left:
                return
            if self.stream.left > MAX_DRAIN:
                self.close_connection = True
                return
            while self.stream.read(1 << 16):
                pass

        def _length(self) -> int:
            try:
                return max(0, int(self.headers.get("Content-Length") or 0))
            except ValueError:
                return 0

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
            length = self._length()
            if length > MAX_JSON:
                raise HTTPError(413, "Too large.")
            if not length:
                return {}
            if "application/json" not in self.headers.get("Content-Type", ""):
                raise HTTPError(415, "JSON only.")
            try:
                data = json.loads(self.stream.read(length))
            except ValueError:
                raise HTTPError(400, "Not valid JSON.") from None
            if not isinstance(data, dict):
                raise HTTPError(400, "Expected a JSON object.")
            return data

        def _upload(self) -> dict:
            if "application/octet-stream" not in self.headers.get("Content-Type", ""):
                raise HTTPError(415, "Send the file's bytes.")
            return {"stream": self.stream, "length": self._length(),
                    "filename": unquote(self.headers.get("X-BMID-Filename", ""))}

        def _handle(self, method: str) -> None:
            self.stream = _Body(self.rfile, self._length())
            try:
                self._check(method)
                parsed = urlparse(self.path)
                query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
                if method == "GET" and parsed.path in FILES:
                    return self._static(parsed.path, query)
                if not parsed.path.startswith("/api/"):
                    raise HTTPError(404, "Not found.")
                route, arg = parsed.path, None
                if route.startswith("/api/jobs/"):
                    route, arg = "/api/jobs/", route.removeprefix("/api/jobs/")
                handler = app.routes.get((method, route))
                sent = self.headers.get("X-BMID-Token", "")
                if not sent and handler and getattr(handler, "token_in_query", False):
                    sent = query.pop("t", "")
                if not secrets.compare_digest(sent, app.token):
                    raise HTTPError(403, "Open this page from BetterMarkItDown itself.")
                app.last_seen = time.monotonic()
                if handler is None:
                    raise HTTPError(404, "Not found.")
                if method == "GET":
                    body = query
                elif getattr(handler, "raw_body", False):
                    body = {**query, **self._upload()}
                else:
                    body = self._body()
                if arg is not None:
                    body["id"] = arg
                reply = handler(app, body)
                if isinstance(reply, Response):
                    self._send(200, reply.body, reply.content_type, reply.filename)
                else:
                    self._json(200, reply)
            except HTTPError as exc:
                self._json(exc.status, {"error": str(exc)})
            except ValueError as exc:            # a bad choice sent by the page
                self._json(400, {"error": str(exc)})
            except Exception as exc:
                traceback.print_exc()
                self._json(500, {"error": f"Something went wrong: {exc}"})

        def _static(self, path: str, query: dict) -> None:
            if path == "/" and not secrets.compare_digest(query.get("t", ""), app.token):
                self._send(403, b"<p>Open BetterMarkItDown from its icon, or run "
                                b"<code>bettermarkitdown app</code>.</p>", "text/html")
                return
            name = FILES[path]
            body = (STATIC / name).read_bytes()
            if name == "index.html":
                from .. import settings

                body = body.replace(b"__TOKEN__", app.token.encode())
                # The chosen colours from the first paint, not after the page asks.
                theme = settings.load().theme
                if theme in ("light", "dark"):
                    body = body.replace(b"<html ", f'<html data-theme="{theme}" '.encode(), 1)
            self._send(200, body, TYPES[Path(name).suffix])

        def do_GET(self):  # noqa: N802 - the http.server API
            self._handle("GET")

        def do_POST(self):  # noqa: N802
            self._handle("POST")

    return Handler


def job_json(job: Job) -> dict:
    return {f.name: getattr(job, f.name) for f in fields(job) if f.name != "abort"}
