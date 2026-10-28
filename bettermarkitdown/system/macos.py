"""macOS: sysctl. Untested on a Mac so far; every reading fails soft.

On Apple Silicon the graphics share one memory pool with the processor, so a
model's size is limited by main memory (macOS lets the GPU use roughly two thirds
to three quarters of it). Intel Macs run local models on the processor.
"""

from __future__ import annotations

from . import GB, GPU, SystemProfile, run


def fill(profile: SystemProfile) -> None:
    memory = run(["sysctl", "-n", "hw.memsize"]).strip()
    if memory.isdigit():
        profile.ram_gb = round(int(memory) / GB, 1)
    profile.cpu = run(["sysctl", "-n", "machdep.cpu.brand_string"]).strip()
    if profile.arch == "arm64":
        profile.gpus = [GPU(name="Apple Silicon GPU", vendor="Apple", shared_gb=profile.ram_gb,
                            integrated=True, unified=True, source="sysctl")]
