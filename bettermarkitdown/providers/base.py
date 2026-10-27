"""What the engine needs from a vision model, whoever serves it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class Usage:
    """Token counts in the shape `Meter.add` reads (the OpenAI one).

    Hidden thinking tokens are billed as output. OpenAI-protocol servers leave them
    out of completion_tokens but count them in total_tokens; Anthropic counts them
    in output_tokens. Either way, total - prompt is what was billed as output."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class Reply:
    text: str
    # Normalised: "stop", "length" (hit the output cap), or "content_filter..." (the
    # provider declined); anything else is passed through as the server sent it.
    finish_reason: str
    usage: Usage | None = None


class DailyQuotaExceeded(RuntimeError):
    """The key's per-day quota for this model is gone; waiting will not help."""


class RateLimited(RuntimeError):
    """Too many requests. `retry_after` is the server's own wait, in seconds, if it gave one."""

    def __init__(self, message: str, retry_after: float = 0.0):
        super().__init__(message)
        self.retry_after = retry_after


class VisionClient(Protocol):
    def describe(self, png: bytes, prompt: str, *, model: str, max_tokens: int,
                 reasoning: str = "none") -> Reply: ...

    def list_models(self) -> list[str]: ...
