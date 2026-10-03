"""Release hygiene: one version number, and a What's New for it before it can ship."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bettermarkitdown import __version__  # noqa: E402

spec = importlib.util.spec_from_file_location("release_notes",
                                              ROOT / "scripts" / "release_notes.py")
release_notes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_notes)


def test_changelog_has_a_whats_new_for_the_current_version():
    notes = release_notes.section((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"),
                                  __version__)
    assert notes, f"CHANGELOG.md needs a '## [{__version__}]' section"
    assert "### What's New" in notes or "### Fixed" in notes


def test_release_notes_rejoin_wrapped_bullets_and_stop_at_the_next_version():
    changelog = ("## [2.0.0] - 2027-01-01\n\n- **Big** change that wraps\n  onto a second line.\n\n"
                 "## [1.0.0] - 2026-01-01\n\n- Old.\n\n[2.0.0]: https://example.com\n")
    expected = "- **Big** change that wraps onto a second line."
    assert release_notes.section(changelog, "2.0.0") == expected
    assert release_notes.section(changelog, "1.0.0") == "- Old."
    assert release_notes.section(changelog, "3.0.0") is None


def test_a_tag_that_does_not_match_the_package_version_is_refused(capsys):
    assert release_notes.main(["v0.0.1"]) == 1
    assert "does not match" in capsys.readouterr().err


def test_cli_reports_its_version(capsys):
    from bettermarkitdown.cli import build_parser

    with pytest.raises(SystemExit):
        build_parser().parse_args(["--version"])
    assert __version__ in capsys.readouterr().out
