"""Turn a PDF page into visual rows of positioned cells, using the text layer only.

This is the one reusable piece behind the codebook parsers in this folder. A
codebook, data dictionary or statistical table is laid out on a grid: labels
start at a fixed x, numbers are right-aligned to a fixed column edge. Plain text
extraction throws those coordinates away, and a vision model re-reads digits it
could have copied. Keeping each span's position lets a parser assign every value
to its column exactly, with no API call and no transcription error.

    rows = page_rows(page)
    for y, cells in rows:
        for x0, x1, text, bold in cells:
            ...
"""

from __future__ import annotations

import pymupdf

# Leaving out TEXT_PRESERVE_LIGATURES makes PyMuPDF expand ligature glyphs such as
# U+FB01 into plain "fi", so 'ﬁle' is searchable as 'file'.
FLAGS = pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_MEDIABOX_CLIP


def page_rows(page, ytol: float = 2.5, gap: float = 3.0):
    """Rows top to bottom: (y, [(x0, x1, text, bold), ...]) with cells left to right.

    Spans whose vertical centres lie within `ytol` points form one row. Spans less
    than `gap` points apart horizontally are merged into one cell, so a word split
    across fonts stays one word while separate columns stay separate cells.
    """
    spans = []
    for block in page.get_text("dict", flags=FLAGS)["blocks"]:
        for line in block.get("lines", []):
            for s in line["spans"]:
                if not s["text"].strip():
                    continue
                x0, y0, x1, y1 = s["bbox"]
                bold = bool(s["flags"] & 16) or "bold" in s["font"].lower()
                # Tab characters in the source come out of this mode as U+FFFD.
                text = s["text"].replace("�", " ")
                spans.append(((y0 + y1) / 2, x0, x1, text, bold))
    spans.sort(key=lambda s: (s[0], s[1]))

    groups: list[list] = []
    for s in spans:
        if groups and abs(groups[-1][0] - s[0]) <= ytol:
            groups[-1][1].append(s)
        else:
            groups.append([s[0], [s]])

    rows = []
    for y, members in groups:
        members.sort(key=lambda s: s[1])
        cells: list[tuple] = []
        for _, x0, x1, text, bold in members:
            if cells and x0 - cells[-1][1] < gap:
                px0, px1, ptext, pbold = cells[-1]
                touching = ptext.endswith(" ") or text.startswith(" ") or x0 - px1 < 0.8
                cells[-1] = (px0, x1, ptext + ("" if touching else " ") + text, pbold or bold)
            else:
                cells.append((x0, x1, text, bold))
        rows.append((y, [(a, b, " ".join(t.split()), bo) for a, b, t, bo in cells]))
    return rows


if __name__ == "__main__":
    # Dump one page with coordinates: the first step in writing a parser for a new layout.
    #   python layout_rows.py codebook.pdf 21
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    doc = pymupdf.open(sys.argv[1])
    for y, cells in page_rows(doc[int(sys.argv[2]) - 1]):
        print(f"{y:6.1f}  " + " | ".join(
            f"{x0:.0f}-{x1:.0f}{'*' if b else ''}:{t}" for x0, x1, t, b in cells))
