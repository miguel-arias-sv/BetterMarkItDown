"""Tests that never touch the network, so CI can run them for free.

They cover the parts that broke during development: page-range parsing, the
billing arithmetic (thinking tokens are invisible in completion_tokens), and a
full text-only conversion of a generated PDF.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bettermarkitdown.config import (  # noqa: E402
    GEMINI_BASE_URL,
    Options,
    get_base_url,
    get_model,
)
from bettermarkitdown.core import Meter, convert, parse_pages  # noqa: E402


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """A two-page PDF: one page with a text layer, one that is only an image."""
    pymupdf = pytest.importorskip("pymupdf")

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 90), "Chapter 3: Harvest Yields", fontsize=18, fontname="hebo")
    page.insert_text((72, 120), "The following figure shows annual wheat yield by region.",
                     fontsize=11)
    page.draw_rect(pymupdf.Rect(100, 200, 400, 420), color=(0, 0, 0))

    rendered = doc.new_page(width=595, height=842)
    scratch = pymupdf.open()
    tmp = scratch.new_page(width=595, height=842)
    tmp.insert_text((72, 120), "Pixels only, no text layer.", fontsize=20)
    rendered.insert_image(pymupdf.Rect(0, 0, 595, 842),
                          pixmap=tmp.get_pixmap(matrix=pymupdf.Matrix(2, 2)))
    scratch.close()

    path = tmp_path / "sample.pdf"
    doc.save(path)
    doc.close()
    return path


def test_parse_pages_forms():
    assert parse_pages(None, 5) == [0, 1, 2, 3, 4]
    assert parse_pages("3", 5) == [2]
    assert parse_pages("2-4", 5) == [1, 2, 3]
    assert parse_pages("1,3-4", 5) == [0, 2, 3]
    assert parse_pages("99", 5) == []          # out of range is dropped, not an error


def test_meter_counts_hidden_thinking_tokens_as_output():
    """The gap between total and prompt+completion is thinking, and it is billed."""

    class Usage:
        prompt_tokens = 1293
        completion_tokens = 487
        total_tokens = 3354          # 1574 of these are invisible thinking tokens

    meter = Meter(price_in=0.75, price_out=3.75)
    meter.add(Usage())
    assert meter.tok_in == 1293
    assert meter.tok_out == 2061     # NOT 487
    assert meter.cost() == pytest.approx(0.00870, abs=1e-5)


def test_meter_formats_small_amounts():
    assert Meter.usd(0.0014) == "$0.0014"
    assert Meter.usd(1.5) == "$1.50"


def test_text_only_conversion_writes_markdown(sample_pdf: Path, tmp_path: Path):
    pytest.importorskip("markitdown")
    pytest.importorskip("pdfminer")

    output = tmp_path / "out.md"
    result = convert(Options(pdf=sample_pdf, output=output,
                             work_dir=tmp_path / "work", no_vision=True))

    assert output.is_file()
    text = output.read_text(encoding="utf-8")
    assert "## Page 1" in text and "## Page 2" in text
    assert "Harvest Yields" in text                 # text layer was extracted
    assert result.pages_converted == 2
    assert result.cost == 0.0                       # no API calls were made


def test_rerun_resumes_without_redoing_pages(sample_pdf: Path, tmp_path: Path):
    pytest.importorskip("markitdown")
    pytest.importorskip("pdfminer")

    output = tmp_path / "out.md"
    work = tmp_path / "work"
    opts = Options(pdf=sample_pdf, output=output, work_dir=work, no_vision=True)

    convert(opts)
    second = convert(opts)
    assert second.pages_converted == 2              # counted as already done
    assert len(list((work / "pages").glob("*.md"))) == 2


def test_partial_page_run_keeps_the_rest_of_the_document(sample_pdf: Path, tmp_path: Path):
    """Regression: assembling from the page selection alone destroyed the document."""
    pytest.importorskip("markitdown")
    pytest.importorskip("pdfminer")

    output = tmp_path / "out.md"
    work = tmp_path / "work"

    convert(Options(pdf=sample_pdf, output=output, work_dir=work, no_vision=True))
    convert(Options(pdf=sample_pdf, output=output, work_dir=work, no_vision=True,
                    pages="2", fresh=True))

    text = output.read_text(encoding="utf-8")
    assert "## Page 1" in text, "rerunning one page must not drop the other pages"
    assert "## Page 2" in text


def test_endpoint_and_model_resolution_precedence(monkeypatch, tmp_path: Path):
    """An explicit flag beats the environment, which beats the default."""
    monkeypatch.chdir(tmp_path)          # no .env to find
    monkeypatch.delenv("BMID_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("BMID_MODEL", raising=False)

    assert get_base_url() == GEMINI_BASE_URL
    assert get_model() == "gemini-3.6-flash"

    monkeypatch.setenv("BMID_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("BMID_MODEL", "qwen3-vl:8b")
    assert get_base_url() == "http://localhost:11434/v1"
    assert get_model() == "qwen3-vl:8b"

    assert get_base_url("http://elsewhere/v1") == "http://elsewhere/v1"
    assert get_model("gemini-3.8-flash") == "gemini-3.8-flash"


def test_unknown_endpoint_reports_no_cost_rather_than_geminis(tmp_path: Path):
    """Quoting Gemini's rates for someone else's model would be a fiction.

    A local model costs nothing, and for another paid provider the honest answer
    is zero-until-told, via --price-in / --price-out.
    """
    common = dict(pdf=tmp_path / "x.pdf", output=tmp_path / "x.md")

    assert Options(**common).prices() == (0.75, 3.75)          # Gemini default
    assert Options(**common, model="gemini-9-unreleased").prices() == (0.75, 3.75)

    local = Options(**common, base_url="http://localhost:11434/v1", model="qwen3-vl:8b")
    assert local.is_gemini() is False
    assert local.prices() == (0.0, 0.0)

    told = Options(**common, base_url="https://openrouter.ai/api/v1", model="some/vl",
                   price_in=0.2, price_out=0.8)
    assert told.prices() == (0.2, 0.8)


def test_comment_only_reply_counts_as_empty(tmp_path: Path, monkeypatch):
    """`<!-- page number:  -->` alone once passed as a transcription and was cached,
    so two pages came out blank with no fallback and no failure reported."""
    import hashlib
    from types import SimpleNamespace

    from bettermarkitdown import core
    from bettermarkitdown.core import Cache, RateLimiter, describe_image, has_content

    assert not has_content("<!-- page number:  -->")
    assert not has_content("  \n<!-- a -->\n<!-- b -->  ")
    assert has_content("Text.\n\n<!-- page number: 12 -->")

    replies = iter(["<!-- page number:  -->", "Real text.\n<!-- page number: 7 -->"])

    def create(**_):
        message = SimpleNamespace(content=next(replies))
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")],
                               usage=None)

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(core.time, "sleep", lambda _: None)
    cache = Cache(tmp_path / "cache.json")
    limiter = RateLimiter(0)

    out = describe_image(client, "m", b"png", "p", cache=cache, limiter=limiter)
    assert out.startswith("Real text.")            # the blank was retried, not accepted
    assert all(has_content(v) for v in cache.data.values())

    # A blank cached by an older version is ignored, not served.
    cache.data.clear()
    key = hashlib.sha256(b"png2" + b"p" + b"m" + b"none").hexdigest()
    cache.put(key, "<!-- page number:  -->")
    replies = iter(["Fresh text."])
    assert describe_image(client, "m", b"png2", "p", cache=cache, limiter=limiter) == "Fresh text."


def _fake_client(replies, seen_caps):
    """An OpenAI-style client answering with (text, finish_reason) pairs in order."""
    from types import SimpleNamespace

    replies = iter(replies)

    def create(**kwargs):
        seen_caps.append(kwargs["max_tokens"])
        text, reason = next(replies)
        choice = SimpleNamespace(message=SimpleNamespace(content=text), finish_reason=reason)
        return SimpleNamespace(choices=[choice], usage=None)

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_reply_cut_off_at_the_token_cap_is_retried_with_more_room(tmp_path: Path):
    """A dense table page stopped at 4,096 tokens and the partial page was cached as
    if complete: the rest of the table and the text under it were silently lost."""
    from bettermarkitdown.core import MAX_TOKENS, Cache, RateLimiter, describe_image

    caps: list[int] = []
    client = _fake_client([("| 1 | 2 |\n| 300 | 7.", "length"),
                           ("| 1 | 2 |\n| 300 | 7.3 |\n\nThe paragraph below.", "stop")], caps)
    cache = Cache(tmp_path / "cache.json")
    out = describe_image(client, "m", b"png", "p", cache=cache, limiter=RateLimiter(0))

    assert out.endswith("The paragraph below.")
    assert caps == [MAX_TOKENS[0], MAX_TOKENS[1]]
    assert list(cache.data.values()) == [out]          # only the complete reply is cached


def test_reply_still_cut_off_at_the_largest_cap_is_marked_and_never_cached(tmp_path: Path):
    from bettermarkitdown.core import (
        MAX_TOKENS,
        TRUNCATED_TAG,
        Cache,
        RateLimiter,
        describe_image,
    )

    caps: list[int] = []
    client = _fake_client([("short partial", "length"),
                           ("a longer partial transcription", "length")], caps)
    cache = Cache(tmp_path / "cache.json")
    out = describe_image(client, "m", b"png", "p", cache=cache, limiter=RateLimiter(0))

    assert out.startswith("a longer partial transcription")
    assert TRUNCATED_TAG in out and "cut off" in out
    assert caps == list(MAX_TOKENS)
    assert cache.data == {}                            # a rerun will try again


def test_cut_off_recognises_the_finish_reasons_servers_use():
    from bettermarkitdown.core import cut_off

    assert cut_off("length") and cut_off("MAX_TOKENS")
    assert not cut_off("stop") and not cut_off("") and not cut_off("content_filter")


# --- v1.4.0 -----------------------------------------------------------------

def _equation_image_pdf(path: Path) -> Path:
    """One page of ordinary text plus a 200 x 10 pt picture: how publishers set a
    display equation. The text layer has nothing where the equation is."""
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 90), "The linear probability model is given by", fontsize=11)
    for i in range(4):
        page.insert_text((72, 140 + 14 * i), "where the explanatory variables are "
                         "measured in millions of dollars and so on.", fontsize=11)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 80, 4), False)
    pix.clear_with(40)
    page.insert_image(pymupdf.Rect(150, 100, 350, 110), pixmap=pix)
    doc.save(path)
    doc.close()
    return path


def test_equation_sized_images_are_counted_but_figures_and_specks_are_not(tmp_path: Path):
    pymupdf = pytest.importorskip("pymupdf")
    from bettermarkitdown.core import small_images

    with pymupdf.open(_equation_image_pdf(tmp_path / "eq.pdf")) as doc:
        assert small_images(doc[0], 60) == 1
        assert small_images(doc[0], 5) == 0          # 10 pt tall is a figure at min 5 pt


def test_text_path_reports_pages_whose_equations_it_dropped(tmp_path: Path):
    pytest.importorskip("markitdown")
    result = convert(Options(pdf=_equation_image_pdf(tmp_path / "eq.pdf"),
                             output=tmp_path / "out.md", work_dir=tmp_path / "work",
                             no_vision=True))
    assert result.pages_small_images == [1]


def test_money_from_the_text_layer_is_escaped_so_it_never_starts_a_formula(tmp_path: Path):
    """A financial statement converted for free: '$0.00 |' in a table was left bare, which
    viewers read as the start of a formula and the check flagged."""
    pymupdf = pytest.importorskip("pymupdf")
    pytest.importorskip("markitdown")
    from bettermarkitdown.verify import markup_problems

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 90), "Tuition fees charged this term: $1,200.50", fontsize=11)
    page.insert_text((72, 110), "Balance owing after the payment received: $0.00", fontsize=11)
    page.insert_text((72, 130), "Paid in full by the student on the due date.", fontsize=11)
    doc.save(tmp_path / "statement.pdf")
    doc.close()
    output = tmp_path / "statement.md"
    convert(Options(pdf=tmp_path / "statement.pdf", output=output, work_dir=tmp_path / "work",
                    no_vision=True))
    md = output.read_text(encoding="utf-8")
    assert "\\$1,200.50" in md and "\\$0.00" in md
    assert "\\\\$" not in md                     # escaped once, not twice
    assert markup_problems(md) == []


def test_pages_with_equation_images_are_transcribed_whole(tmp_path: Path, monkeypatch):
    pytest.importorskip("markitdown")
    pytest.importorskip("openai")
    from bettermarkitdown import core

    sent = []

    def fake_describe(client, model, png, prompt, **kwargs):
        sent.append(prompt)
        return ("$$\\begin{aligned} a &= b \\tag{1} \\\\ c &= d \\tag{2} \\end{aligned}$$"
                "\n\n<!-- page number: 1 -->")

    monkeypatch.setattr(core, "describe_image", fake_describe)
    common = dict(pdf=_equation_image_pdf(tmp_path / "eq.pdf"), output=tmp_path / "out.md",
                  base_url="http://localhost:1/v1", save_images=False)
    convert(Options(**common, work_dir=tmp_path / "w1"))
    page = (tmp_path / "w1" / "pages" / "0001.md").read_text(encoding="utf-8")
    assert sent == [core.PAGE_PROMPT]
    assert "full-page vision transcription" in page
    assert "\\tag" not in page and "\\qquad (1)" in page and "\\qquad (2)" in page

    sent.clear()
    convert(Options(**common, work_dir=tmp_path / "w2", ignore_small_images=True))
    assert core.PAGE_PROMPT not in sent


def test_one_tag_per_display_leaves_single_tags_alone():
    from bettermarkitdown.core import one_tag_per_display
    single = "$$y_t = u_t \\tag{6.87}$$ and $x$"
    assert one_tag_per_display(single) == single


def test_title_option_and_unix_line_endings(sample_pdf: Path, tmp_path: Path):
    pytest.importorskip("markitdown")
    output = tmp_path / "out.md"
    convert(Options(pdf=sample_pdf, output=output, work_dir=tmp_path / "work",
                    no_vision=True, title="Chapter 12: Limited Dependent Variables"))
    assert output.read_text(encoding="utf-8").startswith(
        "# Chapter 12: Limited Dependent Variables\n")
    for f in [output, *(tmp_path / "work" / "pages").glob("*.md")]:
        assert b"\r\n" not in f.read_bytes(), f.name


def test_figure_links_survive_spaces_in_the_output_name():
    from bettermarkitdown.core import md_link
    assert md_link("My Notes_assets/page_0001.png") == "My%20Notes_assets/page_0001.png"


def _outline_pdf(path: Path) -> Path:
    """Ch 1 on pp. 1-2; 1.2 starts mid-page 2 below a paragraph; Ch 2 opens p. 3."""
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    for _ in range(3):
        doc.new_page()
    doc[1].insert_text((72, 100), "The end of section 1.1 runs onto this page, and it "
                                  "is a full line of body text.", fontsize=10)
    doc[1].insert_text((72, 400), "1.2 The Next Section", fontsize=12)
    doc[2].insert_text((72, 80), "Chapter 2", fontsize=16)

    def dest(page, y):
        return {"kind": pymupdf.LINK_GOTO, "page": page - 1, "to": pymupdf.Point(72, y)}

    doc.set_toc([[1, "Chapter 1", 1, dest(1, 72)], [2, "1.1 First", 1, dest(1, 300)],
                 [2, "1.2 The Next Section", 2, dest(2, 390)],
                 [1, "Chapter 2", 3, dest(3, 70)]])
    doc.save(path)
    doc.close()
    return path


def test_outline_ranges_share_a_page_only_when_the_next_heading_is_below_text(
        tmp_path: Path):
    pymupdf = pytest.importorskip("pymupdf")
    from bettermarkitdown.core import outline_ranges

    with pymupdf.open(_outline_pdf(tmp_path / "toc.pdf")) as doc:
        ranges = {title: (first, last) for _, title, first, last in outline_ranges(doc)}
    assert ranges["1.1 First"] == (1, 2)             # 1.2 starts below text on p. 2
    assert ranges["1.2 The Next Section"] == (2, 2)  # Chapter 2 opens p. 3
    assert ranges["Chapter 1"] == (1, 2)
    assert ranges["Chapter 2"] == (3, 3)


def test_cli_toc_prints_the_outline(tmp_path: Path, capsys):
    from bettermarkitdown.cli import main
    assert main([str(_outline_pdf(tmp_path / "toc.pdf")), "--toc"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert any(line.split() == ["1-2", "1.1", "First"] for line in lines)
    assert any(line.split() == ["3", "Chapter", "2"] for line in lines)
