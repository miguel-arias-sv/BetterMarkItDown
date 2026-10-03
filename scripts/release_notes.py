"""Print one version's section of CHANGELOG.md, for use as GitHub Release notes.

    python scripts/release_notes.py            # the version in bettermarkitdown/__init__.py
    python scripts/release_notes.py v1.1.0     # a tag; must match __init__.py

Exits 1, with the reason on stderr, if the tag and the package version disagree or the
changelog has no section for the version. The release workflow relies on both checks.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def package_version() -> str:
    init = (ROOT / "bettermarkitdown" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'^__version__ = "([^"]+)"', init, re.M).group(1)


def section(changelog: str, version: str) -> str | None:
    """The text under `## [version]`, up to the next version heading or link list."""
    m = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|^\[[^\]]+\]: |\Z)",
                  changelog, re.M | re.S)
    if not m:
        return None
    # GitHub release notes keep single line breaks, so rejoin the hard-wrapped
    # continuation lines of each bullet into one line.
    return re.sub(r"\n {2,}(?=\S)", " ", m.group(1).strip())


def main(argv: list[str]) -> int:
    version = package_version()
    if argv:
        tag = argv[0].removeprefix("v")
        if tag != version:
            print(f"Tag v{tag} does not match __version__ {version} in "
                  "bettermarkitdown/__init__.py. Bump one of them.", file=sys.stderr)
            return 1
    notes = section((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), version)
    if not notes:
        print(f"CHANGELOG.md has no '## [{version}]' section. Write the What's New first.",
              file=sys.stderr)
        return 1
    sys.stdout.reconfigure(encoding="utf-8")
    print(notes)
    print("\n---\nInstall: `pip install bettermarkitdown-" + version + "-py3-none-any.whl` "
          "(attached below), or see the README. Full history: CHANGELOG.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
