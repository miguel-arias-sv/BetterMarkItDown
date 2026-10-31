"""Linux: /proc and sysfs, plus nvidia-smi. Every reading fails soft."""

from __future__ import annotations

from pathlib import Path

from . import GB, GPU, SystemProfile, merge_nvidia, nvidia_gpus


def _meminfo() -> dict[str, int]:
    values = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            name, _, rest = line.partition(":")
            if rest.split():
                values[name] = int(rest.split()[0]) * 1024     # kB -> bytes
    except OSError:
        pass
    return values


def _cpu_name() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.partition(":")[2].strip()
    except OSError:
        pass
    return ""


def _amd_gpus() -> list[GPU]:
    """amdgpu publishes each card's VRAM in sysfs."""
    cards = []
    for vram in sorted(Path("/sys/class/drm").glob("card*/device/mem_info_vram_total")):
        try:
            size = int(vram.read_text().strip()) / GB
        except (OSError, ValueError):
            continue
        cards.append(GPU(name=f"AMD GPU ({vram.parts[-3]})", vendor="AMD",
                         dedicated_gb=round(size, 2), integrated=size < 1.0, source="sysfs"))
    return cards


def fill(profile: SystemProfile) -> None:
    memory = _meminfo()
    profile.ram_gb = round(memory.get("MemTotal", 0) / GB, 1)
    profile.ram_available_gb = round(memory.get("MemAvailable", 0) / GB, 1)
    profile.cpu = _cpu_name()
    profile.gpus = merge_nvidia(_amd_gpus(), nvidia_gpus())
