"""What this computer can run: memory, processor, graphics, disk.

Each operating system has its own module; `detect()` picks the right one and
never raises. A part it cannot read is left at zero or empty and a note says
why, so a recommendation can still be made from what is known.

Sources, most trusted first (see the notes in each module):
  Windows  RAM: GetPhysicallyInstalledSystemMemory; graphics: DXGI (dedicated and
           shared memory, every vendor), then nvidia-smi for NVIDIA's exact VRAM
           and driver version
  macOS    sysctl; Apple Silicon graphics share the main memory ("unified")
  Linux    /proc/meminfo, /proc/cpuinfo, nvidia-smi, the amdgpu sysfs files
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

GB = 1024 ** 3

# PCI vendor ids, as DXGI and Linux report them.
VENDORS = {0x10DE: "NVIDIA", 0x1002: "AMD", 0x8086: "Intel", 0x5143: "Qualcomm",
           0x106B: "Apple", 0x1414: "Microsoft"}


@dataclass
class GPU:
    name: str
    vendor: str
    dedicated_gb: float = 0.0       # the card's own memory (VRAM)
    shared_gb: float = 0.0          # main memory it may borrow
    integrated: bool = False        # built into the processor: borrows main memory
    unified: bool = False           # Apple Silicon: one pool for processor and graphics
    driver: str = ""
    source: str = ""                # where the numbers came from


@dataclass
class SystemProfile:
    os: str = ""
    os_version: str = ""
    arch: str = ""
    cpu: str = ""
    cores: int = 0
    ram_gb: float = 0.0             # installed
    ram_available_gb: float = 0.0   # free right now
    gpus: list[GPU] = field(default_factory=list)
    disk_free_gb: float = 0.0       # where local models are stored
    disk_path: str = ""
    ollama: str = ""                # path to the ollama program, if installed
    notes: list[str] = field(default_factory=list)

    def best_gpu(self) -> GPU | None:
        """The graphics card with the most memory of its own, if there is one."""
        cards = [g for g in self.gpus if not g.integrated and g.dedicated_gb > 0]
        return max(cards, key=lambda g: g.dedicated_gb, default=None)

    def unified_memory(self) -> bool:
        return any(g.unified for g in self.gpus)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> SystemProfile:
        data = dict(data)
        data["gpus"] = [GPU(**g) for g in data.get("gpus", [])]
        return cls(**data)


def models_dir() -> Path:
    """Where Ollama keeps its models: $OLLAMA_MODELS, else ~/.ollama/models."""
    configured = os.environ.get("OLLAMA_MODELS", "").strip()
    return Path(configured) if configured else Path.home() / ".ollama" / "models"


def run(args: list[str], timeout: float = 10.0) -> str:
    """A command's output, or "" if it is missing, fails, or hangs."""
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout if done.returncode == 0 else ""


def parse_nvidia_smi(output: str) -> list[GPU]:
    """`nvidia-smi --query-gpu=name,memory.total,driver_version
    --format=csv,noheader,nounits`: one 'name, MiB, driver' line per card."""
    cards = []
    for line in output.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        try:
            mib = float(parts[1])
        except ValueError:
            continue
        cards.append(GPU(name=parts[0], vendor="NVIDIA", dedicated_gb=round(mib / 1024, 2),
                         driver=parts[2], source="nvidia-smi"))
    return cards


def nvidia_gpus() -> list[GPU]:
    if not shutil.which("nvidia-smi"):
        return []
    return parse_nvidia_smi(run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
                                 "--format=csv,noheader,nounits"]))


def is_integrated(vendor: str, name: str, dedicated_gb: float) -> bool:
    """Built into the processor? Such chips have little or no memory of their own;
    AMD's can be given a large slice of main memory in the BIOS, so go by name too."""
    if dedicated_gb < 1.0:
        return True
    lowered = name.lower()
    return vendor == "AMD" and " rx " not in f" {lowered} " and "pro w" not in lowered


def merge_nvidia(gpus: list[GPU], nvidia: list[GPU]) -> list[GPU]:
    """nvidia-smi knows NVIDIA cards exactly; it replaces the generic reading."""
    if not nvidia:
        return gpus
    others = [g for g in gpus if g.vendor != "NVIDIA"]
    return nvidia + others


def detect() -> SystemProfile:
    profile = SystemProfile(os=platform.system(), os_version=platform.version(),
                            arch=platform.machine(), cores=os.cpu_count() or 0)
    try:
        if profile.os == "Windows":
            from . import windows as backend
        elif profile.os == "Darwin":
            from . import macos as backend
        else:
            from . import linux as backend
        backend.fill(profile)
    except Exception as exc:          # a partial profile beats no profile
        profile.notes.append(f"System details could not be read fully: {exc}")

    profile.ollama = shutil.which("ollama") or ""
    folder = models_dir()
    probe = folder if folder.exists() else Path(folder.anchor or Path.home())
    try:
        profile.disk_free_gb = round(shutil.disk_usage(probe).free / GB, 1)
        profile.disk_path = str(folder)
    except OSError as exc:
        profile.notes.append(f"Free disk space unknown: {exc}")
    return profile


__all__ = ["GB", "GPU", "SystemProfile", "VENDORS", "detect", "is_integrated", "models_dir",
           "parse_nvidia_smi"]
