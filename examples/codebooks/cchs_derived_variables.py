"""CCHS 2022 PUMF Derived Variable (DV) Specifications -> Markdown, from the text layer.

    python cchs_derived_variables.py CCHS_2022_PUMF_Grouped_Variables.pdf derived_variables.md

Each derived variable becomes a section (source variables, description, notes) with
its Value / Condition(s) / Description / Notes table. Module introductions and the
module-level "Temporary Reformat" tables (food-security sums, income cut-offs) are
kept with their module.

Two layout facts do most of the work:

  - Table rows are separated by ruled lines, so a cell that wraps over several
    lines is grouped by the rules around it, not guessed from spacing.
  - Inside a cell, a line break is either a soft wrap (the next word did not fit)
    or a deliberate one ("Group:" followed by one health region per line). The
    test is whether the next line's first word would have fitted on the line
    before; deliberate breaks are kept as <br>.

Check the result with check_words.py: every word of the PDF body must appear in
the Markdown.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from layout_rows import page_rows  # noqa: E402

TOP, BOTTOM = 52, 725
FIELD_LABELS = {"Variable name", "Based on", "Description", "Note", "Internet site", "Source"}
COLNAMES = ["Value", "Condition(s)", "Description", "Notes"]
RIGHT_MARGIN = 578
CHAR_W = 4.6  # approximate width of one character at the body font size, in points


def hrules(page) -> list[float]:
    """y positions of the horizontal rules that separate table rows."""
    ys = []
    for drawing in page.get_drawings():
        r = drawing["rect"]
        if r.height <= 2.5 and r.width > 300:
            ys.append((r.y0 + r.y1) / 2)
    return sorted(ys)


def joiner(prev_x1: float, prev_text: str, nxt: str, right: float) -> str:
    """How to join two lines of one cell: ' ' for a soft wrap, '<br>' for a real break."""
    first = nxt.split()[0] if nxt.split() else ""
    if prev_x1 + CHAR_W * (len(first) + 1) > right:
        return " "                    # the next word would not have fitted: soft wrap
    if re.search(r"[A-Za-z]-$", prev_text):
        return ""                     # a word hyphenated across lines ("cut-" + "off")
    if re.search(r"(\bor|\band|\+|,|\(|-|/)$", prev_text):
        return " "                    # a condition or list that carries on
    return "<br>"


class Cell:
    def __init__(self):
        self.parts: list[list] = []   # [x1, text, y]

    def add(self, x1, text, y, right, numeric_join=False):
        if self.parts:
            px1, ptext, py = self.parts[-1]
            if numeric_join and re.fullmatch(r"\d+", text) and re.search(r"\d$", ptext):
                # a long code split over two lines: 9999.99999999 + 6
                self.parts[-1] = [x1, ptext + text, y]
                return
            if y - py > 14:
                sep = "<br><br>"      # a paragraph gap
            elif self.parts[0][1] == "Group:":
                sep = "<br>"          # one health region per line
            else:
                sep = joiner(px1, ptext, text, right)
            self.parts.append([x1, sep + text, y])
        else:
            self.parts.append([x1, text, y])

    def text(self) -> str:
        return "".join(t for _, t, _ in self.parts).replace("|", "\\|").strip()


def container(kind, title, page, num=""):
    return {"kind": kind, "title": title, "num": num, "page": page,
            "fields": [], "tables": [], "intro": Cell()}


def parse(pdf):
    doc = pymupdf.open(pdf)
    items, notes = [], []
    cur, field, mode, cols, table = None, None, None, None, None

    def col_of(x0):
        idx = 0
        for i, c in enumerate(cols):
            if x0 >= c - 6:
                idx = i
        return idx

    def col_right(i):
        return cols[i + 1] - 6 if i + 1 < len(cols) else RIGHT_MARGIN

    for pno in range(4, doc.page_count):   # pages 1-4: cover and contents (index rebuilt)
        page = doc[pno]
        rules = hrules(page)
        last_y = None
        for y, cells in page_rows(page):
            if not TOP < y < BOTTOM:
                continue
            texts = [c[2] for c in cells]
            joined = " ".join(texts)
            bold0 = cells[0][3]
            if bold0 and re.search(r"\(\d+ DVs?\)$", joined) and cells[0][0] > 100:
                cur = container("module", joined, pno + 1)
                items.append(cur)
                mode, field = "intro", None
                continue
            if bold0 and re.fullmatch(r"\d+ \)", texts[0]) and len(cells) >= 2:
                cur = container("dv", " ".join(texts[1:]), pno + 1, texts[0].replace(" ", ""))
                items.append(cur)
                mode, field = "fields", None
                continue
            if cur is None:
                notes.append(f"p{pno + 1}: text before the first module: {joined}")
                continue
            label = texts[0].rstrip(":")
            if bold0 and texts[0].endswith(":") and label in FIELD_LABELS and cells[0][0] < 60:
                c = Cell()
                if len(cells) > 1:
                    c.add(cells[-1][1], " ".join(texts[1:]), y, RIGHT_MARGIN)
                field = [label, c]
                cur["fields"].append(field)
                mode = "fields"
                continue
            if bold0 and joined in ("Specifications", "Temporary Reformat"):
                table = {"kind": joined, "rows": []}
                cur["tables"].append(table)
                mode = "await_header"
                continue
            if mode == "await_header":
                if bold0 and texts[0] == "Value":
                    cols = [c[0] for c in cells]
                    if texts != COLNAMES:
                        notes.append(f"p{pno + 1}: unexpected table header {texts}")
                    mode, last_y = "table", None
                else:
                    notes.append(f"p{pno + 1}: expected a table header, got: {joined}")
                continue
            if mode == "intro":
                line = " ".join(f"**{c[2]}**" if c[3] else c[2] for c in cells)
                cur["intro"].add(cells[-1][1], line, y, RIGHT_MARGIN)
                continue
            if mode == "fields" and field and cells[0][0] > 100:
                field[1].add(cells[-1][1], joined, y, RIGHT_MARGIN)
                continue
            if mode == "table":
                if bold0 and len(cells) == 1 and cells[0][0] < 60:
                    table["rows"].append(("sub", texts[0]))   # a temporary variable's name
                    last_y = y
                    continue
                rows = table["rows"]
                if not rows or rows[-1][0] == "sub":
                    new_row = True
                elif last_y is None:          # first table line on a new page
                    new_row = col_of(cells[0][0]) == 0
                else:
                    new_row = any(last_y < r < y for r in rules)
                if new_row:
                    rows.append(("row", [Cell() for _ in cols], pno + 1))
                row = rows[-1][1]
                for x0, x1, t, _ in cells:
                    i = col_of(x0)
                    row[i].add(x1, t, y, col_right(i), numeric_join=(i == 0))
                last_y = y
                continue
            notes.append(f"p{pno + 1}: unhandled ({mode}) in {cur['title']}: {joined}")
    return items, notes


def varname(dv) -> str:
    for label, cell in dv["fields"]:
        if label == "Variable name":
            return cell.text()
    return dv["title"]


def render_tables(o, item):
    for t in item["tables"]:
        o.append(f"**{t['kind']}**\n")
        o.append("| Value | Condition(s) | Description | Notes |")
        o.append("|---|---|---|---|")
        for r in t["rows"]:
            if r[0] == "sub":
                o.append(f"| **{r[1]}** |  |  |  |")
            else:
                o.append("| " + " | ".join(c.text().replace("<br><br>", "<br>") for c in r[1])
                         + " |")
        o.append("")


def render(items) -> str:
    dvs = [it for it in items if it["kind"] == "dv"]
    o = [
        "# Canadian Community Health Survey (CCHS), 2022 — Annual Component",
        "## Public Use Microdata File (PUMF) — Derived Variable (DV) Specifications "
        "(Grouped Variables)\n",
        "*Statistics Canada, 2025. Converted from `CCHS_2022_PUMF_Grouped_Variables.pdf`.*\n",
        "> **How to read this file**",
        "> - Each derived/grouped variable has a section `### VARNAME — Title`, listing the "
        "source variables (*Based on*), a description, notes, and a **Specifications** table: "
        "the variable takes the **Value** when the **Condition(s)** hold. Rows are evaluated in "
        "the order listed.",
        "> - **Temporary Reformat** tables define intermediate (temporary) variables used in "
        "the specifications; temporary variables are not on the PUMF file.",
        "> - Notes column: **NA** = not applicable / valid skip; **NS** = not stated.",
        "> - `<br>` marks a line break inside a table cell of the original.\n",
        f"**{len(dvs)} derived variables in {len(items) - len(dvs)} modules.**\n",
        "## Index\n",
        "| Module | No. | Variable | Title | PDF page |",
        "|---|---|---|---|---|",
    ]
    module = ""
    for it in items:
        if it["kind"] == "module":
            module = it["title"]
            continue
        name = varname(it)
        o.append(f"| {module} | {it['num']} | [`{name}`](#{name.lower()}) | {it['title']} | "
                 f"{it['page']} |")
    o.append("\n---\n")
    for it in items:
        if it["kind"] == "module":
            o.append(f"## {it['title']}\n")
            intro = it["intro"].text().replace("<br><br>", "\n\n").replace("<br>", "  \n")
            if intro or it["tables"]:
                o.append(f"*(PDF p. {it['page']})*\n")
            if intro:
                o.append(intro + "\n")
            render_tables(o, it)
            continue
        name = varname(it)
        o.append(f'<a id="{name.lower()}"></a>')
        o.append(f"### {name} — {it['title']}")
        o.append(f"\n*DV {it['num']} of this module · (PDF p. {it['page']})*\n")
        for label, cell in it["fields"]:
            value = cell.text().replace("<br><br>", "<br>")
            if label == "Variable name":
                value = f"`{value}`"
            o.append(f"- **{label}:** {value}")
        o.append("")
        render_tables(o, it)
    return "\n".join(o) + "\n"


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    items, notes = parse(argv[0])
    Path(argv[1]).write_text(render(items), encoding="utf-8")
    n_dv = sum(1 for i in items if i["kind"] == "dv")
    n_rows = sum(len(t["rows"]) for i in items for t in i["tables"])
    print(f"{n_dv} derived variables, {len(items) - n_dv} modules, {n_rows} table rows")
    for note in notes:
        print("PROBLEM", note)
    print("no unhandled lines" if not notes else f"{len(notes)} problem(s)")
    return 1 if notes else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
