# The Windows installer

`python installer/build.py` makes `dist/BetterMarkItDown-Setup-<version>.exe`. It needs
[Inno Setup 6](https://jrsoftware.org/isinfo.php) (`winget install JRSoftware.InnoSetup`)
and pip. The release workflow builds it on a clean Windows machine, installs and uninstalls
it there as a test, and attaches it to the GitHub Release.

| File | What it is |
|---|---|
| `BetterMarkItDown.iss` | The Inno Setup script: per user, no administrator rights; tasks for a desktop icon, the PATH, local OCR and Claude support; a progress page during setup; on uninstall, asks before deleting the person's data |
| `install.ps1` | Run by setup: gives the program its own Python 3.12 and libraries with uv, all inside the program's folder |
| `build.py` | Stages the package, a pinned uv (fetched from PyPI, so pip checks its hash), the icon and the licence, and runs the compiler |
| `make_icon.py` | Draws the icon: the setup page game's llama on a page. Original pixel art |

## What goes where on a person's computer

| Where | What | On uninstall |
|---|---|---|
| `%LOCALAPPDATA%\Programs\BetterMarkItDown` | uv, the package, `python\`, `tools\`, `bin\` (the commands) | removed |
| Start menu, desktop | shortcuts to `bin\bettermarkitdown-app.exe` (opens the setup page, no console window) | removed |
| user `PATH` (HKCU only) | `...\BetterMarkItDown\bin`, if the person ticked it | that entry alone is removed |
| `%LOCALAPPDATA%\BetterMarkItDown` | the setup page's library and work folders | removed only if the person says yes |
| `%APPDATA%\BetterMarkItDown` | settings | removed only if the person says yes |
| Windows Credential Manager | saved API keys | removed only if the person says yes |
| `Documents\BetterMarkItDown` | converted files | never touched |

## Code signing (to do)

Until the installer is signed, Windows SmartScreen warns about it; the README says how to
get past that. The plan is [SignPath Foundation](https://signpath.org), free for
open-source projects. It asks for: an OSI licence (MIT, done), a public repository (done),
builds made in CI rather than on a laptop (the release workflow, done), multi-factor
authentication for every maintainer, and a code signing policy page in the repository
naming who may sign. The application is made by the maintainer, at signpath.org.
