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

from bettermarkitdown.config import Options  # noqa: E402
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
