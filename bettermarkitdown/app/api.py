"""What the setup page can ask for. Each handler takes the app and the request's
JSON (or query) and returns JSON. Keys only ever leave here redacted."""

from __future__ import annotations

import importlib.util
import subprocess
from dataclasses import asdict

from .. import __version__, credentials, formats, settings
from ..config import find_api_key, get_model, redact, resolve_endpoint
from ..core import list_models
from ..local import CATALOG, describe, ollama, recommend
from ..providers import PROVIDERS, get_provider
from ..system import detect
from .server import HTTPError, job_json

# Rough tokens for one page, to show a price per page next to each model: a page
# image plus the prompt in, a transcription out. Real pages vary a lot.
PAGE_TOKENS_IN, PAGE_TOKENS_OUT = 1500, 600


def _provider_json(spec) -> dict:
    key, source = find_api_key(spec.id) if (spec.needs_key or spec.key_env) else (None, "")
    models = [{"id": name, "price_in": p[0], "price_out": p[1],
               "per_page": round((PAGE_TOKENS_IN * p[0] + PAGE_TOKENS_OUT * p[1]) / 1e6, 4),
               "note": spec.model_notes.get(name, "")} for name, p in spec.models.items()]
    return {
        "id": spec.id, "name": spec.name, "summary": spec.summary,
        "needs_key": spec.needs_key, "local": spec.local, "free_tier": spec.free_tier,
        "key_url": spec.key_url, "key_steps": list(spec.key_steps),
        "default_model": spec.default_model or "", "models": models,
        "key_source": source, "key_hint": redact(key) if key else "",
        "ready": not spec.pip_extra or importlib.util.find_spec(spec.pip_extra) is not None,
    }


def state(app, _body) -> dict:
    try:
        provider, _url = resolve_endpoint()
        active = {"provider": provider.id, "model": get_model(None, provider.id)}
    except ValueError as exc:
        active = {"provider": "", "model": "", "error": str(exc)}
    return {
        "version": __version__,
        "settings": asdict(settings.load()),
        "active": active,
        "providers": [_provider_json(p) for p in PROVIDERS.values()],
        "office": {"word": formats.office_installed("Word"),
                   "powerpoint": formats.office_installed("PowerPoint"),
                   "libreoffice": bool(formats.find_soffice()),
                   "can_install_libreoffice": bool(formats.libreoffice_install_command())},
    }


def ping(app, _body) -> dict:
    return {"ok": True}


def save_settings(app, body) -> dict:
    allowed = {"audience", "help_level", "provider", "model", "setup_done"}
    unknown = set(body) - allowed
    if unknown:
        raise ValueError(f"unknown setting(s): {', '.join(sorted(unknown))}")
    return {"settings": asdict(settings.update(**body))}


def save_key(app, body) -> dict:
    """Check the key with a free request (listing models), then store it."""
    spec = get_provider(str(body.get("provider", "")))
    key = str(body.get("key", "")).strip()
    if not key:
        raise ValueError("Paste the key first.")
    if not spec.base_url:
        raise ValueError(f"{spec.name} needs an address; set it up from the command line.")
    if spec.pip_extra and importlib.util.find_spec(spec.pip_extra) is None:
        raise ValueError(f'{spec.name} needs an add-on: pip install "bettermarkitdown'
                         f'[{spec.pip_extra}]", then try again.')
    try:
        models = list_models(key, spec.base_url, provider=spec.id)
    except Exception as exc:
        # Some providers quote part of a bad key back; never echo it in full.
        message = str(exc).replace(key, redact(key))
        raise HTTPError(400, f"{spec.name} did not accept this key: {message[:300]}") from None
    credentials.store_key(spec.id, key)
    return {"ok": True, "hint": redact(key), "models": len(models)}


def forget_key(app, body) -> dict:
    spec = get_provider(str(body.get("provider", "")))
    return {"removed": credentials.forget_key(spec.id)}


def models(app, body) -> dict:
    """The models a provider offers, live, for providers without a curated list."""
    spec = get_provider(str(body.get("provider", "")))
    key = find_api_key(spec.id)[0]
    if spec.needs_key and not key:
        raise ValueError(f"Save a {spec.name} key first.")
    return {"models": list_models(key, spec.base_url or "", provider=spec.id)}


def system(app, _body) -> dict:
    profile = detect()
    rec = recommend(profile)
    running = ollama.version()
    installed = ollama.installed() if running else []
    return {
        "system": profile.to_dict(),
        "recommendation": rec.to_dict(),
        "report": describe(profile, rec),
        "catalog": [asdict(m) for m in CATALOG],
        "ollama": {"program": ollama.find(), "running": running, "models": installed,
                   "can_install": bool(ollama.install_command())},
    }


def _catalog_model(tag: str):
    for model in CATALOG:
        if model.tag == tag:
            return model
    raise ValueError(f"Unknown local model '{tag}'.")


def local_install(app, _body) -> dict:
    def work(job):
        if ollama.ensure_running():
            job.message = "Ollama is already running."
            return {"version": ollama.version()}
        job.message = "Installing Ollama. Windows may ask for permission."
        if not ollama.find() and not ollama.install():
            raise RuntimeError(f"The installer did not finish. Install Ollama from "
                               f"{ollama.DOWNLOAD_URL}, then come back.")
        job.message = "Starting Ollama..."
        version = ollama.ensure_running()
        if not version:
            raise RuntimeError("Ollama is installed but did not start. Open it from the Start "
                               "menu, then try again.")
        return {"version": version}

    return job_json(app.jobs.start("local-install", work))


def local_pull(app, body) -> dict:
    model = _catalog_model(str(body.get("model", "")))

    def work(job):
        if not ollama.has(model.tag):
            job.message = f"Downloading {model.name}"

            def progress(status, done, total):
                job.done, job.total = done, total
                if not total:
                    job.message = status
            ollama.pull(model.tag, progress)
        job.message = "Preparing the model..."
        return {"name": ollama.with_context(model.tag)}

    return job_json(app.jobs.start("local-pull", work))


def local_test(app, body) -> dict:
    model = _catalog_model(str(body.get("model", "")))

    def work(job):
        job.message = "Loading the model and reading a test page..."
        result = ollama.speed_test(ollama.with_context(model.tag))
        return {"load_seconds": result.load_seconds, "page_seconds": result.page_seconds,
                "gpu_share": result.gpu_share, "read_ok": result.read_ok,
                "verdict": result.verdict()}

    return job_json(app.jobs.start("local-test", work))


def office_install(app, _body) -> dict:
    command = formats.libreoffice_install_command()
    if not command:
        raise ValueError(f"Install LibreOffice from {formats.LIBREOFFICE_URL}.")

    def work(job):
        job.message = "Installing LibreOffice. Windows will ask for permission."
        done = subprocess.run(command, capture_output=True, text=True, check=False)
        if not formats.find_soffice():
            raise RuntimeError(f"The installer did not finish ({done.returncode}). Install it "
                               f"from {formats.LIBREOFFICE_URL}.")
        return {"path": formats.find_soffice()}

    return job_json(app.jobs.start("office-install", work))


def job(app, body) -> dict:
    found = app.jobs.get(str(body.get("id", "")))
    if not found:
        raise HTTPError(404, "No such task.")
    return job_json(found)


def quit_app(app, _body) -> dict:
    app.stop()
    return {"ok": True}


ROUTES = {
    ("GET", "/api/state"): state,
    ("GET", "/api/ping"): ping,
    ("GET", "/api/system"): system,
    ("GET", "/api/models"): models,
    ("GET", "/api/jobs/"): job,
    ("POST", "/api/settings"): save_settings,
    ("POST", "/api/key"): save_key,
    ("POST", "/api/key/forget"): forget_key,
    ("POST", "/api/local/install"): local_install,
    ("POST", "/api/local/pull"): local_pull,
    ("POST", "/api/local/test"): local_test,
    ("POST", "/api/office/install"): office_install,
    ("POST", "/api/quit"): quit_app,
}
