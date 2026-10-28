"""Ollama: find it, install it (with consent), download models, and time a page.

Talks to Ollama's own REST API with the standard library only. Conversions go
through its OpenAI-compatible endpoint like any other provider (see providers/).

The one trap: Ollama gives every model a 4,096-token context by default, and the
OpenAI endpoint has no way to change it. A page image is about 2,000 tokens, the
prompt 600, and a dense transcription 4,000 more, so the default silently cuts
pages short. `with_context()` makes a copy of the model with a larger context
(metadata only, no second download) and conversions use that name.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

DOWNLOAD_URL = "https://ollama.com/download"
WINGET_ID = "Ollama.Ollama"
# Image (~2k) + prompt (~0.6k) + a dense page (~4k), with room for the larger
# retry. Each extra 1k tokens costs roughly 100-150 MB of memory on these models.
LOCAL_CONTEXT = 12288
PREFIX = "bmid-"


class OllamaError(RuntimeError):
    pass


def api_url() -> str:
    """Ollama's address. 127.0.0.1, not localhost: on Windows, localhost tries IPv6
    first and Ollama listens on IPv4 only, which costs seconds per request."""
    host = os.environ.get("OLLAMA_HOST", "").strip() or "127.0.0.1:11434"
    if "://" not in host:
        host = "http://" + host
    return host.replace("0.0.0.0", "127.0.0.1").rstrip("/")


def _request(method: str, path: str, body: dict | None = None, timeout: float = 10.0) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(api_url() + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        raise OllamaError(_error_text(exc)) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise OllamaError(f"Ollama is not reachable at {api_url()}: {exc}") from exc
    if isinstance(payload, dict) and payload.get("error"):
        raise OllamaError(payload["error"])
    return payload


def _stream(path: str, body: dict, timeout: float = 60.0) -> Iterator[dict]:
    """POST and yield each line of Ollama's newline-delimited JSON reply."""
    req = urllib.request.Request(api_url() + path, data=json.dumps(body).encode(),
                                 method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for line in resp:
                if not line.strip():
                    continue
                event = json.loads(line)
                if event.get("error"):
                    raise OllamaError(event["error"])
                yield event
    except urllib.error.HTTPError as exc:
        raise OllamaError(_error_text(exc)) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise OllamaError(f"Ollama is not reachable at {api_url()}: {exc}") from exc


def _error_text(exc: urllib.error.HTTPError) -> str:
    try:
        return json.loads(exc.read().decode()).get("error") or str(exc)
    except Exception:
        return str(exc)


# --- the program --------------------------------------------------------------------

def find() -> str:
    """Path to the ollama program, or "". Looks in the usual install folders too:
    right after an install, this process's PATH has not caught up yet."""
    found = shutil.which("ollama")
    if found:
        return found
    candidates = []
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "")
        candidates.append(Path(local) / "Programs" / "Ollama" / "ollama.exe")
    elif sys.platform == "darwin":
        candidates += [Path("/Applications/Ollama.app/Contents/Resources/ollama"),
                       Path("/opt/homebrew/bin/ollama"), Path("/usr/local/bin/ollama")]
    else:
        candidates += [Path("/usr/local/bin/ollama"), Path("/usr/bin/ollama")]
    return next((str(p) for p in candidates if p.is_file()), "")


def version() -> str:
    """The running server's version, or "" if none is listening."""
    try:
        return _request("GET", "/api/version", timeout=3).get("version", "")
    except OllamaError:
        return ""


def start(program: str, wait: float = 20.0) -> bool:
    """Start `ollama serve` in the background and wait until it answers."""
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
    subprocess.Popen([program, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     stdin=subprocess.DEVNULL, creationflags=flags,
                     start_new_session=sys.platform != "win32")
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if version():
            return True
        time.sleep(0.5)
    return False


def ensure_running() -> str:
    """The server's version, starting it if it is installed but not running."""
    running = version()
    if running:
        return running
    program = find()
    if program and start(program):
        return version()
    return ""


def install_command() -> list[str] | None:
    """How to install Ollama without a browser, where we know one. Windows only for
    now; macOS and Linux get the download page until they are tested."""
    if sys.platform == "win32" and shutil.which("winget"):
        return ["winget", "install", "--id", WINGET_ID, "-e", "--silent",
                "--accept-source-agreements", "--accept-package-agreements",
                "--disable-interactivity"]
    return None


def install() -> bool:
    """Run the installer, showing its output. True once the program can be found."""
    command = install_command()
    if not command:
        return False
    subprocess.run(command, check=False)
    return bool(find())


# --- models ---------------------------------------------------------------------------

def installed() -> list[str]:
    return [m.get("name", "") for m in _request("GET", "/api/tags").get("models", [])]


def has(name: str, models: list[str] | None = None) -> bool:
    models = installed() if models is None else models
    wanted = name if ":" in name else name + ":latest"
    return wanted in models or name in models


def pull(tag: str, on_progress: Callable[[str, int, int], None] | None = None) -> None:
    """Download a model. on_progress(status, done_bytes, total_bytes) sums every
    layer, so the numbers mean the whole download."""
    totals: dict[str, int] = {}
    done: dict[str, int] = {}
    for event in _stream("/api/pull", {"model": tag}, timeout=120.0):
        digest = event.get("digest")
        if digest and event.get("total"):
            totals[digest] = int(event["total"])
            done[digest] = int(event.get("completed", 0))
        if on_progress:
            on_progress(event.get("status", ""), sum(done.values()), sum(totals.values()))
        if event.get("status") == "success":
            return
    raise OllamaError(f"The download of {tag} ended before it finished.")


def local_name(tag: str) -> str:
    """'qwen3-vl:4b-instruct' -> 'bmid-qwen3-vl-4b-instruct'."""
    return PREFIX + tag.replace(":", "-").replace("/", "-")


def with_context(tag: str, num_ctx: int = LOCAL_CONTEXT) -> str:
    """The name to convert with: a copy of `tag` with a context large enough for a
    page, made on first use. Returns `tag` unchanged if the copy cannot be made."""
    if tag.startswith(PREFIX):
        return tag
    name = local_name(tag)
    try:
        models = installed()
        if has(name, models):
            return name
        if not has(tag, models):
            return tag
        _request("POST", "/api/create",
                 {"model": name, "from": tag, "parameters": {"num_ctx": num_ctx},
                  "stream": False}, timeout=120.0)
        return name
    except OllamaError:
        return tag


def gpu_share(name: str) -> float | None:
    """How much of a loaded model sits in graphics memory: 1.0 all, 0.0 none."""
    try:
        for model in _request("GET", "/api/ps").get("models", []):
            if model.get("name", "").split(":")[0] == name.split(":")[0] and model.get("size"):
                return round(model.get("size_vram", 0) / model["size"], 2)
    except OllamaError:
        pass
    return None


# --- the speed test -------------------------------------------------------------------

@dataclass
class SpeedTest:
    model: str
    load_seconds: float
    page_seconds: float
    gpu_share: float | None
    read_ok: bool             # did the transcription contain the test page's words?
    text: str

    def verdict(self) -> str:
        per_page = self.page_seconds
        book = _duration(per_page * 100)
        where = ("on the graphics card" if (self.gpu_share or 0) >= 0.9
                 else "partly on the graphics card" if (self.gpu_share or 0) > 0.1
                 else "on the processor")
        if per_page < 20:
            feel = "Quick"
        elif per_page < 60:
            feel = "Usable"
        elif per_page < 180:
            feel = "Slow: fine for a chapter, a whole book takes hours"
        else:
            feel = "Very slow: try a lighter model, or an online provider for long documents"
        return (f"{feel}. About {per_page:.0f} s per page, running {where}; "
                f"a 100-page book would take about {book}.")


def _duration(seconds: float) -> str:
    if seconds < 90:
        return f"{seconds:.0f} seconds"
    if seconds < 5400:
        return f"{seconds / 60:.0f} minutes"
    return f"{seconds / 3600:.1f} hours"


TEST_WORDS = ("Harvest", "wheat", "region")


def test_page_png(dpi: int = 200, max_edge: int = 1568) -> bytes:
    """A small made-up page: a heading, prose, a table and a formula, rendered as an
    image the way a scanned page would be."""
    import pymupdf

    from ..core import render, shrink

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 90), "Chapter 3: Harvest Yields", fontsize=18, fontname="hebo")
    lines = ["The table below shows the annual wheat yield by region, in tonnes per",
             "hectare. Yields rose in every region between the two survey years."]
    for i, line in enumerate(lines):
        page.insert_text((72, 130 + 16 * i), line, fontsize=11)
    rows = [("Region", "2019", "2023"), ("North", "3.1", "3.6"), ("South", "2.4", "2.9"),
            ("Coast", "4.0", "4.2")]
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            page.insert_text((90 + 120 * c, 200 + 18 * r), cell, fontsize=11,
                             fontname="hebo" if r == 0 else "helv")
    page.insert_text((72, 300), "Growth rate:  g = (Y2023 - Y2019) / Y2019", fontsize=12)
    png = shrink(render(page, dpi), max_edge)
    doc.close()
    return png


def speed_test(name: str) -> SpeedTest:
    """Load `name`, transcribe the test page once, and time both."""
    from ..prompts import PAGE_PROMPT
    from ..providers import PROVIDERS
    from ..providers.openai_compat import OpenAICompatible

    started = time.monotonic()
    _request("POST", "/api/generate", {"model": name, "keep_alive": "10m"}, timeout=600.0)
    load_seconds = time.monotonic() - started

    client = OpenAICompatible(PROVIDERS["ollama"], base_url=api_url() + "/v1", timeout=900.0)
    png = test_page_png()
    started = time.monotonic()
    reply = client.describe(png, PAGE_PROMPT, model=name, max_tokens=4096, reasoning="default")
    page_seconds = time.monotonic() - started
    text = reply.text or ""
    return SpeedTest(model=name, load_seconds=round(load_seconds, 1),
                     page_seconds=round(page_seconds, 1), gpu_share=gpu_share(name),
                     read_ok=all(w.lower() in text.lower() for w in TEST_WORDS), text=text)
