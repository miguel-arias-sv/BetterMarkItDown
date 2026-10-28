"""Models that run on this computer, and which one to suggest.

One family (Qwen3-VL) in three sizes, so the output looks the same whatever the
machine and only speed and accuracy change. The `-instruct` tags are named
explicitly: a "thinking" variant would spend minutes reasoning before each page.
Sizes are Ollama's downloads (https://ollama.com/library/qwen3-vl/tags, checked
2026-10-27).

Memory rules of thumb: on a graphics card, the model needs its download size plus
about 1.5-2 GB for the image encoder and the page's context. On the processor it
runs from main memory, alongside Windows and everything else that is open, so the
thresholds are the common sizes computers are sold with: 8, 16 and 32 GB.

The suggestion is only that. Every option is listed with whether it fits, and the
person chooses; after the download a timed test page gives the real speed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from ..system import SystemProfile

# On Apple Silicon the graphics may use roughly two thirds of main memory.
UNIFIED_SHARE = 0.66
DISK_MARGIN_GB = 2.0
MIN_NVIDIA_DRIVER = 550        # Ollama's minimum for most NVIDIA cards


@dataclass(frozen=True)
class LocalModel:
    tag: str                   # what `ollama pull` takes
    name: str
    tier: str                  # basic | standard | high
    download_gb: float
    min_vram_gb: float         # to run wholly on a graphics card
    min_ram_gb: float          # to run on the processor from main memory
    good_at: str
    limits: str


CATALOG: tuple[LocalModel, ...] = (       # smallest first
    LocalModel(
        tag="qwen3-vl:2b-instruct", name="Qwen3-VL 2B", tier="basic",
        download_gb=1.9, min_vram_gb=3.5, min_ram_gb=8,
        good_at="Clean printed text and simple layouts, on modest computers.",
        limits="The least accurate: expect slips in maths, tables and small print, "
               "so read its output closely."),
    LocalModel(
        tag="qwen3-vl:4b-instruct", name="Qwen3-VL 4B", tier="standard",
        download_gb=3.3, min_vram_gb=5.0, min_ram_gb=16,
        good_at="Everyday documents, tables and most scans.",
        limits="Dense maths and multi-column pages still need a careful read."),
    LocalModel(
        tag="qwen3-vl:8b-instruct", name="Qwen3-VL 8B", tier="high",
        download_gb=6.2, min_vram_gb=8.0, min_ram_gb=32,
        good_at="The most accurate local option: hard scans, tables and much of the maths.",
        limits="Still behind the large online models on dense notation, and slow without "
               "a graphics card."),
)


@dataclass
class Option:
    model: LocalModel
    fits: bool
    runs_on: str = ""          # "graphics card" | "shared memory" | "processor"


@dataclass
class Recommendation:
    model: LocalModel | None   # None: use an online provider instead
    runs_on: str = ""
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    options: list[Option] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def where_it_runs(model: LocalModel, profile: SystemProfile) -> str:
    """Where `model` would run on this computer, or "" if it would not fit."""
    gpu = profile.best_gpu()
    if gpu and gpu.dedicated_gb >= model.min_vram_gb:
        return "graphics card"
    if profile.unified_memory() and profile.ram_gb * UNIFIED_SHARE >= model.min_vram_gb:
        return "shared memory"
    if profile.ram_gb >= model.min_ram_gb:
        return "processor"
    return ""


def recommend(profile: SystemProfile) -> Recommendation:
    options = []
    for model in CATALOG:
        where = where_it_runs(model, profile)
        options.append(Option(model, bool(where), where))
    fitting = [o for o in options if o.fits]
    if not fitting:
        known = f"{profile.ram_gb:g} GB of memory" if profile.ram_gb else "unknown memory"
        return Recommendation(
            model=None, options=options,
            reasons=[f"This computer has {known}: a local model would not load, or would be "
                     "too slow to use. A free Gemini key is the better choice here."])

    # The largest that fits: the tiers already encode "smallest that works well"
    # for each class of machine. Lighter options stay listed for speed.
    chosen = fitting[-1]
    rec = Recommendation(model=chosen.model, runs_on=chosen.runs_on, options=options)
    gpu = profile.best_gpu()

    if chosen.runs_on == "graphics card":
        rec.reasons.append(f"{gpu.name} has {gpu.dedicated_gb:g} GB of its own memory, enough "
                           f"to run {chosen.model.name} entirely on the card.")
    elif chosen.runs_on == "shared memory":
        rec.reasons.append(f"{profile.ram_gb:g} GB of memory shared with the graphics is enough "
                           f"for {chosen.model.name}.")
    else:
        rec.reasons.append(f"{profile.ram_gb:g} GB of memory is enough for "
                           f"{chosen.model.name}.")
        lighter = fitting[-2].model.name if len(fitting) > 1 else None
        rec.warnings.append(
            "No graphics card with memory of its own, so the processor reads the pages. "
            "Expect it to be slow, possibly a minute or more per page. The speed test after "
            "the download gives the real figure"
            + (f"; {lighter} is faster if that is too slow." if lighter else "."))
        if any(g.integrated and g.vendor in ("Intel", "AMD") for g in profile.gpus):
            rec.warnings.append("Ollama may use the built-in graphics to speed this up "
                                "(its Vulkan support is still experimental).")

    if profile.disk_free_gb and profile.disk_free_gb < chosen.model.download_gb + DISK_MARGIN_GB:
        rec.warnings.append(f"Only {profile.disk_free_gb:g} GB free on the disk that holds the "
                            f"models; {chosen.model.name} needs {chosen.model.download_gb:g} GB "
                            "plus room to spare.")
    for card in profile.gpus:
        major = card.driver.split(".")[0]
        if card.vendor == "NVIDIA" and major.isdigit() and int(major) < MIN_NVIDIA_DRIVER:
            rec.warnings.append(f"Update the NVIDIA driver ({card.driver} installed, "
                                f"{MIN_NVIDIA_DRIVER} or newer needed) so Ollama can use "
                                f"the {card.name}.")
    return rec


def describe(profile: SystemProfile, rec: Recommendation) -> str:
    """The plain-text report `bettermarkitdown system` prints."""
    lines = ["This computer",
             f"  Processor   {profile.cpu or 'unknown'} ({profile.cores} threads)",
             f"  Memory      {profile.ram_gb:g} GB installed, "
             f"{profile.ram_available_gb:g} GB free now"]
    for gpu in profile.gpus or []:
        kind = ("built-in, borrows main memory" if gpu.integrated
                else f"{gpu.dedicated_gb:g} GB of its own")
        driver = f", driver {gpu.driver}" if gpu.driver else ""
        lines.append(f"  Graphics    {gpu.name} ({kind}{driver})")
    if not profile.gpus:
        lines.append("  Graphics    none found")
    lines.append(f"  Disk        {profile.disk_free_gb:g} GB free for models ({profile.disk_path})")
    lines.append(f"  Ollama      {profile.ollama or 'not installed'}")
    lines += [f"  Note        {note}" for note in profile.notes]

    lines += ["", "Suggested local model"]
    if rec.model:
        lines.append(f"  {rec.model.name}  ({rec.model.tag}, {rec.model.download_gb:g} GB "
                     f"download, runs on the {rec.runs_on})")
    else:
        lines.append("  None: use an online provider")
    lines += [f"  Why: {reason}" for reason in rec.reasons]
    lines += [f"  ! {warning}" for warning in rec.warnings]

    lines += ["", "All options (you choose)"]
    for option in rec.options:
        mark = "fits" if option.fits else "too big"
        lines.append(f"  {option.model.name:<12} {option.model.download_gb:>4g} GB  {mark:<7}  "
                     f"Good at: {option.model.good_at}")
        lines.append(f"  {'':<12} {'':>4}     {'':<7}  Limits:  {option.model.limits}")
    return "\n".join(lines)


__all__ = ["CATALOG", "LocalModel", "Option", "Recommendation", "describe", "recommend",
           "where_it_runs"]
