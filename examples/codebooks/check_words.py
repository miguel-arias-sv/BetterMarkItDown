"""Check that a parsed document lost nothing: every word and number of the PDF body
must appear in the Markdown at least as many times.

    python check_words.py document.pdf document.md --top 52 --bottom 725 --first-page 5

`--top` / `--bottom` (points) cut off the running header and footer, and
`--first-page` skips a cover and table of contents that the parser rebuilt.
What it reports as missing is usually boilerplate the parser dropped on purpose,
such as repeated column headings or empty field labels. Anything else is a bug.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from layout_rows import page_rows  # noqa: E402

TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9.,'’_%$<>=/+-]*")


def tokens(text: str) -> list[str]:
    return [t.rstrip(".,").replace("’", "'") for t in TOKEN.findall(text)]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pdf")
    ap.add_argument("markdown")
    ap.add_argument("--top", type=float, default=50)
    ap.add_argument("--bottom", type=float, default=765)
    ap.add_argument("--first-page", type=int, default=1)
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    source = Counter()
    for page in pymupdf.open(args.pdf).pages(args.first_page - 1):
        for y, cells in page_rows(page):
            if args.top < y < args.bottom:
                for c in cells:
                    source.update(tokens(c[2]))
    text = Path(args.markdown).read_text(encoding="utf-8")
    text = re.sub(r"<br>|\*\*|`|\\(?=\|)", " ", text)     # markup that splits or wraps words
    missing = source - Counter(tokens(text))

    print(f"{sum(source.values())} words and numbers in the PDF body, "
          f"{sum(missing.values())} missing from the Markdown")
    for word, n in missing.most_common(40):
        print(f"  {word} x{n}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
