"""BetterMarkItDown as a Model Context Protocol server, for AI agents: `bettermarkitdown mcp`.

Standard library only, over stdio: one JSON-RPC message per line in, one per line out
(https://modelcontextprotocol.io/specification). It offers the same steps as the command
line and the setup page, as tools. A document is either a file on disk (`path`, with the
command line's default output and work dir) or one in the setup page's library
(`document_id`), which the person can then review and edit in `bettermarkitdown app`.

Conversions run in the background, one at a time: `convert` returns a job id at once, and
`job_status` follows it. Nothing but protocol messages goes to stdout; anything a library
prints there is sent to stderr instead.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import sys
import threading
from dataclasses import asdict
from pathlib import Path

from . import __version__, formats, library, runs, settings

PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
FIX = "The person can run `bettermarkitdown app`, or `bettermarkitdown key set PROVIDER`."

INSTRUCTIONS = (
    "Converts PDF, Word and PowerPoint files to Markdown, reading scanned pages, equations "
    "and figures with a vision model. Start with setup_status, then inspect (free) and tell "
    "the person the estimate before converting; pass budget_usd for online services. After "
    "a conversion, run verify and look at the flagged pages before reporting success. Never "
    "ask the person for an API key in the conversation.")


def _schema(properties: dict, required: tuple[str, ...] = ()) -> dict:
    return {"type": "object", "properties": properties, "required": list(required),
            "additionalProperties": False}


DOC = {
    "path": {"type": "string", "description": "The file on disk: PDF, DOCX, PPTX, DOC or PPT."},
    "document_id": {"type": "string", "description": "A document in the setup page's library, "
                                                     "instead of path."},
    "output": {"type": "string", "description": "The .md to write; default: next to the file."},
    "work_dir": {"type": "string", "description": "Per-page files and cache; default: "
                                                  "OUTPUT_work. Use a local disk when the "
                                                  "output is in a synced folder."},
}
PAGES = {"type": "string", "description": "1-based pages, e.g. '5', '10-40', '1,5,9-12'; "
                                          "default: all."}
TOOLS = [
    {"name": "setup_status",
     "description": "Which AI service and model a conversion would use, and whether it is "
                    "ready (a key saved, a model chosen). Free.",
     "inputSchema": _schema({})},
    {"name": "inspect",
     "description": "A free look at a file: pages, scanned pages, pages with equations set "
                    "as pictures, figures, chapters, and an estimate of requests, cost (US "
                    "dollars, list price) and time for converting it.",
     "inputSchema": _schema({"path": DOC["path"], "pages": PAGES,
                             "every_page": {"type": "boolean", "description":
                                            "Estimate for reading every page whole."}},
                            ("path",))},
    {"name": "toc",
     "description": "A PDF's outline (chapters and sections) with each entry's page range, "
                    "for choosing pages. Free.",
     "inputSchema": _schema({"path": DOC["path"]}, ("path",))},
    {"name": "convert",
     "description": "Start converting in the background; returns a job_id at once. Follow "
                    "it with job_status. Pages already converted are kept and skipped, so "
                    "calling it again continues a stopped run. Costs money with an online "
                    "service: ask the person first and pass budget_usd.",
     "inputSchema": _schema({
         **DOC, "pages": PAGES,
         "every_page": {"type": "boolean", "description": "Read every page whole with the "
                        "AI: best for maths, which a PDF's text layer often garbles."},
         "budget_usd": {"type": "number", "description": "Stop cleanly once this much has "
                        "been spent; finished pages are kept."},
         "text_only": {"type": "boolean", "description": "No AI at all: free; scanned pages "
                       "and pictures come out empty."},
         "as_pages": {"type": "boolean", "description": "Word / PowerPoint: go through a PDF "
                      "(needs Microsoft Office or LibreOffice), page by page."},
         "library": {"type": "boolean", "description": "With path: add the file to the setup "
                     "page's library and convert it there, so the person can review it in "
                     "bettermarkitdown app."}})},
    {"name": "job_status",
     "description": "A conversion's progress: pages done of total, the pages being read, "
                    "money spent, seconds left; and its result once status is done. "
                    "wait_seconds (up to 60) waits for the job to end before answering, "
                    "instead of polling.",
     "inputSchema": _schema({"job_id": {"type": "string"},
                             "wait_seconds": {"type": "number", "minimum": 0, "maximum": 60}},
                            ("job_id",))},
    {"name": "stop",
     "description": "Stop a conversion after the pages being read. Finished pages are kept.",
     "inputSchema": _schema({"job_id": {"type": "string"}}, ("job_id",))},
    {"name": "verify",
     "description": "Free, offline check of converted pages against the PDF's own text: per "
                    "page, words or numbers that differ, local-OCR pages, cut-off pages, "
                    "broken maths and markup faults. Not every flag is an error.",
     "inputSchema": _schema({**DOC, "pages": PAGES})},
    {"name": "get_page",
     "description": "One converted page's Markdown (page 0: the whole file, for Word and "
                    "PowerPoint read directly).",
     "inputSchema": _schema({**DOC, "page": {"type": "integer", "minimum": 0}}, ("page",))},
    {"name": "set_page",
     "description": "Replace one page's Markdown, put it back into the output, and check it "
                    "again. Keep the page's '## Page N' heading.",
     "inputSchema": _schema({**DOC, "page": {"type": "integer", "minimum": 0},
                             "markdown": {"type": "string"}}, ("page", "markdown"))},
    {"name": "library_list",
     "description": "The documents in the setup page's library, with what has been done to "
                    "each.",
     "inputSchema": _schema({})},
    {"name": "library_add",
     "description": "Copy a file into the setup page's library (nothing is converted or "
                    "sent anywhere). Returns its document_id.",
     "inputSchema": _schema({"path": DOC["path"]}, ("path",))},
]


class ToolError(Exception):
    """A tool's failure, reported to the agent as text (isError), not as a protocol error."""


class Server:
    def __init__(self):
        from .app.server import Jobs
        self.jobs = Jobs()           # the workspace's handlers take an object with .jobs
        self.out = sys.stdout
        self.lock = threading.Lock()

    # --- protocol -----------------------------------------------------------------------
    def send(self, message: dict) -> None:
        with self.lock:
            self.out.write(json.dumps(message, default=str) + "\n")
            self.out.flush()

    def handle(self, message: dict) -> dict | None:
        method, msg_id = message.get("method"), message.get("id")
        if msg_id is None:                   # a notification: nothing to answer
            return None
        try:
            if method == "initialize":
                asked = (message.get("params") or {}).get("protocolVersion")
                result = {
                    "protocolVersion": asked if asked in PROTOCOL_VERSIONS
                    else PROTOCOL_VERSIONS[0],
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "bettermarkitdown", "version": __version__},
                    "instructions": INSTRUCTIONS}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                params = message.get("params") or {}
                result = self.call(params.get("name", ""), params.get("arguments") or {})
            else:
                return {"jsonrpc": "2.0", "id": msg_id,
                        "error": {"code": -32601, "message": f"Unknown method: {method}"}}
        except Exception as exc:             # a bug here must not end the session
            return {"jsonrpc": "2.0", "id": msg_id,
                    "error": {"code": -32603, "message": f"{type(exc).__name__}: {exc}"}}
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def call(self, name: str, args: dict) -> dict:
        tool = getattr(self, f"tool_{name}", None)
        if tool is None or name not in {t["name"] for t in TOOLS}:
            return _text(f"Unknown tool: {name}", error=True)
        try:
            return _text(tool(args))
        except (ToolError, ValueError, library.LibraryError, formats.ConverterMissing) as exc:
            return _text(str(exc), error=True)
        except Exception as exc:
            from .app.server import HTTPError
            if isinstance(exc, HTTPError):
                return _text(str(exc), error=True)
            raise

    def serve(self, stdin=None) -> None:
        for line in stdin or sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                self.send({"jsonrpc": "2.0", "id": None,
                           "error": {"code": -32700, "message": "Not valid JSON."}})
                continue
            reply = self.handle(message) if isinstance(message, dict) else None
            if reply is not None:
                self.send(reply)

    # --- tools ------------------------------------------------------------------------
    def tool_setup_status(self, _args) -> dict:
        saved = asdict(settings.load())
        saved.pop("speed", None)
        return {"engine": runs.engine(fix=FIX), "settings": saved}

    def tool_inspect(self, args) -> dict:
        return runs.inspect_file(_file(args), args.get("pages") or None,
                                 bool(args.get("every_page")), fix=FIX)

    def tool_toc(self, args) -> dict:
        import pymupdf

        from .core import outline_ranges
        path = _file(args)
        if path.suffix.lower() != ".pdf":
            raise ToolError("Only a PDF has an outline.")
        with pymupdf.open(path) as doc:
            entries = outline_ranges(doc)
        return {"entries": [{"level": lvl, "title": t, "first": a, "last": b}
                            for lvl, t, a, b in entries]}

    def tool_convert(self, args) -> dict:
        from .app import workspace
        from .app.server import job_json

        body = {"pages": args.get("pages") or "", "whole_pages": bool(args.get("every_page")),
                "budget_usd": args.get("budget_usd") or 0,
                "text_only": bool(args.get("text_only")), "as_pages": bool(args.get("as_pages"))}
        if args.get("document_id") or args.get("library"):
            doc = (library.get(args["document_id"]) if args.get("document_id")
                   else library.add_file(_file(args)))
            job = workspace.convert(self, {**body, "id": doc.id})
            return {**job, "document_id": doc.id, "output": str(doc.output())}
        return job_json(self._convert_path(args, body))

    def _convert_path(self, args, body):
        if self.jobs.running("convert"):
            raise ToolError("Another conversion is running. Wait for it, or stop it.")
        source, output, work_dir = _paths(args)
        plan = runs.plan(body["text_only"], fix=FIX)
        try:
            budget = max(0.0, float(body["budget_usd"]))
        except (TypeError, ValueError):
            raise ToolError("budget_usd must be a number of dollars.") from None

        def work(job):
            opts = runs.options(plan, source=source, output=output, work_dir=work_dir,
                                pages=body["pages"] or None, whole_pages=body["whole_pages"],
                                budget_usd=budget, say=lambda m: setattr(job, "message", m))
            run = formats.runner_for(opts, body["as_pages"],
                                     log=lambda line: setattr(job, "message", line.strip()))
            pictures = source.suffix.lower() != ".pdf" and not body["as_pages"]
            progress = runs.Progress(job, plan.prior_seconds, "picture" if pictures else "page")
            job.message = ""
            result = run(opts, progress.event, abort=job.abort)
            return {**runs.summary(result, plan, progress, aborted=job.abort.is_set(),
                                   whole_pages=body["whole_pages"], trial=False),
                    "output": str(result.output), "work_dir": str(opts.resolved_work_dir())}

        job = self.jobs.start("convert", work)
        job.info.update(path=str(source), output=str(output))
        return job

    def tool_job_status(self, args) -> dict:
        import time

        from .app.server import job_json
        job = self.jobs.get(str(args.get("job_id", "")))
        if not job:
            raise ToolError("No such job in this session.")
        try:
            wait = min(60.0, max(0.0, float(args.get("wait_seconds") or 0)))
        except (TypeError, ValueError):
            wait = 0.0
        deadline = time.monotonic() + wait
        while job.status == "running" and time.monotonic() < deadline:
            time.sleep(0.25)
        return job_json(job)

    def tool_stop(self, args) -> dict:
        from .app.server import job_json
        job = self.jobs.get(str(args.get("job_id", "")))
        if not job or job.kind != "convert":
            raise ToolError("No such conversion in this session.")
        job.abort.set()
        job.info["stopping"] = True
        job.message = "Stopping after the pages being read. Finished pages are kept."
        return job_json(job)

    def tool_verify(self, args) -> dict:
        from .core import parse_pages
        from .verify import add_render_check, page_notes, verify

        if args.get("document_id"):
            doc = library.get(args["document_id"])
            pdf = doc.page_pdf()
            if pdf is None:
                raise ToolError("This document has no pages to check (a Word or PowerPoint "
                                "file read directly).")
            chosen = [i + 1 for i in parse_pages(args.get("pages"), doc.pages or
                                                 doc.inspection.get("pages", 0))] \
                if args.get("pages") else None
            library.check_pages(doc, pdf, chosen)
            doc.save()
            return {"document_id": doc.id, "flagged": sorted(int(p) for p in doc.checks),
                    "pages": doc.checks}
        source, _output, work_dir = _paths(args)
        if source.suffix.lower() != ".pdf":
            raise ToolError("verify reads a PDF: convert with as_pages, then check that PDF.")
        if not (work_dir / "pages").is_dir():
            raise ToolError(f"No converted pages in {work_dir}.")
        import pymupdf
        with pymupdf.open(source) as d:
            total = d.page_count
        results = verify(source, work_dir, parse_pages(args.get("pages"), total))
        render = add_render_check(results, work_dir)
        return {"flagged": [r.page for r in results if r.flagged],
                "no_text_layer": [r.page for r in results if r.status == "no-text-layer"],
                "not_converted": [r.page for r in results if r.status == "no-page-file"],
                "render_check": render,
                "pages": {str(r.page): page_notes(r) for r in results if page_notes(r)}}

    def tool_get_page(self, args) -> dict:
        page = int(args.get("page", 0))
        if args.get("document_id"):
            from .app import workspace
            return workspace.page_get(self, {"id": args["document_id"], "page": page})
        path = self._page_path(args, page)
        if not path.is_file():
            raise ToolError(f"Page {page} has not been converted yet.")
        return {"page": page, "markdown": path.read_text(encoding="utf-8")}

    def tool_set_page(self, args) -> dict:
        page, markdown = int(args.get("page", 0)), args.get("markdown")
        if not isinstance(markdown, str):
            raise ToolError("markdown must be text.")
        if args.get("document_id"):
            from .app import workspace
            return workspace.page_save(self, {"id": args["document_id"], "page": page,
                                              "markdown": markdown})
        if self.jobs.running("convert"):
            raise ToolError("A conversion is running; save once it has finished.")
        source, output, work_dir = _paths(args)
        path = self._page_path(args, page)
        if not path.is_file():
            raise ToolError(f"Page {page} has not been converted yet.")
        path.write_text(markdown.replace("\r\n", "\n"), encoding="utf-8", newline="\n")
        if page == 0:
            return {"saved": True}
        from .core import assemble_output
        title, model = _header(output, source)
        assemble_output(output, work_dir / "pages", title=title, source_name=source.name,
                        model=model)
        notes: list[str] = []
        if source.suffix.lower() == ".pdf":
            from .verify import page_notes, verify
            notes = page_notes(verify(source, work_dir, [page - 1])[0])
        return {"saved": True, "output": str(output), "notes": notes}

    def _page_path(self, args, page: int) -> Path:
        _source, output, work_dir = _paths(args)
        return output if page == 0 else work_dir / "pages" / f"{page:04d}.md"

    def tool_library_list(self, _args) -> dict:
        from .app import workspace
        return workspace.library_list(self, {})

    def tool_library_add(self, args) -> dict:
        from .app import workspace
        doc = library.add_file(_file(args))
        return workspace.document(self, {"id": doc.id})


def _text(payload, error: bool = False) -> dict:
    if isinstance(payload, str):
        return {"content": [{"type": "text", "text": payload}], "isError": error}
    return {"content": [{"type": "text", "text": json.dumps(payload, default=str)}],
            "structuredContent": json.loads(json.dumps(payload, default=str)), "isError": error}


def _file(args) -> Path:
    raw = args.get("path")
    if not raw:
        raise ToolError("Give path (a file on disk) or document_id.")
    path = Path(str(raw)).expanduser().resolve()
    if not path.is_file():
        raise ToolError(f"Not found: {path}")
    if path.suffix.lower() not in formats.SUPPORTED:
        raise ToolError(f"Cannot read {path.suffix or 'files without an extension'}. It reads "
                        f"{', '.join(sorted(formats.SUPPORTED))}.")
    return path


def _paths(args) -> tuple[Path, Path, Path]:
    """(source, output, work dir), with the command line's defaults."""
    source = _file(args)
    output = (Path(args["output"]).expanduser().resolve() if args.get("output")
              else source.with_suffix(".md"))
    work_dir = (Path(args["work_dir"]).expanduser().resolve() if args.get("work_dir")
                else output.parent / (output.stem + "_work"))
    return source, output, work_dir


def _header(output: Path, source: Path) -> tuple[str, str]:
    """The title and model in an existing output's header, to keep them on a rebuild."""
    try:
        head = output.read_text(encoding="utf-8")[:2000]
    except OSError:
        head = ""
    title = re.search(r"^# (.+)$", head, re.M)
    model = re.search(r"with BetterMarkItDown \(([^)]*)\)", head)
    return (title.group(1).strip() if title else source.stem,
            model.group(1) if model else "edited")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bettermarkitdown mcp",
        description="A Model Context Protocol server over stdio, for AI agents. Register it "
                    "with your agent (bettermarkitdown agent mcp shows how); it is not run "
                    "by hand.")
    parser.parse_args(sys.argv[2:] if argv is None else argv)
    server = Server()
    # Only protocol messages may reach stdout: send anything else to stderr.
    sys.stdout = sys.stderr
    with contextlib.suppress(KeyboardInterrupt):
        server.serve()
    return 0
