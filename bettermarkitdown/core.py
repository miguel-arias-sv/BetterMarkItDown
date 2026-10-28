"""The conversion engine.

MarkItDown's `llm_client` / `llm_model` options describe standalone image files
and images inside .pptx/.docx. Its PDF path is pure text extraction
(pdfplumber -> pdfminer.six): it never looks at the images inside a PDF and never
calls the LLM. On a scanned book, or a book full of graphs, that silently drops
exactly the content you care about.

So MarkItDown stays the text engine, page by page, and this module adds the
vision layer around it:

    page has a text layer  -> MarkItDown extracts it, then each figure (embedded
                              raster images AND vector-drawn charts) is cropped
                              and sent to the model for a description plus a data
                              table read off the axes
    page has no text layer -> the whole page is rendered and transcribed
    page has a text layer AND images too small to be figures (publishers often set
    every equation as a picture) -> also transcribed whole, because the text path
    would drop those equations without a trace
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

from . import ocr as local_ocr
from .config import GEMINI_BASE_URL, Options, Result
from .prompts import FIGURE_PROMPT, PAGE_PROMPT
from .providers import (
    DailyQuotaExceeded,
    as_vision_client,
    get_provider,
    infer_provider,
    make_client,
)

Event = Callable[[str, dict], None]


class BudgetExceeded(RuntimeError):
    """budget_usd reached; stop before spending more."""


class PageFailed(RuntimeError):
    """Vision produced nothing for a page and no fallback recovered it."""


# Each run has its own stop signal (a threading.Event), passed down as `abort`: the
# budget, a daily quota or the page's Stop button sets it, and only that run stops.
# The setup page's server can run a conversion next to a speed test, so one shared
# flag would let either stop, or restart, the other.

# Output-token caps, tried in order. Almost every page fits in the first; a dense
# full-page table does not, and a reply cut off at the cap used to be cached as if
# it were the whole page. The larger cap is only paid for when it is needed.
MAX_TOKENS = (4096, 16384)
# Marks a reply that was still cut off at the largest cap. verify.py flags any page
# carrying it, and the run summary lists it.
TRUNCATED_TAG = "<!-- bmid: truncated -->"
TRUNCATION_NOTE = (f"\n\n{TRUNCATED_TAG}\n*[transcription cut off: the model reached its "
                   "output limit before the end of this page, so the rest of it is missing. "
                   "Check the PDF.]*")


# ---------------------------------------------------------------------------
# Plumbing
# ---------------------------------------------------------------------------
class RateLimiter:
    """Requests-per-minute throttle shared across worker threads."""

    def __init__(self, rpm: int):
        self.min_interval = 60.0 / rpm if rpm > 0 else 0.0
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        if not self.min_interval:
            return
        with self._lock:
            now = time.monotonic()
            sleep_for = max(0.0, self._next - now)
            self._next = max(now, self._next) + self.min_interval
        if sleep_for:
            time.sleep(sleep_for)


class Cache:
    """Disk cache keyed by image bytes, so a rerun never pays for the same page twice."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        try:
            self.data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            self.data = {}

    def get(self, key: str):
        with self._lock:
            return self.data.get(key)

    def put(self, key: str, value: str) -> None:
        with self._lock:
            self.data[key] = value
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data), encoding="utf-8")
            tmp.replace(self.path)


class Meter:
    """Counts tokens actually billed and converts them to dollars.

    Gemini bills hidden thinking tokens as output, and they do NOT appear in
    completion_tokens - they are the gap between total and prompt+completion. So
    billed output is total_tokens - prompt_tokens. On a dense book page that gap
    was measured at 1574 thinking tokens against a 475-token transcription, which
    is why `reasoning="none"` is the default.
    """

    def __init__(self, price_in: float, price_out: float, budget: float = 0.0,
                 abort: threading.Event | None = None):
        self._lock = threading.Lock()
        self.price_in = price_in
        self.price_out = price_out
        self.budget = budget
        self.abort = abort if abort is not None else threading.Event()
        self.calls = 0
        self.tok_in = 0
        self.tok_out = 0

    def add(self, usage) -> None:
        if usage is None:
            return
        prompt = getattr(usage, "prompt_tokens", 0) or 0
        total = getattr(usage, "total_tokens", 0) or 0
        completion = getattr(usage, "completion_tokens", 0) or 0
        with self._lock:
            self.calls += 1
            self.tok_in += prompt
            self.tok_out += max(completion, total - prompt)
            over = self.budget and self.cost() > self.budget
        if over:
            self.abort.set()

    def cost(self) -> float:
        return (self.tok_in * self.price_in + self.tok_out * self.price_out) / 1e6

    @staticmethod
    def usd(amount: float) -> str:
        return f"${amount:.4f}" if amount < 0.01 else f"${amount:.2f}"


def _retry_after(message: str) -> float:
    """Gemini says how long to wait on a 429; obey it instead of guessing."""
    match = (re.search(r"retryDelay['\"]?\s*:\s*['\"](\d+(?:\.\d+)?)s", message)
             or re.search(r"retry in (\d+(?:\.\d+)?)s", message))
    return float(match.group(1)) + 1.0 if match else 0.0


# ---------------------------------------------------------------------------
# Vision
# ---------------------------------------------------------------------------
def has_content(text: str) -> bool:
    """False for a reply that is blank or only HTML comments.

    The page prompt asks for a trailing `<!-- page number: N -->`, so a model that
    transcribes nothing can still answer `<!-- page number:  -->`. That is as empty
    as an empty string, and has to be treated as one.
    """
    return bool(re.sub(r"<!--.*?-->", "", text or "", flags=re.S).strip())


def cut_off(finish_reason: str) -> bool:
    """True when the reply stopped at the output-token cap rather than finishing.
    OpenAI-compatible servers, Gemini's included, report this as 'length'."""
    reason = (finish_reason or "").lower()
    return "length" in reason or "max_tokens" in reason


def describe_image(client, model: str, png: bytes, prompt: str, *, cache: Cache,
                   limiter: RateLimiter, meter: Meter | None = None,
                   reasoning: str = "none", max_retries: int = 5,
                   abort: threading.Event | None = None, use_cache: bool = True) -> str:
    """Transcribe one image. `client` is a providers.VisionClient, or a raw
    `openai.OpenAI` client as before 1.5. `abort` defaults to the meter's run signal.
    `use_cache=False` asks the model again even when an earlier answer is cached."""
    if abort is None:
        abort = meter.abort if meter is not None else threading.Event()
    key = hashlib.sha256(png + prompt.encode() + model.encode()
                         + str(reasoning).encode()).hexdigest()
    hit = cache.get(key) if use_cache else None
    if hit is not None and has_content(hit):   # older runs cached comment-only blanks
        return hit

    client = as_vision_client(client)
    delay = 4.0
    last_err: Exception | None = None
    step = 0                   # index into MAX_TOKENS
    partial = ""               # the longest cut-off reply so far

    for attempt in range(max_retries):
        if abort.is_set():
            raise BudgetExceeded("aborted")
        try:
            limiter.wait()
            reply = client.describe(png, prompt, model=model, max_tokens=MAX_TOKENS[step],
                                    reasoning=reasoning)
            if meter is not None:
                meter.add(reply.usage)

            text = (reply.text or "").strip()
            text = re.sub(r"^```(?:markdown)?\s*|\s*```$", "", text).strip()
            reason = reply.finish_reason

            if cut_off(reason):
                # A reply that hit the cap is incomplete, however long it looks.
                # Ask again with room to finish; if even the largest cap is not
                # enough, keep what came back but say so on the page. Never cache
                # it: a cached partial page would pass for a whole one forever.
                if has_content(text) and len(text) > len(partial):
                    partial = text
                if step + 1 < len(MAX_TOKENS):
                    step += 1
                    continue
                if partial:
                    return partial + TRUNCATION_NOTE

            if not has_content(text):
                # An empty answer is a failure, not a result. Never cache it:
                # caching a blank makes the loss permanent, because the next run
                # would "resume" straight past the page and you would never know.
                last_err = RuntimeError(f"empty response (finish_reason={reason})")
                if "content_filter" in reason or "RECITATION" in reason:
                    break          # a verdict, not a hiccup: retrying cannot help
                if attempt == max_retries - 1:
                    break
                time.sleep(delay)
                delay *= 2
                continue

            cache.put(key, text)
            return text

        except DailyQuotaExceeded:
            abort.set()
            raise
        except Exception as exc:
            last_err = exc
            message = str(exc)
            if partial and step > 0 and re.search(r"max_tokens|context|too large", message, re.I):
                # A local server whose context is smaller than the larger cap.
                return partial + TRUNCATION_NOTE
            if abort.is_set():
                raise BudgetExceeded(message) from exc
            if attempt == max_retries - 1:
                break
            time.sleep(getattr(exc, "retry_after", 0) or _retry_after(message) or delay)
            delay *= 2

    return f"*[vision call failed: {type(last_err).__name__}: {last_err}]*"


# ---------------------------------------------------------------------------
# Page rendering and extraction
# ---------------------------------------------------------------------------
def render(page, dpi: int, clip=None) -> bytes:
    import pymupdf
    pix = page.get_pixmap(matrix=pymupdf.Matrix(dpi / 72, dpi / 72), clip=clip, alpha=False)
    return pix.tobytes("png")


def shrink(png: bytes, max_edge: int = 1568) -> bytes:
    """Cap the long edge: past this the model gains nothing and you pay per pixel."""
    from PIL import Image
    img = Image.open(io.BytesIO(png))
    if max(img.size) <= max_edge:
        return png
    scale = max_edge / max(img.size)
    img = img.convert("RGB").resize(
        (max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.LANCZOS)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def markitdown_page_text(md, doc, index: int) -> str:
    """Run MarkItDown over a one-page slice of the PDF."""
    import pymupdf
    from markitdown import StreamInfo

    single = pymupdf.open()
    single.insert_pdf(doc, from_page=index, to_page=index)
    data = single.tobytes()
    single.close()
    try:
        result = md.convert_stream(
            io.BytesIO(data),
            stream_info=StreamInfo(extension=".pdf", mimetype="application/pdf"))
        return (result.text_content or "").strip()
    except Exception as exc:
        return f"*[MarkItDown failed on this page: {exc}]*"


def figure_regions(page, min_pt: float):
    """Embedded raster images, plus vector-drawing clusters (charts drawn as lines)."""
    regions = []
    seen = set()
    for info in page.get_images(full=True):
        xref = info[0]
        if xref in seen:
            continue
        seen.add(xref)
        for rect in page.get_image_rects(xref):
            if rect.width >= min_pt and rect.height >= min_pt:
                regions.append(rect)
    try:
        for rect in page.cluster_drawings():
            big_enough = rect.width >= min_pt and rect.height >= min_pt
            if big_enough and not any(rect.intersects(existing) for existing in regions):
                regions.append(rect)
    except Exception:
        # Older PyMuPDF builds have no cluster_drawings; embedded images alone
        # are still a useful answer, so a page without vector figures is fine.
        pass
    regions.sort(key=lambda r: (round(r.y0, 1), round(r.x0, 1)))
    return regions


def small_images(page, min_pt: float) -> int:
    """How many embedded images on the page are too small to be figures.

    Publishers' PDFs often set every equation as a picture: a 353 x 10 pt strip for
    a display equation, 11 x 13 pt for an inline P-hat. The text path skips them
    (they are below min_pt) and the text layer has nothing in their place, so the
    page reads cleanly with every equation missing, and --verify cannot see it
    either. Specks under 2 pt are rules and bullets, not content."""
    count = 0
    for info in page.get_image_info():
        x0, y0, x1, y1 = info["bbox"]
        w, h = x1 - x0, y1 - y0
        if min(w, h) >= 2 and min(w, h) < min_pt:
            count += 1
    return count


def outline_ranges(doc) -> list[tuple[int, str, int, int]]:
    """The PDF's outline as (level, title, first page, last page), 1-based.

    A section ends where the next entry at its level or above begins. That page is
    included when the heading sits below body text, since sections usually share
    it; when the heading opens the page (a new chapter), it is not."""
    toc = doc.get_toc(simple=False)
    out = []
    for i, (level, title, first, *_) in enumerate(toc):
        last = doc.page_count
        for later_level, _, start, later_dest in toc[i + 1:]:
            if later_level <= level:
                last = start if _text_above(doc, start, later_dest) else start - 1
                break
        out.append((level, title.strip(), first, max(first, last)))
    return out


def _text_above(doc, page_no: int, dest) -> bool:
    """True when body text precedes the heading that `dest` points to."""
    to = dest.get("to") if isinstance(dest, dict) else None
    if to is None or not 1 <= page_no <= doc.page_count:
        return True              # position unknown: keep the page, it may be shared
    page = doc[page_no - 1]
    for *_, bottom, text, _no, _kind in page.get_text("blocks"):
        # A running header or a page number is short; a paragraph is not.
        if bottom <= to.y - 2 and len(text.strip()) >= 40:
            return True
    return False


_DISPLAY = re.compile(r"(?<!\\)\$\$(.*?)(?<!\\)\$\$", re.S)
_TAG = re.compile(r"\\tag\*?\{([^{}]*)\}")


def one_tag_per_display(md: str) -> str:
    r"""KaTeX and MathJax allow one \tag per display equation. The model numbers
    each line of an `aligned` block with its own \tag, and the whole block then
    fails to render. Print those numbers as (n) at the end of their lines."""
    def fix(m: re.Match) -> str:
        body = m.group(1)
        if len(_TAG.findall(body)) < 2:
            return m.group(0)
        return "$$" + _TAG.sub(lambda t: rf"\qquad ({t.group(1)})", body) + "$$"
    return _DISPLAY.sub(fix, md)


def md_link(path: str) -> str:
    """A link target that survives spaces: CommonMark ends a bare target at the
    first space, so 'My Notes_assets/p1.png' would not display."""
    return quote(path, safe="/")


def process_page(index: int, *, pdf_path: str, md, client, opts: Options,
                 cache: Cache, limiter: RateLimiter,
                 meter: Meter) -> tuple[int, str, bool, bool, bool]:
    """Convert one page. Returns (index, markdown, used_local_ocr, truncated,
    has_small_images)."""
    import pymupdf

    doc = pymupdf.open(pdf_path)   # one handle per thread: PyMuPDF is not thread-safe
    try:
        page = doc[index]

        # The embedded text layer is the honest signal for "is this page scanned?".
        # MarkItDown's own output is not: an error message is a long string too.
        native = page.get_text("text").strip()
        scanned = len(re.sub(r"\s", "", native)) < opts.min_chars
        small = not scanned and small_images(page, opts.min_figure_pt) > 0

        text = markitdown_page_text(md, doc, index)
        if text.startswith("*[MarkItDown failed") and native:
            text = native + "\n\n<!-- text layer read by PyMuPDF: MarkItDown errored here -->"

        parts = [f"\n\n---\n\n## Page {index + 1}\n"]
        assets = opts.assets_dir()

        whole_page = scanned or (small and not opts.ignore_small_images)
        if whole_page and not opts.no_vision:
            png = shrink(render(page, opts.dpi), opts.max_edge)
            if opts.save_images:
                assets.mkdir(parents=True, exist_ok=True)
                (assets / f"page_{index + 1:04d}.png").write_bytes(png)

            body = describe_image(client, opts.model, png, PAGE_PROMPT, cache=cache,
                                  limiter=limiter, meter=meter, reasoning=opts.reasoning,
                                  use_cache=not opts.ask_again)

            if not has_content(body) or body.startswith("*[vision call failed"):
                recovered = local_ocr.ocr_page(page, opts.dpi) if opts.ocr_fallback else None
                if recovered:
                    parts.append(
                        "<!-- source: local OCR (rapidocr). The vision model returned "
                        "nothing for this page, usually its recitation/copyright filter. "
                        "Layout is flattened and any mathematical notation here is "
                        "unreliable - check it against the PDF. -->\n\n" + recovered)
                    return index, "\n".join(parts), True, False, small
                raise PageFailed(f"page {index + 1}: {body.strip() or 'empty response'}")

            body = one_tag_per_display(body)
            parts.append("<!-- source: full-page vision transcription -->\n\n" + body)
            if opts.save_images:
                parts.append(f"\n\n![Page {index + 1} scan]"
                             f"({md_link(f'{assets.name}/page_{index + 1:04d}.png')})")
            return index, "\n".join(parts), False, TRUNCATED_TAG in body, small

        parts.append(text if text else "*[no extractable text on this page]*")

        truncated = False
        if not opts.no_vision:
            for n, rect in enumerate(figure_regions(page, opts.min_figure_pt), start=1):
                # Widen the crop: axis labels, legends and captions sit just
                # outside the figure's own bounding box.
                pad = opts.figure_pad
                rect = (rect + (-pad, -pad, pad, pad)) & page.rect
                png = shrink(render(page, opts.dpi, clip=rect), opts.max_edge)
                name = f"page_{index + 1:04d}_fig_{n:02d}.png"
                assets.mkdir(parents=True, exist_ok=True)
                (assets / name).write_bytes(png)

                description = describe_image(client, opts.model, png, FIGURE_PROMPT,
                                             cache=cache, limiter=limiter, meter=meter,
                                             reasoning=opts.reasoning,
                                             use_cache=not opts.ask_again)
                truncated = truncated or TRUNCATED_TAG in description
                quoted = quote_block(description)
                parts.append(
                    f"\n\n![Page {index + 1}, figure {n}]({md_link(f'{assets.name}/{name}')})"
                    f"\n\n**Figure {index + 1}.{n} - transcribed by {opts.model}:**\n\n{quoted}")

        return index, "\n".join(parts), False, truncated, small
    finally:
        doc.close()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def parse_pages(spec: str | None, total: int) -> list[int]:
    """'3', '10-40', '1,5,9-12' -> sorted 0-based page indices."""
    if not spec:
        return list(range(total))
    out: set[int] = set()
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            first, last = chunk.split("-", 1)
            out.update(range(int(first) - 1, int(last)))
        else:
            out.add(int(chunk) - 1)
    return sorted(p for p in out if 0 <= p < total)


def list_models(api_key: str | None, base_url: str = GEMINI_BASE_URL,
                provider: str | None = None) -> list[str]:
    spec = get_provider(provider) if provider else infer_provider(base_url)
    return make_client(spec, api_key, base_url).list_models()


def vision_client(opts: Options):
    """The run's vision client, or None with no_vision. Refuses to start without a key
    for a provider that needs one, rather than failing on the first page."""
    if opts.no_vision:
        return None
    spec = opts.provider_spec()
    if not opts.api_key and spec.needs_key:
        raise RuntimeError(f"No API key for {spec.name}. Run `bettermarkitdown key set "
                           f"{spec.id}`, set {' or '.join(spec.key_env)}, or use no_vision.")
    return make_client(spec, opts.api_key, opts.base_url)


def quote_block(text: str) -> str:
    """Markdown blockquote, keeping blank lines inside it."""
    return "\n".join("> " + line if line.strip() else ">" for line in text.splitlines())


def assemble_output(output: Path, pages_dir: Path, *, title: str, source_name: str,
                    model: str, note: str = "") -> None:
    """Write the output .md from every page file in `pages_dir`, in page order."""
    header = (f"# {title}\n\n{note}<!-- Converted from {source_name} with BetterMarkItDown "
              f"({model}) on {time.strftime('%Y-%m-%d %H:%M')} -->\n")
    body = [f.read_text(encoding="utf-8")
            for f in sorted(pages_dir.glob("[0-9][0-9][0-9][0-9].md"))]
    tmp = output.with_suffix(".md.tmp")
    tmp.write_text(header + "".join(body) + "\n", encoding="utf-8", newline="\n")
    tmp.replace(output)


def convert(opts: Options, on_event: Event | None = None,
            abort: threading.Event | None = None) -> Result:
    """Convert a PDF to Markdown. `on_event(name, payload)` reports progress. Setting
    `abort` stops the run: pages in progress are left unwritten, for a rerun."""
    import pymupdf
    from markitdown import MarkItDown

    abort = abort if abort is not None else threading.Event()

    def emit(name: str, **payload):
        if on_event:
            on_event(name, payload)

    work_dir = opts.resolved_work_dir()
    pages_dir = work_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    opts.output.parent.mkdir(parents=True, exist_ok=True)

    client = vision_client(opts)

    # MarkItDown still receives an OpenAI-protocol client when there is one: unused on
    # the PDF path, but it is what makes md.convert("figure.png") work if you reuse
    # this object for images.
    openai_protocol = client is not None and opts.provider_spec().protocol == "openai"
    llm = getattr(client, "sdk", None) if openai_protocol else None
    md = (MarkItDown(enable_plugins=False, llm_client=llm, llm_model=opts.model)
          if llm else MarkItDown(enable_plugins=False))

    doc = pymupdf.open(opts.pdf)
    total = doc.page_count
    doc.close()

    targets = parse_pages(opts.pages, total)
    if not targets:
        raise RuntimeError("No pages selected.")

    price_in, price_out = opts.prices()
    meter = Meter(price_in, price_out, opts.budget_usd, abort)
    cache = Cache(work_dir / "cache.json")
    limiter = RateLimiter(opts.rpm)

    todo = [p for p in targets
            if opts.fresh or not (pages_dir / f"{p + 1:04d}.md").exists()]
    already_done = len(targets) - len(todo)
    if opts.estimate:
        todo = todo[:opts.estimate]

    result = Result(output=opts.output, pages_total=total, pages_selected=len(targets),
                    pages_converted=already_done)
    lock = threading.Lock()

    def assemble(partial: bool = False) -> None:
        # Assemble from everything the work dir holds, NOT just this run's page
        # selection: otherwise rerunning a few pages would rewrite the output as
        # those pages alone and throw the rest of the book away.
        note = (f"<!-- IN PROGRESS: {result.pages_converted} of {len(targets)} pages so far; "
                "this file is rewritten as the run continues. -->\n" if partial else "")
        assemble_output(opts.output, pages_dir, title=opts.title or opts.pdf.stem,
                        source_name=opts.pdf.name, model=opts.model, note=note)

    emit("start", total=total, selected=len(targets), todo=len(todo), done=already_done)
    assemble(partial=bool(todo))     # the output file exists from the first second

    def run(index: int) -> None:
        if abort.is_set():
            return
        emit("page_start", page=index + 1)
        try:
            idx, text, used_ocr, truncated, small = process_page(
                index, pdf_path=str(opts.pdf), md=md, client=client,
                opts=opts, cache=cache, limiter=limiter, meter=meter)
        except (DailyQuotaExceeded, BudgetExceeded) as exc:
            result.stopped_reason = type(exc).__name__
            return                    # leave unwritten so a rerun picks it up
        except PageFailed as exc:
            with lock:
                result.failed.append(index + 1)
            emit("page_failed", page=index + 1, message=str(exc))
            return

        # Always \n: Windows would write \r\n, and a script patching a page by
        # matching '\n\n' would then miss without a word.
        (pages_dir / f"{idx + 1:04d}.md").write_text(text, encoding="utf-8", newline="\n")
        with lock:
            result.pages_converted += 1
            if used_ocr:
                result.pages_ocr.append(idx + 1)
            if truncated:
                result.truncated.append(idx + 1)
            if small:
                result.pages_small_images.append(idx + 1)
            count = result.pages_converted
            if count % 10 == 0:
                assemble(partial=True)
        emit("page_done", page=idx + 1, done=count, total=len(targets), ocr=used_ocr,
             cost=meter.cost())

    if todo:
        with ThreadPoolExecutor(max_workers=max(1, opts.workers)) as pool:
            list(pool.map(run, todo))

    assemble()

    result.calls = meter.calls
    result.tokens_in = meter.tok_in
    result.tokens_out = meter.tok_out
    result.cost = meter.cost()
    result.pages_ocr.sort()
    result.failed.sort()
    result.truncated.sort()
    result.pages_small_images.sort()
    if abort.is_set() and opts.budget_usd and meter.cost() > opts.budget_usd:
        result.stopped_reason = "budget"
    emit("finished", result=result)
    return result
