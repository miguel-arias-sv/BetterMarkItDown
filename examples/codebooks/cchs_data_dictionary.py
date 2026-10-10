"""CCHS 2022 PUMF Data Dictionary (with frequencies) -> Markdown, from the text layer.

    python cchs_data_dictionary.py CCHS_2022_DataDictionary_Freqs.pdf data_dictionary.md

Each variable becomes a section with its metadata and an answer-category table
(code, frequency, weighted frequency, %). The numbers are copied from the PDF,
never re-read, and then checked arithmetically:

  - every category table's frequencies sum exactly to its printed Total;
  - weighted frequencies sum to the weighted Total within rounding;
  - every Total is the same (every variable covers every respondent);
  - no category row is missing a cell;
  - the variables found match the table of contents, in order.

Exit code 1 if any check fails. The column positions below are specific to this
document's layout: dump a page with `python layout_rows.py <pdf> <page>` to read
off the positions for another one.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from layout_rows import page_rows  # noqa: E402

TOP, BOTTOM = 50, 765          # running header / footer cut-offs, in points
VALUE_X = 150                  # field values start at x ~178; labels end before this
FIELDS = ["Question Name", "Concept", "Question Text", "Universe", "Note", "Source"]
# Right edges of the right-aligned numeric columns of the answer-category table.
COLUMNS = {"code": 306, "freq": 387, "wfreq": 485, "pct": 523}


def classify(cell) -> str:
    x0, x1, text, bold = cell
    for name, edge in COLUMNS.items():
        if abs(x1 - edge) <= 4 and re.fullmatch(r"[\d.,\s-]+", text):
            return name
    return "label"


def parse(pdf):
    doc = pymupdf.open(pdf)
    toc, variables, notes = [], [], []
    cur, field, mode = None, None, None
    for pno, page in enumerate(doc, start=1):
        for y, cells in page_rows(page):
            if not TOP < y < BOTTOM:
                continue
            first = cells[0][2]
            texts = [c[2] for c in cells]

            # Table of contents: VARIABLE | positions | description .... page
            if first == "Variable" and "Position" in texts and "Description" in texts:
                mode = "toc"
                continue
            if mode == "toc" and first != "Variable Name:":
                if re.fullmatch(r"[A-Z0-9_]+", first) and len(cells) >= 3:
                    desc = " ".join(texts[2:])
                    m = (re.match(r"(.*?)[ .]*\.\s*(\d+)$", desc)
                         or re.match(r"(.*?)\s+(\d+)$", desc))
                    toc.append((first, texts[1], m.group(1).strip(" .") if m else desc,
                                m.group(2) if m else ""))
                continue

            # Variable header: Variable Name: X   Length: n   Position: n
            if first == "Variable Name:":
                pairs = dict(zip(texts, texts[1:], strict=False))
                cur = {"name": texts[1], "length": pairs.get("Length:", ""),
                       "position": pairs.get("Position:", ""), "page": pno,
                       "fields": {}, "cats": [], "total": None}
                variables.append(cur)
                field, mode = None, "var"
                continue
            if cur is None:
                continue

            label = first.rstrip(":")
            if cells[0][3] and first.endswith(":") and label in FIELDS:
                field, mode = label, "var"
                cur["fields"][field] = " ".join(c[2] for c in cells[1:] if c[0] > VALUE_X)
                continue
            if first == "Answer Categories" and "Code" in texts:
                mode = "table"          # also skips the header repeated at a page top
                continue
            if mode == "var" and field and cells[0][0] > VALUE_X:
                # A wrapped field value. A line starting with '- ' is a list item in
                # the question text: keep it visibly separate.
                value = " ".join(texts)
                if re.match(r"^[-•]\s", value):
                    value, sep = re.sub(r"^[-•]\s+", "", value), " — "
                else:
                    sep = " "
                cur["fields"][field] = (cur["fields"][field] + sep + value).strip()
                continue
            if mode == "table":
                kinds = [classify(c) for c in cells]
                row = {"label": " ".join(c[2] for c, k in zip(cells, kinds, strict=True)
                                         if k == "label")}
                row.update({k: c[2] for c, k in zip(cells, kinds, strict=True) if k != "label"})
                if row["label"] == "Total" and cells[0][3]:
                    cur["total"] = row
                elif any(k in row for k in ("freq", "wfreq", "pct")):
                    cur["cats"].append(row)
                elif cur["cats"]:
                    # A label too long for its column wraps onto a line of its own,
                    # below the line that carries the numbers.
                    cur["cats"][-1]["label"] += " " + row["label"]
                else:
                    notes.append(f"p{pno}: label line before any category in {cur['name']}")
                continue
            notes.append(f"p{pno}: unhandled row in {cur['name']} ({mode}): {texts}")
    return toc, variables, notes


def check(toc, variables) -> list[str]:
    def num(x):
        return int(x.replace(",", "")) if x else 0

    problems = []
    totals = {v["total"]["freq"] for v in variables if v["total"]}
    if len(totals) > 1:
        problems.append(f"Totals differ between variables: {sorted(totals)}")
    for v in variables:
        t = v["total"]
        if not t:
            if v["cats"]:
                problems.append(f"{v['name']}: categories but no Total row")
            continue                  # e.g. record IDs and weights have no table
        if sum(num(c.get("freq")) for c in v["cats"]) != num(t["freq"]):
            problems.append(f"{v['name']}: frequencies do not sum to the Total")
        if abs(sum(num(c.get("wfreq")) for c in v["cats"]) - num(t["wfreq"])) > len(v["cats"]):
            problems.append(f"{v['name']}: weighted frequencies do not sum to the Total")
        for c in v["cats"]:
            if not c["label"] or not all(c.get(k) for k in COLUMNS):
                problems.append(f"{v['name']}: incomplete row {c}")
    if [t[0] for t in toc] != [v["name"] for v in variables]:
        problems.append("variables found do not match the table of contents")
    return problems


def esc(s: str) -> str:
    return s.replace("|", "\\|")


def render(toc, variables) -> str:
    o = [
        "# Canadian Community Health Survey (CCHS), 2022 — Annual Component",
        "## Public Use Microdata File (PUMF) — Data Dictionary with Frequencies\n",
        "*Statistics Canada, September 2025. Converted from "
        "`CCHS_2022_DataDictionary_Freqs.pdf`.*\n",
        "> **How to read this file**",
        "> - One section per variable, in file order, headed `### VARNAME — Concept`.",
        "> - *Length* and *Position* give the fixed-width record layout; *(PDF p. N)* is the "
        "page in the source PDF.",
        "> - **Frequency** = unweighted sample count; **Weighted Frequency** = estimated "
        "population count (using the survey weight); **%** = weighted percentage. Totals may "
        "not add up due to rounding.",
        "> - Reserve codes (fill the variable's length): **6, 96, 996, 999.6, 9999.6, 99996** = "
        "*Valid skip* (respondent outside the question's universe); **9, 99, 999, 999.9, 9999.9, "
        "99999** = *Not stated* (in the universe but no answer — includes don't know / refusal). "
        "Exclude both from analyses as appropriate.",
        "> - Suffixes in the concept: **(D)** derived variable, **(G)** grouped variable, "
        "**(F)** inclusion flag.",
        "",
        f"**{len(variables)} variables.**\n",
        "## Variable index\n",
        "| Variable | Position | Description | PDF page |",
        "|---|---|---|---|",
    ]
    page_of = {v["name"]: v["page"] for v in variables}
    for name, pos, desc, pg in toc:
        o.append(f"| [`{name}`](#{name.lower()}) | {pos} | {esc(desc)} | {page_of.get(name, pg)} |")
    o += ["\n---\n", "## Variables\n"]
    for v in variables:
        concept = v["fields"].get("Concept", "")
        o.append(f'<a id="{v["name"].lower()}"></a>')
        o.append(f"### {v['name']} — {concept}" if concept else f"### {v['name']}")
        o.append("")
        o.append(f"- **Variable name:** `{v['name']}` · **Length:** {v['length']} · "
                 f"**Position:** {v['position']} · *(PDF p. {v['page']})*")
        for f in FIELDS:
            value = v["fields"].get(f, "").strip()
            if value and f != "Concept":
                o.append(f"- **{f}:** {value}")
        o.append("")
        if v["cats"] or v["total"]:
            o.append("| Answer category | Code | Frequency | Weighted frequency | % |")
            o.append("|---|---:|---:|---:|---:|")
            for c in v["cats"]:
                o.append(f"| {esc(c['label'])} | {c.get('code', '')} | {c.get('freq', '')} | "
                         f"{c.get('wfreq', '')} | {c.get('pct', '')} |")
            t = v["total"]
            if t:
                o.append(f"| **Total** |  | **{t.get('freq', '')}** | **{t.get('wfreq', '')}** | "
                         f"**{t.get('pct', '')}** |")
            o.append("")
    return "\n".join(o) + "\n"


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    toc, variables, notes = parse(argv[0])
    Path(argv[1]).write_text(render(toc, variables), encoding="utf-8")
    problems = check(toc, variables) + notes
    print(f"{len(variables)} variables, {sum(len(v['cats']) for v in variables)} categories")
    for p in problems:
        print("PROBLEM", p)
    print("all checks passed" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
