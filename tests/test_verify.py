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


# A codebook page: few words, many numbers. Every word can be right and a figure wrong.
CODEBOOK_PDF = (
    "Variable Name: WTP_50 Length: 1.0 Position: 59\n"
    "Concept: Self-perceived weight - overweight / underweight / just about right\n"
    "Universe: Respondents with DOWTP = 1 and PROXYSEX = (1, 2)\n"
    "Answer Categories Code Frequency Weighted Frequency %\n"
    "Overweight 1 27,143 12,027,139 36.3\n"
    "Underweight 2 2,399 1,336,749 4.0\n"
    "Just about right 3 36,255 18,873,345 57.0\n"
    "Not stated 9 1,282 862,492 2.6\n"
    "Total 67,079 33,099,725 100.0\n"
    "21\n"
)

CODEBOOK_MD = """
## Page 21

- **Variable Name:** WTP_50 · **Length:** 1.0 · **Position:** 59
- **Concept:** Self-perceived weight - overweight / underweight / just about right
- **Universe:** Respondents with DOWTP = 1 and PROXYSEX = (1, 2)

| Answer Categories | Code | Frequency | Weighted Frequency | % |
|---|---:|---:|---:|---:|
| Overweight | 1 | 27,143 | 12,027,139 | 36.3 |
| Underweight | 2 | 2,399 | 1,336,749 | 4.0 |
| Just about right | 3 | 36,255 | 18,873,345 | 57.0 |
| Not stated | 9 | 1,282 | 862,492 | 2.6 |
| **Total** | | **67,079** | **33,099,725** | **100.0** |

<!-- page number: 21 -->
"""


def test_faithful_codebook_page_passes():
    result = check_page(CODEBOOK_PDF, CODEBOOK_MD, 21)
    assert result.status == "ok", (result.numbers_missing, result.numbers_extra)


def test_a_changed_number_is_flagged_even_when_every_word_matches():
    result = check_page(CODEBOOK_PDF, CODEBOOK_MD.replace("1,336,749", "1,386,749"), 21)
    assert result.flagged
    assert not result.missing and not result.extra             # the words are all fine
    assert result.numbers_missing["1336749"] == 1
    assert result.numbers_extra["1386749"] == 1


def test_a_page_of_numbers_is_checked_not_skipped():
    # Fewer than 20 words, but plenty of numbers: it has a text layer worth checking.
    assert check_page(CODEBOOK_PDF, CODEBOOK_MD, 21).status != "no-text-layer"


def test_thousands_separators_do_not_count_as_differences():
    pdf = CODEBOOK_PDF + "a minimum population size of 70, 000 inhabitants, or 70 000.\n"
    md = CODEBOOK_MD + "\na minimum population size of $70,000$ inhabitants, or 70,000.\n"
    assert check_page(pdf, md, 21).status == "ok"
    # ...and the other way round: spaced in the Markdown, plain in the PDF
    md = CODEBOOK_MD + "\na minimum population size of 70 000 inhabitants, or 70 000.\n"
    pdf = CODEBOOK_PDF + "a minimum population size of 70000 inhabitants, or 70,000.\n"
    assert check_page(pdf, md, 21).status == "ok"


def test_adjacent_table_cells_are_not_read_as_one_spaced_number():
    # '1,282 862,492' is two cells. Joining them would hide a wrong cell.
    md = CODEBOOK_MD.replace("| 1,282 | 862,492 |", "| 1,282 | 862,493 |")
    result = check_page(CODEBOOK_PDF, md, 21)
    assert result.numbers_missing["862492"] == 1 and result.numbers_extra["862493"] == 1


def test_link_targets_are_not_counted_as_page_text():
    pdf = CODEBOOK_PDF + "see https://www150.statcan.gc.ca/n1/pub/82-003-x/10795-eng.pdf\n"
    url = "https://www150.statcan.gc.ca/n1/pub/82-003-x/10795-eng.pdf"
    md = CODEBOOK_MD + f"\nsee [{url}]({url})\n"
    assert check_page(pdf, md, 21).status == "ok"


def test_number_pieces_scattered_by_an_equation_text_layer_are_forgiven():
    # PowerPoint equations store '1.96' as '96' and '.1' in the text layer.
    pdf = PDF_TEXT + "P 96 .1 Z 96 .1 95 .0\n"
    md = MD + "\n$$P(-1.96 \\le Z \\le 1.96) = 0.95$$\n"
    assert check_page(pdf, md, 3).status == "ok"


def test_a_page_cut_off_at_the_output_limit_is_flagged():
    from bettermarkitdown.core import TRUNCATION_NOTE

    result = check_page(PDF_TEXT, MD + TRUNCATION_NOTE, 3)
    assert result.truncated and result.flagged
    # ...also when the page has no text layer to compare against
    assert check_page("Figure 3", MD + TRUNCATION_NOTE, 3).flagged


# A textbook page with chapter endnotes: the markers are on the page, the note
# texts are printed at the end of the chapter. Cases from Hill, Griffiths and Lim,
# *Principles of Econometrics*, 5th ed.
BOOK_PDF = (
    "In this example, we consider data used by Riphahn, Wambach, and Million (2003)22.\n"
    "The data file contains data on 1,200 individuals and the correlation between the\n"
    "divorce rate in Maine and the per capita consumption of margarine is 0.992623 over\n"
    "the period 2000 to 2009. If the advertising budget is $1900, Big Andy plans staffing\n"
    "and purchasing of inputs on the assumption that sales are maximized at that level.\n"
)
BOOK_MD = """
## Page 1050

<!-- source: full-page vision transcription -->

In this example, we consider data used by Riphahn, Wambach, and Million (2003)[^22].
The data file contains data on 1,200 individuals and the correlation between the
divorce rate in Maine and the per capita consumption of margarine is 0.9926[^23] over
the period 2000 to 2009. If the advertising budget is \\$1900, Big Andy plans staffing
and purchasing of inputs on the assumption that $SALES$ are maximized at that level.
"""


def test_endnote_markers_fused_to_numbers_by_the_text_layer_are_forgiven():
    result = check_page(BOOK_PDF, BOOK_MD, 1050)
    assert not result.numbers_missing and not result.numbers_extra
    assert result.status == "ok" and not result.markup


def test_escaped_dollar_is_not_paired_with_the_next_formula():
    # '\$1900 ... $SALES$' used to be read as one formula, hiding the words between.
    result = check_page(BOOK_PDF, BOOK_MD.replace("of inputs", "of"), 1050)
    assert result.missing["inputs"] == 1


@pytest.mark.parametrize("definition", [
    "[^22]: [footnote text not present on page]",
    "[^22]: [illegible: text for footnote 22 missing on page]",
    "[^22]: Text of footnote 22 not present on this page.",
    "[^22]: text missing from image",
    "[^22]: 22",
])
def test_invented_footnote_text_is_flagged(definition):
    result = check_page(BOOK_PDF, BOOK_MD + "\n" + definition + "\n", 1050)
    assert result.flagged and result.markup


def test_footnote_repeating_a_body_sentence_is_flagged():
    from bettermarkitdown.verify import markup_problems
    md = ("However, the logit model is widely used in many disciplines and leads to very "
          "convenient generalizations.[^2] We will discuss both.\n\n"
          "[^2]: However, the logit model is widely used in many disciplines and leads to "
          "very convenient generalizations.\n")
    assert markup_problems(md)


def test_real_endnotes_pass():
    from bettermarkitdown.verify import markup_problems
    md = ("[^22]: Regina T. Riphahn, Achim Wambach, and Andreas Million, \"Incentive Effects "
          "in the Demand for Health Care\", Journal of Applied Econometrics, 2003.\n"
          "[^23]: http://www.tylervigen.com/\n"
          "[^24]: How to cope with missing data is considered in Chapter 10.\n")
    assert markup_problems(md) == []


@pytest.mark.parametrize("bad", [
    "beyond the scope of this book.$^{24}$",
    "Angrist and Pischke$^{12}$ report",
    "[^8]Jeffery M. Wooldridge (2010) Econometric Analysis",
    "[<u>20</u>]Everaert, G. and L. Ponzi (2014)",
    "| *SSE* | \\multicolumn{2}{c|}{213774.0} | 125880.0 |",
    "If we raise the price of Pepsi to $1.10, we estimate that the probability falls",
    "the average price of Pepsi was $1.23, 7-Up $1.12, and Coke $1.21.",
])
def test_markup_problems_are_caught(bad):
    from bettermarkitdown.verify import markup_problems
    assert markup_problems(bad)


@pytest.mark.parametrize("fine", [
    "an area of 30 m$^2$ per worker",
    "| $\\beta_2$ | $1 - p$ |",
    "when $0 \\le p(\\mathbf{x}_i) \\le 1$ holds",
    "the estimate is $0.4848$ and the price is \\$1.10",
    "$$\\$1{,}900 = x$$",
])
def test_ordinary_math_and_escaped_currency_pass(fine):
    from bettermarkitdown.verify import markup_problems
    assert markup_problems(fine) == []


def test_report_names_the_pages_without_a_text_layer():
    from bettermarkitdown.verify import format_report
    report = format_report([check_page("Figure 3", MD, 433)])
    assert "Pages without a text layer: 433." in report


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


# --- v1.4.0: cases from a publisher's textbook (Brooks, Introductory Econometrics
# for Finance) whose equations are images and whose tables are often images too.

LR_PDF = (
    "the second derivatives comprise the information matrix, measuring the\n"
    "peakedness of the LLF, and how much higher the LLF value is at the optimum.\n"
    "The LM test involves estimating only a restricted regression, since the slope\n"
    "of the LLF at the maximum will be zero by definition. A naïve forecast.\n"
)
LR_MD = (
    "the second derivatives comprise the information matrix, measuring the peakedness "
    "of the $LLF$, and how much higher the $LLF$ value is at the optimum. The $LM$ test "
    "involves estimating only a restricted regression, since the slope of the $LLF$ at "
    "the maximum will be zero by definition. A naive forecast, $L_u$ and $L_r$.\n"
)


def test_variables_written_as_math_are_not_lost_to_ligature_stripping():
    """'$LLF$ $L_u$' was joined into 'llflu' before 'fl' was dropped as a ligature,
    so the PDF's 'LLF' was reported missing six times on a correct page."""
    result = check_page(LR_PDF.replace("naïve", "naive"), LR_MD, 531)
    assert result.status == "ok", (result.missing, result.extra)


def test_an_accented_letter_dropped_by_the_text_layer_is_forgiven():
    pdf = LR_PDF.replace("naïve", "nave")          # what the text layer really held
    assert check_page(pdf, LR_MD, 667).status == "ok"
    plural = check_page(pdf.replace("restricted regression", "restricted test"),
                        LR_MD.replace("restricted regression", "restricted tests"), 667)
    assert plural.flagged, "a changed word must still be caught"


IMAGE_TABLE_MD = MD + (
    "\n| Variable | Equity equation | Bonds equation |\n| :--- | :---: | :---: |\n"
    "| Unlevered Z-score | 0.14 | 0.26 |\n| Venture-backed | 0.70 | 0.86 |\n"
)


def test_a_table_transcribed_from_an_image_is_listed_not_flagged():
    from bettermarkitdown.verify import format_report
    plain = check_page(PDF_TEXT, IMAGE_TABLE_MD, 674)
    assert plain.flagged                     # no image on the page: the words are invented
    imaged = check_page(PDF_TEXT, IMAGE_TABLE_MD, 674, image_on_page=True)
    assert imaged.status == "ok", (imaged.extra, imaged.numbers_extra)
    assert imaged.from_image["venture"] and imaged.from_image["0.86"]
    assert "Tables transcribed from images" in format_report([imaged])


def test_image_page_still_flags_a_dropped_sentence():
    md = IMAGE_TABLE_MD.replace("supply slopes upward in the wage.", "")
    assert check_page(PDF_TEXT, md, 674, image_on_page=True).flagged


def test_more_than_one_tag_in_a_display_is_broken_math():
    from bettermarkitdown.verify import math_problems
    block = ("$$\\begin{aligned}\ny_t &= (1 - \\phi_1 L)^{-1} u_t \\tag{6.85} \\\\\n"
             "y_t &= (1 + \\phi_1 L) u_t \\tag{6.86}\n\\end{aligned}$$")
    assert any("\\tag" in p for p in math_problems(block))
    assert math_problems("$$y_t = u_t \\tag{6.87}$$") == []


@pytest.mark.parametrize("bad", [
    "\\tag{6.55}\n\nit would be stated that the process is stationary",
    "\\begin{align*}\nx &= 1\n\\end{align*}",
    "see [Exercise 9.29](Exercise 9.29) for the data",
    "![Page 12, figure 1](My Notes_assets/page_0012_fig_01.png)",
])
def test_latex_outside_math_and_links_with_spaces_are_caught(bad):
    from bettermarkitdown.verify import markup_problems
    assert markup_problems(bad)


@pytest.mark.parametrize("fine", [
    "$$y_t = \\phi(L)^{-1} u_t \\tag{6.56}$$",
    "$$\\begin{aligned} a &= b \\\\ c &= d \\end{aligned} \\tag{6.70}$$",
    "the number (6.55) is printed on the next page",
    "![Page 12, figure 1](My%20Notes_assets/page_0012_fig_01.png)",
    "[Brooks](https://example.org/book \"Introductory Econometrics\")",
])
def test_math_and_well_formed_links_pass(fine):
    from bettermarkitdown.verify import markup_problems
    assert markup_problems(fine) == []


def test_the_converters_own_pictures_and_labels_are_not_page_text():
    """Page 85's scan link says "Page 85 scan"; that is not on page 85, and neither is a
    figure's "transcribed by" label. They used to flag every page converted with them."""
    from bettermarkitdown.verify import check_page
    pdf_text = ("The mean of the sample is 4.3 and its variance is 2.1. A larger sample "
                "would narrow the interval estimate, other things being equal. ") * 3
    md = ("\n\n---\n\n## Page 85\n<!-- source: full-page vision transcription -->\n\n"
          + pdf_text + "\n\n"
          "![Page 85, figure 1](Book_assets/page_0085_fig_01.png)\n\n"
          "**Figure 85.1 - transcribed by gemini-3.6-flash:**\n\n> A bar chart.\n\n"
          "![Page 85 scan](Book%20Name_assets/page_0085.png)")
    assert check_page(pdf_text, md, 85).status == "ok"
