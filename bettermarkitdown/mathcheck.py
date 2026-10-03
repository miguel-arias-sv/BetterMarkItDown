"""Render every formula with KaTeX and report the ones that fail.

`verify.math_problems` catches structural slips (an unmatched `$$`, a review note
inside an equation). This goes further: it hands each `$$display$$` and `$inline$`
formula to KaTeX, the renderer most Markdown viewers use, so an unknown macro or an
unbalanced brace is caught before a reader meets a red error box.

It needs Node.js and the `katex` npm package, and is skipped -- never failed -- when
either is missing. KaTeX is looked for in `$BMID_KATEX_DIR`, the repo's own
`node_modules` (`npm install`), the current directory, and the global npm root
(`npm install -g katex`).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

_COMMENT = re.compile(r"<!--.*?-->", re.S)
_DISPLAY = re.compile(r"\$\$(.*?)\$\$", re.S)
# One `$...$` pair inside a paragraph; `\$` is a literal dollar sign, not a delimiter.
_INLINE = re.compile(r"(?<!\\)\$((?:\\.|[^$\\])+?)(?<!\\)\$")
_SCRIPT = Path(__file__).with_name("katex_render.js")
INSTALL_HINT = ("install Node.js and run `npm install` in the BetterMarkItDown folder "
                "(or `npm install -g katex`)")


def extract_formulas(md: str) -> list[tuple[str, bool]]:
    """Every formula on a page, as (tex, is_display), in reading order of each kind."""
    md = _COMMENT.sub(" ", md)
    found = [(m.group(1), True) for m in _DISPLAY.finditer(md)]
    rest = _DISPLAY.sub(" ", md)            # so display dollars cannot pair with inline ones
    for paragraph in re.split(r"\n\s*\n", rest):
        found += [(m.group(1), False) for m in _INLINE.finditer(paragraph)]
    return found


def find_node() -> str | None:
    node = shutil.which("node")
    if node:
        return node
    # A fresh Windows install is not on PATH until the next login.
    default = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "nodejs" / "node.exe"
    return str(default) if default.is_file() else None


def _search_paths(node: str) -> list[str]:
    paths = [os.environ.get("BMID_KATEX_DIR", ""), str(Path(__file__).resolve().parents[1])]
    npm = shutil.which("npm") or shutil.which("npm", path=str(Path(node).parent))
    if npm:
        try:
            root = subprocess.run([npm, "root", "-g"], capture_output=True, text=True,
                                  timeout=30).stdout.strip()
            paths.append(root)
        except (OSError, subprocess.SubprocessError):
            pass                            # no global root is fine: the local paths remain
    return [p for p in paths if p]


def render_check(pages: dict[int, str]) -> tuple[dict[int, list[str]], str | None]:
    """Render the formulas of each page. Returns ({page: [problem, ...]}, skip_reason).

    skip_reason is None when the check ran; otherwise it says why it could not."""
    node = find_node()
    if not node:
        return {}, f"Node.js not found -- {INSTALL_HINT}"

    items, where = [], []
    for page, md in pages.items():
        for tex, display in extract_formulas(md):
            items.append({"id": len(items), "tex": tex, "display": display})
            where.append((page, tex))
    if not items:
        return {}, None

    payload = json.dumps({"paths": _search_paths(node), "items": items})
    try:
        proc = subprocess.run([node, str(_SCRIPT)], input=payload, capture_output=True,
                              text=True, encoding="utf-8", timeout=600)
        reply = json.loads(proc.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        return {}, f"KaTeX check could not run ({exc})"
    if "error" in reply:
        return {}, f"KaTeX not found -- {INSTALL_HINT}"

    problems: dict[int, list[str]] = {}
    for failure in reply["failures"]:
        page, tex = where[failure["id"]]
        snippet = " ".join(tex.split())
        snippet = snippet if len(snippet) <= 70 else snippet[:70] + " ..."
        message = failure["message"]
        if not message.startswith("KaTeX"):
            message = "KaTeX: " + message
        problems.setdefault(page, []).append(f"{message} in `{snippet}`")
    return problems, None
