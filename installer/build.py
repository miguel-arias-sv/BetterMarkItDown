"""Build the Windows installer: dist/BetterMarkItDown-Setup-<version>.exe.

    python installer/build.py

Needs Inno Setup 6 (ISCC.exe: on the PATH, in $ISCC, or in its usual folders) and pip.
Steps: build the package; fetch uv (pinned below, from PyPI, so pip checks its hash); draw
the icon; compile installer/BetterMarkItDown.iss. Everything is staged in
build/installer, so the repository stays clean.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

# uv inside the installer gives the program its own Python. Pinned, and at least two
# weeks old when chosen; raise it deliberately.
UV_VERSION = "0.12.24"

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / "build" / "installer"
DIST = ROOT / "dist"


def version() -> str:
    text = (ROOT / "bettermarkitdown" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__\s*=\s*"([^"]+)"', text).group(1)


def run(*command: str, **kwargs) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, check=True, **kwargs)


def find_iscc() -> str:
    candidates = [os.environ.get("ISCC", ""), shutil.which("iscc") or "",
                  shutil.which("ISCC") or ""]
    for base in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("PROGRAMFILES(X86)", ""),
                 os.environ.get("PROGRAMFILES", "")):
        if base:
            candidates += [str(Path(base) / sub / "Inno Setup 6" / "ISCC.exe")
                           for sub in ("Programs", "")]
    found = next((c for c in candidates if c and Path(c).is_file()), "")
    if not found:
        sys.exit("Inno Setup 6 was not found. Install it (winget install JRSoftware.InnoSetup) "
                 "or set ISCC to ISCC.exe.")
    return found


def fetch_uv(into: Path) -> None:
    downloads = STAGE / "downloads"
    run(sys.executable, "-m", "pip", "download", f"uv=={UV_VERSION}", "--no-deps",
        "--only-binary=:all:", "--platform", "win_amd64", "--python-version", "3.12",
        "-d", str(downloads), "-q")
    wheel = next(downloads.glob(f"uv-{UV_VERSION}-*win_amd64.whl"))
    with zipfile.ZipFile(wheel) as z:
        (into / "uv.exe").write_bytes(z.read(f"uv-{UV_VERSION}.data/scripts/uv.exe"))


def main() -> int:
    ver = version()
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    DIST.mkdir(exist_ok=True)

    run(sys.executable, "-m", "pip", "wheel", str(ROOT), "--no-deps", "-w", str(STAGE), "-q")
    wheel = next(STAGE.glob(f"bettermarkitdown-{ver}-*.whl")).name
    fetch_uv(STAGE)
    run(sys.executable, str(ROOT / "installer" / "make_icon.py"), str(STAGE / "app.ico"))
    shutil.copy(ROOT / "installer" / "install.ps1", STAGE / "install.ps1")
    shutil.copy(ROOT / "LICENSE", STAGE / "LICENSE.txt")

    run(find_iscc(), "/Q", f"/DAppVersion={ver}", f"/DWheelFile={wheel}",
        f"/DSourceDir={STAGE}", f"/DOutputDir={DIST}",
        str(ROOT / "installer" / "BetterMarkItDown.iss"))
    out = DIST / f"BetterMarkItDown-Setup-{ver}.exe"
    print(f"Built {out} ({out.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
