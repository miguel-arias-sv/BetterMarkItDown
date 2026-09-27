"""Check a finished transcription against the PDF's own text layer.

A born-digital PDF (LaTeX notes, Word exports, most papers) carries its words in
a text layer. That layer is often too mangled to use as the transcription itself
-- ligatures, split words, math glyphs out of order -- but it is an exact record
of *which words* are on the page. Comparing bags of words against it catches
dropped sentences, invented text and garbled OCR for free, without any API call.

What it cannot check: math, figures, or scanned pages (no text layer). Those
still need a look at the page image.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

_WORD = re.compile(r"[A-Za-z]+")
# Typeset ligatures come out of the text layer as single glyphs (ﬁ, ﬀ) or vanish,
# so drop the letter pairs from both sides rather than guess which happened.
_LIGATURES = re.compile(r"ffi|ffl|ff|fi|fl")
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_MATH = re.compile(r"\$\$.*?\$\$|\$[^$\n]*\$", re.S)
_REVIEW_MARK = re.compile(r"\*\[[^\]]*\]\*")     # *[sic: ...]*, *[corrected in review: ...]*
_QUOTE_LINE = re.compile(r"^>.*$", re.M)          # figure descriptions are blockquotes
_PAGE_HEADING = re.compile(r"^## Page \d+\s*$", re.M)
_OCR_SOURCE = "<!-- source: local OCR"


def _norm(word: str) -> str:
    return _LIGATURES.sub("", word.lower())


def _words(text: str) -> list[str]:
    return [w for w in (_norm(m) for m in _WORD.findall(text)) if len(w) >= 3]


@dataclass
class PageCheck:
    page: int                        # 1-based
    pdf_words: int
    missing: Counter = field(default_factory=Counter)   # in the PDF, not in the Markdown
    extra: Counter = field(default_factory=Counter)     # in the Markdown, not in the PDF
    status: str = "ok"               # ok | flagged | no-text-layer | no-page-file
    ocr: bool = False                # page still carries the local-OCR fallback text

    @property
    def flagged(self) -> bool:
        return self.status == "flagged" or self.ocr


def split_markdown(md: str) -> tuple[str, str]:
    """Return (prose, non-prose). Non-prose is math plus figure descriptions:
    words there are allowed to account for PDF words but are never required."""
    md = _COMMENT.sub(" ", md)
    other = " ".join(_MATH.findall(md))
    prose = _MATH.sub(" ", md)
    prose = _REVIEW_MARK.sub(" ", prose)
    other += " " + " ".join(_QUOTE_LINE.findall(prose))
    prose = _QUOTE_LINE.sub(" ", prose)
    prose = _PAGE_HEADING.sub(" ", prose)
    return prose, other


def _pdf_words(pdf_text: str, known: Counter) -> list[str]:
    """Words of the text layer, with hyphenation undone.

    Hyphenation leaves 'consump' + 'tion' across a line break. Merge a pair only
    when a line break separates them and their concatenation is a word the
    Markdown has -- merging anywhere else glues 'firm' + 's' into nonsense."""
    tokens = list(re.finditer(r"[A-Za-z]+", pdf_text))
    out, i = [], 0
    while i < len(tokens):
        w = _norm(tokens[i].group())
        if i + 1 < len(tokens):
            gap = pdf_text[tokens[i].end():tokens[i + 1].start()]
            joined = w + _norm(tokens[i + 1].group())
            if "\n" in gap and w not in known and joined in known:
                out.append(joined)
                i += 2
                continue
        out.append(w)
        i += 1
    return [w for w in out if len(w) >= 3]


_SHORT_WORDS = {"a", "an", "as", "at", "be", "by", "if", "in", "is", "it", "of", "on",
                "or", "to"}


def _forgive_math_fusion(missing: Counter, extra: Counter, md_words: Counter) -> None:
    """LaTeX written as `when$A$` puts 'whenA' in the text layer, while the
    Markdown has 'when' plus math. Drop a missing word that is a real word plus
    one trailing variable letter (and the matching extra, if any)."""
    for w in list(missing):
        stem = w[:-1]
        if stem in _SHORT_WORDS or stem in md_words:
            n = missing.pop(w)
            if extra.get(stem):
                extra[stem] -= min(n, extra[stem])
                if extra[stem] <= 0:
                    del extra[stem]


def check_page(pdf_text: str, md: str, page: int, *, max_diff: int = 1,
               min_words: int = 20) -> PageCheck:
    """Flag the page when more than `max_diff` words differ in total. The
    default of 1 still catches a single swapped word (one missing + one extra)."""
    # OCR keeps the words and wrecks the math, so a clean word match proves nothing
    # on these pages: always send them back for a look.
    ocr = _OCR_SOURCE in md
    prose, other = split_markdown(md)
    md_words = Counter(_words(prose))
    raw = _words(pdf_text)
    if len(raw) < min_words:
        return PageCheck(page, len(raw), status="no-text-layer", ocr=ocr)
    pdf_words = Counter(_pdf_words(pdf_text, md_words))
    other_letters = _norm(re.sub(r"[^A-Za-z]", "", other))
    missing = Counter({w: n for w, n in (pdf_words - md_words).items()
                       if w not in other_letters})
    extra = md_words - pdf_words
    _forgive_math_fusion(missing, extra, md_words)
    flagged = sum(missing.values()) + sum(extra.values()) > max_diff
    return PageCheck(page, len(raw), missing, extra, "flagged" if flagged else "ok", ocr)


def verify(pdf: Path, work_dir: Path, pages: list[int] | None = None,
           **thresholds) -> list[PageCheck]:
    """Compare each page file in `work_dir/pages/` with the PDF's text layer.
    `pages` are 0-based indexes, as returned by core.parse_pages."""
    import pymupdf

    results = []
    doc = pymupdf.open(pdf)
    try:
        for idx in (pages if pages is not None else range(doc.page_count)):
            path = work_dir / "pages" / f"{idx + 1:04d}.md"
            if not path.is_file():
                results.append(PageCheck(idx + 1, 0, status="no-page-file"))
                continue
            text = doc[idx].get_text("text", flags=pymupdf.TEXT_DEHYPHENATE)
            results.append(check_page(text, path.read_text(encoding="utf-8"), idx + 1,
                                      **thresholds))
    finally:
        doc.close()
    return results


def format_report(results: list[PageCheck], limit: int = 20) -> str:
    def show(c: Counter) -> str:
        return " ".join(f"{w}x{n}" if n > 1 else w for w, n in c.most_common(limit)) or "-"

    lines = []
    for r in results:
        if r.status == "flagged":
            lines.append(f"page {r.page}: FLAGGED ({r.pdf_words} words in the text layer)")
            lines.append(f"    missing from the Markdown: {show(r.missing)}")
            lines.append(f"    not in the PDF:            {show(r.extra)}")
        if r.ocr:
            lines.append(f"page {r.page}: still local-OCR text -- the words may match, but "
                         "math and layout are unreliable. Retype it from the page image.")
    counts = Counter(r.status for r in results)
    n_ocr = sum(r.ocr for r in results)
    lines.append(f"\n{counts['ok']} page(s) match the text layer, {counts['flagged']} flagged, "
                 f"{n_ocr} still OCR, "
                 f"{counts['no-text-layer']} without a text layer (check those by eye), "
                 f"{counts['no-page-file']} not converted yet.")
    lines.append("Math and figure descriptions are not checked here -- compare those "
                 "with the page image.")
    return "\n".join(lines)
