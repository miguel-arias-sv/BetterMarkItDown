"""The workspace's library: the files added on the setup page, and their results.

Two places, on purpose:
- The copy of each added file, its per-page work and the response cache live in
  the per-user app-data folder (%LOCALAPPDATA%\\BetterMarkItDown\\library on
  Windows). Never in Documents: OneDrive often syncs Documents, and a sync client
  locking page files in the middle of a run is the known synced-drive problem.
- The result, the .md and its pictures, goes to Documents\\BetterMarkItDown\\<name>\\,
  where people look for their files.

Adding a file only copies it here. Nothing leaves the computer unless it is
converted with an online AI service.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import BinaryIO

from .formats import SUPPORTED

MAX_BYTES = 2 * 1024 ** 3                 # 2 GB: bigger than any book scan we have seen
_ID = re.compile(r"[0-9a-f]{12}")
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
             *(f"lpt{i}" for i in range(1, 10))}


class LibraryError(ValueError):
    """Something the person can fix: a wrong file type, a file that will not open."""


def data_dir() -> Path:
    """$BMID_LIBRARY_DIR, else the platform's per-user, unsynced app-data folder."""
    override = os.environ.get("BMID_LIBRARY_DIR", "").strip()
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "BetterMarkItDown" / "library"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "BetterMarkItDown" / "library"
    base = os.environ.get("XDG_DATA_HOME", "").strip() or str(Path.home() / ".local" / "share")
    return Path(base) / "bettermarkitdown" / "library"


def _documents_folder() -> Path:
    """The real Documents folder. On Windows it may have been moved, to OneDrive for
    one, so ask the shell rather than assume ~/Documents."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                        ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

        # FOLDERID_Documents {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
        folder = GUID(0xFDD39AD0, 0x238F, 0x46AF,
                      (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7))
        found = ctypes.c_wchar_p()
        try:
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(folder), 0, None,
                                                          ctypes.byref(found)) == 0:
                path = Path(found.value)
                ctypes.windll.ole32.CoTaskMemFree(found)
                return path
        except (OSError, AttributeError):
            pass
    return Path.home() / "Documents"


def output_root() -> Path:
    """$BMID_OUTPUT_DIR, else Documents\\BetterMarkItDown."""
    override = os.environ.get("BMID_OUTPUT_DIR", "").strip()
    return Path(override) if override else _documents_folder() / "BetterMarkItDown"


def safe_name(name: str) -> str:
    """A file name every system accepts, from whatever the person's file was called."""
    name = _UNSAFE.sub("_", name).strip().rstrip(". ")[:80].rstrip(". ")
    if not name or name.lower() in _RESERVED:
        name = f"document_{name}" if name else "document"
    return name


@dataclass
class Document:
    id: str
    name: str                  # the file's name without its extension, as shown
    filename: str              # the name it was added with
    kind: str                  # ".pdf", ".docx", ...
    size: int
    added: str
    folder: str                # its result folder's name, unique in output_root()
    pages: int = 0             # PDF pages; 0 for Word and PowerPoint
    as_pages: bool = False     # Word / PowerPoint read through a PDF, for page images
    inspection: dict = field(default_factory=dict)
    last_run: dict = field(default_factory=dict)
    edited: list[int] = field(default_factory=list)    # pages changed by hand (0: whole file)
    checks: dict[str, list[str]] = field(default_factory=dict)  # page -> what to look at

    # --- where things are -----------------------------------------------------------
    def home(self) -> Path:
        return data_dir() / self.id

    def source(self) -> Path:
        """The library's copy, under the file's own name: the output's header says
        which file it was converted from."""
        return self.home() / (safe_name(Path(self.filename).stem) + self.kind)

    def work_dir(self) -> Path:
        return self.home() / "work"

    def output(self) -> Path:
        return output_root() / self.folder / (self.folder + ".md")

    def assets_dir(self) -> Path:
        out = self.output()
        return out.parent / (out.stem + "_assets")

    def page_pdf(self) -> Path | None:
        """The PDF whose pages are shown next to the Markdown, if there is one."""
        if self.kind == ".pdf":
            return self.source()
        made = self.work_dir() / (self.source().stem + ".pdf")
        return made if self.as_pages and made.is_file() else None

    def paged(self) -> bool:
        """Converted page by page (a PDF, or an Office file read through one)."""
        return self.kind == ".pdf" or self.as_pages

    def save(self) -> None:
        target = self.home() / "document.json"
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        tmp.replace(target)


def _load(folder: Path) -> Document | None:
    try:
        data = json.loads((folder / "document.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    known = {f.name for f in fields(Document)}
    try:
        return Document(**{k: v for k, v in data.items() if k in known})
    except TypeError:
        return None


def documents() -> list[Document]:
    """Every document in the library, the most recently added first."""
    root = data_dir()
    found = [doc for d in root.iterdir() if d.is_dir() and (doc := _load(d))] \
        if root.is_dir() else []
    return sorted(found, key=lambda d: d.added, reverse=True)


def get(doc_id: str) -> Document:
    if not _ID.fullmatch(str(doc_id)):
        raise LibraryError("No such document.")
    doc = _load(data_dir() / doc_id)
    if doc is None:
        raise LibraryError("No such document. It may have been removed.")
    return doc


def _unique_folder(name: str) -> str:
    taken = {d.folder.lower() for d in documents()}
    root = output_root()
    candidate, n = name, 2
    while candidate.lower() in taken or (root / candidate).exists():
        candidate, n = f"{name} ({n})", n + 1
    return candidate


def add(stream: BinaryIO, filename: str, length: int) -> Document:
    """Copy `length` bytes from `stream` into the library as a new document."""
    filename = Path(filename.replace("\\", "/")).name
    kind = Path(filename).suffix.lower()
    if kind not in SUPPORTED:
        raise LibraryError(f"{filename or 'This file'} is not a file this tool reads. "
                           f"It reads {', '.join(sorted(SUPPORTED))}.")
    if length <= 0:
        raise LibraryError(f"{filename} is empty.")
    if length > MAX_BYTES:
        raise LibraryError(f"{filename} is larger than {MAX_BYTES // 1024 ** 3} GB.")

    name = safe_name(Path(filename).stem)
    doc = Document(id=uuid.uuid4().hex[:12], name=Path(filename).stem or name,
                   filename=filename, kind=kind, size=length,
                   added=time.strftime("%Y-%m-%d %H:%M:%S"), folder=_unique_folder(name))
    doc.home().mkdir(parents=True)
    try:
        with open(doc.source(), "wb") as out:
            left = length
            while left:
                chunk = stream.read(min(left, 1 << 20))
                if not chunk:
                    raise LibraryError(f"{filename} did not arrive in full. Add it again.")
                out.write(chunk)
                left -= len(chunk)
        if kind == ".pdf":
            doc.pages = _page_count(doc.source(), filename)
        doc.save()
    except BaseException:
        shutil.rmtree(doc.home(), ignore_errors=True)
        raise
    return doc


def _page_count(path: Path, filename: str) -> int:
    import pymupdf
    try:
        with pymupdf.open(path) as pdf:
            if pdf.needs_pass:
                raise LibraryError(f"{filename} is password-protected. Save a copy without "
                                   "the password, then add that.")
            return pdf.page_count
    except LibraryError:
        raise
    except Exception:
        raise LibraryError(f"{filename} does not open as a PDF. It may be damaged.") from None


def remove(doc_id: str) -> Document:
    """Take a document out of the library: its copy and its work go. Its result in
    Documents stays, since the person may already be using it."""
    doc = get(doc_id)
    shutil.rmtree(doc.home(), ignore_errors=True)
    return doc


# --- a free look before converting -------------------------------------------------------

def inspect(pdf: Path, min_chars: int = 120, min_figure_pt: float = 60.0,
            progress=None) -> dict:
    """What a PDF holds, without spending anything: which pages are scanned, which set
    their equations as pictures, how many figures, and its outline. About 3 s per 100
    pages, so `progress(done, total)` is called as it goes."""
    import pymupdf

    from .core import figure_regions, outline_ranges, small_images

    scanned, equations, figures = [], [], 0
    with pymupdf.open(pdf) as doc:
        for page in doc:
            text = page.get_text("text")
            if len(re.sub(r"\s", "", text)) < min_chars:
                scanned.append(page.number + 1)
            elif small_images(page, min_figure_pt):
                equations.append(page.number + 1)
            else:
                figures += len(figure_regions(page, min_figure_pt))
            if progress:
                progress(page.number + 1, doc.page_count)
        outline = [{"level": level, "title": title, "first": first, "last": last}
                   for level, title, first, last in outline_ranges(doc)]
        total = doc.page_count
    return {"pages": total, "scanned": scanned, "equations": equations, "figures": figures,
            "outline": outline}


def vision_calls(inspection: dict, pages: list[int] | None = None) -> int:
    """How many model requests a conversion of these pages (1-based) would make, roughly:
    one per scanned or equation page, plus one per figure on the others."""
    whole = set(inspection.get("scanned", [])) | set(inspection.get("equations", []))
    total = inspection.get("pages", 0) or 1
    if pages is None:
        return len(whole) + inspection.get("figures", 0)
    chosen = set(pages)
    text_pages = max(1, total - len(whole))
    figures = inspection.get("figures", 0) * len(chosen - whole) / text_pages
    return len(chosen & whole) + round(figures)
