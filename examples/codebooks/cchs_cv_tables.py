"""CCHS 2022 PUMF Approximate Sampling Variability (CV) Tables -> Markdown, from the text layer.

    python cchs_cv_tables.py CCHS_2022_CV_Tables_PUMF.pdf cv_tables.md

108 look-up tables (Canada, age groups, provinces, health regions) of the
approximate coefficient of variation by numerator (rows) and estimated percentage
(14 columns), plus the input data used to build them.

Each value is assigned to its column by its right edge, then checked against the
formula the tables are generated from. Under simple random sampling with a design
effect, the CV of an estimated proportion p with numerator X is

    CV(X, p) = K * sqrt((1 - p) / X)

with one constant K per table. K is fitted per table and every non-asterisk cell
must agree with the formula within rounding. A value in the wrong column, or a
misread digit, fails this check. Exit code 1 if any table fails.
"""

from __future__ import annotations

import math
import re
import sys
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from layout_rows import page_rows  # noqa: E402

HEADER_Y = 50          # the running header sits above this
NUM = re.compile(r"^[\d,]+(\.\d+)?$")
PERCENTAGES = ["0.1%", "1.0%", "2.0%", "5.0%", "10.0%", "15.0%", "20.0%", "25.0%", "30.0%",
               "35.0%", "40.0%", "50.0%", "70.0%", "90.0%"]
SUPPRESSED = "*****"


def parse_toc(doc):
    """[(level, title, page)] from the table of contents. Level by indent: part,
    section, sub-entry."""
    toc = []
    for pno in range(2, 5):
        for _, cells in page_rows(doc[pno]):
            m = re.match(r"^(.*?)\s*\.{3,}\s*(\d+)$", " ".join(c[2] for c in cells))
            if not m:
                continue
            x0 = cells[0][0]
            level = 0 if x0 < 26 else (1 if x0 < 45 else 2)
            toc.append((level, m.group(1).strip(), int(m.group(2))))
    return toc


def parse_inputs(doc, pages):
    """Input-data tables: label, design effect, sample size, population."""
    tables = []
    for pno in pages:
        pending = ""
        for y, cells in page_rows(doc[pno]):
            if y < HEADER_Y or (re.fullmatch(r"\d+", cells[0][2]) and y > 740):
                continue
            texts = [c[2] for c in cells]
            if (len(cells) == 1 and cells[0][0] > 150 and texts[0] != "POPULATION"
                    and not NUM.match(texts[0])):
                if texts[0] != "INPUT DATA FOR SAMPLING VARIABILITY TABLES":
                    tables.append({"title": texts[0], "rows": [], "page": pno + 1})
                continue
            if any(t in ("POPULATION", "EFFECT", "DESIGN")
                   or t.startswith(("PROVINCES", "AGEGROUP", "REGIONS", "SIZE")) for t in texts):
                continue                                  # column headings
            nums = [c for c in cells if NUM.match(c[2]) and c[0] > 270]
            labels = [c[2] for c in cells if c not in nums]
            if len(nums) == 3:
                label = (pending + " " + " ".join(labels)).strip()
                tables[-1]["rows"].append([label] + [c[2] for c in nums])
                pending = ""
            elif not nums:
                pending = (pending + " " + " ".join(labels)).strip()   # a wrapped label
            else:
                raise ValueError(f"p{pno + 1}: unexpected input row {texts}")
    return tables


def parse_cv(doc, pno):
    titles, header, data, edges = [], None, [], None
    for y, cells in page_rows(doc[pno]):
        texts = [c[2] for c in cells]
        if y < HEADER_Y + 40 and texts[0].startswith("CCHS 2022"):
            continue
        if header is None:
            if texts[0] == "PERCENTAGE" and len(cells) == 15:
                header = texts[1:]
                edges = [c[1] for c in cells[1:]]       # right edge of each column
            elif texts[0] not in ("NUMERATOR", "OF", "ESTIMATED PERCENTAGE",
                                  "Canadian Community Health Survey - 2022",
                                  "APPROXIMATE SAMPLING VARIABILITY TABLES"):
                titles.append(" ".join(texts))
            continue
        if texts[0] == "('000)" or texts[0].startswith("NOTE:"):
            continue
        if re.fullmatch(r"\d+", texts[0]) and len(cells) == 15:
            values = [""] * 14
            for _, x1, t, _ in cells[1:]:
                i = min(range(14), key=lambda k: abs(edges[k] - x1))
                if abs(edges[i] - x1) > 4 or values[i]:
                    raise ValueError(f"p{pno + 1}: misaligned cell {t} at x={x1:.1f}")
                values[i] = t
            data.append((texts[0], values))
            continue
        if re.fullmatch(r"\d+", texts[0]) and len(cells) == 1 and y > 690:
            continue                                      # page number
        raise ValueError(f"p{pno + 1}: unexpected row {texts}")
    return {"titles": titles, "header": header, "rows": data, "page": pno + 1}


def formula_mismatches(table) -> list[tuple]:
    """Cells that disagree with CV = K * sqrt((1 - p) / X) beyond rounding."""
    ps = [float(h.rstrip("%")) / 100 for h in table["header"]]
    cells = [(int(x), p, float(v)) for x, values in table["rows"]
             for p, v in zip(ps, values, strict=True) if v != SUPPRESSED]
    ks = sorted(v / math.sqrt((1 - p) / x) for x, p, v in cells)
    k = ks[len(ks) // 2]
    return [(x, p, v, round(k * math.sqrt((1 - p) / x), 2)) for x, p, v in cells
            if abs(k * math.sqrt((1 - p) / x) - v) > 0.05 + 0.002 * v]


def render(toc, inputs, cv) -> str:
    o = [
        "# Canadian Community Health Survey (CCHS), 2022 — Annual Component",
        "## Public-Use Microdata File (PUMF) — Approximate Sampling Variability Tables "
        "(CV look-up tables)\n",
        "*Statistics Canada, September 2025. Converted from `CCHS_2022_CV_Tables_PUMF.pdf`.*\n",
        "> **How to read this file**",
        "> - Each table gives the approximate **coefficient of variation (CV, in %)** of an "
        "estimate, by the **numerator of the percentage in thousands** (rows, `'000`) and the "
        "**estimated percentage** (columns).",
        "> - `*****` = cell shown as asterisks in the source (no CV given for that combination). "
        "Per the User Guide (§11.2, Rule 1), for an estimate of a *number* locate the row and "
        "follow the asterisks across to the first figure; when the exact value is not a row, use "
        "the closest **smaller** row value.",
        "> - The tables are approximate and unofficial; for exact CVs use the bootstrap weights. "
        "The User Guide (§10.4 release guidelines, §11 How to use the CV tables) explains CVs, "
        "confidence intervals (CI = X̂ ± z·X̂·CV) and the minimum-sample rules.",
        "> - The **input data** (design effect, sample size, population) used to build each "
        "table are listed first.",
        '> - Every table in the source carries the note: *"NOTE: FOR CORRECT USAGE OF THESE '
        'TABLES PLEASE REFER TO MICRODATA DOCUMENTATION"*.\n',
        "## Contents\n",
    ]
    for level, title, page in toc:
        o.append("  " * level + f"- {title} — PDF p. {page}")
    o += ["\n---\n", "# Input data for sampling variability tables\n"]
    for t in inputs:
        o.append(f"## Input data — {t['title']}\n")
        o.append(f"*(PDF p. {t['page']})*\n")
        first = {"Provinces": "Province / territory",
                 "Canada by Age Group": "Age group"}.get(t["title"], "Region")
        o.append(f"| {first} | Design effect | Sample size | Population size (aged 12 and older) |")
        o.append("|---|---:|---:|---:|")
        for r in t["rows"]:
            o.append("| " + " | ".join(r) + " |")
        o.append("")
    o += ["---\n", "# Approximate sampling variability tables\n"]
    section = None
    for t in cv:
        leaf = [e for e in toc if e[2] == t["page"]][-1]   # the entry naming this table
        for s in (e for e in toc if e[2] == t["page"] and e[0] == 1):
            if s[1] != section:
                section = s[1]
                # A section that is itself one table (Canada) gets no separate heading.
                if not (leaf == s and len(t["titles"]) <= 1):
                    o.append(f"## {s[1]}\n")
        o.append(f"{'##' if leaf[0] == 1 else '###'} CV table: {leaf[1]}\n")
        o.append(f"*(PDF p. {t['page']})*\n")
        o.append("| Numerator ('000) | " + " | ".join(t["header"]) + " |")
        o.append("|---:|" + "---:|" * 14)
        for x, values in t["rows"]:
            o.append(f"| {x} | " + " | ".join(values) + " |")
        o.append("")
    return "\n".join(o) + "\n"


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    doc = pymupdf.open(argv[0])
    toc = parse_toc(doc)
    inputs = parse_inputs(doc, range(5, 10))
    cv = [parse_cv(doc, p) for p in range(10, doc.page_count)]
    problems = []
    for t in cv:
        if t["header"] != PERCENTAGES:
            problems.append(f"p{t['page']}: unexpected header {t['header']}")
        bad = formula_mismatches(t)
        if bad:
            problems.append(f"p{t['page']}: {len(bad)} cell(s) off the CV formula, e.g. {bad[:3]}")
        # The table's own title lines must name the same domain as the contents entry.
        entries = [e for e in toc if e[2] == t["page"]]
        page_title = " ".join(t["titles"])
        if not entries:
            problems.append(f"p{t['page']}: no table-of-contents entry")
        elif entries[-1][1] not in page_title:
            problems.append(f"p{t['page']}: title '{page_title}' vs contents '{entries[-1][1]}'")
    Path(argv[1]).write_text(render(toc, inputs, cv), encoding="utf-8")
    print(f"{len(inputs)} input tables ({sum(len(t['rows']) for t in inputs)} rows), "
          f"{len(cv)} CV tables ({sum(len(t['rows']) for t in cv)} rows)")
    for p in problems:
        print("PROBLEM", p)
    print("all checks passed" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
