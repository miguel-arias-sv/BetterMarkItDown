"""Reading the computer, and the local model suggested for it.

The recommender is tested on recorded profiles in tests/fixtures/systems, one per
kind of machine; add a file there when a real machine gets a surprising answer.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bettermarkitdown.local import CATALOG, recommend
from bettermarkitdown.system import (
    SystemProfile,
    detect,
    is_integrated,
    parse_nvidia_smi,
)

FIXTURES = Path(__file__).parent / "fixtures" / "systems"


def machine(name: str) -> SystemProfile:
    return SystemProfile.from_dict(json.loads((FIXTURES / f"{name}.json").read_text("utf-8")))


@pytest.mark.parametrize(("name", "tag", "runs_on"), [
    ("old_netbook_4gb", None, ""),
    ("budget_laptop_8gb_uhd", "qwen3-vl:2b-instruct", "processor"),
    ("office_desktop_16gb_apu", "qwen3-vl:4b-instruct", "processor"),
    ("laptop_rtx4050_6gb_old_driver_full_disk", "qwen3-vl:4b-instruct", "graphics card"),
    ("gaming_desktop_rtx3060_12gb", "qwen3-vl:8b-instruct", "graphics card"),
    ("laptop_core_ultra_32gb_arc_igpu", "qwen3-vl:8b-instruct", "processor"),
    ("macbook_air_m3_16gb", "qwen3-vl:8b-instruct", "shared memory"),
])
def test_each_kind_of_machine_gets_a_sensible_model(name, tag, runs_on):
    rec = recommend(machine(name))
    assert (rec.model.tag if rec.model else None) == tag
    assert rec.runs_on == runs_on
    assert rec.reasons, "every suggestion says why"
    assert [o.model for o in rec.options] == list(CATALOG), "every option is shown"


def test_too_little_memory_points_to_an_online_provider():
    rec = recommend(machine("old_netbook_4gb"))
    assert not any(o.fits for o in rec.options)
    assert "Gemini" in rec.reasons[0]


def test_processor_only_machines_are_warned_about_speed_and_offered_a_lighter_model():
    rec = recommend(machine("laptop_core_ultra_32gb_arc_igpu"))
    assert any("slow" in w and "Qwen3-VL 4B is faster" in w for w in rec.warnings)
    assert any("Vulkan" in w for w in rec.warnings)


def test_a_full_disk_and_an_old_nvidia_driver_are_reported():
    warnings = " ".join(recommend(machine("laptop_rtx4050_6gb_old_driver_full_disk")).warnings)
    assert "4 GB free" in warnings
    assert "531.79" in warnings and "550" in warnings


def test_a_card_with_its_own_memory_needs_no_speed_warning():
    assert recommend(machine("gaming_desktop_rtx3060_12gb")).warnings == []


def test_nvidia_smi_output_is_parsed():
    cards = parse_nvidia_smi("NVIDIA GeForce RTX 3060, 12288, 566.36\n"
                             "NVIDIA RTX A2000, 6138, 566.36\nnot, a, number\n")
    assert [(c.name, c.dedicated_gb, c.driver) for c in cards] == [
        ("NVIDIA GeForce RTX 3060", 12.0, "566.36"), ("NVIDIA RTX A2000", 5.99, "566.36")]


def test_built_in_graphics_are_recognised():
    assert is_integrated("Intel", "Intel(R) Arc(TM) Graphics", 0.12)
    assert not is_integrated("Intel", "Intel(R) Arc(TM) A770 Graphics", 16.0)
    assert is_integrated("AMD", "AMD Radeon(TM) Graphics", 4.0)       # APU with a big carve-out
    assert not is_integrated("AMD", "AMD Radeon RX 7800 XT", 16.0)
    assert not is_integrated("NVIDIA", "NVIDIA GeForce RTX 3060", 12.0)


def test_profiles_survive_a_round_trip_through_json():
    profile = machine("laptop_rtx4050_6gb_old_driver_full_disk")
    again = SystemProfile.from_dict(json.loads(json.dumps(profile.to_dict())))
    assert again == profile and again.best_gpu().name.startswith("NVIDIA GeForce RTX 4050")


def test_detect_reads_this_machine_without_failing():
    profile = detect()
    assert profile.os and profile.cores > 0
    assert profile.ram_gb > 0, profile.notes


def test_system_command_prints_json(monkeypatch, capsys):
    from bettermarkitdown import system
    from bettermarkitdown.cli import main

    monkeypatch.setattr(system, "detect", lambda: machine("budget_laptop_8gb_uhd"))
    assert main(["system", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["recommendation"]["model"]["tag"] == "qwen3-vl:2b-instruct"
    assert data["system"]["ram_gb"] == 8.0

    assert main(["system"]) == 0
    text = capsys.readouterr().out
    assert "All options (you choose)" in text and "Limits:" in text


def test_doctor_names_where_a_key_comes_from_but_never_prints_it(monkeypatch, capsys, tmp_path):
    from bettermarkitdown import doctor
    from bettermarkitdown.cli import main

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(doctor, "detect", lambda: machine("office_desktop_16gb_apu"))
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-very-secret-value")
    for args in (["doctor"], ["doctor", "--json"]):
        assert main(args) == 0
        out = capsys.readouterr().out
        assert "very-secret" not in out
        assert "GEMINI_API_KEY" in out
