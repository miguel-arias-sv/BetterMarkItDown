"""Configuration, credentials and pricing.

No secret is ever hard-coded here. The key is read at runtime from the
environment or from a local .env file that is gitignored.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Gemini speaks the OpenAI protocol at this base URL, so the `openai` client
# library works against it unchanged - which is also what MarkItDown expects.
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

DEFAULT_MODEL = "gemini-3.6-flash"

# Paid-tier list prices, USD per 1M tokens.
# Source: https://ai.google.dev/gemini-api/docs/pricing (checked 2026-09-21).
# The 3.x Flash rates are promotional through 2026-12-31 and double on
# 2027-01-01. Override per run with --price-in / --price-out.
PRICES: dict[str, tuple[float, float]] = {
    "gemini-3.8-flash":      (0.75, 3.75),
    "gemini-3.6-flash":      (0.75, 3.75),
    "gemini-3.5-flash":      (1.50, 9.00),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.1-flash-lite": (0.30, 2.50),
    "gemini-2.5-flash":      (0.30, 2.50),
}
FALLBACK_PRICE = (0.75, 3.75)


def load_dotenv(start: Path | None = None) -> None:
    """Load KEY=VALUE lines from the nearest .env into os.environ.

    Deliberately tiny: no dependency, and it never overwrites a variable that is
    already set, so a real environment variable always wins over the file.
    """
    here = (start or Path.cwd()).resolve()
    for folder in (here, *here.parents):
        env = folder / ".env"
        if not env.is_file():
            continue
        for raw in env.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value
        return


def get_api_key(explicit: str | None = None) -> str | None:
    """Resolve the API key. Never logs or returns it anywhere user-visible."""
    if explicit:
        return explicit.strip()
    load_dotenv()
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


def redact(key: str | None) -> str:
    """Show only enough of a key to confirm which one is loaded."""
    if not key:
        return "(none)"
    return key[:6] + "..." + key[-4:] if len(key) > 14 else "(set)"


@dataclass
class Options:
    """Everything one conversion run needs. The CLI and the wizard both build this."""

    pdf: Path
    output: Path
    work_dir: Path | None = None
    pages: str | None = None

    model: str = DEFAULT_MODEL
    reasoning: str = "none"
    api_key: str | None = None

    dpi: int = 200
    max_edge: int = 1568
    min_chars: int = 120
    min_figure_pt: float = 60.0
    figure_pad: float = 22.0

    workers: int = 3
    rpm: int = 60

    budget_usd: float = 0.0
    price_in: float | None = None
    price_out: float | None = None
    estimate: int = 0

    no_vision: bool = False
    save_images: bool = True
    ocr_fallback: bool = True
    fresh: bool = False

    def resolved_work_dir(self) -> Path:
        return self.work_dir or self.output.parent / (self.output.stem + "_work")

    def assets_dir(self) -> Path:
        return self.output.parent / (self.output.stem + "_assets")

    def prices(self) -> tuple[float, float]:
        base = PRICES.get(self.model, FALLBACK_PRICE)
        return (self.price_in if self.price_in is not None else base[0],
                self.price_out if self.price_out is not None else base[1])


@dataclass
class Result:
    """What a run produced, for the CLI/wizard to report."""

    output: Path
    pages_total: int = 0
    pages_selected: int = 0
    pages_converted: int = 0
    pages_ocr: list[int] = field(default_factory=list)
    failed: list[int] = field(default_factory=list)
    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    stopped_reason: str = ""
