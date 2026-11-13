"""The limits on a computer with little memory. Everything is faked: no model is loaded,
ever. The tests marked for Windows read that computer's real memory and process list."""

from __future__ import annotations

import os
import sys
import threading
from types import SimpleNamespace

import pymupdf
import pytest

from bettermarkitdown import core, system
from bettermarkitdown.config import Options
from bettermarkitdown.local import guard, ollama
from bettermarkitdown.system import linux, macos

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
        monkeypatch.setattr(system, "sys", type("S", (), {"platform": "darwin"}))
        monkeypatch.setattr(system, "card_gb", lambda: 0.0)
        monkeypatch.setattr(macos.platform, "machine", lambda: "arm64")
        monkeypatch.setattr(macos, "ram_gb", lambda: 8.0)
        monkeypatch.setattr(macos, "available_gb", lambda: self.free)
        monkeypatch.setattr(macos, "pressure_critical", lambda: self.critical)
        monkeypatch.setattr(ollama, "size_gb", lambda name: 4.1)
        monkeypatch.setattr(ollama, "unload", lambda name: self.log.append("unload"))
        monkeypatch.setattr(guard, "model_processes", lambda: [4321])
        monkeypatch.setattr(guard.os, "kill", lambda pid, sig: self.log.append(("kill", pid, sig)))
        monkeypatch.setattr(guard, "POLL_SECONDS", 0.01)


class PC:
    """An 8 GB Windows or Linux laptop whose memory the test sets."""

    def __init__(self, monkeypatch, platform_name):
        self.ram, self.free, self.card = 8.0, 6.0, 0.0
        self.log: list[str] = []
        self.pressure_critical = lambda: False
        self.ram_gb = lambda: self.ram
        self.available_gb = lambda: self.free
        monkeypatch.setattr(system, "SMALL_RAM_GB", 16)
        monkeypatch.setattr(system, "sys", type("S", (), {"platform": platform_name}))
        monkeypatch.setattr(system, "memory_source", lambda: self)
        monkeypatch.setattr(system, "card_gb", lambda: self.card)
        monkeypatch.setattr(ollama, "size_gb", lambda name: 4.1)
        monkeypatch.setattr(ollama, "unload", lambda name: self.log.append("unload"))
        monkeypatch.setattr(guard, "model_processes", lambda: [4321])
        monkeypatch.setattr(guard.os, "kill", lambda pid, sig: self.log.append(("kill", pid, sig)))
        monkeypatch.setattr(guard, "POLL_SECONDS", 0.01)


@pytest.fixture
def mac(monkeypatch):
    return Mac(monkeypatch)


@pytest.fixture(params=["win32", "linux"])
def pc(request, monkeypatch):
    return PC(monkeypatch, request.param)


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
    monkeypatch.setattr(guard, "sys", type("S", (), {"platform": "linux"}))
    tree = {("-f", "ollama serve"): "100\n", ("-P", "100"): "200\n201\n", ("-P", "200"): "300\n",
            ("-P", "201"): "", ("-P", "300"): ""}
    monkeypatch.setattr(guard.subprocess, "run", lambda args, **k: SimpleNamespace(
        stdout=tree[tuple(args[1:])]))
    assert guard.model_processes() == [300, 200, 201]


def test_no_server_or_no_model_means_nothing_to_end(monkeypatch):
    monkeypatch.setattr(guard, "sys", type("S", (), {"platform": "linux"}))
    monkeypatch.setattr(guard.subprocess, "run", lambda args, **k: SimpleNamespace(stdout=""))
    assert guard.model_processes() == []


def test_a_mac_with_room_loads_2b(mac):
    guard.check(TWO_B)


@pytest.mark.parametrize("name", [FOUR_B, "qwen3-vl:4b-instruct", "mistral:latest"])
def test_a_model_too_big_for_the_mac_is_refused_however_much_is_free(mac, name):
    mac.free = 7.5
    with pytest.raises(guard.NotEnoughMemory, match="more than this computer can spare"):
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
    assert mac.log[:3] == ["stop", ("kill", 4321, guard.KILL), "unload"]


def test_a_pc_with_room_loads_2b_inside_a_watch(pc):
    with guard.contained(TWO_B) as watch:
        assert not watch.tripped
    assert pc.log == ["unload"]


def test_a_model_too_big_for_the_pc_is_refused_however_much_is_free(pc):
    pc.free = 7.5
    with pytest.raises(guard.NotEnoughMemory, match="more than this computer can spare"):
        guard.check(FOUR_B)


def test_a_pc_short_of_free_memory_is_refused_with_what_to_do(pc):
    pc.free = 2.0
    with pytest.raises(guard.NotEnoughMemory, match="2.0 GB right now.*Close other apps.*Gemini"):
        guard.check(TWO_B)


@pytest.mark.parametrize(("ram", "free", "message"), [
    (0.0, 6.0, "how much memory this computer has"),
    (8.0, None, "how much memory is free"),
])
def test_a_pc_whose_memory_cannot_be_read_is_refused(pc, ram, free, message):
    pc.ram, pc.free = ram, free
    with pytest.raises(guard.NotEnoughMemory, match=message), guard.contained(TWO_B):
        pytest.fail("the model must not run")


def test_a_4_gb_laptop_is_refused_even_with_the_smallest_model(pc):
    pc.ram, pc.free = 4.0, 3.9
    with pytest.raises(guard.NotEnoughMemory, match="more than this computer can spare"):
        guard.check(TWO_B)


@pytest.mark.parametrize("free", [0.3, None])
def test_a_pc_running_out_during_a_page_stops_and_ends_the_model(pc, free):
    stopped = threading.Event()

    def on_stop():
        pc.log.append("stop")
        stopped.set()

    with guard.contained(TWO_B, on_stop=on_stop) as watch:
        pc.free = free
        wait_for(stopped)
    assert watch.tripped
    assert pc.log[:3] == ["stop", ("kill", 4321, guard.KILL), "unload"]


def test_a_pc_with_16_gb_needs_no_limits(pc):
    pc.ram, pc.free = 16.0, 0.1
    with guard.contained(TWO_B) as watch:
        assert watch is None
    assert pc.log == []


def test_a_model_that_fits_on_the_graphics_card_needs_no_limits(pc):
    pc.card, pc.free = 4.0, 0.1
    with guard.contained(TWO_B) as watch:
        assert watch is None


def test_a_card_too_small_for_the_model_does_not_lift_the_limits(pc):
    pc.card, pc.free = 2.0, 1.0
    with pytest.raises(guard.NotEnoughMemory), guard.contained(TWO_B):
        pytest.fail("the model must not run")


def test_windows_finds_what_runs_under_the_server_deepest_first():
    table = [(1, 0, "explorer.exe"), (10, 1, "ollama app.exe"), (20, 10, "ollama.exe"),
             (21, 20, "conhost.exe"), (30, 20, "ollama.exe"), (40, 30, "llama-server.exe"),
             (50, 1, "Code.exe")]
    assert guard.windows_model_processes(table) == [40, 30]


@pytest.mark.parametrize("table", [
    [],
    [(10, 1, "ollama app.exe"), (20, 10, "ollama.exe")],      # the server, with no model loaded
    [(50, 1, "notepad.exe"), (60, 50, "ollama-helper.exe")],
])
def test_windows_finds_nothing_to_end_without_a_model(table):
    assert guard.windows_model_processes(table) == []


def test_a_process_list_that_loops_still_ends():
    table = [(20, 1, "OLLAMA.EXE"), (30, 20, "runner.exe"), (20, 30, "runner.exe")]
    assert guard.windows_model_processes(table) == [30]


def test_model_processes_uses_the_process_list_on_windows(monkeypatch):
    table = [(20, 1, "ollama.exe"), (30, 20, "runner.exe")]
    monkeypatch.setattr(guard, "sys", type("S", (), {"platform": "win32"}))
    source = SimpleNamespace(process_table=lambda: table)
    monkeypatch.setattr(system, "memory_source", lambda: source)
    assert guard.model_processes() == [30]


def test_no_pgrep_means_nothing_to_end(monkeypatch):
    def missing(*_a, **_k):
        raise OSError("no pgrep")

    monkeypatch.setattr(guard.subprocess, "run", missing)
    assert guard._pgrep("-f", "ollama serve") == []


def test_linux_reads_memory_from_the_kernel(monkeypatch):
    monkeypatch.setattr(linux, "_meminfo", lambda: {"MemTotal": 8 * system.GB,
                                                    "MemAvailable": 3 * system.GB})
    assert linux.ram_gb() == 8.0
    assert linux.available_gb() == 3.0
    assert not linux.pressure_critical()


def test_linux_with_no_reading_says_so(monkeypatch):
    monkeypatch.setattr(linux, "_meminfo", dict)
    assert linux.ram_gb() == 0.0
    assert linux.available_gb() is None


@pytest.mark.parametrize(("ram", "small"), [(8.0, True), (15.9, True), (16.0, False),
                                            (0.0, True)])
def test_under_16_gb_is_small_and_unreadable_counts_as_small(monkeypatch, ram, small):
    monkeypatch.setattr(system, "SMALL_RAM_GB", 16)
    monkeypatch.setattr(system, "sys", type("S", (), {"platform": "linux"}))
    monkeypatch.setattr(system, "memory_source", lambda: SimpleNamespace(ram_gb=lambda: ram))
    assert system.small_memory() is small


@pytest.mark.skipif(sys.platform != "win32", reason="reads Windows itself")
def test_windows_reads_its_real_memory_and_processes():
    from bettermarkitdown.system import windows

    assert windows.ram_gb() > 0
    assert 0 < windows.available_gb() <= windows.ram_gb()
    assert os.getpid() in {pid for pid, _, _ in windows.process_table()}


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
    assert ("kill", 4321, guard.KILL) in mac.log


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
