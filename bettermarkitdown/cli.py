"""Flag-driven CLI, for scripting and repeat runs.

With no arguments at all, `bettermarkitdown` starts the interactive wizard
instead (see wizard.py). Other commands:

    bettermarkitdown app                         the setup page, in your browser
    bettermarkitdown providers
    bettermarkitdown key set|test|forget|status [PROVIDER]
    bettermarkitdown system | doctor              [--json]
    bettermarkitdown local status|install|pull|test|setup [MODEL]
"""

from __future__ import annotations

import argparse
import contextlib
import sys
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
from .core import Meter, convert, list_models
from .providers import PROVIDERS, get_provider, known_price, model_note


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
    parser.add_argument("--fresh", action="store_true",
                        help="redo pages already finished. Overwrites hand edits in the "
                             "work dir")
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


def print_toc(pdf: Path) -> int:
    import pymupdf

    from .core import outline_ranges

    with pymupdf.open(pdf) as doc:
        entries = outline_ranges(doc)
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


def print_providers() -> int:
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
        return print_providers()
    if argv[0] == "key":
        return key_command(argv[1:])
    if argv[0] in ("system", "doctor"):
        return system_command(argv[0], argv[1:])
    if argv[0] == "app":
        from .app import launch
        return launch(argv[1:])
    if argv[0] == "local":
        from .local.commands import main as local_main
        return local_main(argv[1:])

    args = build_parser().parse_args(argv)
    try:
        provider, base_url = resolve_endpoint(args.provider, args.base_url)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    api_key = get_api_key(provider=provider.id)
    no_key = (f"No {provider.name} key. Run `bettermarkitdown key set {provider.id}`, set "
              f"{' or '.join(provider.key_env) or 'a key'}, or pass --no-vision.")

    if args.list_models:
        if not api_key and provider.needs_key:
            print(no_key, file=sys.stderr)
            return 1
        for name in list_models(api_key, base_url, provider=provider.id):
            print(describe_model(name))
        return 0

    if not args.pdf:
        build_parser().error("the following arguments are required: pdf")

    pdf = Path(args.pdf).expanduser().resolve()
    if not pdf.is_file():
        print(f"Not found: {pdf}", file=sys.stderr)
        return 1
    from . import formats
    suffix = pdf.suffix.lower()
    if suffix not in formats.SUPPORTED:
        print(f"Cannot read {suffix or 'files without an extension'}. Supported: "
              f"{', '.join(sorted(formats.SUPPORTED))}.", file=sys.stderr)
        return 1
    through_pdf = suffix != ".pdf" and args.as_pages
    if suffix != ".pdf" and (args.toc or args.verify):
        print("--toc and --verify read a PDF. For this file, convert with --as-pages first, "
              "then run them on the PDF in the work folder.", file=sys.stderr)
        return 1

    if args.toc:
        return print_toc(pdf)

    if args.verify:
        import pymupdf

        from .core import parse_pages
        from .verify import add_render_check, format_report, verify

        output = (Path(args.output).expanduser().resolve() if args.output
                  else pdf.with_suffix(".md"))
        work_dir = (Path(args.work_dir).expanduser().resolve() if args.work_dir
                    else output.parent / (output.stem + "_work"))
        if not (work_dir / "pages").is_dir():
            print(f"No converted pages in {work_dir}. Pass the same -o / --work-dir "
                  "you converted with.", file=sys.stderr)
            return 1
        with pymupdf.open(pdf) as doc:
            total = doc.page_count
        results = verify(pdf, work_dir, parse_pages(args.pages, total))
        render_note = add_render_check(results, work_dir)
        print(format_report(results, render_note=render_note))
        return 3 if any(r.flagged for r in results) else 0

    if not api_key and not args.no_vision and provider.needs_key:
        print(no_key, file=sys.stderr)
        return 1

    model = get_model(args.model, provider.id)
    if not model and not args.no_vision:
        print(f"{provider.name} has no default model. Pick one with --model "
              f"(--list-models --provider {provider.id} lists them).", file=sys.stderr)
        return 1
    model = model or DEFAULT_MODEL
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
        dpi=args.dpi, max_edge=args.max_edge, min_chars=args.min_chars,
        min_figure_pt=args.min_figure_pt, figure_pad=args.figure_pad,
        ignore_small_images=args.ignore_small_images,
        workers=workers, rpm=rpm, budget_usd=args.budget_usd,
        price_in=args.price_in, price_out=args.price_out, estimate=args.estimate,
        no_vision=args.no_vision, save_images=args.save_images,
        ocr_fallback=args.ocr_fallback and ocr.available(), fresh=args.fresh,
    )

    run = convert
    if suffix in formats.NATIVE and not through_pdf:
        run = formats.convert_office
    elif suffix in formats.LEGACY and not through_pdf:
        # Saved as DOCX / PPTX first: through PDF, every table would come out flattened.
        modern = opts.resolved_work_dir() / (pdf.stem + formats.modern_suffix(pdf))
        if not modern.is_file() or modern.stat().st_mtime < pdf.stat().st_mtime:
            print(f"Opening {pdf.name} to save it as {modern.suffix}...", flush=True)
            try:
                used = formats.office_convert(pdf, modern, modern.suffix[1:])
            except formats.ConverterMissing as exc:
                print(exc, file=sys.stderr)
                return 1
            print(f"  done, with {used}", flush=True)
        opts.pdf = modern
        opts.title = opts.title or pdf.stem
        original = pdf

        def run(opts, on_event=None):
            return formats.convert_office(opts, on_event, original=original)
    elif through_pdf:
        as_pdf = opts.resolved_work_dir() / f"{pdf.stem}.pdf"
        if not as_pdf.is_file() or as_pdf.stat().st_mtime < pdf.stat().st_mtime:
            print(f"Turning {pdf.name} into a PDF...", flush=True)
            try:
                used = formats.office_to_pdf(pdf, as_pdf)
            except formats.ConverterMissing as exc:
                print(exc, file=sys.stderr)
                return 1
            print(f"  done, with {used}", flush=True)
        opts.pdf = as_pdf
        opts.title = opts.title or pdf.stem

    def on_event(name: str, payload: dict) -> None:
        if name == "start" and run is not convert:
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
        print("\nInterrupted - finished pages are kept, rerun to resume.")
        return 130
    except Exception as exc:
        print(f"Failed: {exc}", file=sys.stderr)
        return 1

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
