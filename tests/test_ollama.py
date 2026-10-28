"""Ollama support, against a fake server: no network, no Ollama needed."""

from __future__ import annotations

import pytest

from bettermarkitdown.local import CATALOG, ollama
from bettermarkitdown.local.commands import resolve


class FakeOllama:
    """Answers the few REST calls the tool makes, and records them."""

    def __init__(self, models=()):
        self.models = list(models)
        self.calls: list[tuple[str, str, dict | None]] = []

    def request(self, method, path, body=None, timeout=10.0):
        self.calls.append((method, path, body))
        if path == "/api/version":
            return {"version": "0.40.11"}
        if path == "/api/tags":
            return {"models": [{"name": m} for m in self.models]}
        if path == "/api/create":
            self.models.append(body["model"] + ":latest")
            return {"status": "success"}
        if path == "/api/ps":
            return {"models": [{"name": "bmid-qwen3-vl-4b-instruct:latest",
                                "size": 6_000_000_000, "size_vram": 1_500_000_000}]}
        if path == "/api/generate":
            return {"done": True}
        raise AssertionError(path)

    def stream(self, path, body, timeout=60.0):
        self.calls.append(("POST", path, body))
        yield {"status": "pulling manifest"}
        yield {"status": "pulling a", "digest": "sha256:a", "total": 3_000, "completed": 1_000}
        yield {"status": "pulling b", "digest": "sha256:b", "total": 1_000, "completed": 1_000}
        yield {"status": "pulling a", "digest": "sha256:a", "total": 3_000, "completed": 3_000}
        self.models.append(body["model"])          # the caller stops reading at "success"
        yield {"status": "success"}


@pytest.fixture
def server(monkeypatch):
    fake = FakeOllama()
    monkeypatch.setattr(ollama, "_request", fake.request)
    monkeypatch.setattr(ollama, "_stream", fake.stream)
    return fake


def test_pull_reports_progress_over_every_layer(server):
    seen = []
    ollama.pull("qwen3-vl:4b-instruct", lambda s, done, total: seen.append((done, total)))
    assert seen[-1] == (4_000, 4_000)
    assert (2_000, 4_000) in seen                    # two layers summed, mid-download
    assert server.models == ["qwen3-vl:4b-instruct"]


def test_a_download_that_stops_early_is_an_error(monkeypatch):
    monkeypatch.setattr(ollama, "_stream", lambda *a, **k: iter([{"status": "pulling"}]))
    with pytest.raises(ollama.OllamaError, match="ended before"):
        ollama.pull("x")


def test_the_default_context_is_replaced_by_a_copy_with_room_for_a_page(server):
    """Ollama's 4,096-token default silently cuts a dense page short."""
    server.models = ["qwen3-vl:4b-instruct"]
    name = ollama.with_context("qwen3-vl:4b-instruct")

    assert name == "bmid-qwen3-vl-4b-instruct"
    create = next(body for _, path, body in server.calls if path == "/api/create")
    assert create == {"model": name, "from": "qwen3-vl:4b-instruct",
                      "parameters": {"num_ctx": ollama.LOCAL_CONTEXT}, "stream": False}
    assert ollama.LOCAL_CONTEXT >= 8192

    server.calls.clear()
    assert ollama.with_context("qwen3-vl:4b-instruct") == name     # made once, then reused
    assert not any(path == "/api/create" for _, path, _ in server.calls)


def test_with_context_leaves_unknown_or_missing_models_alone(server, monkeypatch):
    assert ollama.with_context("not-downloaded:1b") == "not-downloaded:1b"
    assert ollama.with_context("bmid-anything") == "bmid-anything"

    def down(*_a, **_k):
        raise ollama.OllamaError("not reachable")

    monkeypatch.setattr(ollama, "_request", down)
    assert ollama.with_context("qwen3-vl:4b-instruct") == "qwen3-vl:4b-instruct"


def test_gpu_share_reads_how_much_of_the_model_is_in_graphics_memory(server):
    assert ollama.gpu_share("bmid-qwen3-vl-4b-instruct") == 0.25
    assert ollama.gpu_share("something-else") is None


def test_speed_test_verdicts_are_plain_and_scale_with_speed():
    def verdict(seconds, share=0.0):
        return ollama.SpeedTest("m", 5, seconds, share, True, "").verdict()

    assert verdict(8, 1.0).startswith("Quick") and "graphics card" in verdict(8, 1.0)
    assert verdict(45).startswith("Usable") and "processor" in verdict(45)
    assert "hours" in verdict(120)
    assert verdict(400).startswith("Very slow")


def test_the_test_page_is_a_real_image():
    pytest.importorskip("pymupdf")
    png = ollama.test_page_png()
    assert png.startswith(b"\x89PNG") and len(png) > 5_000


def test_address_honours_ollama_host(monkeypatch):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    assert ollama.api_url() == "http://127.0.0.1:11434"
    monkeypatch.setenv("OLLAMA_HOST", "0.0.0.0:11500")
    assert ollama.api_url() == "http://127.0.0.1:11500"


def test_sizes_and_tiers_pick_catalog_models():
    small, medium, large = CATALOG
    assert resolve("2b", large) is small
    assert resolve("standard", large) is medium
    assert resolve("qwen3-vl:8b-instruct", small) is large
    assert resolve(None, medium) is medium
    assert resolve("llava:7b", medium) == "llava:7b"            # any other tag passes through


def test_local_status_without_ollama(monkeypatch, capsys):
    from bettermarkitdown import cli

    monkeypatch.setattr(ollama, "find", lambda: "")
    monkeypatch.setattr(ollama, "version", lambda: "")
    assert cli.main(["local", "status"]) == 0
    out = capsys.readouterr().out
    assert "not installed" in out and "Suggested model" in out


def test_pull_needs_a_yes_before_downloading(server, monkeypatch, capsys):
    from bettermarkitdown import cli

    monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)
    assert cli.main(["local", "pull", "4b"]) == 1
    assert "needs a yes" in capsys.readouterr().out
    assert not any(path == "/api/pull" for _, path, _ in server.calls)

    assert cli.main(["local", "pull", "4b", "--yes"]) == 0
    assert "--model bmid-qwen3-vl-4b-instruct" in capsys.readouterr().out


def test_cli_converts_with_the_roomy_copy_one_page_at_a_time(server, monkeypatch, tmp_path):
    from bettermarkitdown import cli

    server.models = ["qwen3-vl:4b-instruct"]
    captured = {}

    def fake_convert(opts, on_event=None):
        captured["opts"] = opts
        raise KeyboardInterrupt            # stop before any real work

    monkeypatch.setattr(cli, "convert", fake_convert)
    monkeypatch.chdir(tmp_path)
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    assert cli.main([str(pdf), "--provider", "ollama", "--model", "qwen3-vl:4b-instruct"]) == 130
    opts = captured["opts"]
    assert opts.model == "bmid-qwen3-vl-4b-instruct"
    assert (opts.workers, opts.rpm) == (1, 0)
