"""Providers, keys and the adapters that talk to each kind of server. All offline."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from bettermarkitdown.config import Options, find_api_key, get_api_key, resolve_endpoint
from bettermarkitdown.providers import (
    GEMINI_BASE_URL,
    PROVIDERS,
    DailyQuotaExceeded,
    RateLimited,
    get_provider,
    infer_provider,
)


@pytest.fixture
def no_dotenv(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)          # no .env above this folder to pick keys up from


# --- the registry -------------------------------------------------------------

def test_every_provider_is_complete():
    for spec in PROVIDERS.values():
        assert spec.protocol in ("openai", "anthropic"), spec.id
        if spec.needs_key:
            assert spec.key_env and spec.key_url.startswith("https://"), spec.id
            assert spec.key_steps, f"{spec.id} needs a how-to-get-a-key guide"
        if spec.models:
            assert spec.prices_checked, f"{spec.id} prices need the date they were checked"
            assert spec.default_model in spec.models, spec.id
        assert spec.summary, f"{spec.id} needs a one-line summary of what to expect"
        missing = set(spec.models) - set(spec.model_notes)
        assert not missing, f"{spec.id}: say what these are good and bad at: {missing}"


def test_endpoints_map_back_to_their_provider():
    assert infer_provider(GEMINI_BASE_URL).id == "gemini"
    assert infer_provider("https://api.openai.com/v1/").id == "openai"
    assert infer_provider("http://127.0.0.1:11434/v1").id == "ollama"
    assert infer_provider("http://localhost:8080/v1").id == "custom"
    with pytest.raises(ValueError, match="Known"):
        get_provider("nope")


# --- keys -----------------------------------------------------------------------

def test_a_key_is_only_ever_sent_to_its_own_provider(monkeypatch, no_dotenv):
    """Before 1.5 the Gemini key was read first whatever the endpoint, so pointing
    the tool at OpenAI with both keys set sent the Google key to OpenAI's server."""
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")
    monkeypatch.setenv("BMID_BASE_URL", "https://api.openai.com/v1")

    provider, _ = resolve_endpoint()
    assert provider.id == "openai"
    assert get_api_key(provider=provider.id) == "openai-secret"
    assert get_api_key(provider="openrouter") is None
    assert get_api_key(provider="anthropic") is None


def test_environment_beats_the_password_store(monkeypatch, no_dotenv, isolated_keys):
    from bettermarkitdown import credentials

    credentials.store_key("anthropic", "  stored-key \n")
    assert find_api_key("anthropic") == ("stored-key", "password store")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    assert find_api_key("anthropic") == ("env-key", "ANTHROPIC_API_KEY")

    assert credentials.forget_key("anthropic") is True
    assert credentials.forget_key("anthropic") is False
    assert isolated_keys.saved == {}


def test_no_password_store_means_no_key_not_a_crash(monkeypatch, no_dotenv):
    from bettermarkitdown import credentials

    class Broken:
        def get_password(self, *_):
            raise RuntimeError("No recommended backend was available")

        set_password = get_password

    monkeypatch.setattr(credentials, "_backend", lambda: Broken())
    assert get_api_key(provider="openai") is None
    with pytest.raises(credentials.KeyStoreUnavailable, match="environment variable"):
        credentials.store_key("openai", "sk-1")


def test_endpoint_resolution_order(monkeypatch, no_dotenv):
    assert resolve_endpoint()[0].id == "gemini"                  # the old default stays
    assert resolve_endpoint("anthropic") == (PROVIDERS["anthropic"],
                                             "https://api.anthropic.com")
    assert resolve_endpoint(None, "http://localhost:11434/v1")[0].id == "ollama"
    assert resolve_endpoint("openai", "http://proxy.local/v1") == (PROVIDERS["openai"],
                                                                    "http://proxy.local/v1")
    monkeypatch.setenv("BMID_PROVIDER", "kimi")
    assert resolve_endpoint()[0].id == "kimi"
    with pytest.raises(ValueError, match="endpoint"):
        resolve_endpoint("custom")


def test_prices_come_from_the_registry_for_every_provider(tmp_path: Path):
    common = dict(pdf=tmp_path / "x.pdf", output=tmp_path / "x.md")
    assert Options(**common, model="claude-haiku-5-5", provider="anthropic").prices() == (0.10,
                                                                                         0.50)
    assert Options(**common, model="gpt-5.4-mini", provider="openai").prices() == (0.75, 4.50)
    assert Options(**common, model="kimi-unknown", provider="kimi").prices() == (0.0, 0.0)


def test_conversion_refuses_to_start_without_a_key(tmp_path: Path):
    from bettermarkitdown.core import convert

    opts = Options(pdf=tmp_path / "x.pdf", output=tmp_path / "x.md", provider="openai",
                   base_url="https://api.openai.com/v1", model="gpt-5.4-mini")
    with pytest.raises(RuntimeError, match="key set openai"):
        convert(opts)


# --- the OpenAI-protocol client --------------------------------------------------

def _openai_sdk(handler):
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=handler)))


def _completion(text="ok", reason="stop"):
    choice = SimpleNamespace(message=SimpleNamespace(content=text), finish_reason=reason)
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=20)
    return SimpleNamespace(choices=[choice], usage=usage)


def test_openai_gets_the_parameters_gpt5_accepts():
    from bettermarkitdown.providers.openai_compat import OpenAICompatible

    seen = []
    client = OpenAICompatible(PROVIDERS["openai"],
                              sdk=_openai_sdk(lambda **kw: seen.append(kw) or _completion()))
    reply = client.describe(b"png", "p", model="gpt-5.4-mini", max_tokens=4096)

    assert seen[0]["max_completion_tokens"] == 4096 and "max_tokens" not in seen[0]
    assert "temperature" not in seen[0]
    assert reply.text == "ok" and reply.usage.total_tokens == 20


def test_a_parameter_the_server_refuses_is_dropped_once_and_remembered():
    from bettermarkitdown.providers.openai_compat import OpenAICompatible

    seen = []

    def create(**kwargs):
        seen.append(kwargs)
        if "reasoning_effort" in kwargs:
            raise RuntimeError("Unrecognized request argument supplied: reasoning_effort")
        if "temperature" in kwargs:
            raise RuntimeError("'temperature' does not support 0.0 with this model")
        return _completion()

    client = OpenAICompatible(PROVIDERS["custom"], sdk=_openai_sdk(create))
    client.describe(b"png", "p", model="m", max_tokens=100)
    client.describe(b"png", "p", model="m", max_tokens=100)
    assert len(seen) == 4                      # two refusals, then one call per page


def test_gemini_daily_quota_and_rate_limits_become_typed_errors():
    from bettermarkitdown.providers.openai_compat import OpenAICompatible

    def per_day(**_):
        raise RuntimeError("429 GenerateRequestsPerDayPerProjectPerModel exceeded")

    with pytest.raises(DailyQuotaExceeded):
        OpenAICompatible(PROVIDERS["gemini"], sdk=_openai_sdk(per_day)).describe(
            b"png", "p", model="m", max_tokens=1)

    class TooMany(Exception):
        status_code = 429
        response = SimpleNamespace(headers={"retry-after": "7"})

    def busy(**_):
        raise TooMany("slow down")

    with pytest.raises(RateLimited) as caught:
        OpenAICompatible(PROVIDERS["openai"], sdk=_openai_sdk(busy)).describe(
            b"png", "p", model="m", max_tokens=1)
    assert caught.value.retry_after == 7.0


# --- Claude -----------------------------------------------------------------------

class FakeMessages:
    def __init__(self, response=None, error=None):
        self.calls = []
        self.response, self.error = response, error

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


def _claude(stop_reason="end_turn", text="Page text.", category=None):
    return SimpleNamespace(
        content=[SimpleNamespace(type="thinking", thinking=""),
                 SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        stop_details=SimpleNamespace(category=category) if category else None,
        usage=SimpleNamespace(input_tokens=1500, output_tokens=600))


def _anthropic_client(response=None, error=None):
    from bettermarkitdown.providers.anthropic_sdk import AnthropicClient

    plain, beta = FakeMessages(response, error), FakeMessages(response, error)
    sdk = SimpleNamespace(messages=plain, beta=SimpleNamespace(messages=beta))
    return AnthropicClient(sdk=sdk), plain, beta


def test_claude_request_shape_and_reply():
    pytest.importorskip("anthropic")
    client, plain, beta = _anthropic_client(_claude())
    reply = client.describe(b"\x89PNG", "Transcribe.", model="claude-opus-5-5", max_tokens=4096)

    call = beta.calls[0]                       # refusal fallback is on for Opus
    assert call["fallbacks"] == "default" and call["betas"] == [
        "server-side-fallback-2026-07-01"]
    assert call["output_config"] == {"effort": "low"}       # --reasoning none
    assert "temperature" not in call and "thinking" not in call
    image, text = call["messages"][0]["content"]
    assert image["type"] == "image" and image["source"]["media_type"] == "image/png"
    assert text == {"type": "text", "text": "Transcribe."}
    assert reply.text == "Page text." and reply.finish_reason == "stop"
    assert reply.usage.prompt_tokens == 1500 and reply.usage.total_tokens == 2100

    client.describe(b"png", "p", model="claude-haiku-5-5", max_tokens=10)
    assert len(plain.calls) == 1 and "fallbacks" not in plain.calls[0]   # Haiku has none


def test_claude_stop_reasons_map_onto_what_the_engine_understands():
    pytest.importorskip("anthropic")
    from bettermarkitdown.core import cut_off

    cut = _anthropic_client(_claude("max_tokens"))[0].describe(
        b"p", "p", model="claude-haiku-5-5", max_tokens=1)
    assert cut_off(cut.finish_reason)
    refused = _anthropic_client(_claude("refusal", "", "frontier_llm"))[0].describe(
        b"p", "p", model="claude-haiku-5-5", max_tokens=1)
    assert refused.finish_reason == "content_filter: frontier_llm"


def test_claude_rate_limit_carries_the_servers_wait():
    anthropic = pytest.importorskip("anthropic")
    import httpx2

    response = httpx2.Response(429, headers={"retry-after": "12"},
                               request=httpx2.Request("POST", "https://api.anthropic.com"))
    error = anthropic.RateLimitError("rate limited", response=response, body=None)
    client = _anthropic_client(error=error)[0]
    with pytest.raises(RateLimited) as caught:
        client.describe(b"p", "p", model="claude-haiku-5-5", max_tokens=1)
    assert caught.value.retry_after == 12.0


def test_engine_retries_after_the_servers_wait(tmp_path: Path, monkeypatch):
    from bettermarkitdown import core
    from bettermarkitdown.providers import Reply

    class Flaky:
        calls = 0

        def describe(self, png, prompt, **_):
            Flaky.calls += 1
            if Flaky.calls == 1:
                raise RateLimited("busy", retry_after=9)
            return Reply("Done.", "stop")

    waits = []
    monkeypatch.setattr(core.time, "sleep", waits.append)
    out = core.describe_image(Flaky(), "m", b"png", "p", cache=core.Cache(tmp_path / "c.json"),
                              limiter=core.RateLimiter(0))
    assert out == "Done." and waits == [9]


# --- the command line ----------------------------------------------------------------

def test_key_commands_store_redact_and_forget(monkeypatch, capsys, no_dotenv, isolated_keys):
    import io

    from bettermarkitdown.cli import main

    monkeypatch.setattr("sys.stdin", io.StringIO("sk-ant-abcdefghijklmnop\n"))
    assert main(["key", "set", "anthropic", "--stdin"]) == 0
    assert isolated_keys.saved == {("bettermarkitdown", "anthropic"): "sk-ant-abcdefghijklmnop"}

    assert main(["key", "status"]) == 0
    out = capsys.readouterr().out
    assert "sk-ant...mnop" in out and "abcdefghijkl" not in out

    assert main(["providers"]) == 0
    assert "key from password store" in capsys.readouterr().out

    assert main(["key", "forget", "anthropic"]) == 0
    assert isolated_keys.saved == {}


def test_cli_without_a_key_names_the_command_that_fixes_it(capsys, no_dotenv, tmp_path):
    from bettermarkitdown.cli import main

    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    assert main([str(pdf), "--provider", "openai"]) == 1
    assert "bettermarkitdown key set openai" in capsys.readouterr().err


def test_forget_all_removes_every_saved_key_and_only_those(isolated_keys, capsys):
    from bettermarkitdown import cli, credentials

    credentials.store_key("openai", "sk-proj-abcdefghijklmnop")
    credentials.store_key("gemini", "AIzaSyabcdefghijklmnop")
    assert cli.main(["key", "forget", "all"]) == 0
    assert isolated_keys.saved == {}
    assert "Google Gemini" in capsys.readouterr().out
    assert cli.main(["key", "forget", "all"]) == 0
    assert "No keys were saved" in capsys.readouterr().out
