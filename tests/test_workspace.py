"""The workspace on the setup page, over real HTTP on 127.0.0.1: add a file,
convert it, review and edit it page by page, take the result away. Vision is
faked; the library and the Documents folder are temporary (see conftest)."""

from __future__ import annotations

import http.client
import io
import json
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from apphttp import call, wait

from bettermarkitdown import core, library

pymupdf = pytest.importorskip("pymupdf")


def make_pdf(path: Path, text_pages: int = 2, scanned_pages: int = 1) -> Path:
    doc = pymupdf.open()
    for n in range(text_pages):
        page = doc.new_page()
        page.insert_text((72, 90), f"Chapter {n + 1}: Harvest Yields", fontsize=18)
        for i in range(6):
            page.insert_text((72, 130 + 16 * i), f"Line {i} of page {n + 1}: wheat, barley and "
                             "oats grew by 12 percent in the northern region.", fontsize=11)
    for _ in range(scanned_pages):
        scratch = pymupdf.open()
        tmp = scratch.new_page()
        tmp.insert_text((72, 120), "Pixels only, no text layer.", fontsize=20)
        pix = tmp.get_pixmap(dpi=50)
        doc.new_page().insert_image(doc[-1].rect, pixmap=pix)
    doc.save(path)
    doc.close()
    return path


def upload(app, path: Path, name: str | None = None, *, token=True, origin=None):
    data = path.read_bytes()
    conn = http.client.HTTPConnection("127.0.0.1", app.port, timeout=10)
    headers = {"Host": f"127.0.0.1:{app.port}", "Content-Type": "application/octet-stream",
               "X-BMID-Filename": quote(name or path.name)}
    if token:
        headers["X-BMID-Token"] = app.token
    if origin:
        headers["Origin"] = origin
    conn.request("POST", "/api/library/add", body=data, headers=headers)
    response = conn.getresponse()
    out = json.loads(response.read() or b"{}")
    conn.close()
    return response.status, out


def get_raw(app, path: str):
    conn = http.client.HTTPConnection("127.0.0.1", app.port, timeout=10)
    conn.request("GET", path, headers={"Host": f"127.0.0.1:{app.port}"})
    response = conn.getresponse()
    body = response.read()
    conn.close()
    return response.status, body, dict(response.getheaders())


def add(app, tmp_path, **kwargs) -> dict:
    status, out = upload(app, make_pdf(tmp_path / "Lecture 4.pdf", **kwargs))
    assert status == 200, out
    assert wait(app, out["job"])["status"] == "done"
    return out["document"]


@pytest.fixture
def fake_vision(monkeypatch):
    """Gemini with a made-up key; every picture is 'transcribed' at Flash's tokens."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-0123456789abcdef")
    seen = []

    def describe(client, model, png, prompt, **kwargs):
        seen.append(prompt)
        kwargs["meter"].add(SimpleNamespace(prompt_tokens=1500, completion_tokens=600,
                                            total_tokens=2100))
        return "Pixels only, no text layer."

    monkeypatch.setattr(core, "describe_image", describe)
    return seen


# --- the library ------------------------------------------------------------------------

def test_an_added_file_is_copied_inspected_and_listed(app, tmp_path):
    doc = add(app, tmp_path)
    assert doc["name"] == "Lecture 4" and doc["pages"] == 3

    stored = library.get(doc["id"])
    assert stored.source().read_bytes() == (tmp_path / "Lecture 4.pdf").read_bytes()
    assert stored.source().is_relative_to(library.data_dir())
    assert stored.inspection["scanned"] == [3] and stored.inspection["pages"] == 3

    _, listing = call(app, "GET", "/api/library")
    assert [d["id"] for d in listing["documents"]] == [doc["id"]]
    assert listing["output_root"] == str(library.output_root())


def test_files_it_cannot_read_are_refused_with_a_reason(app, tmp_path):
    other = tmp_path / "notes.txt"
    other.write_text("hello")
    status, out = upload(app, other)
    assert status == 400 and ".pdf" in out["error"]

    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf at all")
    status, out = upload(app, broken)
    assert status == 400 and "does not open" in out["error"]
    assert library.documents() == []


def test_adding_needs_the_token_and_this_site(app, tmp_path):
    pdf = make_pdf(tmp_path / "a.pdf")
    assert upload(app, pdf, token=False)[0] == 403
    assert upload(app, pdf, origin="https://evil.example")[0] == 403
    assert library.documents() == []


def test_two_files_with_one_name_get_their_own_result_folders(app, tmp_path):
    first = add(app, tmp_path)
    second = add(app, tmp_path)
    assert first["folder"] == "Lecture 4" and second["folder"] == "Lecture 4 (2)"


def test_odd_file_names_become_safe_folder_names():
    assert library.safe_name('a:b*c?"d') == "a_b_c__d"
    assert library.safe_name("CON") == "document_CON"
    assert library.safe_name("  trailing dots... ") == "trailing dots"


# --- estimate and convert ------------------------------------------------------------------

def test_the_estimate_counts_only_pages_the_model_reads(app, tmp_path, fake_vision):
    doc = add(app, tmp_path)
    _, out = call(app, "GET", f"/api/doc/estimate?id={doc['id']}")
    assert out["calls"] == 1 and out["pages"] == 3       # one scanned page, no figures
    assert 0 < out["cost"] < 0.01
    _, out = call(app, "GET", f"/api/doc/estimate?id={doc['id']}&pages=1-2")
    assert out["calls"] == 0 and out["pages"] == 2
    status, out = call(app, "GET", f"/api/doc/estimate?id={doc['id']}&pages=abc")
    assert status == 400 and "1-20" in out["error"]


def test_a_text_only_run_writes_the_result_to_documents(app, tmp_path):
    doc = add(app, tmp_path)
    _, job = call(app, "POST", "/api/doc/convert", {"id": doc["id"], "text_only": True})
    job = wait(app, job)
    assert job["status"] == "done", job["error"]

    after = job["result"]["document"]
    assert after["converted"] == [1, 2, 3] and after["output_ready"]
    output = Path(after["output"])
    assert output.is_relative_to(library.output_root())
    assert "# Lecture 4" in output.read_text(encoding="utf-8")
    assert "Converted from Lecture 4.pdf" in output.read_text(encoding="utf-8")
    assert after["last_run"]["text_only"] and after["last_run"]["converted"] == 3


def test_a_run_reports_pages_cost_and_time_left(app, tmp_path, fake_vision):
    doc = add(app, tmp_path, text_pages=1, scanned_pages=2)
    _, job = call(app, "POST", "/api/doc/convert", {"id": doc["id"]})
    job = wait(app, job)
    assert job["status"] == "done", job["error"]
    assert job["done"] == job["total"] == 3
    assert job["info"]["cost"] > 0 and job["info"]["eta"] == 0
    assert job["info"]["reading"] == [] and job["info"]["unit"] == "page"
    assert job["result"]["document"]["last_run"]["cost"] > 0
    assert len(fake_vision) == 2


def test_stop_ends_the_run_and_keeps_nothing_half_done(app, tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-0123456789abcdef")
    started = threading.Event()

    def slow(client, model, png, prompt, **kwargs):
        started.set()
        kwargs["meter"].abort.wait(5)
        raise core.BudgetExceeded("aborted")

    monkeypatch.setattr(core, "describe_image", slow)
    doc = add(app, tmp_path, text_pages=0, scanned_pages=3)
    _, job = call(app, "POST", "/api/doc/convert", {"id": doc["id"]})
    assert started.wait(5)
    assert call(app, "POST", "/api/doc/convert", {"id": doc["id"]})[0] == 409  # one at a time
    call(app, "POST", "/api/doc/stop", {"job": job["id"]})
    job = wait(app, job)
    assert job["status"] == "done"
    assert job["result"]["document"]["last_run"]["stopped"] == "stopped"
    assert job["result"]["document"]["converted"] == []


def test_stopping_one_run_leaves_another_alone(tmp_path):
    from bettermarkitdown.config import Options

    pdf = make_pdf(tmp_path / "a.pdf")
    stopped = threading.Event()
    stopped.set()
    first = core.convert(Options(pdf=pdf, output=tmp_path / "a.md", no_vision=True),
                         abort=stopped)
    second = core.convert(Options(pdf=pdf, output=tmp_path / "b.md", no_vision=True))
    assert first.pages_converted == 0 and second.pages_converted == 3


# --- review, edit, take away -------------------------------------------------------------

def converted(app, tmp_path) -> dict:
    doc = add(app, tmp_path)
    _, job = call(app, "POST", "/api/doc/convert", {"id": doc["id"], "text_only": True})
    return wait(app, job)["result"]["document"]


def test_an_edited_page_is_saved_checked_and_put_back_in_the_result(app, tmp_path):
    doc = converted(app, tmp_path)
    _, page = call(app, "GET", f"/api/doc/page?id={doc['id']}&page=1")
    assert page["converted"] and "Harvest Yields" in page["markdown"] and not page["edited"]

    edited = page["markdown"].replace("Harvest Yields", "Harvest Yields (checked)")
    edited = edited.replace("barley", "rye")             # not what the PDF says
    status, out = call(app, "POST", "/api/doc/page",
                       {"id": doc["id"], "page": 1, "markdown": edited.replace("\n", "\r\n")})
    assert status == 200 and out["edited"] == [1]
    assert any("barley" in note for note in out["notes"])  # --verify noticed

    stored = library.get(doc["id"])
    assert "\r" not in (stored.work_dir() / "pages" / "0001.md").read_text(encoding="utf-8")
    assert "Harvest Yields (checked)" in stored.output().read_text(encoding="utf-8")
    _, pages = call(app, "GET", f"/api/doc/pages?id={doc['id']}")
    assert pages["document"]["flagged"] == [1] and pages["scanned"] == [3]


def test_a_page_not_converted_yet_cannot_be_saved(app, tmp_path):
    doc = add(app, tmp_path)
    status, out = call(app, "POST", "/api/doc/page", {"id": doc["id"], "page": 1,
                                                       "markdown": "x"})
    assert status == 400 and "not been converted" in out["error"]


def test_page_images_and_downloads_take_the_token_in_the_address(app, tmp_path):
    doc = converted(app, tmp_path)
    base = f"id={doc['id']}"
    status, body, headers = get_raw(app, f"/api/doc/image?{base}&page=3&t={app.token}")
    assert status == 200 and body.startswith(b"\x89PNG")
    assert headers["Content-Type"] == "image/png"
    assert get_raw(app, f"/api/doc/image?{base}&page=3")[0] == 403
    # The address token is only for GETs that show or save something, never for changes.
    assert get_raw(app, f"/api/library?t={app.token}")[0] == 403

    status, body, headers = get_raw(app, f"/api/doc/download?{base}&t={app.token}")
    assert status == 200 and b"# Lecture 4" in body
    assert 'filename="Lecture 4.md"' in headers["Content-Disposition"]
    status, body, _ = get_raw(app, f"/api/doc/download?{base}&format=zip&t={app.token}")
    assert status == 200 and "Lecture 4.md" in zipfile.ZipFile(io.BytesIO(body)).namelist()


def test_pictures_come_only_from_the_result_folder(app, tmp_path):
    doc = converted(app, tmp_path)
    secret = library.output_root() / "secret.png"
    secret.write_bytes(b"\x89PNG not yours")
    assets = library.get(doc["id"]).assets_dir()
    assets.mkdir(parents=True, exist_ok=True)
    (assets / "fig 1.png").write_bytes(b"\x89PNG figure")
    base = f"/api/doc/asset?id={doc['id']}&t={app.token}&path="
    assert get_raw(app, base + quote(quote("Lecture 4_assets/fig 1.png")))[1] == b"\x89PNG figure"
    assert get_raw(app, base + quote("../secret.png"))[0] == 404
    assert get_raw(app, base + quote("Lecture 4.md"))[0] == 404        # not a picture


def test_removing_a_file_keeps_its_result(app, tmp_path, monkeypatch):
    from bettermarkitdown.app import workspace

    doc = converted(app, tmp_path)
    opened = []
    monkeypatch.setattr(workspace, "_reveal", opened.append)
    call(app, "POST", "/api/doc/open-folder", {"id": doc["id"]})
    assert opened == [Path(doc["output"]).parent]

    status, out = call(app, "POST", "/api/library/remove", {"id": doc["id"]})
    assert status == 200 and Path(doc["output"]).is_file()
    assert library.documents() == []
    assert call(app, "GET", f"/api/doc?id={doc['id']}")[0] == 400
    assert call(app, "GET", "/api/doc?id=../../etc")[0] == 400


def test_the_speed_test_is_remembered_for_time_estimates(app, monkeypatch, tmp_path):
    from bettermarkitdown import settings
    from bettermarkitdown.local import ollama

    monkeypatch.setattr(ollama, "with_context", lambda tag, num_ctx=0: "bmid-" + tag)
    monkeypatch.setattr(ollama, "speed_test", lambda name: ollama.SpeedTest(
        name, 8.0, 120.0, 0.0, True, "Chapter 3: Harvest Yields"))
    _, job = call(app, "POST", "/api/local/test", {"model": "qwen3-vl:8b-instruct"})
    wait(app, job)
    assert settings.load().speed == {"qwen3-vl:8b-instruct": 120.0}

    settings.update(provider="ollama", model="qwen3-vl:8b-instruct")
    doc = add(app, tmp_path)
    _, out = call(app, "GET", f"/api/doc/estimate?id={doc['id']}")
    assert out["cost"] == 0 and out["seconds"] == 120


def test_a_refused_request_still_gets_its_answer(app):
    """A POST refused before its body is read used to be reset by Windows now and
    then, so the browser saw a network error instead of the refusal."""
    for _ in range(20):
        status, out = call(app, "POST", "/api/settings", {"model": "x" * 200_000},
                            origin="https://evil.example")
        assert status == 403 and "other sites" in out["error"]

