"""The Windows installer's pieces, checked without building or running it: the icon, and
that the Inno Setup script, the build script and the setup script agree. The installer
itself is built, installed and uninstalled on a clean machine by the release workflow."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "installer"


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, INSTALLER / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_icon_has_every_size_windows_asks_for(tmp_path):
    pil = pytest.importorskip("PIL.Image")
    make_icon = load("make_icon")
    out = tmp_path / "app.ico"
    make_icon.draw(256).save(out, sizes=[(s, s) for s in (16, 32, 48, 256)])
    sizes = set(pil.open(out).info["sizes"])
    assert {(16, 16), (32, 32), (48, 48), (256, 256)} <= sizes
    assert make_icon.draw(32).getpixel((0, 0))[3] == 0          # transparent corners


def test_the_script_installs_only_what_the_build_stages():
    iss = (INSTALLER / "BetterMarkItDown.iss").read_text(encoding="utf-8")
    sources = set(re.findall(r'Source: "\{#SourceDir\}\\([^"]+)"', iss))
    staged = {"uv.exe", "{#WheelFile}", "install.ps1", "app.ico", "LICENSE.txt"}
    assert sources == staged
    build = (INSTALLER / "build.py").read_text(encoding="utf-8")
    for name in ("uv.exe", "install.ps1", "app.ico", "LICENSE.txt"):
        assert f'"{name}"' in build
    for define in ("AppVersion", "WheelFile", "SourceDir", "OutputDir"):
        assert f"/D{define}=" in build and f"{{#{define}}}" in iss


def test_it_installs_per_user_and_puts_everything_in_its_own_folder():
    iss = (INSTALLER / "BetterMarkItDown.iss").read_text(encoding="utf-8")
    assert "PrivilegesRequired=lowest" in iss
    assert r"DefaultDirName={localappdata}\Programs\BetterMarkItDown" in iss
    ps1 = (INSTALLER / "install.ps1").read_text(encoding="utf-8")
    for var in ("UV_PYTHON_INSTALL_DIR", "UV_TOOL_DIR", "UV_TOOL_BIN_DIR", "UV_CACHE_DIR"):
        assert re.search(rf'\$env:{var} = Join-Path \$app', ps1), var
    assert 'UV_PYTHON_PREFERENCE = "only-managed"' in ps1
    assert 'UV_NO_MODIFY_PATH = "1"' in ps1                   # the PATH is the installer's job
    # What setup made is what uninstall removes.
    for folder in ("python", "tools", "bin", "cache"):
        assert f'Name: "{{app}}\\{folder}"' in iss


def test_uv_is_pinned():
    build = load("build")
    assert re.fullmatch(r"\d+\.\d+\.\d+", build.UV_VERSION)
