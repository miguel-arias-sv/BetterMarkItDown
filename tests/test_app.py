"""The setup page's server, over real HTTP on 127.0.0.1, with providers and Ollama
faked. Covers the safety rules as much as the features."""

from __future__ import annotations

import json

from apphttp import call, wait

from bettermarkitdown import settings

# --- safety ------------------------------------------------------------------------

def test_api_needs_the_launch_token(app):
    assert call(app, "GET", "/api/state", token=False)[0] == 403
    assert call(app, "GET", "/api/state")[0] == 200


def test_the_page_itself_needs_the_token_in_its_address(app):
    status, body, _ = call(app, "GET", "/", token=False, raw=True)
    assert status == 403 and b"bettermarkitdown app" in body
    status, body, headers = call(app, "GET", f"/?t={app.token}", token=False, raw=True)
    assert status == 200 and app.token.encode() in body and b"__TOKEN__" not in body
    assert "default-src 'self'" in headers["Content-Security-Policy"]


def test_other_hosts_and_other_sites_are_refused(app):
    """DNS rebinding arrives with a foreign Host; a forged form post with a foreign Origin."""
    assert call(app, "GET", "/api/state", host="evil.example:80")[0] == 403
    status, _ = call(app, "POST", "/api/settings", {"audience": "human"},
                     origin="https://evil.example")
    assert status == 403
    status, _ = call(app, "POST", "/api/settings", {"audience": "human"},
                     origin=f"http://127.0.0.1:{app.port}")
    assert status == 200


def test_only_the_page_files_are_served(app):
    assert call(app, "GET", "/app.js", token=False, raw=True)[0] == 200
    assert call(app, "GET", "/../pyproject.toml", token=False, raw=True)[0] == 404
    assert call(app, "GET", "/server.py", token=False, raw=True)[0] == 404


# --- keys and settings -----------------------------------------------------------------

def test_a_key_is_checked_stored_and_only_ever_returned_redacted(app, monkeypatch,
                                                                  isolated_keys):
    from bettermarkitdown.app import api

    seen = []
    monkeypatch.setattr(api, "list_models",
                        lambda key, url, provider=None: seen.append((key, provider)) or ["m1"])
    status, out = call(app, "POST", "/api/key",
                       {"provider": "openai", "key": "sk-proj-abcdefghijklmnopqrstuvwxyz"})
    assert status == 200 and out["hint"] == "sk-pro...wxyz"
    assert seen == [("sk-proj-abcdefghijklmnopqrstuvwxyz", "openai")]
    assert isolated_keys.saved[("bettermarkitdown", "openai")].startswith("sk-proj-")

    _, state = call(app, "GET", "/api/state")
    text = json.dumps(state)
    assert "abcdefghijklmnop" not in text
    openai = next(p for p in state["providers"] if p["id"] == "openai")
    assert openai["key_source"] == "password store" and openai["key_hint"] == "sk-pro...wxyz"


def test_a_rejected_key_is_not_saved_and_not_echoed(app, monkeypatch, isolated_keys):
    from bettermarkitdown.app import api

    def reject(key, url, provider=None):
        raise RuntimeError(f"Incorrect API key provided: {key}")

    monkeypatch.setattr(api, "list_models", reject)
    status, out = call(app, "POST", "/api/key",
                       {"provider": "openai", "key": "sk-wrong-0123456789abcdef"})
    assert status == 400 and "did not accept" in out["error"]
    assert "0123456789abcdef" not in out["error"]
    assert isolated_keys.saved == {}


def test_settings_are_checked_and_kept(app):
    assert call(app, "POST", "/api/settings", {"audience": "robots"})[0] == 400
    assert call(app, "POST", "/api/settings", {"colour": "blue"})[0] == 400
    status, out = call(app, "POST", "/api/settings",
                       {"audience": "both", "help_level": "automatic", "provider": "anthropic",
                        "model": "claude-haiku-5-5", "setup_done": True})
    assert status == 200 and out["settings"]["provider"] == "anthropic"
    assert settings.load().model == "claude-haiku-5-5"


def test_the_chosen_colours_are_kept_and_in_the_page_from_the_start(app):
    page = f"/?t={app.token}"
    assert b"data-theme" not in call(app, "GET", page, token=False, raw=True)[1]  # auto
    assert call(app, "POST", "/api/settings", {"theme": "purple"})[0] == 400
    assert call(app, "POST", "/api/settings", {"theme": "dark"})[0] == 200
    assert settings.load().theme == "dark"
    assert b'<html data-theme="dark" lang="en">' in call(app, "GET", page, token=False, raw=True)[1]


def test_the_saved_choice_becomes_the_default_for_every_run(monkeypatch, tmp_path):
    from bettermarkitdown.config import get_model, resolve_endpoint

    monkeypatch.chdir(tmp_path)
    settings.update(provider="anthropic", model="claude-haiku-5-5")
    provider, url = resolve_endpoint()
    assert provider.id == "anthropic" and url == "https://api.anthropic.com"
    assert get_model(None, "anthropic") == "claude-haiku-5-5"
    assert get_model(None, "openai") == "gpt-5.4-mini"         # saved model is per provider
    monkeypatch.setenv("BMID_PROVIDER", "openai")              # the environment still wins
    assert resolve_endpoint()[0].id == "openai"
    assert get_model("explicit", "anthropic") == "explicit"     # and so does a flag


def test_state_lists_every_provider_with_prices_per_page(app):
    _, state = call(app, "GET", "/api/state")
    ids = [p["id"] for p in state["providers"]]
    assert ids[:3] == ["gemini", "openai", "anthropic"] and "ollama" in ids
    gemini = state["providers"][0]
    flash = next(m for m in gemini["models"] if m["id"] == "gemini-3.6-flash")
    assert 0.001 < flash["per_page"] < 0.01 and flash["note"]
    assert gemini["key_steps"] and gemini["key_url"].startswith("https://")


# --- local models, as background jobs ----------------------------------------------------

def test_download_and_speed_test_run_as_jobs_the_page_can_follow(app, monkeypatch):
    from bettermarkitdown.local import ollama

    have: list[str] = []

    def pull(tag, progress):
        for done in (1, 2, 3):
            progress("pulling", done * 1_000, 3_000)
        have.append(tag)

    monkeypatch.setattr(ollama, "has", lambda tag, models=None: tag in have)
    monkeypatch.setattr(ollama, "pull", pull)
    monkeypatch.setattr(ollama, "with_context", lambda tag, num_ctx=0: "bmid-" + tag)
    monkeypatch.setattr(ollama, "speed_test", lambda name: ollama.SpeedTest(
        name, 8.0, 91.0, 0.0, True, "Chapter 3: Harvest Yields"))

    _, job = call(app, "POST", "/api/local/pull", {"model": "qwen3-vl:4b-instruct"})
    job = wait(app, job)
    assert job["status"] == "done" and job["done"] == job["total"] == 3_000
    assert job["result"]["name"] == "bmid-qwen3-vl:4b-instruct"

    _, job = call(app, "POST", "/api/local/test", {"model": "qwen3-vl:4b-instruct"})
    job = wait(app, job)
    assert job["result"]["read_ok"] and "91 s per page" in job["result"]["verdict"]

    status, out = call(app, "POST", "/api/local/pull", {"model": "not-in-the-catalog"})
    assert status == 400


def test_a_failed_job_reports_why(app, monkeypatch):
    from bettermarkitdown.local import ollama

    monkeypatch.setattr(ollama, "ensure_running", lambda: "")
    monkeypatch.setattr(ollama, "find", lambda: "")
    monkeypatch.setattr(ollama, "install", lambda: False)
    _, job = call(app, "POST", "/api/local/install", {})
    job = wait(app, job)
    assert job["status"] == "failed" and "ollama.com" in job["error"]


def test_quit_stops_the_server(app):
    assert call(app, "POST", "/api/quit", {})[0] == 200
    app.thread.join(5)
    assert not app.thread.is_alive()


def test_the_page_installs_the_skill_only_for_the_agent_clicked(app, monkeypatch):
    from bettermarkitdown import agent

    monkeypatch.setattr(agent.shutil, "which", lambda name: "x" if name == "claude" else None)
    _, out = call(app, "GET", "/api/agents")
    claude = next(a for a in out["agents"] if a["id"] == "claude")
    assert claude["detected"] and "claude mcp add" in out["mcp_instructions"]["claude"]
    status, out = call(app, "POST", "/api/agents/install", {"agents": ["claude"]})
    assert status == 200 and out["results"][0]["result"] == "installed"
    assert (agent.home() / ".claude/skills/bettermarkitdown/SKILL.md").is_file()
    assert not (agent.home() / ".agents").exists()
    assert call(app, "POST", "/api/agents/install", {"agents": ["nope"]})[0] == 400
    status, out = call(app, "POST", "/api/agents/install", {"agents": ["claude"], "remove": True})
    assert out["results"][0]["result"] == "removed"
