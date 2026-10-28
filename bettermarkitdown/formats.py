"""Word and PowerPoint files, current and Office 97-2003.

DOCX and PPTX: MarkItDown reads the text, headings and tables well, but leaves each
picture as an empty placeholder (`![](data:image/png;base64...)` in Word,
`![image.png](Picture2.jpg)` in PowerPoint): the same silent loss as a scanned PDF.
Here every picture is taken out of the document in order, saved next to the
output, and described by the vision model where it stood, as PDF figures are.

DOC and PPT: MarkItDown cannot read them. Microsoft Word or PowerPoint (Windows,
when installed), else LibreOffice, saves them as DOCX / PPTX first, and they are
read as above: going through PDF instead flattens every table into loose lines.
`--as-pages` sends any of these files through PDF and the page pipeline, which
gives page images to check the result against.
"""

from __future__ import annotations

import base64
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import core
from .config import Options, Result
from .prompts import FIGURE_PROMPT

NATIVE = {".docx", ".pptx"}
LEGACY = {".doc", ".ppt"}
SUPPORTED = {".pdf"} | NATIVE | LEGACY

# Smaller than this on either side is a bullet, icon or rule, not worth a vision call.
MIN_PICTURE_PX = 48

_PICTURE = re.compile(r"!\[([^\]]*)\]\(data:image/([\w.+-]+);base64,([A-Za-z0-9+/=\s]+)\)")

LIBREOFFICE_WINGET = "TheDocumentFoundation.LibreOffice"
LIBREOFFICE_URL = "https://www.libreoffice.org/download/"


class ConverterMissing(RuntimeError):
    """No program on this computer can turn this file into PDF."""


# --- DOCX and PPTX, read directly ---------------------------------------------------

def _to_png(raw: bytes) -> tuple[bytes | None, tuple[int, int]]:
    """The picture as PNG and its size, or (None, (0, 0)) if it cannot be read.
    Office also embeds EMF/WMF drawings, which Pillow reads only on Windows."""
    from PIL import Image
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except Exception:
        return None, (0, 0)
    if image.mode not in ("RGB", "RGBA", "L"):
        image = image.convert("RGBA")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue(), image.size


def convert_office(opts: Options, on_event: core.Event | None = None,
                   original: Path | None = None) -> Result:
    """Convert a DOCX or PPTX (`opts.pdf` is the document's path). `original` names the
    file it was saved from, when that was a DOC or PPT."""
    from markitdown import MarkItDown

    core.ABORT.clear()

    def emit(name: str, **payload):
        if on_event:
            on_event(name, payload)

    source = opts.pdf
    work_dir = opts.resolved_work_dir()
    work_dir.mkdir(parents=True, exist_ok=True)
    opts.output.parent.mkdir(parents=True, exist_ok=True)

    client = core.vision_client(opts)
    text = MarkItDown(enable_plugins=False).convert(str(source),
                                                    keep_data_uris=True).text_content or ""
    pictures = list(_PICTURE.finditer(text))

    meter = core.Meter(*opts.prices(), opts.budget_usd)
    cache = core.Cache(work_dir / "cache.json")
    limiter = core.RateLimiter(opts.rpm)
    assets = opts.assets_dir()
    result = Result(output=opts.output, pages_total=len(pictures),
                    pages_selected=len(pictures), unit="picture")
    lock = threading.Lock()
    described = [0]
    emit("start", total=len(pictures), selected=len(pictures), todo=len(pictures), done=0)

    def describe(item: tuple[int, re.Match]) -> str:
        n, match = item
        alt, kind = match.group(1).strip(), match.group(2).lower()
        png, (width, height) = _to_png(base64.b64decode(re.sub(r"\s", "", match.group(3))))
        if png is None:
            return f"*[picture {n}: a {kind} image this tool cannot read; see the original]*"
        name = f"{source.stem}_picture_{n:02d}.png"
        assets.mkdir(parents=True, exist_ok=True)
        (assets / name).write_bytes(png)
        block = f"![{alt or f'Picture {n}'}]({core.md_link(f'{assets.name}/{name}')})"
        if client is None or min(width, height) < MIN_PICTURE_PX:
            return block
        with lock:
            described[0] += 1          # counts toward "remaining" if the run stops early
        try:
            description = core.describe_image(client, opts.model,
                                              core.shrink(png, opts.max_edge), FIGURE_PROMPT,
                                              cache=cache, limiter=limiter, meter=meter,
                                              reasoning=opts.reasoning)
        except (core.DailyQuotaExceeded, core.BudgetExceeded) as exc:
            # Pictures described so far are cached: a rerun pays only for the rest.
            result.stopped_reason = ("budget" if isinstance(exc, core.BudgetExceeded)
                                     else type(exc).__name__)
            return block + "\n\n*[not described: the run stopped early; run it again to finish]*"
        with lock:
            result.pages_converted += 1
            if core.TRUNCATED_TAG in description:
                result.truncated.append(n)
        emit("image_done", picture=n, done=result.pages_converted, total=len(pictures))
        return (f"{block}\n\n**Picture {n} - transcribed by {opts.model}:**\n\n"
                f"{core.quote_block(description)}")

    with ThreadPoolExecutor(max_workers=max(1, opts.workers)) as pool:
        blocks = list(pool.map(describe, enumerate(pictures, start=1)))

    replacements = iter(blocks)
    body = _PICTURE.sub(lambda _m: next(replacements), text).strip()
    header = (f"# {opts.title or source.stem}\n\n<!-- Converted from "
              f"{(original or source).name} with "
              f"BetterMarkItDown ({opts.model if client else 'text only'}) on "
              f"{time.strftime('%Y-%m-%d %H:%M')} -->\n\n")
    tmp = opts.output.with_suffix(".md.tmp")
    tmp.write_text(header + body + "\n", encoding="utf-8", newline="\n")
    tmp.replace(opts.output)

    result.pages_selected = described[0]      # icons and text-only runs owe nothing
    result.calls, result.tokens_in, result.tokens_out = meter.calls, meter.tok_in, meter.tok_out
    result.cost = meter.cost()
    emit("finished", result=result)
    return result


# --- anything Office can open, through PDF --------------------------------------------

def office_installed(app: str) -> bool:
    """Is Microsoft Word / PowerPoint registered for automation on this computer?"""
    if sys.platform != "win32":
        return False
    import winreg
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, f"{app}.Application"))
        return True
    except OSError:
        return False


def find_soffice() -> str:
    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return found
    candidates = [Path(os.environ.get(var, "")) / "LibreOffice" / "program" / "soffice.exe"
                  for var in ("ProgramFiles", "ProgramFiles(x86)") if os.environ.get(var)]
    candidates.append(Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"))
    return next((str(p) for p in candidates if p.is_file()), "")


# Word: ExportAsFixedFormat(path, wdExportFormatPDF=17) or SaveAs2(path,
# wdFormatXMLDocument=16). PowerPoint: SaveAs(path, ppSaveAsPDF=32 or
# ppSaveAsOpenXMLPresentation=24), opened read-only and without a window. Paths
# travel in environment variables, so no quoting can break the script.
_WORD_PS = """
$ErrorActionPreference = 'Stop'
$app = New-Object -ComObject Word.Application
$app.Visible = $false
$app.DisplayAlerts = 0
try {
    $doc = $app.Documents.Open($env:BMID_SRC, $false, $true)
    if ($env:BMID_TARGET -eq 'pdf') { $doc.ExportAsFixedFormat($env:BMID_DEST, 17) }
    else { $doc.SaveAs2($env:BMID_DEST, 16) }
    $doc.Close(0)
} finally { $app.Quit() }
"""
_POWERPOINT_PS = """
$ErrorActionPreference = 'Stop'
$app = New-Object -ComObject PowerPoint.Application
try {
    $deck = $app.Presentations.Open($env:BMID_SRC, $true, $false, $false)
    $deck.SaveAs($env:BMID_DEST, $(if ($env:BMID_TARGET -eq 'pdf') { 32 } else { 24 }))
    $deck.Close()
} finally { $app.Quit() }
"""


def _run(command: list[str], env: dict | None = None, timeout: float = 300.0) -> bool:
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=timeout,
                              env={**os.environ, **(env or {})},
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def modern_suffix(source: Path) -> str:
    """.doc -> .docx, .ppt -> .pptx."""
    return ".docx" if source.suffix.lower() in (".doc", ".docx") else ".pptx"


def office_to_pdf(source: Path, dest: Path) -> str:
    """Write `source` as a PDF at `dest`. See office_convert."""
    return office_convert(source, dest, "pdf")


def office_convert(source: Path, dest: Path, target: str) -> str:
    """Save `source` as `target` ("pdf", "docx" or "pptx") at `dest`, by whatever this
    computer has. Returns the program used; raises ConverterMissing if there is none."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    suffix = source.suffix.lower()
    app = "Word" if suffix in (".doc", ".docx") else "PowerPoint"
    tried = []

    if office_installed(app):
        script = _WORD_PS if app == "Word" else _POWERPOINT_PS
        ok = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                  env={"BMID_SRC": str(source.resolve()), "BMID_DEST": str(dest.resolve()),
                       "BMID_TARGET": target})
        if ok and dest.is_file():
            return f"Microsoft {app}"
        tried.append(f"Microsoft {app}")

    soffice = find_soffice()
    if soffice:
        with tempfile.TemporaryDirectory() as tmp:
            ok = _run([soffice, "--headless", "--convert-to", target, "--outdir", tmp,
                       str(source.resolve())])
            made = Path(tmp) / (source.stem + "." + target)
            if ok and made.is_file():
                shutil.move(str(made), dest)
                return "LibreOffice"
        tried.append("LibreOffice")

    if tried:
        raise ConverterMissing(f"{' and '.join(tried)} could not convert {source.name}. "
                               "Is it open in another program, or password-protected?")
    raise ConverterMissing(converter_help(source))


def converter_help(source: Path) -> str:
    install = (f"winget install --id {LIBREOFFICE_WINGET} -e" if sys.platform == "win32"
               else f"see {LIBREOFFICE_URL}")
    return (f"{source.name} needs Microsoft Office or the free LibreOffice to open it, and "
            f"neither was found. Install LibreOffice ({install}), or save the "
            "file as .docx / .pptx / .pdf from the program that made it.")


def libreoffice_install_command() -> list[str] | None:
    if sys.platform == "win32" and shutil.which("winget"):
        return ["winget", "install", "--id", LIBREOFFICE_WINGET, "-e",
                "--accept-source-agreements", "--accept-package-agreements"]
    return None
