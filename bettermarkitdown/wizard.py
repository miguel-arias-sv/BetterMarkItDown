"""Interactive terminal wizard: paste a path, answer a few questions, watch it run.

Run with no arguments (`bettermarkitdown` or `python -m bettermarkitdown`) and you
land here. Everything it asks has a sensible default, so pressing Enter through
the whole thing is a valid way to use it.
"""

from __future__ import annotations

import sys
from pathlib import Path

from rich.align import Align
from rich.console import Console, Group
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table
from rich.text import Text

from . import ocr
from .config import DEFAULT_MODEL, PRICES, Options, get_api_key, redact
from .core import Meter, convert, list_models

console = Console()

BANNER_WIDE = r"""
 ____       _   _            __  __            _    ___ _   ____
| __ )  ___| |_| |_ ___ _ __|  \/  | __ _ _ __| | _|_ _| |_|  _ \ _____      ___ __
|  _ \ / _ \ __| __/ _ \ '__| |\/| |/ _` | '__| |/ /| || __| | | |/ _ \ \ /\ / / '_ \
| |_) |  __/ |_| ||  __/ |  | |  | | (_| | |  |   < | || |_| |_| | (_) \ V  V /| | | |
|____/ \___|\__|\__\___|_|  |_|  |_|\__,_|_|  |_|\_\___|\__|____/ \___/ \_/\_/ |_| |_|
"""

BANNER_NARROW = r"""
  ___       _   _
 | _ ) ___ | |_| |_ ___ _ _
 | _ \/ -_)|  _|  _/ -_) '_|
 |___/\___| \__|\__\___|_|
  MarkItDown
"""


def _banner() -> str:
    """The wide banner is 86 columns; anything narrower must not wrap."""
    return BANNER_WIDE if console.width >= 90 else BANNER_NARROW


def _clean_path(raw: str) -> Path:
    """Accept what a terminal actually gives you: quotes, drag-and-drop, stray spaces."""
    return Path(raw.strip().strip('"').strip("'")).expanduser()


def _ask_pdf() -> Path:
    while True:
        raw = Prompt.ask("\n[bold cyan]PDF to convert[/] [dim](paste the full path)[/]")
        if not raw.strip():
            continue
        path = _clean_path(raw)
        if path.is_file() and path.suffix.lower() == ".pdf":
            return path.resolve()
        console.print(f"  [red]Not a PDF file:[/] {path}")


def _inspect(pdf: Path) -> tuple[int, int, int]:
    """Return (pages, scanned_pages, embedded_images) without spending anything."""
    import re

    import pymupdf

    doc = pymupdf.open(pdf)
    scanned = 0
    images = 0
    for page in doc:
        if len(re.sub(r"\s", "", page.get_text("text"))) < 120:
            scanned += 1
        images += len(page.get_images(full=True))
    total = doc.page_count
    doc.close()
    return total, scanned, images


def _report_inspection(pdf: Path, total: int, scanned: int, images: int) -> None:
    table = Table(box=None, padding=(0, 2))
    table.add_column(style="dim")
    table.add_column()
    table.add_row("File", pdf.name)
    table.add_row("Pages", str(total))
    table.add_row("Scanned pages", f"{scanned}  [dim](no text layer -> full-page vision)[/]")
    table.add_row("Text pages", f"{total - scanned}  [dim](MarkItDown text + figure crops)[/]")
    table.add_row("Embedded images", str(images))

    if scanned == total:
        verdict = Text("Fully scanned. Plain MarkItDown would produce an empty file.",
                       style="yellow")
    elif scanned == 0:
        verdict = Text("Born-digital. Text is extracted free; you only pay for figures.",
                       style="green")
    else:
        verdict = Text("Mixed. Each page is routed by whether it has a text layer.",
                       style="cyan")

    console.print(Panel(Group(table, Text(), verdict), title="[bold]What is in this PDF[/]",
                        border_style="cyan", expand=False))


def _ask_model(api_key: str | None) -> str:
    if not Confirm.ask(f"\nUse the default model [bold]{DEFAULT_MODEL}[/]?", default=True):
        if api_key:
            with console.status("[cyan]Asking Google which models your key can call..."):
                try:
                    models = list_models(api_key)
                except Exception as exc:
                    models = []
                    console.print(f"  [yellow]Could not list models:[/] {exc}")
            if models:
                for name in models:
                    price = PRICES.get(name)
                    cost = f"  [dim]${price[0]}/${price[1]} per 1M[/]" if price else ""
                    console.print(f"  [green]-[/] {name}{cost}")
        return Prompt.ask("Model", default=DEFAULT_MODEL)
    return DEFAULT_MODEL


def run_wizard() -> int:
    console.print(Align.center(Text(_banner(), style="bold cyan")))
    console.print(Align.center(
        Text("MarkItDown + Gemini vision, for PDFs whose content lives in the pictures\n",
             style="dim")))

    api_key = get_api_key()
    if api_key:
        console.print(f"[green]API key loaded[/] [dim]({redact(api_key)})[/]")
    else:
        console.print("[yellow]No API key found.[/] Set GEMINI_API_KEY or create a .env "
                      "file (see .env.example).")
        console.print("[dim]You can still run a text-only pass with no API calls.[/]")

    pdf = _ask_pdf()

    with console.status("[cyan]Inspecting the PDF..."):
        total, scanned, images = _inspect(pdf)
    _report_inspection(pdf, total, scanned, images)

    default_out = pdf.parent / f"{pdf.stem}.md"
    raw_out = Prompt.ask("\n[bold cyan]Save Markdown to[/]", default=str(default_out))
    output = _clean_path(raw_out).resolve()

    pages = Prompt.ask("[bold cyan]Pages[/] [dim](all, or 10-40, or 1,5,9-12)[/]",
                       default="all")
    pages = None if pages.strip().lower() in ("", "all") else pages.strip()

    model = _ask_model(api_key) if api_key else DEFAULT_MODEL
    no_vision = not api_key

    workers = IntPrompt.ask("[bold cyan]Parallel pages[/]", default=3)
    dpi = IntPrompt.ask("[bold cyan]Render DPI[/] [dim](300 for small or ornate type)[/]",
                        default=200)

    work_dir = None
    if "My Drive" in str(output) or "OneDrive" in str(output) or "Dropbox" in str(output):
        console.print("\n[yellow]That output folder looks like a synced drive.[/]")
        if Confirm.ask("Keep the page cache on a local disk instead?", default=True):
            work_dir = Path.home() / ".bmid_work" / pdf.stem

    opts = Options(pdf=pdf, output=output, work_dir=work_dir, pages=pages, model=model,
                   dpi=dpi, workers=workers, api_key=api_key, no_vision=no_vision,
                   save_images=False, ocr_fallback=ocr.available())

    if not opts.ocr_fallback:
        console.print("[dim]Local OCR fallback unavailable "
                      "(pip install rapidocr-onnxruntime to enable it).[/]")

    budget = Prompt.ask("\n[bold cyan]Spending cap in USD[/] [dim](Enter for none)[/]",
                        default="")
    try:
        opts.budget_usd = float(budget) if budget.strip() else 0.0
    except ValueError:
        opts.budget_usd = 0.0

    console.print()
    if not Confirm.ask(f"Convert [bold]{pages or total}[/] page(s) of "
                       f"[bold]{pdf.name}[/]?", default=True):
        console.print("[yellow]Cancelled.[/]")
        return 1

    return _run(opts)


def _run(opts: Options) -> int:
    """Drive the conversion with a live progress display."""
    progress = Progress(
        SpinnerColumn(style="cyan"),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=None, complete_style="green", finished_style="green"),
        MofNCompleteColumn(),
        TextColumn("[dim]{task.fields[note]}"),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=False,
    )
    state = {"task": None, "ocr": 0, "failed": 0}

    def on_event(name: str, payload: dict) -> None:
        if name == "start":
            state["task"] = progress.add_task(
                "Converting", total=payload["selected"],
                completed=payload["done"], note="")
        elif name == "page_done":
            if payload.get("ocr"):
                state["ocr"] += 1
            progress.update(state["task"], advance=1,
                            note=f"page {payload['page']}"
                                 + (f" | {state['ocr']} via local OCR" if state["ocr"] else ""))
        elif name == "page_failed":
            state["failed"] += 1
            progress.console.print(f"  [yellow]![/] {payload['message']}")

    console.print()
    with progress:
        try:
            result = convert(opts, on_event)
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted.[/] Finished pages are kept - "
                          "run again to resume.")
            return 130
        except Exception as exc:
            console.print(f"\n[red]Failed:[/] {exc}")
            return 1

    summary = Table(box=None, padding=(0, 2))
    summary.add_column(style="dim")
    summary.add_column()
    summary.add_row("Output", str(result.output))
    summary.add_row("Size", f"{result.output.stat().st_size / 1024:.0f} KB")
    summary.add_row("Pages converted", f"{result.pages_converted} of {result.pages_selected}")
    if result.pages_ocr:
        summary.add_row("Local OCR pages",
                        ", ".join(str(n) for n in result.pages_ocr)
                        + "  [dim](model refused; notation unreliable)[/]")
    if result.failed:
        summary.add_row("[yellow]Not converted[/]",
                        ", ".join(str(n) for n in result.failed) + "  [dim](rerun to retry)[/]")
    if result.calls:
        summary.add_row("API calls", str(result.calls))
        summary.add_row("Tokens", f"{result.tokens_in:,} in / {result.tokens_out:,} out")
        summary.add_row("Cost", f"[bold green]{Meter.usd(result.cost)}[/]")
        per_page = result.cost / max(1, result.pages_converted)
        summary.add_row("Per page", Meter.usd(per_page))

    border = "yellow" if (result.failed or result.stopped_reason) else "green"
    title = "[bold]Stopped early[/]" if result.stopped_reason else "[bold]Done[/]"
    console.print(Panel(summary, title=title, border_style=border, expand=False))

    if result.stopped_reason == "budget":
        console.print("[yellow]Spending cap reached.[/] Rerun with a higher cap to continue; "
                      "finished pages are cached and will not be paid for twice.")
    if result.failed:
        console.print("[yellow]Some pages produced no transcription.[/] They are left out of "
                      "the file so a rerun retries them.")
    return 0


def main() -> int:
    try:
        return run_wizard()
    except (KeyboardInterrupt, EOFError):
        console.print("\n[yellow]Cancelled.[/]")
        return 130


if __name__ == "__main__":
    sys.exit(main())
