"""Keeps a local model from taking a small Mac down with it.

On 2026-11-06 Qwen3-VL 4B froze an 8 GB M1 until it was forced off with the power
button. A model on Apple Silicon sits in the memory macOS and every open app also
need, so on a Mac under 16 GB a run is contained:

  before  the model must suit this Mac, and enough memory must be free right now;
          otherwise it is not loaded and the person is told what to do instead
  during  a thread watches memory pressure, because one page can take minutes; if
          memory runs out the run stops and the model's process is ended
  after   the model leaves memory at once, instead of staying loaded for minutes

Every other computer is unaffected. When a limit cannot be read the run is refused:
a wrong "no" costs a retry, and a wrong "yes" can cost a forced shutdown.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from ..system import macos
from . import CATALOG, UNIFIED_SHARE, ollama

MARGIN_GB = 1.5           # the image encoder and the page's context, on top of the weights
FLOOR_GB = 0.5            # below this much free, the computer is about to stop responding
POLL_SECONDS = 2.0

STOPPED_MESSAGE = ("This Mac was running out of memory, so the run stopped and the model was "
                   "closed. Finished pages are kept: close other apps and run it again, or "
                   "use an online provider such as Gemini.")


class NotEnoughMemory(RuntimeError):
    """The model was not loaded, to keep the computer usable."""


@dataclass
class Watch:
    tripped: bool = False


def needed_gb(name: str) -> float:
    """Memory `name` needs: the catalog's figure, or its size on disk plus a margin."""
    for model in CATALOG:
        if name in (model.tag, ollama.local_name(model.tag)):
            return model.min_vram_gb
    size = ollama.size_gb(name)
    return size + MARGIN_GB if size else CATALOG[0].min_vram_gb


def check(name: str) -> None:
    """Raise NotEnoughMemory unless `name` can load on this Mac right now."""
    needed = needed_gb(name)
    usable = macos.ram_gb() * UNIFIED_SHARE
    if needed > usable:
        raise NotEnoughMemory(
            f"{name} needs about {needed:g} GB, more than this Mac can spare "
            f"({usable:.1f} GB), so it was not loaded: it could freeze the computer. Choose "
            "a smaller model, or use an online provider such as Gemini.")
    free = macos.available_gb()
    if free is None:
        raise NotEnoughMemory(f"Could not read how much memory is free, so {name} was not "
                              "loaded: it could freeze the computer.")
    if free < needed or macos.pressure_critical():
        raise NotEnoughMemory(
            f"{name} needs about {needed:g} GB free and this Mac has {free:.1f} GB right now, "
            "so it was not loaded: it could freeze the computer. Close other apps and try "
            "again, or use an online provider such as Gemini.")


def running_out() -> bool:
    free = macos.available_gb()
    return macos.pressure_critical() or free is None or free < FLOOR_GB


def _pgrep(*args: str) -> list[int]:
    found = subprocess.run(["pgrep", *args], check=False, capture_output=True, text=True)
    return [int(pid) for pid in found.stdout.split() if pid.isdigit()]


def model_processes() -> list[int]:
    """Everything running under `ollama serve`, deepest first. Found by parent, not by
    name: the names change with Ollama's version and engine (runner, llama-server, MLX),
    and with no model loaded the server has no children at all."""
    found: list[int] = []
    waiting = _pgrep("-f", "ollama serve")
    while waiting:
        children = [child for pid in waiting for child in _pgrep("-P", str(pid))]
        found = children + found
        waiting = children
    return found


def end_model(name: str) -> None:
    """Free the memory now. A page in progress holds the model in place, so its processes
    are ended first, in a way they cannot delay: asking Ollama to unload it would wait
    for that page."""
    for pid in model_processes():
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGKILL)
    ollama.unload(name)


@contextmanager
def contained(name: str, on_stop: Callable[[], None] | None = None) -> Iterator[Watch | None]:
    """Run a local model inside this Mac's limits. Yields a Watch whose `tripped` says
    whether memory ran out, or None on a computer that needs no limits."""
    if not macos.small_unified():
        yield None
        return
    check(name)
    watch, done = Watch(), threading.Event()

    def keep_watch() -> None:
        while not done.wait(POLL_SECONDS):
            if running_out():
                watch.tripped = True
                if on_stop:
                    on_stop()              # first, so nothing reloads the model
                end_model(name)
                return

    thread = threading.Thread(target=keep_watch, name="memory-watch", daemon=True)
    thread.start()
    try:
        yield watch
    finally:
        done.set()
        thread.join(timeout=30)
        ollama.unload(name)
