# Sets up BetterMarkItDown's own Python and libraries inside this folder, with uv.
# The installer runs it; running it again reinstalls. Needs internet: it downloads
# Python 3.12 and the libraries (about 500 MB on disk).
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1 [-Extras "ocr,anthropic"]
#
# Everything stays in this folder (python\, tools\, bin\), so uninstalling removes it all.
# Nothing is added to the PATH here; the installer does that, if asked.
#
# The installer does not wait on this script (so its progress page keeps moving): the
# output goes to install.log and the exit code to install.done, which it watches.
param([string]$Extras = "")

$ErrorActionPreference = "Continue"          # uv writes progress to stderr
$app = $PSScriptRoot
$log = Join-Path $app "install.log"
$done = Join-Path $app "install.done"
Remove-Item -Force -ErrorAction SilentlyContinue $log, $done

function Say([string]$line) { Add-Content -Path $log -Value $line -Encoding UTF8 }

$code = 1
try {
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $app "python"
    $env:UV_TOOL_DIR = Join-Path $app "tools"
    $env:UV_TOOL_BIN_DIR = Join-Path $app "bin"
    $env:UV_CACHE_DIR = Join-Path $app "cache"
    $env:UV_PYTHON_PREFERENCE = "only-managed"    # never a Python already on this computer
    $env:UV_NO_MODIFY_PATH = "1"
    $env:UV_NATIVE_TLS = "1"                      # trust Windows' certificates (company proxies)
    $env:UV_LINK_MODE = "copy"                    # so the cache can be deleted afterwards
    $env:NO_COLOR = "1"

    $wheel = Get-ChildItem -Path $app -Filter "bettermarkitdown-*.whl" | Select-Object -First 1
    if (-not $wheel) {
        Say "The BetterMarkItDown package is missing from $app."
        $code = 2
        return
    }
    $name = if ($Extras) { "bettermarkitdown[$Extras]" } else { "bettermarkitdown" }
    # A file:// address, with spaces and other characters escaped (user names have spaces).
    $spec = "$name @ " + ([System.Uri]$wheel.FullName).AbsoluteUri

    Say "Installing $($wheel.Name) with extras: $(if ($Extras) { $Extras } else { 'none' })"
    & (Join-Path $app "uv.exe") tool install --force --python 3.12 $spec 2>&1 |
        ForEach-Object { Say "$_" }
    $code = $LASTEXITCODE
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $env:UV_CACHE_DIR
    if ($code -eq 0) {
        & (Join-Path $app "bin\bettermarkitdown.exe") --version 2>&1 | ForEach-Object { Say "$_" }
        $code = $LASTEXITCODE
    }
}
catch {
    Say "Setup stopped: $_"
    $code = 3
}
finally {
    Set-Content -Path $done -Value $code -Encoding ASCII
}
exit $code
