"""A conversion run as the setup page and agents start one: which AI service it uses
and whether that is ready, the run's options, and its progress (pages done, the page
being read, money spent, time left). The command line builds its own options from
flags; it shares the price per request from here."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from . import ocr, settings
from .config import DEFAULT_MODEL, Options, get_api_key, get_model, resolve_endpoint
from .providers import Provider, known_price

# Rough tokens for one request, a page image plus the prompt in and a transcription out,
# for a price per page next to each model and for estimates. Measured on a 352-page
# textbook read whole by Gemini 3.6 Flash: within 5% of the real cost.
PAGE_TOKENS_IN, PAGE_TOKENS_OUT = 1500, 600

# "Read every page with the AI": every page counts as having no text layer, so each is
# transcribed whole. A born-digital book's text layer often garbles its maths (braces,
# sub- and superscripts out of order); the model reads the page as it looks.
EVERY_PAGE = 10 ** 9


def inspect_file(path: Path, pages: str | None = None, every_page: bool = False,
                 fix: str = "") -> dict:
    """A free look at a file and what converting it would take: the setup page's first
    screen, for the command line and agents."""
    from . import formats, library
    from .core import parse_pages

    kind = path.suffix.lower()
    if kind not in formats.SUPPORTED:
        raise ValueError(f"Cannot read {kind or 'files without an extension'}. It reads "
                         f"{', '.join(sorted(formats.SUPPORTED))}.")
    status = engine(fix)
    facts: dict = {"file": str(path), "kind": kind}
    if kind == ".pdf":
        found = library.inspect(path)
        chosen = [i + 1 for i in parse_pages(pages, found["pages"])] if pages else None
        if every_page:
            calls = len(chosen) if chosen else found["pages"]
        else:
            calls = library.vision_calls(found, chosen)
        facts.update(found, selected=len(chosen) if chosen else found["pages"])
    elif kind in formats.NATIVE:
        calls = library.count_pictures(path)
        facts["pictures"] = calls
    else:
        calls = None                  # DOC / PPT: known once Office has opened them
    estimate = {"requests": calls, "cost": None, "seconds": None}
    if calls is not None and status["per_call"] is not None:
        estimate["cost"] = round(calls * status["per_call"], 4)
    if calls is not None and status["seconds_per_call"]:
        estimate["seconds"] = round(calls * status["seconds_per_call"])
    return {**facts, "estimate": estimate, "engine": status}


def price_per_request(model: str, local: bool = False) -> float | None:
    """Dollars per page-sized request at the model's list price; None if unknown."""
    price = (0.0, 0.0) if local else known_price(model)
    if not price:
        return None
    return round((PAGE_TOKENS_IN * price[0] + PAGE_TOKENS_OUT * price[1]) / 1e6, 5)


def engine(fix: str = "") -> dict:
    """The AI service a conversion would use now, and whether it is ready. `fix` is
    appended to a problem: where the reader can put it right. Nothing here goes online:
    Ollama is started, if need be, when the run begins."""
    try:
        provider, _url = resolve_endpoint()
    except ValueError as exc:
        return {"ready": False, "problem": str(exc), "provider": "", "name": "", "model": "",
                "local": False, "per_call": None, "seconds_per_call": None}
    model = get_model(None, provider.id)
    problem = ""
    if provider.needs_key and not get_api_key(provider=provider.id):
        problem = f"There is no {provider.name} key yet."
    elif not model:
        problem = f"No {provider.name} model is chosen yet."
    if problem and fix:
        problem += " " + fix
    return {"ready": not problem, "problem": problem, "provider": provider.id,
            "name": provider.name, "model": model, "local": provider.local,
            "per_call": price_per_request(model, provider.local),
            "seconds_per_call": settings.load().speed.get(model) if provider.local else None}


@dataclass
class Plan:
    """The service a run will use, fixed when it is asked for."""
    provider: Provider
    base_url: str
    key: str | None
    model: str                   # as chosen; Ollama runs a roomier copy of it
    text_only: bool
    prior_seconds: float | None  # the speed test's seconds per page, for a first ETA


def plan(text_only: bool = False, fix: str = "") -> Plan:
    """Raises ValueError, with what to do, when the service is not ready."""
    if not text_only:
        status = engine(fix)
        if not status["ready"]:
            raise ValueError(status["problem"])
    provider, base_url = resolve_endpoint()
    model = get_model(None, provider.id)
    return Plan(provider, base_url, get_api_key(provider=provider.id), model, text_only,
                settings.load().speed.get(model) if provider.local else None)


def options(p: Plan, *, source: Path, output: Path, work_dir: Path | None = None,
            pages: str | None = None, title: str | None = None, whole_pages: bool = False,
            budget_usd: float = 0.0, trial: int = 0, again: bool = False,
            say=lambda _message: None) -> Options:
    """The run's Options. Starts Ollama when the plan needs it (`say` reports that)."""
    name = p.model
    if p.provider.id == "ollama" and not p.text_only:
        from .local import ollama
        say("Starting Ollama...")
        if not ollama.ensure_running():
            raise RuntimeError("Ollama did not start. Open it from the Start menu, then try "
                               "again.")
        name = ollama.with_context(p.model)
    return Options(pdf=source, output=output, work_dir=work_dir, pages=pages, title=title,
                   model=name or DEFAULT_MODEL, api_key=p.key, base_url=p.base_url,
                   provider=p.provider.id,
                   workers=1 if p.provider.local else 3, rpm=0 if p.provider.local else 60,
                   budget_usd=budget_usd, estimate=trial, no_vision=p.text_only,
                   min_chars=EVERY_PAGE if whole_pages and not p.text_only
                   else Options.min_chars,
                   ocr_fallback=ocr.available(), fresh=again, ask_again=again)


class Progress:
    """Turns the engine's events into a job's progress: pages done, the page being read,
    money spent, and the time left, measured from this run's own pages."""

    def __init__(self, job, prior_seconds: float | None, unit: str):
        self.job, self.prior = job, prior_seconds
        self.started = time.monotonic()
        self.now_done = 0
        self.todo = 0
        self.reading: set[int] = set()
        self.pages: list[int] = []               # written by this run
        job.info.update(reading=[], failed=[], cost=0.0, eta=None, per_page=None, unit=unit,
                        todo=0)

    def event(self, name: str, p: dict) -> None:
        job, info = self.job, self.job.info
        if name == "start":
            job.total, job.done, self.todo = p["selected"], p["done"], p["todo"]
            info["todo"] = p["todo"]
        elif name == "page_start":
            self.reading.add(p["page"])
        elif name in ("page_done", "image_done"):
            self.reading.discard(p.get("page", 0))
            if "page" in p:
                self.pages.append(p["page"])
            self.now_done += 1
            job.done = p["done"]
            info["cost"] = p.get("cost", 0.0)
        elif name == "page_failed":
            self.reading.discard(p["page"])
            self.now_done += 1
            info["failed"] = [*info["failed"], p["page"]]
        info["reading"] = sorted(self.reading)
        left = max(0, self.todo - self.now_done)
        if self.now_done:
            per_page = (time.monotonic() - self.started) / self.now_done
            info["per_page"], info["eta"] = round(per_page, 1), round(left * per_page)
        elif self.prior:
            info["eta"] = round(left * self.prior)


def summary(result, p: Plan, progress: Progress, *, aborted: bool, whole_pages: bool,
            trial: bool) -> dict:
    """What a finished run did, as the page and agents report it."""
    reason = result.stopped_reason
    if aborted and reason not in ("budget", "DailyQuotaExceeded"):
        reason = "stopped"                     # a Stop button or an agent's stop
    return {
        "when": time.strftime("%Y-%m-%d %H:%M"), "provider": p.provider.id,
        # The name the person chose, not Ollama's roomier copy of it.
        "provider_name": p.provider.name, "model": "" if p.text_only else p.model,
        "text_only": p.text_only, "whole_pages": whole_pages and not p.text_only,
        "converted": result.pages_converted, "selected": result.pages_selected,
        "total": result.pages_total, "unit": result.unit, "failed": result.failed,
        "ocr": result.pages_ocr, "truncated": result.truncated,
        "cost": round(result.cost, 4), "stopped": reason, "trial": trial,
        "seconds": round(time.monotonic() - progress.started)}
