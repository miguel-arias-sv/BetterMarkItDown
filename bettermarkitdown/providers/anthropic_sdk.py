"""Claude, through Anthropic's own SDK (`pip install "bettermarkitdown[anthropic]"`).

Two things differ from the OpenAI protocol and matter here:

- The current models think on every request and the thinking cannot be switched
  off; `effort` sets how much. Thinking is billed as output, and transcribing a
  page needs little of it, so `--reasoning none` asks for the lowest effort.
- No sampling parameters: the API refuses `temperature` on every model.
"""

from __future__ import annotations

import base64

from .base import RateLimited, Reply, Usage

# Our --reasoning choices to Anthropic effort levels. "default" sends none.
EFFORT = {"none": "low", "low": "low", "medium": "medium", "high": "high"}

# Models that accept the server-side refusal fallback: when a safety classifier
# declines a request, Anthropic reruns it on another model within the same call.
FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"

STOP_REASONS = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length",
                "refusal": "content_filter"}


class AnthropicClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None,
                 timeout: float = 180.0, sdk=None):
        if sdk is None:
            try:
                import anthropic
            except ImportError:
                raise RuntimeError('Claude needs Anthropic\'s SDK: '
                                   'pip install "bettermarkitdown[anthropic]"') from None
            sdk = anthropic.Anthropic(api_key=api_key, base_url=base_url, timeout=timeout)
        self.sdk = sdk
        self._no_effort: set[str] = set()      # models that refused output_config.effort

    def describe(self, png: bytes, prompt: str, *, model: str, max_tokens: int,
                 reasoning: str = "none") -> Reply:
        import anthropic

        params = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                 "data": base64.b64encode(png).decode("ascii")}},
                    {"type": "text", "text": prompt},
                ],
            }],
        }
        effort = EFFORT.get(reasoning)
        if effort and model not in self._no_effort:
            params["output_config"] = {"effort": effort}

        try:
            if model in FALLBACK_MODELS:
                response = self.sdk.beta.messages.create(betas=[FALLBACK_BETA],
                                                         fallbacks="default", **params)
            else:
                response = self.sdk.messages.create(**params)
        except anthropic.RateLimitError as exc:
            raise RateLimited(str(exc), _retry_after(exc)) from exc
        except anthropic.BadRequestError as exc:
            if "effort" in str(exc) and "output_config" in params:
                self._no_effort.add(model)       # an older model: use its default
                return self.describe(png, prompt, model=model, max_tokens=max_tokens,
                                     reasoning=reasoning)
            raise

        text = "".join(block.text for block in response.content
                       if getattr(block, "type", "") == "text")
        stop = str(response.stop_reason or "")
        reason = STOP_REASONS.get(stop, stop)
        details = getattr(response, "stop_details", None)
        if reason == "content_filter" and getattr(details, "category", None):
            reason += f": {details.category}"

        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0   # thinking included
        return Reply(text=text, finish_reason=reason,
                     usage=Usage(prompt_tokens=prompt_tokens, completion_tokens=output_tokens,
                                 total_tokens=prompt_tokens + output_tokens))

    def list_models(self) -> list[str]:
        return sorted(m.id for m in self.sdk.models.list())


def _retry_after(exc) -> float:
    try:
        return float(exc.response.headers.get("retry-after", 0))
    except (AttributeError, TypeError, ValueError):
        return 0.0
