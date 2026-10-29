"""Flag-driven CLI, for scripting and repeat runs.

With no arguments at all, `bettermarkitdown` starts the interactive wizard
instead (see wizard.py). Other commands:

    bettermarkitdown app                         the setup page, in your browser
    bettermarkitdown setup [--provider P] [--model M] [--key-stdin]   the same, without it
    bettermarkitdown inspect FILE [--pages R] [--every-page]   a free look and an estimate
    bettermarkitdown agent status|install|uninstall   the skill for AI agents
    bettermarkitdown mcp                         a tool server for AI agents (MCP, stdio)
    bettermarkitdown providers
    bettermarkitdown key set|test|forget|status [PROVIDER]
    bettermarkitdown system | doctor              [--json]
    bettermarkitdown local status|install|pull|test|setup [MODEL]
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from dataclasses import asdict
from pathlib import Path

from . import __version__, credentials, ocr
from .config import (
    DEFAULT_MODEL,
    Options,
    find_api_key,
    get_api_key,
    get_model,
    redact,
    resolve_endpoint,
)
from .core import Meter, list_models
from .providers import PROVIDERS, get_provider, known_price, model_note
from .runs import EVERY_PAGE


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bettermarkitdown",
        description="Convert image-heavy and scanned PDFs to Markdown with "
                    "MarkItDown + a vision model (Gemini, OpenAI, Claude, Kimi, OpenRouter, "
                    "or one on your own computer).")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("pdf", nargs="?", metavar="FILE",
                        help="the document: PDF, DOCX, PPTX, or Office 97-2003 DOC / PPT "
                             "(omit for the interactive wizard)")
    parser.add_argument("--as-pages", action="store_true",
                        help="Word / PowerPoint files: turn the file into a PDF first (with "
                             "Microsoft Office or LibreOffice) and convert it page by page, "
                             "for page images to check against. Tables come out flatter")
    parser.add_argument("-o", "--output", help="output .md (default: alongside the PDF)")
    parser.add_argument("--pages", help="1-based selection: '5', '10-40', '1,5,9-12'")
    parser.add_argument("--toc", action="store_true",
                        help="print the PDF's outline (chapters, sections) with the page "
                             "range of each entry, for choosing --pages, then exit")
    parser.add_argument("--title", help="the output's # heading (default: the PDF's file "
                                        "name)")
    parser.add_argument("--work-dir", help="where to keep per-page Markdown and the response "
                                           "cache; point it at a local disk when the output "
                                           "lives in a synced folder")

    parser.add_argument("--provider", choices=list(PROVIDERS),
                        help="which AI service to use (default: gemini, or $BMID_PROVIDER). "
                             "`bettermarkitdown providers` lists them")
    parser.add_argument("--model", default=None,
                        help=f"default: the provider's own ({DEFAULT_MODEL} for Gemini), or "
                             "$BMID_MODEL if set")
    parser.add_argument("--base-url",
                        help="OpenAI-compatible endpoint to use instead of the provider's, "
                             "e.g. http://localhost:11434/v1 for Ollama. Also read from "
                             "BMID_BASE_URL")
    parser.add_argument("--reasoning", default="none",
                        choices=["none", "low", "medium", "high", "default"],
                        help="thinking budget. Transcription does not need it and thinking "
                             "tokens bill as output, so 'none' is the default")
    parser.add_argument("--list-models", action="store_true",
                        help="list the models this API key can call, then exit")

    parser.add_argument("--dpi", type=int, default=200, help="render DPI (default 200)")
    parser.add_argument("--max-edge", type=int, default=1568,
                        help="downscale uploads to this long edge (default 1568)")
    parser.add_argument("--min-chars", type=int, default=120,
                        help="pages with fewer non-space chars count as scanned (default 120)")
    parser.add_argument("--min-figure-pt", type=float, default=60.0,
                        help="ignore figures smaller than this many points (default 60)")
    parser.add_argument("--every-page", action="store_true",
                        help="read every page whole with the AI, not only scanned pages and "
                             "figures: best for maths, which a PDF's text layer often "
                             "garbles. One request per page")
    parser.add_argument("--library", action="store_true",
                        help="convert the file in the setup page's library, so it can be "
                             "reviewed and edited there (bettermarkitdown app). Results go "
                             "to Documents\\BetterMarkItDown; -o and --work-dir are ignored")
    parser.add_argument("--ignore-small-images", action="store_true",
                        help="keep pages with a text layer on the free text path even when "
                             "they hold images too small to be figures. By default those "
                             "pages are transcribed whole, because such images are usually "
                             "equations, which the text path drops")
    parser.add_argument("--figure-pad", type=float, default=22.0,
                        help="margin around figure crops so captions come along (default 22)")

    parser.add_argument("--workers", type=int,
                        help="parallel pages (default 3; 1 for a model on this computer)")
    parser.add_argument("--rpm", type=int,
                        help="max requests per minute (default 60; no limit for a model on "
                             "this computer)")

    parser.add_argument("--budget-usd", type=float, default=0.0,
                        help="stop cleanly once this much has been spent (0 = no cap)")
    parser.add_argument("--price-in", type=float, help="USD per 1M input tokens")
    parser.add_argument("--price-out", type=float, help="USD per 1M output tokens")
    parser.add_argument("--estimate", type=int, metavar="N", default=0,
                        help="convert only N pages, then report measured cost and project "
                             "the whole document. Those pages stay done and cached")

    parser.add_argument("--no-vision", action="store_true", help="text only, no API calls")
    parser.add_argument("--no-page-images", dest="save_images", action="store_false",
                        help="do not save a PNG of each scanned page")
    parser.add_argument("--no-ocr-fallback", dest="ocr_fallback", action="store_false",
                        help="do not fall back to local OCR on pages the model refuses")
    parser.add_argument("--no-study-notes", dest="study_notes", action="store_false",
                        help="on a page the model refuses to transcribe, go straight to local "
                             "OCR instead of asking for study notes in the model's own words "
                             "(up to 3 requests a page)")
    parser.add_argument("--fresh", action="store_true",
                        help="redo pages already finished. Overwrites hand edits in the "
                             "work dir")
    parser.add_argument("--json", action="store_true",
                        help="for scripts and AI agents: print one JSON object per line "
                             "(progress events, then a summary) instead of text. Exit codes: "
                             "0 done, 1 error, 2 stopped early (cap or quota), 3 --verify "
                             "flagged pages, 130 interrupted")
    parser.add_argument("--verify", action="store_true",
                        help="convert nothing: compare the finished pages in the work dir "
                             "with the PDF's text layer and list pages whose words or numbers "
                             "differ, and render every formula with KaTeX if Node.js is "
                             "installed. "
                             "No API calls. Exit code 3 if any page is flagged")
    return parser


def _page_list(pages: list[int], limit: int = 12) -> str:
    shown = ", ".join(map(str, pages[:limit]))
    return shown + (f" and {len(pages) - limit} more" if len(pages) > limit else "")


class Say:
    """Text for people, or one JSON object per line for scripts and agents (--json).
    In JSON mode nothing else reaches stdout, so every line parses."""

    def __init__(self, as_json: bool):
        self.json = as_json

    def event(self, kind: str, /, **payload) -> None:
        if self.json:
            print(json.dumps({"event": kind, **payload}, default=str), flush=True)

    def text(self, *lines: str) -> None:
        if not self.json:
            for line in lines:
                print(line, flush=True)

    def fail(self, message: str, code: int = 1) -> int:
        if self.json:
            self.event("error", message=str(message), exit=code)
        else:
            print(message, file=sys.stderr)
        return code


def print_toc(pdf: Path, as_json: bool = False) -> int:
    import pymupdf

    from .core import outline_ranges

    with pymupdf.open(pdf) as doc:
        entries = outline_ranges(doc)
    if as_json:
        print(json.dumps({"event": "toc", "pdf": str(pdf), "entries": [
            {"level": level, "title": title, "first": first, "last": last}
            for level, title, first, last in entries]}))
        return 0
    if not entries:
        print("This PDF has no outline (bookmarks). Find the pages in its table of contents.")
        return 0
    print("Pages are the PDF's own, 1-based, as --pages takes them. A range ends on the page "
          "where the next\nentry begins when that entry starts below text, since both "
          "sections are on it.\n")
    width = len(str(max(last for *_, last in entries)))
    for level, title, first, last in entries:
        span = f"{first}-{last}" if last > first else str(first)
        print(f"{span:>{2 * width + 1}}  {'  ' * (level - 1)}{title}")
    return 0


def print_providers(argv: list[str] | None = None) -> int:
    if argv and "--json" in argv:
        from .runs import price_per_request
        out = []
        for spec in PROVIDERS.values():
            key, source = find_api_key(spec.id)
            out.append({"id": spec.id, "name": spec.name, "local": spec.local,
                        "needs_key": spec.needs_key, "key_source": source,
                        "default_model": spec.default_model or "", "summary": spec.summary,
                        "models": [{"id": m, "price_in": pr[0], "price_out": pr[1],
                                    "per_page": price_per_request(m, spec.local),
                                    "note": spec.model_notes.get(m, "")}
                                   for m, pr in spec.models.items()]})
        print(json.dumps({"providers": out}, indent=2))
        return 0
    for spec in PROVIDERS.values():
        key, source = find_api_key(spec.id)
        if not spec.needs_key and not key:
            status = "no key needed"
        else:
            status = f"key from {source}" if key else "no key"
        model = spec.default_model or "(pick from its list)"
        print(f"{spec.id:<11} {spec.name:<36} {model:<28} {status}")
        if spec.summary:
            print(f"{'':<11} {spec.summary}")
    print("\nSave a key: bettermarkitdown key set PROVIDER. Use one: --provider PROVIDER.")
    print("See a provider's models, prices and limits: --list-models --provider PROVIDER.")
    return 0


def describe_model(name: str) -> str:
    """'name  $in/$out per 1M  - note', for whatever of that we know."""
    price = known_price(name)
    note = model_note(name)
    return (name + (f"  ${price[0]}/${price[1]} per 1M" if price else "")
            + (f"  - {note}" if note else ""))


def key_command(argv: list[str]) -> int:
    """`key set|test|forget|status [PROVIDER] [--stdin]`."""
    parser = argparse.ArgumentParser(prog="bettermarkitdown key",
                                     description="Manage API keys in this computer's "
                                                 "password store.")
    parser.add_argument("action", choices=["set", "test", "forget", "status"])
    parser.add_argument("provider", nargs="?", choices=list(PROVIDERS))
    parser.add_argument("--stdin", action="store_true",
                        help="read the key from standard input instead of a hidden prompt")
    args = parser.parse_args(argv)

    if args.action == "status":
        for spec in PROVIDERS.values():
            if spec.needs_key or spec.key_env:
                key, source = find_api_key(spec.id)
                print(f"{spec.id:<11} {redact(key):<18} {source}")
        return 0

    if not args.provider:
        parser.error(f"'{args.action}' needs a provider: {', '.join(PROVIDERS)}")
    spec = get_provider(args.provider)

    if args.action == "set":
        if args.stdin:
            key = sys.stdin.readline().strip()
        else:
            import getpass
            if spec.key_url:
                print(f"Create a {spec.name} key at {spec.key_url}")
            key = getpass.getpass(f"Paste the {spec.name} key (hidden): ").strip()
        try:
            credentials.store_key(spec.id, key)
        except (ValueError, credentials.KeyStoreUnavailable) as exc:
            print(exc, file=sys.stderr)
            return 1
        print(f"Saved {redact(key)} for {spec.name} in this computer's password store.")
        return 0

    if args.action == "forget":
        try:
            removed = credentials.forget_key(spec.id)
        except credentials.KeyStoreUnavailable as exc:
            print(exc, file=sys.stderr)
            return 1
        print(f"Removed the saved {spec.name} key." if removed
              else f"No {spec.name} key was saved.")
        return 0

    # test: listing models is free, and proves the key and the endpoint both work.
    key, source = find_api_key(spec.id)
    if spec.needs_key and not key:
        print(f"No {spec.name} key. Run: bettermarkitdown key set {spec.id}", file=sys.stderr)
        return 1
    try:
        models = list_models(key, spec.base_url or "", provider=spec.id)
    except Exception as exc:
        print(f"{spec.name} rejected the request: {exc}", file=sys.stderr)
        return 1
    print(f"{spec.name}: key from {source or 'nowhere (none needed)'} works; "
          f"{len(models)} models available.")
    return 0


def inspect_command(argv: list[str]) -> int:
    """`inspect FILE`: what a file holds and what converting it would take. Free."""
    from .runs import inspect_file

    parser = argparse.ArgumentParser(prog="bettermarkitdown inspect",
                                     description="A free look at a file, and an estimate.")
    parser.add_argument("file")
    parser.add_argument("--pages", help="1-based selection, as for converting")
    parser.add_argument("--every-page", action="store_true",
                        help="estimate for reading every page whole with the AI")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    say = Say(args.json)
    path = Path(args.file).expanduser().resolve()
    if not path.is_file():
        return say.fail(f"Not found: {path}")
    try:
        found = inspect_file(path, args.pages, args.every_page,
                             fix="Run `bettermarkitdown setup`.")
    except ValueError as exc:
        return say.fail(exc)
    if args.json:
        say.event("inspect", **found)
        return 0
    status, estimate, calls = found["engine"], found["estimate"], found["estimate"]["requests"]
    if found["kind"] == ".pdf":
        print(f"{path.name}: {found['pages']} pages, {len(found['scanned'])} scanned, "
              f"{len(found['equations'])} with equations set as pictures, {found['figures']} "
              f"figures, {len(found['outline'])} outline entries.")
    elif calls is not None:
        print(f"{path.name}: {calls} picture(s).")
    who = f"{status['name']}, {status['model']}" if status["ready"] else "no AI service yet"
    cost = f", about ${estimate['cost']:.2f}" if estimate["cost"] else ""
    time_left = f", roughly {estimate['seconds'] // 60} min" if estimate["seconds"] else ""
    print(f"Converting ({who}): about {calls if calls is not None else '?'} AI request(s)"
          f"{cost}{time_left}." + ("" if status["ready"] else f" {status['problem']}"))
    return 0


def setup_command(argv: list[str]) -> int:
    """`setup`: the setup page's choices without the page, for scripts and agents. With
    no options it reports what is set up. Keys come from standard input only, never
    from the command line, where they would land in the shell history."""
    from . import settings
    from .runs import engine

    parser = argparse.ArgumentParser(prog="bettermarkitdown setup",
                                     description="Choose the AI service and model, and save "
                                                 "a key, without the setup page.")
    parser.add_argument("--provider", choices=list(PROVIDERS))
    parser.add_argument("--model", help="default: the provider's own")
    parser.add_argument("--key-stdin", action="store_true",
                        help="read the provider's API key from standard input, check it with "
                             "a free request, and keep it in the password store")
    parser.add_argument("--no-check", action="store_true",
                        help="with --key-stdin: save the key without checking it")
    parser.add_argument("--audience", choices=list(settings.AUDIENCES))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    say = Say(args.json)

    if args.key_stdin and not args.provider:
        return say.fail("--key-stdin needs --provider.")
    changes: dict = {}
    if args.provider:
        spec = get_provider(args.provider)
        if args.key_stdin:
            key = sys.stdin.readline().strip()
            if not key:
                return say.fail("No key arrived on standard input.")
            if not args.no_check:
                try:
                    list_models(key, spec.base_url or "", provider=spec.id)
                except Exception as exc:
                    return say.fail(f"{spec.name} did not accept this key: "
                                    f"{str(exc).replace(key, redact(key))[:300]}")
            try:
                credentials.store_key(spec.id, key)
            except (ValueError, credentials.KeyStoreUnavailable) as exc:
                return say.fail(exc)
            say.text(f"Saved {redact(key)} for {spec.name} in this computer's password store.")
        model = args.model or spec.default_model or ""
        if not model and not spec.local:
            return say.fail(f"{spec.name} has no default model: pass --model "
                            f"(`bettermarkitdown --list-models --provider {spec.id}`).")
        changes.update(provider=spec.id, model=model, setup_done=True)
    elif args.model:
        return say.fail("--model needs --provider.")
    if args.audience:
        changes["audience"] = args.audience
    saved = settings.update(**changes) if changes else settings.load()
    status = engine(fix="Run `bettermarkitdown setup --provider P --key-stdin`.")
    if args.json:
        say.event("setup", settings={k: v for k, v in asdict(saved).items() if k != "speed"},
                  engine=status)
    else:
        print(f"Provider: {status['name'] or 'none'}"
              + (f", model {status['model']}" if status["model"] else ""))
        print("Ready." if status["ready"] else f"Not ready: {status['problem']}")
    return 0 if status["ready"] else 1


def system_command(name: str, argv: list[str]) -> int:
    """`system`: this computer and the local model that suits it. `doctor`: that plus
    keys, provider and optional parts, for a bug report. Both take --json."""
    import json

    parser = argparse.ArgumentParser(prog=f"bettermarkitdown {name}")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    if name == "doctor":
        from .doctor import format_report, gather
        report = gather()
        print(json.dumps(report, indent=2) if args.json else format_report(report))
        return 0

    from .local import describe, recommend
    from .system import detect
    profile = detect()
    rec = recommend(profile)
    if args.json:
        print(json.dumps({"system": profile.to_dict(), "recommendation": rec.to_dict()},
                         indent=2))
    else:
        print(describe(profile, rec))
    return 0


def _record_in_library(doc_id, result, opts, provider, model, as_pages, every_page) -> None:
    """What the setup page shows for a run it did not start itself."""
    import time

    from . import library

    doc = library.get(doc_id)
    doc.as_pages = as_pages
    if not opts.no_vision:
        doc.whole_pages = every_page
    doc.last_run = {
        "when": time.strftime("%Y-%m-%d %H:%M"), "provider": provider.id,
        "provider_name": provider.name, "model": "" if opts.no_vision else model,
        "text_only": opts.no_vision, "whole_pages": every_page and not opts.no_vision,
        "converted": result.pages_converted, "selected": result.pages_selected,
        "total": result.pages_total, "unit": result.unit, "failed": result.failed,
        "ocr": result.pages_ocr, "truncated": result.truncated,
        "cost": round(result.cost, 4), "stopped": result.stopped_reason, "trial": False,
        "seconds": 0, "empty": [], "by": "command line"}
    if doc.paged():
        library.check_pages(doc, opts.pdf)
    doc.save()


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    # Piped or redirected on Windows, stdout is cp1252: a PDF named with a curly
    # quote prints as mojibake, and a report holding a Greek letter crashes.
    for stream in (sys.stdout, sys.stderr):
        if (getattr(stream, "encoding", "") or "").lower().replace("-", "") != "utf8":
            with contextlib.suppress(AttributeError, ValueError):
                stream.reconfigure(encoding="utf-8")
    if not argv:
        from .wizard import main as wizard_main
        return wizard_main()
    # A PDF is a path ending in .pdf, so these words cannot be mistaken for one.
    if argv[0] == "providers":
        return print_providers(argv[1:])
    if argv[0] == "key":
        return key_command(argv[1:])
    if argv[0] == "setup":
        return setup_command(argv[1:])
    if argv[0] == "inspect":
        return inspect_command(argv[1:])
    if argv[0] == "agent":
        from .agent import main as agent_main
        return agent_main(argv[1:])
    if argv[0] == "mcp":
        from .mcp import main as mcp_main
        return mcp_main(argv[1:])
    if argv[0] in ("system", "doctor"):
        return system_command(argv[0], argv[1:])
    if argv[0] == "app":
        from .app import launch
        return launch(argv[1:])
    if argv[0] == "local":
        from .local.commands import main as local_main
        return local_main(argv[1:])

    args = build_parser().parse_args(argv)
    say = Say(args.json)
    try:
        provider, base_url = resolve_endpoint(args.provider, args.base_url)
    except ValueError as exc:
        return say.fail(exc)
    api_key = get_api_key(provider=provider.id)
    no_key = (f"No {provider.name} key. Run `bettermarkitdown key set {provider.id}`, set "
              f"{' or '.join(provider.key_env) or 'a key'}, or pass --no-vision.")

    if args.list_models:
        if not api_key and provider.needs_key:
            return say.fail(no_key)
        names = list_models(api_key, base_url, provider=provider.id)
        if args.json:
            say.event("models", provider=provider.id, models=[
                {"id": n, "price": known_price(n), "note": model_note(n)} for n in names])
        for name in names:
            say.text(describe_model(name))
        return 0

    if not args.pdf:
        build_parser().error("the following arguments are required: pdf")

    pdf = Path(args.pdf).expanduser().resolve()
    if not pdf.is_file():
        return say.fail(f"Not found: {pdf}")
    from . import formats
    suffix = pdf.suffix.lower()
    if suffix not in formats.SUPPORTED:
        return say.fail(f"Cannot read {suffix or 'files without an extension'}. Supported: "
                        f"{', '.join(sorted(formats.SUPPORTED))}.")
    through_pdf = suffix != ".pdf" and args.as_pages
    if suffix != ".pdf" and (args.toc or args.verify):
        return say.fail("--toc and --verify read a PDF. For this file, convert with "
                        "--as-pages first, then run them on the PDF in the work folder.")

    if args.toc:
        return print_toc(pdf, args.json)

    if args.verify:
        import pymupdf

        from .core import parse_pages
        from .verify import add_render_check, format_report, page_notes, verify

        output = (Path(args.output).expanduser().resolve() if args.output
                  else pdf.with_suffix(".md"))
        work_dir = (Path(args.work_dir).expanduser().resolve() if args.work_dir
                    else output.parent / (output.stem + "_work"))
        if not (work_dir / "pages").is_dir():
            return say.fail(f"No converted pages in {work_dir}. Pass the same -o / --work-dir "
                            "you converted with.")
        with pymupdf.open(pdf) as doc:
            total = doc.page_count
        results = verify(pdf, work_dir, parse_pages(args.pages, total))
        render_note = add_render_check(results, work_dir)
        code = 3 if any(r.flagged for r in results) else 0
        if args.json:
            say.event("verify", pdf=str(pdf), work_dir=str(work_dir), render_check=render_note,
                      flagged=[r.page for r in results if r.flagged],
                      no_text_layer=[r.page for r in results if r.status == "no-text-layer"],
                      not_converted=[r.page for r in results if r.status == "no-page-file"],
                      pages={r.page: page_notes(r) for r in results if page_notes(r)},
                      exit=code)
        else:
            print(format_report(results, render_note=render_note))
        return code

    if not api_key and not args.no_vision and provider.needs_key:
        return say.fail(no_key)

    model = get_model(args.model, provider.id)
    if not model and not args.no_vision:
        return say.fail(f"{provider.name} has no default model. Pick one with --model "
                        f"(--list-models --provider {provider.id} lists them).")
    model = model or DEFAULT_MODEL
    chosen_model = model
    if provider.id == "ollama" and not args.no_vision:
        # Ollama's default context is too small for a page; use the copy with room.
        from .local import ollama
        model = ollama.with_context(model)

    # A local server reads one page at a time, and has no rate limit to respect.
    workers = args.workers or (1 if provider.local else 3)
    rpm = args.rpm if args.rpm is not None else (0 if provider.local else 60)

    opts = Options(
        pdf=pdf,
        output=(Path(args.output).expanduser().resolve() if args.output
                else pdf.with_suffix(".md")),
        work_dir=Path(args.work_dir).expanduser().resolve() if args.work_dir else None,
        pages=args.pages, title=args.title, model=model,
        reasoning=args.reasoning,
        api_key=api_key,
        base_url=base_url,
        provider=provider.id,
        dpi=args.dpi, max_edge=args.max_edge,
        min_chars=EVERY_PAGE if args.every_page else args.min_chars,
        min_figure_pt=args.min_figure_pt, figure_pad=args.figure_pad,
        ignore_small_images=args.ignore_small_images,
        workers=workers, rpm=rpm, budget_usd=args.budget_usd,
        price_in=args.price_in, price_out=args.price_out, estimate=args.estimate,
        no_vision=args.no_vision, save_images=args.save_images,
        ocr_fallback=args.ocr_fallback and ocr.available(), fresh=args.fresh,
        study_notes=args.study_notes,
    )

    doc = None
    if args.library:
        # The setup page's library: its own copy, work dir and result folder, so the
        # person can review and edit the result there.
        from . import library
        try:
            doc = library.add_file(pdf)
        except library.LibraryError as exc:
            return say.fail(exc)
        opts.pdf, opts.output, opts.work_dir = doc.source(), doc.output(), doc.work_dir()
        opts.title = opts.title or doc.name
        say.text(f"In the library as {doc.name}: results go to {doc.output().parent}")
        say.event("library", document=doc.id, name=doc.name, output=str(doc.output()))

    def log(line: str) -> None:
        say.text(line)
        say.event("log", message=line.strip())

    try:
        run = formats.runner_for(opts, through_pdf, log=log)
    except formats.ConverterMissing as exc:
        return say.fail(exc)

    def on_event(name: str, payload: dict) -> None:
        if args.json:
            if name != "finished":                  # the summary below says it all
                say.event(name, **payload)
            return
        if name == "start" and opts.pdf.suffix.lower() != ".pdf":   # pictures, not pages
            print(f"{pdf.name}: {payload['total']} picture(s) to look at, model="
                  f"{opts.model if not opts.no_vision else 'none (text only)'}", flush=True)
        elif name == "start":
            print(f"{opts.pdf.name}: {payload['total']} pages, converting "
                  f"{payload['selected']} ({payload['done']} already done), "
                  f"model={opts.model}, workers={opts.workers}", flush=True)
        elif name == "image_done":
            print(f"  [{payload['done']}] picture {payload['picture']} of {payload['total']} "
                  "described", flush=True)
        elif name == "page_done":
            tag = " [local OCR]" if payload.get("ocr") else ""
            print(f"  [{payload['done']}/{payload['total']}] page {payload['page']} "
                  f"done{tag}", flush=True)
        elif name == "page_failed":
            print(f"  !! {payload['message']} - left unwritten, rerun to retry", flush=True)

    try:
        result = run(opts, on_event)
    except KeyboardInterrupt:
        if args.json:
            return say.fail("Interrupted - finished pages are kept, rerun to resume.", 130)
        print("\nInterrupted - finished pages are kept, rerun to resume.")
        return 130
    except Exception as exc:
        return say.fail(f"Failed: {exc}")

    code = 2 if result.stopped_reason in ("budget", "DailyQuotaExceeded") else 0
    if doc is not None:
        _record_in_library(doc.id, result, opts, provider, chosen_model, through_pdf,
                           args.every_page)
    if args.json:
        per_page = result.cost / max(1, result.pages_converted)
        remaining = max(0, result.pages_selected - result.pages_converted)
        say.event("summary", **asdict(result), work_dir=str(opts.resolved_work_dir()),
                  model=opts.model, cost_per_unit=round(per_page, 6),
                  cost_to_finish=round(per_page * remaining, 4), exit=code)
        return code

    if result.calls:
        print(f"\nSpend: {result.calls} vision calls | {result.tokens_in:,} in + "
              f"{result.tokens_out:,} out tokens | {Meter.usd(result.cost)}")
        unit = result.unit
        per_page = result.cost / max(1, result.pages_converted)
        print(f"       {Meter.usd(per_page)} per {unit} over {result.pages_converted} "
              f"{unit}(s)")
        remaining = result.pages_selected - result.pages_converted
        if remaining > 0:
            print(f"       ~{Meter.usd(per_page * remaining)} to finish the remaining "
                  f"{remaining} {unit}(s); ~{Meter.usd(per_page * result.pages_total)} for "
                  f"all {result.pages_total} {unit}s")

    if result.pages_notes:
        print(f"\nThe model refused to transcribe {len(result.pages_notes)} page(s), which got "
              f"study notes in its own words instead: {_page_list(result.pages_notes)}")
        print("   Notes keep the ideas and formulas, not the wording or every exact figure; "
              "each says which PDF page to read for the full text.")

    if result.pages_ocr:
        print(f"\nLocal OCR was used for {len(result.pages_ocr)} page(s): "
              f"{', '.join(str(n) for n in result.pages_ocr)}")
        print("   The model refused these (usually its recitation filter). Layout is "
              "flattened and notation is unreliable there.")

    small = result.pages_small_images
    if small and (opts.no_vision or opts.ignore_small_images):
        print(f"\n!! {len(small)} page(s) hold images too small to be figures, usually "
              f"equations set as pictures, and the text path left them out: "
              f"{_page_list(small)}")
        print("   Rerun those pages with vision (without --no-vision / "
              "--ignore-small-images) to transcribe them whole.")
    elif small:
        print(f"\n{len(small)} page(s) had a text layer plus images too small to be figures, "
              f"usually equations set as pictures, so they were transcribed whole: "
              f"{_page_list(small)}")

    if result.truncated:
        print(f"\n!! {len(result.truncated)} page(s) were cut off at the model's output limit "
              f"and are incomplete: {', '.join(str(n) for n in result.truncated)}")
        print("   Each one ends with a note saying so, and --verify flags it. Finish those "
              "pages by hand from the PDF (edit <work-dir>/pages/NNNN.md).")

    if result.failed:
        print(f"\n!! {len(result.failed)} page(s) produced no transcription and are NOT in "
              f"the output: {', '.join(str(n) for n in result.failed)}")
        print("   Rerun the same command to retry just those pages.")

    print(f"\nWrote {result.output}  ({result.output.stat().st_size / 1024:.0f} KB)")
    print(f"Work dir -> {opts.resolved_work_dir()}  (delete it to force a full re-run)")

    if result.stopped_reason == "budget":
        print(f"\n!! Stopped early: spending cap of {Meter.usd(opts.budget_usd)} reached.")
        return 2
    if result.stopped_reason == "DailyQuotaExceeded":
        print("\n!! Stopped early: this key hit its per-day quota for this model.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
