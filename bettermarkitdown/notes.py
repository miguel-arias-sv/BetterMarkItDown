"""Study notes for pages a model refuses to transcribe.

Online models refuse some pages of published books (Gemini's recitation filter: it will
not repeat long passages of text it recognises). This project never tries to defeat that:
no tiling, no disguised prompts, and no transcribing the page some other way word for
word. What a student needs from the page is its knowledge, so the model is asked for
something it does offer: study notes on the page, in its own words, which are then

1. checked against the page by a second request, and revised once if the check finds
   something wrong or missing;
2. checked for the page's numbered items (equations, examples, tables, figures), read
   free from the PDF's text layer: any the notes do not mention are listed above them;
3. checked for copied wording: a bullet that shares a run of eight or more words with
   the page's text is removed;
4. labelled as notes, not the book's text, with the PDF page to read for the full text.

Notes condense by nature: they keep the ideas and formulas, not every detail or exact
figure. A pilot on six textbook pages kept every formula correct, about half the
equation numbers before step 2 existed, and left out one to three points per page.
"""

from __future__ import annotations

import json
import re

from .prompts import NOTES_CHECK_PROMPT, NOTES_PROMPT, NOTES_REVISE_PROMPT

SOURCE_TAG = "<!-- source: study notes"
RUN = 8                                   # words in a row that count as copied wording

_WORD = re.compile(r"[a-z]+")
# Numbered items a student looks up: (15.4), (15A.2), Example 15.7, Table D.5, Figure 9.11.
_EQUATION = re.compile(r"\((\d{1,2}[A-Z]?\.\d{1,3}[a-z]?)\)")
_ITEM = re.compile(r"\b(Example|Table|Figure|Exercise)\s+([A-Z]?\d{0,2}[A-Z]?\.\d{1,3}[a-z]?)\b")


def refused(body: str) -> bool:
    """True when a page came back empty because of a provider's content filter."""
    return "RECITATION" in body or "content_filter" in body


def numbered_items(text: str) -> list[str]:
    """The page's equation, example, table and figure numbers, in reading order."""
    found = [f"({m.group(1)})" for m in _EQUATION.finditer(text)]
    found += [f"{m.group(1)} {m.group(2)}" for m in _ITEM.finditer(text)]
    seen, out = set(), []
    for item in found:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _runs(words: list[str]) -> set[str]:
    return {" ".join(words[i:i + RUN]) for i in range(len(words) - RUN + 1)}


def remove_copied(notes: str, page_text: str) -> tuple[str, int]:
    """Drop every line of the notes that shares RUN words in a row with the page's text.
    Returns the notes and how many lines were dropped."""
    page_runs = _runs(_words(page_text))
    if not page_runs:
        return notes, 0
    kept, dropped = [], 0
    for line in notes.splitlines():
        if _runs(_words(line)) & page_runs:
            dropped += 1
        else:
            kept.append(line)
    return "\n".join(kept).strip(), dropped


def missing_items(notes: str, items: list[str]) -> list[str]:
    """The page's numbered items the notes never mention."""
    flat = re.sub(r"\s+", " ", notes)
    out = []
    for item in items:
        number = item.strip("()").split()[-1]
        if not re.search(rf"(?<![\d.]){re.escape(number)}(?![\d])", flat):
            out.append(item)
    return out


def _parse_check(reply: str) -> dict:
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", reply.strip())
    try:
        found = json.loads(raw)
    except ValueError:
        return {}
    return found if isinstance(found, dict) else {}


def study_notes(describe, png: bytes, page_text: str, page_number: int) -> str | None:
    """Notes on a refused page, checked and labelled, or None if the model gives none.
    `describe(png, prompt)` sends one request and returns its text ("" on failure)."""
    items = numbered_items(page_text)
    hint = (f"\n\nThis page's numbered items, which the notes must each mention: "
            f"{', '.join(items)}." if items else "")
    notes = describe(png, NOTES_PROMPT + hint).strip()
    if not notes or refused(notes) or notes.startswith("*[vision call failed"):
        return None

    check = _parse_check(describe(png, NOTES_CHECK_PROMPT + notes))
    problems = [f"Wrong: {x}" for x in check.get("wrong", []) if x]
    problems += [f"Missing: {x}" for x in check.get("missing", []) if x]
    problems += [f"Missing numbered item: {x}" for x in missing_items(notes, items)]
    revised = False
    if problems:
        better = describe(png, NOTES_REVISE_PROMPT + "\n\nPROBLEMS:\n- " + "\n- ".join(problems)
                          + "\n\nNOTES:\n" + notes + hint).strip()
        if better and not refused(better) and not better.startswith("*[vision call failed"):
            notes, revised = better, True

    notes, dropped = remove_copied(notes, page_text)
    if not notes:
        return None
    absent = missing_items(notes, items)
    lines = [
        f"{SOURCE_TAG} (the model declined to transcribe this page: its recitation filter). "
        f"Not the book's text. {'Checked and revised once' if revised else 'Checked'} "
        f"against the page image. -->",
        "",
        f"> **Study notes, not the book's text.** The model would not transcribe this page, "
        f"so these are notes on its ideas, in the model's own words, checked against the "
        f"page. They may leave out details or exact figures: for the full page, read PDF "
        f"page {page_number}.",
    ]
    if items:
        lines.append(">")
        lines.append(f"> On this page: {', '.join(items)}.")
    if absent:
        lines.append(f"> Not covered in these notes: {', '.join(absent)}: see the PDF.")
    if dropped:
        lines.append(f"> {dropped} line(s) that repeated the page's wording were removed.")
    if not page_text.strip():
        lines.append("> This page has no text layer, so the notes could not be checked "
                     "for copied wording or numbered items.")
    return "\n".join(lines) + "\n\n" + notes
