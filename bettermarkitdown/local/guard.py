"""Keeps a local model from taking a computer with little memory down with it.

On 2026-11-06 Qwen3-VL 4B froze an 8 GB M1 until it was forced off with the power
button. A model read by the processor, or by graphics that borrow main memory, sits
in the memory the system and every open app also need. So under 16 GB a run is
contained, on Windows, Linux and Apple Silicon:

  before  the model must suit this computer, and enough memory must be free right now;
          otherwise it is not loaded and the person is told what to do instead
  during  a thread watches memory, because one page can take minutes; if memory runs
          out the run stops and the model's process is ended
  after   the model leaves memory at once, instead of staying loaded for minutes

A model that fits on a graphics card with its own memory leaves main memory alone, and
every computer with 16 GB or more is unaffected. So are Intel Macs. When a limit cannot
be read the run is refused: a wrong "no" costs a retry, and a wrong "yes" can cost a
forced shutdown.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from .. import system
from . import CATALOG, UNIFIED_SHARE, ollama

MARGIN_GB = 1.5           # the image encoder and the page's context, on top of the weights
FLOOR_GB = 0.5            # below this much free, the computer is about to stop responding
POLL_SECONDS = 2.0

STOPPED_MESSAGE = ("This computer was running out of memory, so the run stopped and the model was "
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


def needs_limits(name: str) -> bool:
    return system.small_memory() and system.card_gb() < needed_gb(name)


def check(name: str) -> None:
    """Raise NotEnoughMemory unless `name` can load on this computer right now."""
    memory = system.memory_source()
    needed, total = needed_gb(name), memory.ram_gb()
    if not total:
        raise NotEnoughMemory(f"Could not read how much memory this computer has, so {name} "
                              "was not loaded: it could freeze the computer.")
    usable = total * UNIFIED_SHARE         # the same share leaves Windows and Linux their room
    if needed > usable:
        raise NotEnoughMemory(
            f"{name} needs about {needed:g} GB, more than this computer can spare "
            f"({usable:.1f} GB), so it was not loaded: it could freeze the computer. Choose "
            "a smaller model, or use an online provider such as Gemini.")
    free = memory.available_gb()
    if free is None:
        raise NotEnoughMemory(f"Could not read how much memory is free, so {name} was not "
                              "loaded: it could freeze the computer.")
    if free < needed or memory.pressure_critical():
        raise NotEnoughMemory(
            f"{name} needs about {needed:g} GB free and this computer has {free:.1f} GB right "
            "now, so it was not loaded: it could freeze the computer. Close other apps and "
            "try again, or use an online provider such as Gemini.")


def running_out() -> bool:
    memory = system.memory_source()
    free = memory.available_gb()
    return memory.pressure_critical() or free is None or free < FLOOR_GB


def _pgrep(*args: str) -> list[int]:
    try:
        found = subprocess.run(["pgrep", *args], check=False, capture_output=True, text=True)
    except OSError:                        # a small Linux may not have it
        return []
    return [int(pid) for pid in found.stdout.split() if pid.isdigit()]


def windows_model_processes(table: list[tuple[int, int, str]]) -> list[int]:
    """The same, from Windows's process list: (id, parent, program). The server is the
    ollama.exe not started by another; the tray app has a name of its own."""
    names = {pid: program.lower() for pid, _, program in table}
    waiting = {pid for pid, parent, program in table
               if program.lower() == "ollama.exe" and names.get(parent) != "ollama.exe"}
    found: list[int] = []
    seen = set(waiting)
    while waiting:
        children = [pid for pid, parent, program in table
                    if parent in waiting and pid not in seen
                    and program.lower() != "conhost.exe"]    # the server's console, not a model
        found = children + found
        seen.update(children)
        waiting = set(children)
    return found


def model_processes() -> list[int]:
    """Everything running under `ollama serve`, deepest first. Found by parent, not by
    name: the names change with Ollama's version and engine (runner, llama-server, MLX),
    and with no model loaded the server has no children at all."""
    if sys.platform == "win32":
        return windows_model_processes(system.memory_source().process_table())
    found: list[int] = []
    waiting = _pgrep("-f", "ollama serve")
    while waiting:
        children = [child for pid in waiting for child in _pgrep("-P", str(pid))]
        found = children + found
        waiting = children
    return found


# Windows has no SIGKILL; its SIGTERM ends a process outright too.
KILL = getattr(signal, "SIGKILL", signal.SIGTERM)


def end_model(name: str) -> None:
    """Free the memory now. A page in progress holds the model in place, so its processes
    are ended first, in a way they cannot delay: asking Ollama to unload it would wait
    for that page."""
    for pid in model_processes():
        with contextlib.suppress(OSError):
            os.kill(pid, KILL)
    ollama.unload(name)


@contextmanager
def contained(name: str, on_stop: Callable[[], None] | None = None) -> Iterator[Watch | None]:
    """Run a local model inside this computer's limits. Yields a Watch whose `tripped` says
    whether memory ran out, or None on a computer that needs no limits."""
    if not needs_limits(name):
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
