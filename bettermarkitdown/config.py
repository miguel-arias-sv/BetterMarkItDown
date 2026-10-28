"""Configuration, credentials and pricing.

No secret is ever hard-coded here. A key is read at runtime from the environment,
a local .env file that is gitignored, or the operating system's password store.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from . import credentials
from .providers import (
    DEFAULT_PROVIDER,
    GEMINI_BASE_URL,
    PROVIDERS,
    Provider,
    get_provider,
    infer_provider,
    known_price,
)

DEFAULT_MODEL = PROVIDERS[DEFAULT_PROVIDER].default_model


def get_base_url(explicit: str | None = None) -> str:
    """Resolve the endpoint from a flag or the environment, else Gemini's."""
    if explicit:
        return explicit.strip()
    load_dotenv()
    for name in ("BMID_BASE_URL", "OPENAI_BASE_URL"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return GEMINI_BASE_URL


def resolve_endpoint(provider: str | None = None,
                     base_url: str | None = None) -> tuple[Provider, str]:
    """Which provider to talk to, and at what URL.

    An explicit --base-url wins, and names its provider unless --provider is also
    given. Then --provider or $BMID_PROVIDER, at that provider's own URL. Then
    $BMID_BASE_URL. Gemini is the default, as it was before providers existed.
    """
    load_dotenv()
    provider = provider or os.environ.get("BMID_PROVIDER", "").strip() or None
    if base_url:
        spec = get_provider(provider) if provider else infer_provider(base_url)
        return spec, base_url.strip()
    if provider:
        spec = get_provider(provider)
        url = spec.base_url or get_base_url()
        if url == GEMINI_BASE_URL and spec.id != "gemini":
            raise ValueError(f"{spec.name} needs an endpoint: pass --base-url or set "
                             "BMID_BASE_URL.")
        return spec, url
    url = get_base_url()
    return infer_provider(url), url

# Used when a Gemini model is not in the price table: the current Flash rate.
# Override per run with --price-in / --price-out.
PRICES: dict[str, tuple[float, float]] = PROVIDERS["gemini"].models
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


def get_model(explicit: str | None = None) -> str:
    """Resolve the model name. BMID_MODEL lets you set a default per machine."""
    if explicit:
        return explicit.strip()
    load_dotenv()
    value = os.environ.get("BMID_MODEL", "").strip()
    return value or DEFAULT_MODEL


def find_api_key(provider: str = DEFAULT_PROVIDER) -> tuple[str | None, str]:
    """(key, where it came from) for one provider.

    Only that provider's own variables are read: before 1.5 the Gemini key was
    read first whatever the endpoint, so it could be sent to OpenAI's server.
    """
    spec = get_provider(provider)
    load_dotenv()
    for name in spec.key_env:
        value = os.environ.get(name, "").strip()
        if value:
            return value, name
    stored = credentials.stored_key(spec.id)
    if stored:
        return stored, "password store"
    return None, ""


def get_api_key(explicit: str | None = None,
                provider: str = DEFAULT_PROVIDER) -> str | None:
    """Resolve the API key. Never logs or returns it anywhere user-visible."""
    if explicit:
        return explicit.strip()
    return find_api_key(provider)[0]


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
    title: str | None = None          # the output's # heading; default: the PDF's file name

    model: str = DEFAULT_MODEL
    reasoning: str = "none"
    api_key: str | None = None
    base_url: str = GEMINI_BASE_URL
    provider: str | None = None       # a PROVIDERS id; None: inferred from base_url

    dpi: int = 200
    max_edge: int = 1568
    min_chars: int = 120
    min_figure_pt: float = 60.0
    figure_pad: float = 22.0
    # Pages with a text layer and images too small to be figures (usually equations
    # set as pictures) go to full-page vision. True keeps them on the free text path.
    ignore_small_images: bool = False

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

    def is_gemini(self) -> bool:
        if self.provider:
            return self.provider == "gemini"
        return self.base_url.rstrip("/") == GEMINI_BASE_URL.rstrip("/")

    def provider_spec(self) -> Provider:
        return get_provider(self.provider) if self.provider else infer_provider(self.base_url)

    def prices(self) -> tuple[float, float]:
        listed = known_price(self.model)
        if listed:
            base = listed
        elif self.is_gemini():
            base = FALLBACK_PRICE
        else:
            # An endpoint we have no price list for - a local model, or another
            # provider. Reporting Gemini's rates there would be a fiction; $0 is
            # right for local and honest about being unknown otherwise. Set real
            # numbers with --price-in / --price-out.
            base = (0.0, 0.0)
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
    truncated: list[int] = field(default_factory=list)   # cut off at the output-token cap
    pages_small_images: list[int] = field(default_factory=list)  # images below figure size
    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    stopped_reason: str = ""
    unit: str = "page"          # what the counts above count: pages, or pictures (DOCX/PPTX)
