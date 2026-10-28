"""`bettermarkitdown doctor`: one report to paste into an issue.

Names where each key comes from, never the key itself.
"""

from __future__ import annotations

import importlib.util
import platform
import sys

from . import __version__, ocr
from .config import find_api_key, resolve_endpoint
from .local import recommend
from .mathcheck import find_node
from .providers import PROVIDERS
from .system import detect


def gather() -> dict:
    profile = detect()
    rec = recommend(profile)
    try:
        provider, base_url = resolve_endpoint()
        active = {"provider": provider.id, "base_url": base_url}
    except ValueError as exc:
        active = {"provider": "", "error": str(exc)}
    return {
        "version": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "active": active,
        "keys": {spec.id: find_api_key(spec.id)[1] for spec in PROVIDERS.values()
                 if spec.needs_key or spec.key_env},
        "optional": {
            "anthropic SDK (Claude)": importlib.util.find_spec("anthropic") is not None,
            "local OCR fallback": ocr.available(),
            "Node.js (math render check)": bool(find_node()),
            "Ollama": bool(profile.ollama),
        },
        "system": profile.to_dict(),
        "suggested_local_model": rec.model.tag if rec.model else None,
        "warnings": rec.warnings,
    }


def format_report(report: dict) -> str:
    lines = [f"BetterMarkItDown {report['version']}  |  Python {report['python']}  |  "
             f"{report['platform']}", ""]
    active = report["active"]
    lines.append(f"Provider in use: {active.get('provider') or 'none'}"
                 + (f" ({active['base_url']})" if active.get("base_url") else "")
                 + (f" - {active['error']}" if active.get("error") else ""))
    lines.append("Keys:")
    for provider, source in report["keys"].items():
        lines.append(f"  {provider:<11} {('set, from ' + source) if source else 'not set'}")
    lines.append("Optional parts:")
    for name, present in report["optional"].items():
        lines.append(f"  {name:<30} {'yes' if present else 'no'}")
    system = report["system"]
    gpus = ", ".join(g["name"] for g in system["gpus"]) or "none found"
    lines += ["System:",
              f"  {system['cpu'] or 'unknown processor'}, {system['ram_gb']:g} GB memory, "
              f"graphics: {gpus}",
              f"  Suggested local model: {report['suggested_local_model'] or 'none'}"]
    lines += [f"  ! {w}" for w in report["warnings"]]
    lines += [f"  Note: {n}" for n in system["notes"]]
    return "\n".join(lines)
