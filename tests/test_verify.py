"""Tests for --verify: checking a transcription against the PDF text layer.

The cases come from reviewing real LaTeX lecture notes: hyphenation split across
lines, words glued to math variables (`when$A$`), ligatures, and local-OCR pages
whose words were right while their math was garbage.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bettermarkitdown.verify import check_page  # noqa: E402

PDF_TEXT = (
    "The household chooses consumption and leisure to maximize utility subject to\n"
    "the budget constraint. An increase in the real wage has an income effect and a\n"
    "substitution effect on the demand for leisure, and the substitution effect is\n"
    "assumed to dominate so that labor supply slopes upward in the wage.\n"
)

MD = """

---

## Page 3

<!-- source: full-page vision transcription -->

The household chooses consumption and leisure to maximize utility subject to the budget
constraint. An increase in the real wage has an income effect and a substitution effect on
the demand for leisure, and the substitution effect is assumed to dominate so that labor
supply slopes upward in the wage.

$$\\max_{\\{C, L\\}} U(C, L)$$

> **[FIGURE]** Budget line with Slope = -w and an indifference curve tangent at point A.

*[sic: the notes print "wa" for "we" on this page]*
"""


def test_faithful_page_passes_despite_math_figures_and_review_marks():
    assert check_page(PDF_TEXT, MD, 3).status == "ok"


def test_dropped_sentence_is_flagged():
    md = MD.replace("and the substitution effect is assumed to dominate so that labor\n"
                    "supply slopes upward in the wage.", "")
    result = check_page(PDF_TEXT, md, 3)
    assert result.flagged
    assert result.missing["dominate"] == 1


def test_single_swapped_word_is_flagged():
    result = check_page(PDF_TEXT, MD.replace("income effect", "wealth effect"), 3)
    assert result.flagged
    assert result.missing["income"] == 1 and result.extra["wealth"] == 1


def test_hyphenation_across_a_line_break_is_rejoined():
    pdf = PDF_TEXT.replace("consumption and", "consump\ntion and")
    assert check_page(pdf, MD, 3).status == "ok"


def test_hyphen_at_line_end_is_rejoined_even_when_the_first_half_is_a_word():
    # Seen in a real PDF the dehyphenation pass left alone: 'there-\nfore', and a
    # ligature inside the split word, 'indef-\ninitely'
    pdf = PDF_TEXT + "We there-\nfore assume it lasts indef-\ninitely.\n"
    md = MD + "\nWe therefore assume it lasts indefinitely.\n"
    assert check_page(pdf, md, 3).status == "ok"


def test_possessive_is_not_glued_into_a_fake_word():
    # 'firm's' must not become 'firms' just because the Markdown says 'firms' elsewhere
    pdf = PDF_TEXT + "The firm's profit is paid to households who own the firms.\n"
    md = MD + "\nThe firm's profit is paid to households who own the firms.\n"
    assert check_page(pdf, md, 3).status == "ok"


def test_word_glued_to_a_math_variable_is_forgiven():
    pdf = PDF_TEXT + "Output rises whenA increases.\n"
    md = MD + "\nOutput rises when $A$ increases.\n"
    assert check_page(pdf, md, 3).status == "ok"


def test_local_ocr_page_is_flagged_even_when_the_words_match():
    md = MD.replace("<!-- source: full-page vision transcription -->",
                    "<!-- source: local OCR (rapidocr). The vision model returned nothing -->")
    result = check_page(PDF_TEXT, md, 3)
    assert result.status == "ok" and result.ocr and result.flagged


def test_review_note_pasted_inside_an_equation_block_is_caught():
    # A real slip from a review: the note landed between the lines of an aligned block
    md = MD + ("\n$$\\begin{aligned}\nc^* &= Ak^{*\\alpha} - \\delta k^* \\\\\n"
               "&= \\text{something}\n\n*[sic: wrong in the book]*\n\\end{aligned}$$\n")
    result = check_page(PDF_TEXT, md, 3)
    assert result.flagged
    assert "review note inside a display equation" in result.math


def test_math_check_runs_on_pages_without_a_text_layer():
    result = check_page("Figure 3", MD + "\n$$x = 1\n", 3)
    assert result.status == "no-text-layer" and result.math == ["unmatched $$"]


def test_page_without_a_text_layer_is_reported_not_passed():
    assert check_page("Figure 3", MD, 3).status == "no-text-layer"


def test_cli_verify_exit_codes(tmp_path: Path):
    pymupdf = pytest.importorskip("pymupdf")
    from bettermarkitdown.cli import main

    pdf = tmp_path / "notes.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    for i, line in enumerate(PDF_TEXT.splitlines()):
        page.insert_text((50, 72 + 16 * i), line, fontsize=10)
    doc.save(pdf)
    doc.close()

    pages = tmp_path / "work" / "pages"
    pages.mkdir(parents=True)
    (pages / "0001.md").write_text(MD, encoding="utf-8")
    args = [str(pdf), "--work-dir", str(tmp_path / "work"), "--verify"]
    assert main(args) == 0

    (pages / "0001.md").write_text(MD.replace("income effect", "wealth effect"),
                                   encoding="utf-8")
    assert main(args) == 3
