"""macOS: sysctl and vm_stat. Every reading fails soft.

On Apple Silicon the graphics share one memory pool with the processor, so a
model's size is limited by main memory (macOS lets the GPU use roughly two thirds
to three quarters of it). Intel Macs run local models on the processor.
"""

from __future__ import annotations

import platform
import re
import sys

from . import GB, GPU, SystemProfile, run

SMALL_UNIFIED_GB = 16     # under this, a local model competes with macOS for memory
PRESSURE_CRITICAL = "4"   # kern.memorystatus_vm_pressure_level: 1 normal, 2 warning, 4 critical


def ram_gb() -> float:
    memory = run(["sysctl", "-n", "hw.memsize"]).strip()
    return round(int(memory) / GB, 1) if memory.isdigit() else 0.0


def small_unified() -> bool:
    """An Apple Silicon Mac small enough that a local model needs limits."""
    return (sys.platform == "darwin" and platform.machine() == "arm64"
            and 0 < ram_gb() < SMALL_UNIFIED_GB)


def available_gb() -> float | None:
    """Memory that can be used right now without swapping, or None if unreadable.
    Inactive pages count: macOS hands them over at once."""
    report = run(["vm_stat"])
    size = re.search(r"page size of (\d+) bytes", report)
    pages = re.findall(r"^Pages (?:free|inactive|speculative|purgeable):\s+(\d+)\.", report,
                       re.MULTILINE)
    if not size or len(pages) != 4:
        return None
    return round(sum(map(int, pages)) * int(size.group(1)) / GB, 1)


def pressure_critical() -> bool:
    return run(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"]).strip() == PRESSURE_CRITICAL


def fill(profile: SystemProfile) -> None:
    profile.ram_gb = ram_gb()
    profile.ram_available_gb = available_gb() or 0.0
    profile.cpu = run(["sysctl", "-n", "machdep.cpu.brand_string"]).strip()
    if profile.arch == "arm64":
        profile.gpus = [GPU(name="Apple Silicon GPU", vendor="Apple", shared_gb=profile.ram_gb,
                            integrated=True, unified=True, source="sysctl")]
