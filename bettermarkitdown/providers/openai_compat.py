"""Any server that speaks OpenAI's chat-completions protocol.

That is Gemini (through its OpenAI endpoint), OpenAI itself, Kimi, OpenRouter, and
every local server: Ollama, llama.cpp, LM Studio, vLLM.
"""

from __future__ import annotations

import base64

from .base import DailyQuotaExceeded, RateLimited, Reply, Usage

# Words in a Gemini model id that mark it as not a vision chat model.
_GEMINI_SKIP = ("embedding", "tts", "live", "robotics")


class OpenAICompatible:
    def __init__(self, provider, api_key: str | None = None, base_url: str | None = None,
                 timeout: float = 180.0, sdk=None):
        if sdk is None:
            from openai import OpenAI
            # Local servers accept any non-empty key; the openai client demands one.
            sdk = OpenAI(api_key=api_key or "not-needed", base_url=base_url, timeout=timeout)
        self.sdk = sdk          # MarkItDown takes this too: it describes images with it
        self.provider = provider
        # Parameters a server has refused, per model, so each refusal costs one call.
        self._refused: dict[str, set[str]] = {}

    def describe(self, png: bytes, prompt: str, *, model: str, max_tokens: int,
                 reasoning: str = "none") -> Reply:
        url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
        refused = self._refused.setdefault(model, set())

        while True:
            kwargs = {
                "model": model,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": url}},
                    ],
                }],
            }
            token_param = self.provider.token_param
            if "max_tokens" in refused:
                token_param = "max_completion_tokens"
            kwargs[token_param] = max_tokens
            if self.provider.send_temperature and "temperature" not in refused:
                kwargs["temperature"] = 0.0
            if reasoning and reasoning != "default" and "reasoning_effort" not in refused:
                kwargs["reasoning_effort"] = reasoning

            try:
                response = self.sdk.chat.completions.create(**kwargs)
            except Exception as exc:
                message = str(exc)
                if "PerDay" in message:            # Gemini's per-day quota
                    raise DailyQuotaExceeded(message) from exc
                param = _refused_param(message, kwargs)
                if param and param not in refused:
                    refused.add(param)             # an older or stricter model: drop it
                    continue
                if getattr(exc, "status_code", None) == 429:
                    raise RateLimited(message, _retry_after_header(exc)) from exc
                raise

            choice = response.choices[0]
            return Reply(text=choice.message.content or "",
                         finish_reason=str(choice.finish_reason or ""),
                         usage=_usage(getattr(response, "usage", None)))

    def list_models(self) -> list[str]:
        names = [m.id.replace("models/", "") for m in self.sdk.models.list()]
        if self.provider.id != "gemini":
            # We cannot tell which of another server's models see images, so list
            # everything rather than filter to nothing.
            return sorted(names)
        return [n for n in names if "gemini" in n and not any(w in n for w in _GEMINI_SKIP)]


def _refused_param(message: str, sent: dict) -> str | None:
    """The request parameter a 400 complains about, if it is one we can drop."""
    if "reasoning_effort" in message and "reasoning_effort" in sent:
        return "reasoning_effort"
    if "temperature" in message and "temperature" in sent:
        return "temperature"
    if "max_completion_tokens" in message and "max_tokens" in sent:
        return "max_tokens"                    # use max_completion_tokens instead
    return None


def _retry_after_header(exc) -> float:
    try:
        return float(exc.response.headers.get("retry-after", 0))
    except (AttributeError, TypeError, ValueError):
        return 0.0


def _usage(raw) -> Usage | None:
    if raw is None:
        return None
    return Usage(prompt_tokens=getattr(raw, "prompt_tokens", 0) or 0,
                 completion_tokens=getattr(raw, "completion_tokens", 0) or 0,
                 total_tokens=getattr(raw, "total_tokens", 0) or 0)
