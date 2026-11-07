"""The limits on a small Mac. Everything is faked: no model is loaded, ever."""

from __future__ import annotations

import signal
import threading
from types import SimpleNamespace

import pymupdf
import pytest

from bettermarkitdown import core
from bettermarkitdown.config import Options
from bettermarkitdown.local import guard, ollama
from bettermarkitdown.system import macos

TWO_B, FOUR_B = "bmid-qwen3-vl-2b-instruct", "bmid-qwen3-vl-4b-instruct"
VM_STAT = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                                     4273.
Pages active:                                 105928.
Pages inactive:                               104936.
Pages speculative:                               556.
Pages throttled:                                   0.
Pages wired down:                             100590.
Pages purgeable:                                   4.
"""


class Mac:
    """An 8 GB M1 whose memory the test sets, with Ollama and pkill recorded."""

    def __init__(self, monkeypatch):
        self.free, self.critical = 6.0, False
        self.log: list[str] = []
        monkeypatch.setattr(macos, "SMALL_UNIFIED_GB", 16)
        monkeypatch.setattr(macos, "sys", type("S", (), {"platform": "darwin"}))
        monkeypatch.setattr(macos.platform, "machine", lambda: "arm64")
        monkeypatch.setattr(macos, "ram_gb", lambda: 8.0)
        monkeypatch.setattr(macos, "available_gb", lambda: self.free)
        monkeypatch.setattr(macos, "pressure_critical", lambda: self.critical)
        monkeypatch.setattr(ollama, "size_gb", lambda name: 4.1)
        monkeypatch.setattr(ollama, "unload", lambda name: self.log.append("unload"))
        monkeypatch.setattr(guard, "model_processes", lambda: [4321])
        monkeypatch.setattr(guard.os, "kill", lambda pid, sig: self.log.append(("kill", pid, sig)))
        monkeypatch.setattr(guard, "POLL_SECONDS", 0.01)


@pytest.fixture
def mac(monkeypatch):
    return Mac(monkeypatch)


def wait_for(event: threading.Event) -> None:
    assert event.wait(5), "the watch never noticed"


def test_vm_stat_is_read_as_memory_that_can_be_used_now(monkeypatch):
    monkeypatch.setattr(macos, "run", lambda args, **k: VM_STAT)
    assert macos.available_gb() == 1.7
    monkeypatch.setattr(macos, "run", lambda args, **k: "")
    assert macos.available_gb() is None


def test_only_a_critical_pressure_level_counts_as_critical(monkeypatch):
    monkeypatch.setattr(macos, "run", lambda args, **k: "2\n")
    assert not macos.pressure_critical()
    monkeypatch.setattr(macos, "run", lambda args, **k: "4\n")
    assert macos.pressure_critical()


@pytest.mark.parametrize(("ram", "platform_name", "machine", "small"), [
    (8.0, "darwin", "arm64", True),
    (16.0, "darwin", "arm64", False),
    (8.0, "darwin", "x86_64", False),
    (8.0, "linux", "arm64", False),
    (0.0, "darwin", "arm64", False),
])
def test_only_apple_silicon_under_16_gb_is_a_small_mac(
        monkeypatch, ram, platform_name, machine, small):
    monkeypatch.setattr(macos, "SMALL_UNIFIED_GB", 16)
    monkeypatch.setattr(macos, "sys", type("S", (), {"platform": platform_name}))
    monkeypatch.setattr(macos.platform, "machine", lambda: machine)
    monkeypatch.setattr(macos, "ram_gb", lambda: ram)
    assert macos.small_unified() is small


def test_model_processes_are_found_by_parent_with_the_deepest_first(monkeypatch):
    tree = {("-f", "ollama serve"): "100\n", ("-P", "100"): "200\n201\n", ("-P", "200"): "300\n",
            ("-P", "201"): "", ("-P", "300"): ""}
    monkeypatch.setattr(guard.subprocess, "run", lambda args, **k: SimpleNamespace(
        stdout=tree[tuple(args[1:])]))
    assert guard.model_processes() == [300, 200, 201]


def test_no_server_or_no_model_means_nothing_to_end(monkeypatch):
    monkeypatch.setattr(guard.subprocess, "run", lambda args, **k: SimpleNamespace(stdout=""))
    assert guard.model_processes() == []


def test_a_mac_with_room_loads_2b(mac):
    guard.check(TWO_B)


@pytest.mark.parametrize("name", [FOUR_B, "qwen3-vl:4b-instruct", "mistral:latest"])
def test_a_model_too_big_for_the_mac_is_refused_however_much_is_free(mac, name):
    mac.free = 7.5
    with pytest.raises(guard.NotEnoughMemory, match="more than this Mac can spare"):
        guard.check(name)


def test_too_little_free_right_now_is_refused_with_what_to_do(mac):
    mac.free = 1.8                       # what this Mac had free with no model at all
    with pytest.raises(guard.NotEnoughMemory, match="1.8 GB right now.*Close other apps.*Gemini"):
        guard.check(TWO_B)


def test_critical_pressure_is_refused_even_with_memory_free(mac):
    mac.critical = True
    with pytest.raises(guard.NotEnoughMemory):
        guard.check(TWO_B)


def test_unreadable_memory_is_refused(mac):
    mac.free = None
    with pytest.raises(guard.NotEnoughMemory, match="Could not read"):
        guard.check(TWO_B)


def test_a_refused_model_is_never_watched_or_unloaded(mac):
    mac.free = 1.0
    with pytest.raises(guard.NotEnoughMemory), guard.contained(TWO_B):
        pytest.fail("the model must not run")
    assert mac.log == []


def test_other_computers_get_no_limits(monkeypatch):
    def forbidden(*_a):
        raise AssertionError("no check on a computer that needs none")

    monkeypatch.setattr(guard, "check", forbidden)
    monkeypatch.setattr(ollama, "unload", forbidden)
    with guard.contained(TWO_B) as watch:
        assert watch is None


def test_the_model_leaves_memory_after_a_run(mac):
    with guard.contained(TWO_B) as watch:
        pass
    assert not watch.tripped
    assert mac.log == ["unload"]


def test_the_model_leaves_memory_after_a_failed_run(mac):
    with pytest.raises(ValueError), guard.contained(TWO_B):
        raise ValueError
    assert mac.log == ["unload"]


@pytest.mark.parametrize("change", [{"critical": True}, {"free": 0.3}, {"free": None}])
def test_running_out_during_a_page_stops_the_run_and_ends_the_model(mac, change):
    stopped = threading.Event()

    def on_stop():
        mac.log.append("stop")           # before the kill: nothing may reload the model
        stopped.set()

    with guard.contained(TWO_B, on_stop=on_stop) as watch:
        for key, value in change.items():
            setattr(mac, key, value)
        wait_for(stopped)
    assert watch.tripped
    assert mac.log[:3] == ["stop", ("kill", 4321, signal.SIGKILL), "unload"]


def make_options(tmp_path, monkeypatch, **extra) -> Options:
    doc = pymupdf.open()
    for _ in range(3):
        doc.new_page().insert_text((72, 72), "Some words on the page.")
    pdf = tmp_path / "a.pdf"
    doc.save(pdf)
    doc.close()
    monkeypatch.setattr(core, "vision_client", lambda opts: object())
    return Options(pdf=pdf, output=tmp_path / "a.md", work_dir=tmp_path / "work", model=TWO_B,
                   provider="ollama", base_url="http://127.0.0.1:11434/v1", api_key="", workers=1,
                   **extra)


def test_a_conversion_stops_mid_page_and_keeps_the_pages_it_finished(mac, tmp_path, monkeypatch):
    read = []

    def process_page(index, *, opts, meter, **_):
        if index == 0:
            read.append(index)
            return index, "first page", False, False, 0
        mac.critical = True              # memory runs out while this page is being read
        if not meter.abort.wait(5):
            pytest.fail("the page was never stopped")
        raise core.BudgetExceeded("aborted")

    monkeypatch.setattr(core, "process_page", process_page)
    result = core.convert(make_options(tmp_path, monkeypatch))
    assert result.stopped_reason == "memory"
    assert result.pages_converted == 1
    assert (tmp_path / "work" / "pages" / "0001.md").read_text("utf-8").strip() == "first page"
    assert ("kill", 4321, signal.SIGKILL) in mac.log


def test_a_conversion_is_refused_before_any_page_when_memory_is_short(
        mac, tmp_path, monkeypatch):
    mac.free = 1.0
    monkeypatch.setattr(core, "process_page", lambda *a, **k: pytest.fail("must not run"))
    with pytest.raises(guard.NotEnoughMemory):
        core.convert(make_options(tmp_path, monkeypatch))


def test_a_text_only_conversion_needs_no_model_and_no_limits(mac, tmp_path, monkeypatch):
    mac.free = 1.0
    result = core.convert(make_options(tmp_path, monkeypatch, no_vision=True))
    assert result.pages_converted == 3
    assert mac.log == []
