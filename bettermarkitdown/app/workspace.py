"""The workspace on the setup page: add files, convert them, check and edit the
result page by page, and take it away. Each handler takes the app and the
request's JSON (or query) and returns JSON, or a Response for images and files."""

from __future__ import annotations

import io
import os
import subprocess
import sys
import zipfile
from dataclasses import asdict
from pathlib import Path
from urllib.parse import unquote

from .. import formats, library, ocr, runs, verify
from ..core import assemble_output, parse_pages
from .server import HTTPError, Response, job_json, route

IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".gif": "image/gif", ".webp": "image/webp"}
PAGE_DPI = 110                     # sharp enough to read beside the editor
TRY_PAGES = 3                      # "convert a few pages first, to measure the cost"
FIX = "Add one in Settings."


def _doc(body) -> library.Document:
    return library.get(str(body.get("id", "")))


def _page(body) -> int:
    try:
        return int(body.get("page", ""))
    except ValueError:
        raise ValueError("No such page.") from None


def _page_file(doc: library.Document, page: int) -> Path:
    return doc.work_dir() / "pages" / f"{page:04d}.md"


def _page_count(doc: library.Document) -> int:
    if doc.kind == ".pdf":
        return doc.pages
    return doc.inspection.get("pages", 0) if doc.as_pages else 0


def _summary(doc: library.Document) -> dict:
    """A document as the page shows it, with what has been done to it so far."""
    converted = library.converted(doc)
    return {**asdict(doc), "paged": doc.paged(), "page_count": _page_count(doc),
            "converted": converted, "output": str(doc.output()),
            "output_ready": doc.output().is_file(),
            "flagged": sorted(int(p) for p in doc.checks)}


# --- what a run would use --------------------------------------------------------------

def _engine() -> dict:
    return runs.engine(fix=FIX)


def _selection(doc: library.Document, pages: str | None) -> list[int] | None:
    """The chosen pages, 1-based; None for all of them. A bad range is the person's
    to fix, so it comes back as a plain message."""
    total = _page_count(doc)
    if not pages or not total:
        return None
    try:
        chosen = [i + 1 for i in parse_pages(pages, total)]
    except ValueError:
        raise ValueError(f"Pages: use numbers and ranges such as 1-20 or 3,5,9-12 "
                         f"(this file has {total}).") from None
    if not chosen:
        raise ValueError(f"No pages in that range: this file has {total}.")
    return chosen


def _calls(doc: library.Document, chosen: list[int] | None,
           whole_pages: bool = False) -> int | None:
    if doc.paged() and doc.inspection.get("pages"):
        if whole_pages:
            return len(chosen) if chosen is not None else doc.inspection["pages"]
        return library.vision_calls(doc.inspection, chosen)
    return doc.inspection.get("pictures")          # Word / PowerPoint: one per picture


def estimate(app, body) -> dict:
    """What converting would take. Pages already converted are skipped by a run, so
    they are left out here too."""
    doc = _doc(body)
    chosen = _selection(doc, str(body.get("pages") or "").strip() or None)
    engine = _engine()
    total = _page_count(doc)
    done = set(library.converted(doc))
    if total:
        todo = [p for p in (chosen or range(1, total + 1)) if p not in done]
        already = (len(chosen) if chosen else total) - len(todo)
    else:
        todo, already = None, 0
    calls = 0 if body.get("text_only") else _calls(doc, todo, bool(body.get("whole_pages")))
    out = {"calls": calls, "pages": len(todo) if todo is not None else 0, "already": already,
           "cost": None, "seconds": None}
    if calls is not None and engine.get("per_call") is not None:
        out["cost"] = round(calls * engine["per_call"], 4)
    if calls is not None and engine.get("seconds_per_call"):
        out["seconds"] = round(calls * engine["seconds_per_call"])
    return out


# --- the library ---------------------------------------------------------------------

def library_list(app, _body) -> dict:
    running = app.jobs.running("convert")
    return {"documents": [_summary(d) for d in library.documents()],
            "output_root": str(library.output_root()),
            "converting": job_json(running) if running else None,
            "engine": _engine()}


def _start_inspect(app, doc: library.Document):
    def work(job):
        job.message = "Looking through the file..."

        def progress(done, total):
            job.done, job.total = done, total

        if doc.kind == ".pdf":
            inspection = library.inspect(doc.source(), progress=progress)
        elif doc.kind in formats.NATIVE:
            inspection = {"pictures": library.count_pictures(doc.source())}
        else:
            inspection = {}
        # Read again: a run may have finished while this one looked, and saved its own
        # results, which saving an older copy would undo.
        found = library.get(doc.id)
        found.inspection = {**found.inspection, **inspection}
        found.save()
        return {"inspection": found.inspection}

    return app.jobs.start(f"inspect:{doc.id}", work)


@route(raw_body=True)
def library_add(app, body) -> dict:
    doc = library.add(body["stream"], body.get("filename", ""), body["length"])
    return {"document": _summary(doc), "job": job_json(_start_inspect(app, doc))}


def library_remove(app, body) -> dict:
    doc = _doc(body)
    running = app.jobs.running("convert")
    if running and running.info.get("doc") == doc.id:
        raise HTTPError(409, "Stop the conversion of this file first.")
    library.remove(doc.id)
    return {"removed": doc.id, "kept": str(doc.output().parent)}


def document(app, body) -> dict:
    doc = _doc(body)
    running = app.jobs.running("convert")
    inspecting = app.jobs.running(f"inspect:{doc.id}")
    if not doc.inspection and not inspecting and doc.kind in (".pdf", *formats.NATIVE):
        inspecting = _start_inspect(app, doc)        # added by an older version, or failed
    if (doc.checks and doc.checks_wording != verify.NOTES_WORDING
            and not (running and running.info.get("doc") == doc.id)):
        # Notes kept from an older version, in its words: check again (free, offline).
        library.check_pages(doc, doc.page_pdf() or doc.source())
        doc.save()
    office = formats.office_installed("Word" if doc.kind in (".doc", ".docx")
                                      else "PowerPoint") or bool(formats.find_soffice())
    return {"document": _summary(doc), "engine": _engine(),
            "converting": job_json(running) if running else None,
            "inspecting": job_json(inspecting) if inspecting else None,
            "can_as_pages": doc.kind != ".pdf" and office,
            "ocr": ocr.available()}


# --- converting ------------------------------------------------------------------------

def convert(app, body) -> dict:
    doc = _doc(body)
    if app.jobs.running("convert"):
        raise HTTPError(409, "Another file is being converted. Wait for it, or stop it.")
    text_only = bool(body.get("text_only"))
    as_pages = bool(body.get("as_pages")) and doc.kind != ".pdf"
    whole_pages = bool(body.get("whole_pages")) and not text_only
    pages = str(body.get("pages") or "").strip() or None
    again = bool(body.get("again"))               # this page, asked of the model anew
    if again and not pages:
        raise ValueError("Say which page to transcribe again.")
    try:
        budget = max(0.0, float(body.get("budget_usd") or 0))
    except (TypeError, ValueError):
        raise ValueError("The spending cap must be a number of dollars.") from None
    trial = TRY_PAGES if body.get("trial") else 0
    _selection(doc, pages)                         # a bad range fails here, not in the job

    plan = runs.plan(text_only, fix=FIX)

    def work(job):
        opts = runs.options(plan, source=doc.source(), output=doc.output(),
                            work_dir=doc.work_dir(), pages=pages, title=doc.name,
                            whole_pages=whole_pages, budget_usd=budget, trial=trial,
                            again=again, say=lambda m: setattr(job, "message", m))
        run = formats.runner_for(opts, as_pages, log=lambda line: setattr(job, "message",
                                                                            line.strip()))
        pictures = doc.kind != ".pdf" and not as_pages
        progress = runs.Progress(job, plan.prior_seconds, "picture" if pictures else "page")
        job.message = ""
        result = run(opts, progress.event, abort=job.abort)

        fresh = library.get(doc.id)                # edits may have been saved meanwhile
        fresh.as_pages = as_pages
        if not text_only:
            fresh.whole_pages = whole_pages
        if as_pages and not fresh.inspection.get("pages"):
            fresh.inspection = {**fresh.inspection, **library.inspect(opts.pdf)}
        if again:
            fresh.edited = [p for p in fresh.edited if str(p) != pages]
        fresh.last_run = {
            **runs.summary(result, plan, progress, aborted=job.abort.is_set(),
                           whole_pages=whole_pages, trial=bool(trial)),
            # Pages with (almost) no text layer, read without the AI: empty, or nearly.
            "empty": sorted(set(fresh.inspection.get("scanned", [])) & set(progress.pages))
            if text_only else []}
        if fresh.paged():
            library.check_pages(fresh, opts.pdf)
        fresh.save()
        return {"document": _summary(fresh)}

    job = app.jobs.start("convert", work)
    job.info["doc"] = doc.id
    job.info["name"] = doc.name
    return job_json(job)


def stop(app, body) -> dict:
    job = app.jobs.get(str(body.get("job", "")))
    if not job or job.kind != "convert":
        raise HTTPError(404, "No such conversion.")
    job.abort.set()
    job.info["stopping"] = True
    job.message = "Stopping after the page being read. Finished pages are kept."
    return job_json(job)


# --- review and edit ---------------------------------------------------------------

def page_list(app, body) -> dict:
    doc = _doc(body)
    return {"document": _summary(doc),
            "scanned": doc.inspection.get("scanned", []),
            "checks": doc.checks}


def page_get(app, body) -> dict:
    """One page's Markdown; page 0 is the whole file, for Word and PowerPoint."""
    doc = _doc(body)
    page = _page(body)
    path = doc.output() if page == 0 else _page_file(doc, page)
    if page and not 1 <= page <= max(1, _page_count(doc)):
        raise ValueError("No such page.")
    return {"page": page, "converted": path.is_file(),
            "markdown": path.read_text(encoding="utf-8") if path.is_file() else "",
            "edited": page in doc.edited, "notes": doc.checks.get(str(page), []),
            "scanned": page in doc.inspection.get("scanned", [])}


def page_save(app, body) -> dict:
    doc = _doc(body)
    page = _page(body)
    markdown = body.get("markdown")
    if not isinstance(markdown, str):
        raise ValueError("Nothing to save.")
    running = app.jobs.running("convert")
    if running and running.info.get("doc") == doc.id:
        raise HTTPError(409, "This file is being converted. Save once it has finished.")
    if page == 0:
        if doc.paged():
            raise ValueError("Edit this file page by page.")
        target = doc.output()
    else:
        target = _page_file(doc, page)
        if not target.is_file():
            raise ValueError("This page has not been converted yet.")
    # Always \n, as the engine writes: the page files are matched line by line.
    target.write_text(markdown.replace("\r\n", "\n"), encoding="utf-8", newline="\n")
    if page not in doc.edited:
        doc.edited = sorted([*doc.edited, page])
    if page:
        assemble_output(doc.output(), doc.work_dir() / "pages", title=doc.name,
                        source_name=doc.source().name,
                        model=doc.last_run.get("model") or "text only")
        library.check_pages(doc, doc.page_pdf() or doc.source(), [page])
    doc.save()
    return {"saved": True, "notes": doc.checks.get(str(page), []), "edited": doc.edited}


@route(token_in_query=True)
def page_image(app, body) -> Response:
    import pymupdf

    doc = _doc(body)
    pdf = doc.page_pdf()
    if pdf is None:
        raise HTTPError(404, "This file has no pages to show.")
    page = _page(body)
    with pymupdf.open(pdf) as d:
        if not 1 <= page <= d.page_count:
            raise HTTPError(404, "No such page.")
        png = d[page - 1].get_pixmap(dpi=PAGE_DPI, alpha=False).tobytes("png")
    return Response(png, "image/png")


@route(token_in_query=True)
def asset(app, body) -> Response:
    """A picture the Markdown links to, for the preview: only from the result folder."""
    doc = _doc(body)
    folder = doc.output().parent.resolve()
    target = (folder / unquote(str(body.get("path", "")))).resolve()
    if not target.is_relative_to(folder) or target.suffix.lower() not in IMAGE_TYPES \
            or not target.is_file():
        raise HTTPError(404, "No such picture.")
    return Response(target.read_bytes(), IMAGE_TYPES[target.suffix.lower()])


@route(token_in_query=True)
def download(app, body) -> Response:
    doc = _doc(body)
    output = doc.output()
    if not output.is_file():
        raise HTTPError(404, "Nothing has been converted yet.")
    if body.get("format") != "zip":
        return Response(output.read_bytes(), "text/markdown", filename=output.name)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(output, output.name)
        assets = doc.assets_dir()
        if assets.is_dir():
            for f in sorted(assets.rglob("*")):
                if f.is_file():
                    z.write(f, f.relative_to(output.parent).as_posix())
    return Response(buffer.getvalue(), "application/zip", filename=output.stem + ".zip")


def _reveal(folder: Path) -> None:
    if sys.platform == "win32":
        os.startfile(folder)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(folder)])


def open_folder(app, body) -> dict:
    folder = _doc(body).output().parent
    if not folder.is_dir():
        raise ValueError("Nothing has been converted yet.")
    _reveal(folder)
    return {"folder": str(folder)}


ROUTES = {
    ("GET", "/api/library"): library_list,
    ("POST", "/api/library/add"): library_add,
    ("POST", "/api/library/remove"): library_remove,
    ("GET", "/api/doc"): document,
    ("GET", "/api/doc/estimate"): estimate,
    ("POST", "/api/doc/convert"): convert,
    ("POST", "/api/doc/stop"): stop,
    ("GET", "/api/doc/pages"): page_list,
    ("GET", "/api/doc/page"): page_get,
    ("POST", "/api/doc/page"): page_save,
    ("GET", "/api/doc/image"): page_image,
    ("GET", "/api/doc/asset"): asset,
    ("GET", "/api/doc/download"): download,
    ("POST", "/api/doc/open-folder"): open_folder,
}
