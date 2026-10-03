"""The KaTeX render check. Formula extraction is pure Python and always tested; the
rendering itself needs Node.js and KaTeX, and is skipped when they are missing."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bettermarkitdown import mathcheck  # noqa: E402
from bettermarkitdown.mathcheck import extract_formulas, render_check  # noqa: E402


def test_extracts_display_and_inline_math():
    md = "Text $x^2$ and $y_i$.\n\n$$\na = b\n$$\n\nMore $z$."
    assert extract_formulas(md) == [("\na = b\n", True), ("x^2", False), ("y_i", False),
                                    ("z", False)]


def test_escaped_dollars_are_currency_not_math():
    md = r"It costs \$100 and \$5.97, while $\beta_2$ is a parameter."
    assert extract_formulas(md) == [(r"\beta_2", False)]


def test_comments_and_paragraph_breaks_do_not_pair_dollars():
    md = "<!-- source: $ not math $ -->\nA stray $ sign.\n\nAnother $ sign."
    assert extract_formulas(md) == []


def test_missing_node_skips_rather_than_fails(monkeypatch):
    monkeypatch.setattr(mathcheck, "find_node", lambda: None)
    problems, skipped = render_check({1: "$x$"})
    assert problems == {} and "Node.js not found" in skipped


def test_broken_formula_is_reported_with_its_page():
    problems, skipped = render_check({
        3: r"Fine $\frac{a}{b}$ here.",
        7: r"Broken $\frac{a}{b$ and $$\undefinedmacro{y}$$ there.",
    })
    if skipped:
        pytest.skip(skipped)
    assert list(problems) == [7]
    assert len(problems[7]) == 2
    assert all(p.startswith("KaTeX") for p in problems[7])
