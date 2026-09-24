"""Flag-driven CLI, for scripting and repeat runs.

With no arguments at all, `bettermarkitdown` starts the interactive wizard
instead (see wizard.py).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import ocr
from .config import (
    DEFAULT_MODEL,
    GEMINI_BASE_URL,
    Options,
    get_api_key,
    get_base_url,
    get_model,
)
from .core import Meter, convert, list_models


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bettermarkitdown",
        description="Convert image-heavy and scanned PDFs to Markdown with "
                    "MarkItDown + Gemini vision.")
    parser.add_argument("pdf", nargs="?", help="input PDF (omit for the interactive wizard)")
    parser.add_argument("-o", "--output", help="output .md (default: alongside the PDF)")
    parser.add_argument("--pages", help="1-based selection: '5', '10-40', '1,5,9-12'")
    parser.add_argument("--work-dir", help="where to keep per-page Markdown and the response "
                                           "cache; point it at a local disk when the output "
                                           "lives in a synced folder")

    parser.add_argument("--model", default=None,
                        help=f"default: {DEFAULT_MODEL}, or $BMID_MODEL if set")
    parser.add_argument("--base-url",
                        help="OpenAI-compatible endpoint to use instead of Gemini, e.g. "
                             "http://localhost:11434/v1 for Ollama. Also read from "
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
    parser.add_argument("--figure-pad", type=float, default=22.0,
                        help="margin around figure crops so captions come along (default 22)")

    parser.add_argument("--workers", type=int, default=3, help="parallel pages (default 3)")
    parser.add_argument("--rpm", type=int, default=60, help="max requests per minute")

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
    parser.add_argument("--fresh", action="store_true", help="redo pages already finished")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        from .wizard import main as wizard_main
        return wizard_main()

    args = build_parser().parse_args(argv)
    api_key = get_api_key()
    base_url = get_base_url(args.base_url)
    gemini = base_url.rstrip("/") == GEMINI_BASE_URL.rstrip("/")

    if args.list_models:
        if not api_key and gemini:
            print("No API key. Set GEMINI_API_KEY or create a .env file.", file=sys.stderr)
            return 1
        for name in list_models(api_key, base_url):
            print(name)
        return 0

    if not args.pdf:
        build_parser().error("the following arguments are required: pdf")

    pdf = Path(args.pdf).expanduser().resolve()
    if not pdf.is_file():
        print(f"Not found: {pdf}", file=sys.stderr)
        return 1

    if not api_key and not args.no_vision and gemini:
        print("No API key. Set GEMINI_API_KEY, create a .env file, or pass --no-vision.",
              file=sys.stderr)
        return 1

    opts = Options(
        pdf=pdf,
        output=(Path(args.output).expanduser().resolve() if args.output
                else pdf.with_suffix(".md")),
        work_dir=Path(args.work_dir).expanduser().resolve() if args.work_dir else None,
        pages=args.pages, model=get_model(args.model), reasoning=args.reasoning,
        api_key=api_key,
        base_url=base_url,
        dpi=args.dpi, max_edge=args.max_edge, min_chars=args.min_chars,
        min_figure_pt=args.min_figure_pt, figure_pad=args.figure_pad,
        workers=args.workers, rpm=args.rpm, budget_usd=args.budget_usd,
        price_in=args.price_in, price_out=args.price_out, estimate=args.estimate,
        no_vision=args.no_vision, save_images=args.save_images,
        ocr_fallback=args.ocr_fallback and ocr.available(), fresh=args.fresh,
    )

    def on_event(name: str, payload: dict) -> None:
        if name == "start":
            print(f"{opts.pdf.name}: {payload['total']} pages, converting "
                  f"{payload['selected']} ({payload['done']} already done), "
                  f"model={opts.model}, workers={opts.workers}", flush=True)
        elif name == "page_done":
            tag = " [local OCR]" if payload.get("ocr") else ""
            print(f"  [{payload['done']}/{payload['total']}] page {payload['page']} "
                  f"done{tag}", flush=True)
        elif name == "page_failed":
            print(f"  !! {payload['message']} - left unwritten, rerun to retry", flush=True)

    try:
        result = convert(opts, on_event)
    except KeyboardInterrupt:
        print("\nInterrupted - finished pages are kept, rerun to resume.")
        return 130
    except Exception as exc:
        print(f"Failed: {exc}", file=sys.stderr)
        return 1

    if result.calls:
        print(f"\nSpend: {result.calls} vision calls | {result.tokens_in:,} in + "
              f"{result.tokens_out:,} out tokens | {Meter.usd(result.cost)}")
        per_page = result.cost / max(1, result.pages_converted)
        print(f"       {Meter.usd(per_page)} per page over {result.pages_converted} page(s)")
        remaining = result.pages_selected - result.pages_converted
        if remaining > 0:
            print(f"       ~{Meter.usd(per_page * remaining)} to finish the remaining "
                  f"{remaining} page(s); ~{Meter.usd(per_page * result.pages_total)} for "
                  f"all {result.pages_total} pages")

    if result.pages_ocr:
        print(f"\nLocal OCR was used for {len(result.pages_ocr)} page(s): "
              f"{', '.join(str(n) for n in result.pages_ocr)}")
        print("   The model refused these (usually its recitation filter). Layout is "
              "flattened and notation is unreliable there.")

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
