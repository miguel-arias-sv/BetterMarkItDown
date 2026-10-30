"""Check a finished transcription against the PDF's own text layer.

A born-digital PDF (LaTeX notes, Word exports, most papers) carries its words in
a text layer. That layer is often too mangled to use as the transcription itself
-- ligatures, split words, math glyphs out of order -- but it is an exact record
of *which words* are on the page. Comparing bags of words against it catches
dropped sentences, invented text and garbled OCR for free, without any API call.

Numbers are compared the same way, separately from words. A codebook, a table of
results or a problem set can have every word right and a wrong figure, and a word
check alone would pass it.

What it cannot check: whether math and figures are *right*, or the words of
scanned pages (no text layer). Those still need a look at the page image. It does
check that the math is still well-formed on every page, scanned or not: a review
note pasted into the middle of an equation block breaks it silently. When Node.js
and KaTeX are installed, every formula is also rendered (see mathcheck.py).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .core import TRUNCATED_TAG
from .notes import SOURCE_TAG as _NOTES_SOURCE

_WORD = re.compile(r"[A-Za-z]+")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
# '70 000' with an ordinary, non-breaking or thin space between digit groups, and
# '70, 000', which is how some text layers store a plain '70,000'. Never joined up
# front: in a table row '1,282 862,492' is two cells, not one number.
_SPACED_THOUSANDS = re.compile(
    r"(?<![\d.,])\d{1,3}(?:,?[    ]\d{3})+(?![\d,]|\.\d)")
_LINK_TARGET = re.compile(r"\]\([^)\s]*\)")       # [text](url): the url is not page text
# What the converter adds itself: its picture of the page or of a figure, and the label
# over a figure's description. "Page 85 scan" is not on page 85, so none of it may count
# as the page's words or numbers.
_OWN_IMAGE = re.compile(r"!\[Page \d+(?: scan|, figure \d+)\]\([^)\n]*\)")
_OWN_LABEL = re.compile(r"^\*\*(?:Figure|Picture) [\d.]+ - transcribed by [^*\n]*:\*\*$", re.M)
# Typeset ligatures come out of the text layer as single glyphs (ﬁ, ﬀ) or vanish,
# so drop the letter pairs from both sides rather than guess which happened.
_LIGATURES = re.compile(r"ffi|ffl|ff|fi|fl")
_COMMENT = re.compile(r"<!--.*?-->", re.S)
# An escaped `\$` is a dollar sign, not a delimiter: '\$1900 ... when $P$' must not
# pair the currency sign with the formula's opening `$`.
_MATH = re.compile(r"(?<!\\)\$\$.*?(?<!\\)\$\$|(?<!\\)\$(?:\\.|[^$\\\n])*\$", re.S)
_DISPLAY_DELIM = re.compile(r"(?<!\\)\$\$")
_NOTE_LABEL = re.compile(r"\[\^(\w+)\]:?")       # [^12] and [^12]: are labels, not page text
_REVIEW_MARK = re.compile(r"\*\[[^\]]*\]\*")     # *[sic: ...]*, *[corrected in review: ...]*
_QUOTE_LINE = re.compile(r"^>.*$", re.M)          # figure descriptions are blockquotes
_PAGE_HEADING = re.compile(r"^## Page \d+\s*$", re.M)
_OCR_SOURCE = "<!-- source: local OCR"


def _norm(word: str) -> str:
    return _LIGATURES.sub("", word.lower())


def _words(text: str) -> list[str]:
    return [w for w in (_norm(m) for m in _WORD.findall(text)) if len(w) >= 3]


def _numbers(text: str) -> list[str]:
    """Numbers as written, with thousands separators removed: '33,099,725',
    '33 099 725' and '33099725' are the same number; '(1,2)' is two numbers."""
    out = []
    for token in _NUMBER.findall(text):
        if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", token):
            out.append(token.replace(",", ""))
        else:
            out.extend(token.split(","))
    return out


def _reconcile_spaced_thousands(text: str, unmatched: Counter, other_side: Counter) -> None:
    """Where `text` writes '70 000' as separate groups that are unmatched here while
    '70000' is unmatched on the other side, they are the same number: drop both."""
    for run in _SPACED_THOUSANDS.findall(text):
        parts = _numbers(run)
        joined = "".join(parts)
        need = Counter(parts)
        if other_side[joined] and all(unmatched[p] >= k for p, k in need.items()):
            unmatched.subtract(need)
            other_side[joined] -= 1
    for c in (unmatched, other_side):
        for key in [k for k, v in c.items() if v <= 0]:
            del c[key]


@dataclass
class PageCheck:
    page: int                        # 1-based
    pdf_words: int
    missing: Counter = field(default_factory=Counter)   # in the PDF, not in the Markdown
    extra: Counter = field(default_factory=Counter)     # in the Markdown, not in the PDF
    status: str = "ok"               # ok | flagged | no-text-layer | no-page-file
    ocr: bool = False                # page still carries the local-OCR fallback text
    math: list[str] = field(default_factory=list)       # structural problems in the math
    numbers_missing: Counter = field(default_factory=Counter)
    numbers_extra: Counter = field(default_factory=Counter)
    truncated: bool = False          # the model hit its output limit on this page
    markup: list[str] = field(default_factory=list)     # footnote, currency, table faults
    # Table words with no match in the text layer, on a page holding an image: the
    # table is most likely that image. Listed, but they do not flag the page.
    from_image: Counter = field(default_factory=Counter)
    notes: bool = False              # study notes on a refused page, not its text

    @property
    def flagged(self) -> bool:
        return (self.status == "flagged" or self.ocr or bool(self.math) or self.truncated
                or bool(self.markup))


def math_problems(md: str) -> list[str]:
    """Structural faults that stop equations rendering. Says nothing about
    whether an equation is correct."""
    md = _COMMENT.sub(" ", md)
    problems = []
    if len(_DISPLAY_DELIM.findall(md)) % 2:
        problems.append("unmatched $$")
    else:
        for block in re.findall(r"\$\$(.*?)\$\$", md, re.S):
            if re.search(r"\n\s*\n", block):
                problems.append("blank line inside a display equation")
            if "*[" in block:
                problems.append("review note inside a display equation")
            if len(re.findall(r"\\tag\b", block)) > 1:
                problems.append("more than one \\tag in a display equation; give each "
                                "numbered line its own $$...$$ or write (n) after \\qquad")
    for env in set(re.findall(r"\\begin\{(\w+\*?)\}", md)):
        if md.count(rf"\begin{{{env}}}") != md.count(rf"\end{{{env}}}"):
            problems.append(f"unmatched \\begin{{{env}}}")
    return problems


def split_markdown(md: str) -> tuple[str, str]:
    """Return (prose, non-prose). Non-prose is math plus figure descriptions:
    words there are allowed to account for PDF words but are never required."""
    md = _COMMENT.sub(" ", md)
    other = " ".join(_MATH.findall(md))
    prose = _MATH.sub(" ", md)
    prose = _OWN_LABEL.sub(" ", _OWN_IMAGE.sub(" ", prose))
    prose = _LINK_TARGET.sub("] ", prose)
    prose = _REVIEW_MARK.sub(" ", prose)
    other += " " + " ".join(_QUOTE_LINE.findall(prose))
    prose = _QUOTE_LINE.sub(" ", prose)
    prose = _PAGE_HEADING.sub(" ", prose)
    prose = _NOTE_LABEL.sub(" ", prose)
    return prose, other


# Placeholders the model writes when a page has a note marker but the note's text
# is printed elsewhere (a book's chapter endnotes): "[footnote text not present on
# this page]", "Text of footnote 18 not present on this page.", "text missing from image".
_PLACEHOLDER = re.compile(
    r"foot ?notes?\b.{0,40}\b(?:not (?:present|visible|shown|provided|printed|included|"
    r"available|given)|missing|omitted)"
    r"|\btext (?:is )?(?:not (?:present|visible|shown|provided|printed|included|available)"
    r"|missing|omitted)"
    r"|^\[?illegible\b", re.I)
_NOTE_DEF = re.compile(r"^\[\^(\w+)\]:[ \t]*(.*)$", re.M)
# A marker the model wrote as a math superscript. After punctuation or emphasis any
# number counts; after a letter only two digits do, so units such as m$^2$ pass.
_MATH_MARKER = re.compile(r"(?:(?<=[.,;:?!)\"”’*])\$\^\{?\d{1,3}\}?\$"
                          r"|(?<=[A-Za-z])\$\^\{?\d{2,3}\}?\$)")
_FUSED_NOTE = re.compile(r"^(?:\[\^\d+\](?!:)|\[<u>\d+</u>\])\S", re.M)
_LATEX_TABLE = re.compile(r"\\(?:multicolumn|multirow|hline|cline)\b")
# Outside $...$ these are printed as raw LaTeX source.
_LATEX_OUTSIDE_MATH = re.compile(
    r"\\begin\{(?:align|aligned|equation|eqnarray|gather|gathered|multline|split|array|"
    r"cases|[pbvBV]?matrix)\*?\}|\\tag\*?\{[^}]*\}")
# A link or image whose target holds a space: CommonMark ends the target there, so
# '[Exercise 9.29](Exercise 9.29)' prints as plain text. 'url "title"' is allowed.
_SPACED_LINK = re.compile(r"!?\[[^\]\n]*\]\((?!<)([^)\n]*\s[^)\n]*)\)")
# `$` + an amount that is not a closed `$12$` formula.
_CURRENCY = re.compile(r"(?:(?<=[\s(“—–])|^)\$(?=\d[\d,]*(?:\.\d+)?(?:s\b|[\s,.;:)\-–]|$))"
                       r"(?![\d,.]*\$)", re.M)


def _looks_like_currency(md: str, i: int) -> bool:
    """`$` at i opens a formula unless the span to the next `$` on its line reads as
    prose: it ends in a space ('$1.23, 7-Up $1.12'), holds four or more words, or
    never closes."""
    end = md.find("\n", i)
    rest = md[i + 1:end if end != -1 else len(md)]
    close = re.search(r"(?<!\\)\$", rest)
    if close is None:
        return True
    span = rest[:close.start()]
    words = re.findall(r"[A-Za-z]{2,}", re.sub(r"\\[A-Za-z]+(?:\{[^}]*\})?", " ", span))
    return span.endswith(" ") or len(words) >= 4


def markup_problems(md: str) -> list[str]:
    """Faults in the Markdown itself that a word count cannot see: invented
    footnotes, footnote markers or labels in the wrong form, dollar signs that
    renderers will read as math, and LaTeX table commands inside Markdown tables."""
    text = _COMMENT.sub(" ", md)
    problems = []
    prose_lines = _NOTE_DEF.sub(" ", text)
    for label, body in _NOTE_DEF.findall(text):
        body = body.strip()
        if not body or body.strip("[]*. ") == label:
            problems.append(f"footnote [^{label}] has no text (a stub)")
        elif _PLACEHOLDER.search(body.strip("[]* ")):
            problems.append(f"footnote [^{label}] is a placeholder, not the book's text: "
                            f"{body[:60]!r}")
        elif len(body) > 40 and body.rstrip(".") in prose_lines:
            problems.append(f"footnote [^{label}] repeats a sentence from the page body")
    for m in _MATH_MARKER.finditer(text):
        problems.append(f"footnote marker written as math {m.group()!r}; use [^n]")
    for m in _FUSED_NOTE.finditer(text):
        problems.append(f"note label fused to its text {m.group()!r}; use [^n]: text")
    displays = [(a.start(), a.end())
                for a in re.finditer(r"(?<!\\)\$\$.*?(?<!\\)\$\$", text, re.S)]
    for m in _CURRENCY.finditer(text):
        in_display = any(a <= m.start() < b for a, b in displays)
        if not in_display and _looks_like_currency(text, m.start()):
            problems.append("unescaped dollar sign, probably money "
                            f"{text[m.start():m.start() + 12]!r}; write \\$")
    prose = _MATH.sub(" ", text)
    if _LATEX_TABLE.search(prose):
        problems.append("LaTeX table command (\\multicolumn, \\hline, ...) in a Markdown "
                        "table; it will not render")
    for m in _LATEX_OUTSIDE_MATH.finditer(prose):
        problems.append(f"LaTeX outside $$...$$ {m.group()!r}; it prints as source. Wrap "
                        "the equation in $$, or write an orphaned equation number as (n)")
    for m in _SPACED_LINK.finditer(text):
        if not re.fullmatch(r"\S+\s+([\"']).*\1|\S+\s+\(.*\)", m.group(1).strip()):
            problems.append(f"link target with a space {m.group()[:60]!r}; it shows as "
                            "plain text. Write the space as %20, or drop the link")
    return problems


def _forgive_fused_markers(md: str, missing: Counter, extra: Counter) -> None:
    """The text layer runs a superscript note marker into what precedes it: '0.9926'
    + marker 22 becomes '0.992622', 'year 2014.' + 3 becomes '2014.3', and a marker
    alone is just '22'. Drop those when the Markdown has the marker."""
    labels = Counter(re.findall(r"\[\^(\d+)\]", md))
    for num in list(missing):
        if num in labels:
            missing[num] -= labels[num]
            continue
        for lab in labels:
            base = num[:-len(lab)].rstrip(".,") if num.endswith(lab) else ""
            if base and extra.get(base):
                missing[num] -= 1
                extra[base] -= 1
                break
    for c in (missing, extra):
        for key in [k for k, v in c.items() if v <= 0]:
            del c[key]


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
            # Normalise after joining: 'indef' + 'initely' only loses its 'fi' once whole.
            joined = _norm(tokens[i].group() + tokens[i + 1].group())
            # An explicit end-of-line hyphen settles it even when the first half is a
            # word of its own ('there-' + 'fore'); a bare line break needs more care.
            hyphenated = re.fullmatch(r"[-­‐]\s*\n\s*", gap) is not None
            if "\n" in gap and joined in known and (hyphenated or w not in known):
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


_ACCENTABLE = set("aeiouync")


def _forgive_dropped_accents(missing: Counter, extra: Counter) -> None:
    """Some text layers drop an accented letter outright: 'naïve' is stored as
    'nave', while the Markdown has 'naive'. Forgive a missing word that is an extra
    word less one vowel (or y, n, c: ÿ, ñ, ç), never any other letter, so 'test'
    against 'tests' is still flagged."""
    for w in list(missing):
        for x in list(extra):
            if len(x) == len(w) + 1 and any(
                    x[i] in _ACCENTABLE and x[:i] + x[i + 1:] == w for i in range(len(x))):
                n = min(missing[w], extra[x])
                missing[w] -= n
                extra[x] -= n
                break
    for c in (missing, extra):
        for key in [k for k, v in c.items() if v <= 0]:
            del c[key]


def _table_text(prose: str) -> str:
    return " ".join(line for line in prose.splitlines() if line.lstrip().startswith("|"))


def check_page(pdf_text: str, md: str, page: int, *, max_diff: int = 1,
               max_number_diff: int = 0, min_words: int = 20,
               image_on_page: bool = False) -> PageCheck:
    """Flag the page when more than `max_diff` words differ in total, or more than
    `max_number_diff` numbers. The word default of 1 still catches a single swapped
    word (one missing + one extra); for numbers any difference counts.

    `image_on_page`: the page holds an image large enough to be a figure. A table
    transcribed from it has no text layer, so its unmatched words are listed under
    `from_image` instead of flagging the page."""
    # OCR keeps the words and wrecks the math, so a clean word match proves nothing
    # on these pages: always send them back for a look.
    ocr = _OCR_SOURCE in md
    truncated = TRUNCATED_TAG in md
    math = math_problems(md)
    markup = markup_problems(md)
    if _NOTES_SOURCE in md:
        # Notes are in other words by design: comparing words would flag them all.
        return PageCheck(page, len(_words(pdf_text)), status="notes", notes=True, math=math,
                         markup=markup)
    prose, other = split_markdown(md)
    md_words = Counter(_words(prose))
    raw = _words(pdf_text)
    pdf_numbers = Counter(_numbers(pdf_text))
    # A page of tables can be nearly all numbers: count them towards "has a text layer".
    if len(raw) + sum(pdf_numbers.values()) < min_words:
        return PageCheck(page, len(raw), status="no-text-layer", ocr=ocr, math=math,
                         truncated=truncated, markup=markup)
    pdf_words = Counter(_pdf_words(pdf_text, md_words))
    # Normalise each token before joining: '$LLF$ $L_u$' joined first reads 'llflu',
    # and dropping the ligature pair 'fl' from that leaves no 'llf' to find.
    other_letters = "".join(_norm(t) for t in re.findall(r"[A-Za-z]+", other))
    missing = Counter({w: n for w, n in (pdf_words - md_words).items()
                       if w not in other_letters})
    extra = md_words - pdf_words
    _forgive_math_fusion(missing, extra, md_words)
    _forgive_dropped_accents(missing, extra)
    from_image = Counter()
    if image_on_page:
        from_image = extra & Counter(_words(_table_text(prose)))
        extra -= from_image

    # Numbers in math, figure descriptions and comments (the page prompt's
    # `<!-- page number: N -->`) may account for PDF numbers, but are never required.
    # Equation text layers scatter a number's pieces ('1.96' stored as '96' and '.1'),
    # so a piece found inside one of those numbers is accounted for too, the same way
    # a word found inside the math is.
    md_numbers = Counter(_numbers(prose))
    in_comments = Counter(_numbers(" ".join(_COMMENT.findall(md))))
    in_math = " ".join(_numbers(other))
    numbers_missing = pdf_numbers - md_numbers - in_comments
    numbers_extra = md_numbers - pdf_numbers
    _reconcile_spaced_thousands(pdf_text, numbers_missing, numbers_extra)
    _reconcile_spaced_thousands(prose, numbers_extra, numbers_missing)
    numbers_missing = Counter({n: k for n, k in numbers_missing.items() if n not in in_math})
    _forgive_fused_markers(md, numbers_missing, numbers_extra)
    if image_on_page:
        image_numbers = numbers_extra & Counter(_numbers(_table_text(prose)))
        numbers_extra -= image_numbers
        from_image += image_numbers

    flagged = (sum(missing.values()) + sum(extra.values()) > max_diff
               or sum(numbers_missing.values()) + sum(numbers_extra.values())
               > max_number_diff)
    return PageCheck(page, len(raw), missing, extra, "flagged" if flagged else "ok", ocr,
                     math, numbers_missing, numbers_extra, truncated, markup, from_image)


def _has_figure_image(page, min_pt: float = 60.0) -> bool:
    for info in page.get_image_info():
        x0, y0, x1, y1 = info["bbox"]
        if x1 - x0 >= min_pt and y1 - y0 >= min_pt:
            return True
    return False


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
            page = doc[idx]
            text = page.get_text("text", flags=pymupdf.TEXT_DEHYPHENATE)
            results.append(check_page(text, path.read_text(encoding="utf-8"), idx + 1,
                                      image_on_page=_has_figure_image(page), **thresholds))
    finally:
        doc.close()
    return results


def add_render_check(results: list[PageCheck], work_dir: Path) -> str:
    """Render each checked page's formulas with KaTeX; failures join `math`, so the
    page is flagged. Returns one line for the report, saying what ran or why not."""
    from .mathcheck import render_check

    pages = {}
    for r in results:
        path = work_dir / "pages" / f"{r.page:04d}.md"
        if path.is_file():
            pages[r.page] = path.read_text(encoding="utf-8")
    problems, skipped = render_check(pages)
    if skipped:
        return f"Math render check skipped: {skipped}."
    for r in results:
        r.math += problems.get(r.page, [])
    failed = sum(len(v) for v in problems.values())
    return (f"Math render check (KaTeX): {failed} formula(s) failed to render."
            if failed else "Math render check (KaTeX): every formula renders.")


def page_notes(r: PageCheck, limit: int = 12) -> list[str]:
    """What to look at on one page, in a sentence each: the setup page's badges."""
    def show(c: Counter) -> str:
        return ", ".join(w for w, _ in c.most_common(limit))

    notes = []
    if r.status == "flagged":
        parts = [f"missing here: {show(r.missing)}" if r.missing else "",
                 f"not in the PDF: {show(r.extra)}" if r.extra else ""]
        notes.append("The words differ from the PDF's own text ("
                     + "; ".join(p for p in parts if p) + ").")
        if r.numbers_missing or r.numbers_extra:
            parts = [f"missing here: {show(r.numbers_missing)}" if r.numbers_missing else "",
                     f"not in the PDF: {show(r.numbers_extra)}" if r.numbers_extra else ""]
            notes.append("Numbers differ (" + "; ".join(p for p in parts if p) + ").")
    if r.truncated:
        notes.append("Cut off: the model reached its output limit, so the end of the page "
                     "is missing. Finish it from the page image.")
    if r.ocr:
        notes.append("Read by the local OCR fallback, because the model refused this page: "
                     "the words may be right, but maths and layout are unreliable. Read this "
                     "page in the original.")
    if r.notes:
        notes.append("Study notes, not the page's text: the model refused to transcribe this "
                     "page. For exact wording and figures, read it in the original.")
    notes += [_in_plain_words(problem) for problem in r.math + r.markup]
    return notes


# The --verify report names each fault for whoever fixes the Markdown; the setup page
# says the same in plain words. Anything not listed here keeps its report wording.
_PLAIN = [
    (r"unescaped dollar sign, probably money '(\$[\d,.]*)",
     "A dollar amount, {0}, may show as the start of a formula in some Markdown viewers. "
     "Put a backslash before it, \\{0}, and it shows as money everywhere."),
    (r"unmatched \$\$", "A formula is missing its opening or closing $$, so the maths after "
                        "it may not show."),
    (r"blank line inside a display equation",
     "A formula has a blank line inside it, which stops it showing. Remove the blank line."),
    (r"review note inside a display equation",
     "A review note sits inside a formula, which stops it showing. Move it below the $$."),
    (r"more than one \\tag",
     "A formula has more than one equation number, so it will not show. Give each numbered "
     "line its own $$...$$."),
    (r"unmatched \\begin\{(.+?)\}",
     "A formula opens \\begin{{{0}}} without its \\end{{{0}}}, so it will not show."),
    (r"footnote \[\^(\w+)\] has no text", "Footnote {0} has no text."),
    (r"footnote \[\^(\w+)\] is a placeholder",
     "Footnote {0} holds a placeholder, not the book's note. Its text is probably printed "
     "elsewhere, such as the end of the chapter."),
    (r"footnote \[\^(\w+)\] repeats", "Footnote {0} repeats a sentence from the page."),
    (r"footnote marker written as math '(.+?)'",
     "A footnote number is written as a formula ({0}), so it shows as a superscript, not "
     "a footnote. Write it as [^n]."),
    (r"note label fused to its text '(.+?)'",
     "A footnote's number runs into its text ({0}). Write it as [^n]: followed by the text."),
    (r"LaTeX table command",
     "A table uses LaTeX commands (such as \\hline) that Markdown tables cannot show."),
    (r"LaTeX outside \$\$\.\.\.\$\$ '(.+?)'",
     "Maths code outside a formula ({0}) shows as code. Put the equation between $$ and "
     "$$, or write a lone equation number as (n)."),
    (r"link target with a space '(.+?)'",
     "A link with a space in its address shows as plain text: {0}"),
]


def _in_plain_words(problem: str) -> str:
    for pattern, text in _PLAIN:
        m = re.match(pattern, problem)
        if m:
            return text.format(*(g.replace("\\\\", "\\") for g in m.groups()))
    return problem[:1].upper() + problem[1:] + "."


def format_report(results: list[PageCheck], limit: int = 20,
                  render_note: str | None = None) -> str:
    def show(c: Counter) -> str:
        return " ".join(f"{w}x{n}" if n > 1 else w for w, n in c.most_common(limit)) or "-"

    lines = []
    for r in results:
        if r.status == "flagged":
            lines.append(f"page {r.page}: FLAGGED ({r.pdf_words} words in the text layer)")
            lines.append(f"    missing from the Markdown: {show(r.missing)}")
            lines.append(f"    not in the PDF:            {show(r.extra)}")
            if r.numbers_missing or r.numbers_extra:
                lines.append(f"    numbers missing:           {show(r.numbers_missing)}")
                lines.append(f"    numbers not in the PDF:    {show(r.numbers_extra)}")
            if r.from_image:
                lines.append(f"    from an image, unchecked:  {show(r.from_image)}")
        if r.truncated:
            lines.append(f"page {r.page}: cut off -- the model reached its output limit and "
                         "the rest of the page is missing. Finish it from the PDF.")
        if r.ocr:
            lines.append(f"page {r.page}: still local-OCR text -- the words may match, but "
                         "math and layout are unreliable. Read this page in the original.")
        if r.notes:
            lines.append(f"page {r.page}: study notes, not the page's text (the model "
                         "refused it) -- read it in the original for exact wording.")
        if r.math:
            lines.append(f"page {r.page}: broken math -- {'; '.join(r.math)}")
        for problem in r.markup:
            lines.append(f"page {r.page}: markup -- {problem}")
    counts = Counter(r.status for r in results)
    n_markup = sum(bool(r.markup) for r in results)
    no_layer = [r.page for r in results if r.status == "no-text-layer"]
    n_ocr = sum(r.ocr for r in results)
    n_math = sum(bool(r.math) for r in results)
    n_cut = sum(r.truncated for r in results)
    n_notes = sum(r.notes for r in results)
    lines.append(f"\n{counts['ok']} page(s) match the text layer, {counts['flagged']} flagged, "
                 f"{n_ocr} still OCR, {n_math} with broken math, {n_markup} with markup "
                 f"problems, {n_cut} cut off, "
                 f"{n_notes} study-notes pages, "
                 f"{counts['no-text-layer']} without a text layer (check those by eye), "
                 f"{counts['no-page-file']} not converted yet.")
    if no_layer:
        lines.append("Pages without a text layer: " + ", ".join(map(str, no_layer)) + ".")
    image_tables = [r.page for r in results if r.from_image]
    if image_tables:
        lines.append("Tables transcribed from images, whose words the text layer cannot "
                     "check (compare them with the page image): pages "
                     + ", ".join(map(str, image_tables)) + ".")
    if render_note:
        lines.append(render_note)
    lines.append("Whether equations and figure descriptions are *correct* is not checked "
                 "here -- compare those with the page image.")
    return "\n".join(lines)
