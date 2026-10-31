"""Measure how well study notes keep a page's knowledge, for pages you already have a
reviewed transcription of (the answer key). Prints numbers only, never page text; the
notes themselves are saved in --out for you to read.

    python scripts/notes_eval.py BOOK.pdf --key WORK_DIR/pages --pages 948,950,953 \\
        [--provider gemini] [--model gemini-3.6-flash] [--out notes_eval]

For each page it runs the same pipeline as a refused page in a real conversion (notes,
check, one revision, the copied-wording guard), then one more check of the final notes,
and reports:
  copied     8-word runs of the notes found in the page's text layer (should be 0)
  items      the page's equation / example / table / figure numbers the notes mention
  decimals   numbers with 2+ decimals in the answer key that the notes have exactly
  wrong      statements the final check says do not match the page
  missing    important points the final check says are left out
The checker is itself a model and makes mistakes; read a sample of the notes yourself.
Costs about four requests a page. Use your own documents, or ones you may share.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bettermarkitdown import notes  # noqa: E402
from bettermarkitdown.config import get_api_key, get_model, resolve_endpoint  # noqa: E402
from bettermarkitdown.core import (  # noqa: E402,I001
    Cache,
    Meter,
    RateLimiter,
    describe_image,
    render,
    shrink,
)
from bettermarkitdown.prompts import NOTES_CHECK_PROMPT  # noqa: E402
from bettermarkitdown.providers import make_client  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("pdf")
    parser.add_argument("--key", required=True, help="folder of reviewed NNNN.md page files")
    parser.add_argument("--pages", required=True, help="comma-separated, 1-based")
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--out", default="notes_eval")
    args = parser.parse_args()

    import pymupdf

    sys.stdout.reconfigure(encoding="utf-8")
    spec, base_url = resolve_endpoint(args.provider)
    model = get_model(args.model, spec.id)
    client = make_client(spec, get_api_key(provider=spec.id), base_url)
    out = Path(args.out)
    out.mkdir(exist_ok=True)
    meter = Meter(0.75, 3.75) if spec.id == "gemini" else Meter(0, 0)
    cache, limiter = Cache(out / "cache.json"), RateLimiter(60)

    def ask(png: bytes, prompt: str) -> str:
        reply = describe_image(client, model, png, prompt, cache=cache, limiter=limiter,
                               meter=meter, max_retries=2)
        return "" if reply.startswith("*[vision call failed") else reply

    rows = []
    with pymupdf.open(args.pdf) as doc:
        for n in (int(p) for p in args.pages.split(",")):
            page = doc[n - 1]
            png = shrink(render(page, 200), 1568)
            text = page.get_text()
            written = notes.study_notes(ask, png, text, n) or ""
            (out / f"{n:04d}.md").write_text(written, encoding="utf-8")
            body = written.split("\n\n", 1)[-1]
            key = (Path(args.key) / f"{n:04d}.md").read_text(encoding="utf-8")
            check = notes._parse_check(ask(png, NOTES_CHECK_PROMPT + body))
            items = notes.numbered_items(text)
            page_runs = notes._runs(notes._words(text))
            copied = len(notes._runs(notes._words(body)) & page_runs)
            key_nums = set(re.findall(r"\d+\.\d{2,}", re.sub(r"<!--.*?-->", "", key,
                                                             flags=re.S)))
            rows.append({
                "page": n, "notes_chars": len(body), "copied": copied,
                "items": f"{len(items) - len(notes.missing_items(body, items))}/{len(items)}",
                "decimals": f"{sum(x in body for x in key_nums)}/{len(key_nums)}",
                "wrong": len(check.get("wrong", [])), "missing": len(check.get("missing", [])),
                "revised": "revised once" in written})
            print(json.dumps(rows[-1]), flush=True)
    print("cost:", Meter.usd(meter.cost()))
    (out / "report.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
