"""Study notes for pages a model refuses to transcribe: asked for, checked, revised once,
cleared of copied wording, and labelled. The model is faked; the page is made up."""

from __future__ import annotations

import json
import textwrap

import pytest

from bettermarkitdown import core, notes
from bettermarkitdown.config import Options
from bettermarkitdown.prompts import NOTES_CHECK_PROMPT, NOTES_PROMPT, NOTES_REVISE_PROMPT

pymupdf = pytest.importorskip("pymupdf")

PAGE = ("Plot yields follow the model y = a + b x (3.1), estimated in Example 3.2 and shown "
        "in Table 3.4. The estimated slope of the regression line is positive and the "
        "residuals look random across the plots in the northern field this year.")
REFUSED = ("*[vision call failed: RuntimeError: empty response "
           "(finish_reason=content_filter: RECITATION)]*")


def equation_page(path):
    """A page with a text layer and an equation set as a picture: sent whole to vision."""
    doc = pymupdf.open()
    page = doc.new_page()
    for i, line in enumerate(textwrap.wrap(PAGE, 80)):
        page.insert_text((72, 90 + 16 * i), line, fontsize=10)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 80, 4), False)
    pix.clear_with(40)
    page.insert_image(pymupdf.Rect(150, 160, 350, 170), pixmap=pix)
    doc.save(path)
    doc.close()
    return path


def run_options(tmp_path, **extra) -> Options:
    return Options(pdf=equation_page(tmp_path / "book.pdf"), output=tmp_path / "book.md",
                   api_key="test-key-0123456789", **extra)


@pytest.fixture
def model(monkeypatch):
    """Refuses to transcribe; writes notes; its check finds one thing missing."""
    asked = []
    replies = {
        "notes": "- The page models plot yields as a straight line, $y = a + bx$ (3.1).\n"
                 "- Example 3.2 estimates it.\n"
                 "- the residuals look random across the plots in the northern field",  # copied
        "check": json.dumps({"wrong": [], "missing": ["the sign of the slope"]}),
        "revise": "- Yields are modelled as a line, $y = a + bx$ (3.1), fitted in Example 3.2.\n"
                  "- The fitted slope is positive.\n"
                  "- the residuals look random across the plots in the northern field",  # copied
    }

    def describe(client, model_name, png, prompt, **kwargs):
        if prompt.startswith(NOTES_REVISE_PROMPT):
            asked.append("revise")
            return replies["revise"]
        if prompt.startswith(NOTES_CHECK_PROMPT):
            asked.append("check")
            return replies["check"]
        if prompt.startswith(NOTES_PROMPT):
            asked.append("notes")
            return replies["notes"]
        asked.append("transcribe")
        return REFUSED

    monkeypatch.setenv("GEMINI_API_KEY", "test-key-0123456789abcdef")
    monkeypatch.setattr(core, "describe_image", describe)
    return SimpleReplies(asked, replies)


class SimpleReplies:
    def __init__(self, asked, replies):
        self.asked, self.replies = asked, replies


def test_a_refused_page_gets_checked_labelled_notes_not_its_text(tmp_path, model):
    result = core.convert(run_options(tmp_path, ocr_fallback=False))
    assert model.asked == ["transcribe", "notes", "check", "revise", "check"]
    assert "The check still questions these points" in (
        tmp_path / "book_work" / "pages" / "0001.md").read_text(encoding="utf-8")
    assert result.pages_notes == [1] and result.failed == []
    page = (tmp_path / "book_work" / "pages" / "0001.md").read_text(encoding="utf-8")
    assert notes.SOURCE_TAG in page and "Study notes, not the book's text" in page
    assert "read PDF page 1" in page
    assert "The fitted slope is positive." in page            # the revision was used
    assert "residuals look random across the plots" not in page   # copied wording removed
    assert "1 line(s) that repeated the page's wording were removed" in page
    assert "On this page: (3.1), Example 3.2, Table 3.4." in page
    assert "Not covered in these notes: Table 3.4" in page


def test_verify_lists_notes_pages_without_flagging_their_words(tmp_path, model):
    from bettermarkitdown.verify import page_notes, verify

    opts = run_options(tmp_path, ocr_fallback=False)
    pdf = opts.pdf
    core.convert(opts)
    [check] = verify(pdf, tmp_path / "book_work")
    assert check.notes and check.status == "notes" and not check.flagged
    assert any("Study notes, not the page's text" in n for n in page_notes(check))


def test_notes_that_fail_fall_back_to_ocr_and_never_to_the_text(tmp_path, model, monkeypatch):
    model.replies["notes"] = REFUSED
    monkeypatch.setattr(core.local_ocr, "ocr_page", lambda page, dpi: "rough OCR words")
    result = core.convert(run_options(tmp_path))
    assert result.pages_ocr == [1] and result.pages_notes == []
    assert model.asked == ["transcribe", "notes"]


def test_notes_can_be_turned_off(tmp_path, model):
    result = core.convert(run_options(tmp_path, ocr_fallback=False, study_notes=False))
    assert model.asked == ["transcribe"] and result.failed == [1]


def test_only_a_content_filter_brings_notes_not_any_failure():
    assert notes.refused(REFUSED)
    assert not notes.refused("*[vision call failed: TimeoutError: read timed out]*")


def test_numbered_items_and_copied_lines_are_found():
    assert notes.numbered_items(PAGE) == ["(3.1)", "Example 3.2", "Table 3.4"]
    kept, dropped = notes.remove_copied(
        "- my own words about slopes\n- estimated slope of the regression line is positive and",
        PAGE)
    assert dropped == 1 and kept == "- my own words about slopes"
    assert notes.missing_items("see (3.1) and Example 3.2", ["(3.1)", "Example 3.2",
                                                             "Table 3.4"]) == ["Table 3.4"]


def test_the_check_is_read_as_gemini_writes_it_and_never_assumed_clean():
    """Gemini puts a bare `json` label before the object; a reply with no object at all
    must not pass for "no problems"."""
    reply = 'json\n{\n  "wrong": ["(3.1) has b, not a"],\n  "missing": []\n}'
    assert notes._parse_check(reply) == {"wrong": ["(3.1) has b, not a"], "missing": []}
    with pytest.raises(notes.CheckUnreadable):
        notes._parse_check("I could not compare these notes.")
    # LaTeX in the strings, with single backslashes, exactly as the reply arrives.
    latex = "json\n" + r'{"wrong": ["the sum is $\sum_i \beta_i$, not $\bar{x}$"], "missing": []}'
    assert notes._parse_check(latex)["wrong"] == [r"the sum is $\sum_i \beta_i$, not $\bar{x}$"]

    answers = iter(["- $y = a + bx$ (3.1)", "no JSON here",
                    "- $y = a + bx$ (3.1), Example 3.2, Table 3.4"])
    written = notes.study_notes(lambda png, prompt: next(answers), b"", PAGE, 7)
    assert "NOT checked" in written and "not checked against the page" in written
    assert "revised once for missing numbered items" in written


def test_money_in_notes_is_escaped_and_maths_is_left_alone():
    text = "- A wage of $10.00 hourly, and $1 more.\n- The interval is $1.96 \sigma$ wide."
    out = notes.escape_money(text)
    assert "\$10.00 hourly" in out and "\$1 more" in out
    assert "$1.96 \sigma$" in out and "\$1.96" not in out


def test_latex_in_the_check_keeps_its_backslashes_even_where_json_has_an_escape():
    # \beta and \frac start with JSON escapes (\b, \f); read naively they lose a letter.
    # Single backslashes, as the reply arrives, plus one already escaped (\\theta).
    reply = "json\n" + r'{"wrong": ["$\beta_2$, not $\frac{1}{2}$, or \\theta"], "missing": []}'
    assert notes._parse_check(reply)["wrong"] == [r"$\beta_2$, not $\frac{1}{2}$, or \theta"]
