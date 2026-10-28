"""Which AI services the tool can use, as data.

Adding a service is adding a `Provider` entry here (and a test), never a change to
the engine: every entry speaks either the OpenAI chat-completions protocol, which
most services and every local server offer, or Anthropic's own Messages API.

Prices are USD per 1M tokens, from the provider's own pages, with the date they
were checked. A model missing from `models` still works; the cost meter just
reports $0 for it until you pass --price-in / --price-out.

`summary` and `model_notes` are deliberately rough, plain-language expectations
for a person choosing in a menu: what each is good at and where it falls short.
They say "untested here" until a model has actually converted pages with this tool.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .base import DailyQuotaExceeded, RateLimited, Reply, Usage, VisionClient

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
OLLAMA_BASE_URL = "http://localhost:11434/v1"


@dataclass(frozen=True)
class Provider:
    id: str
    name: str                          # what a person sees in a menu
    protocol: str                      # "openai" or "anthropic"
    base_url: str | None               # None: the user supplies it (custom)
    key_env: tuple[str, ...] = ()      # environment variables holding its key, in order
    key_url: str = ""                  # where to create a key
    key_steps: tuple[str, ...] = ()    # plain-language guide to getting one
    default_model: str | None = None   # None: pick from the live model list
    models: dict[str, tuple[float, float]] = field(default_factory=dict)
    prices_checked: str = ""
    needs_key: bool = True
    local: bool = False
    free_tier: bool = False
    pip_extra: str | None = None       # optional dependency this provider needs
    summary: str = ""                  # one line: what to expect from this provider
    model_notes: dict[str, str] = field(default_factory=dict)
    # Request quirks for OpenAI-protocol servers; the client also learns them from
    # a server's 400 replies, so these only save a wasted first call.
    token_param: str = "max_tokens"
    send_temperature: bool = True


PROVIDERS: dict[str, Provider] = {p.id: p for p in (
    Provider(
        id="gemini", name="Google Gemini", protocol="openai", base_url=GEMINI_BASE_URL,
        key_env=("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        key_url="https://aistudio.google.com/apikey",
        key_steps=(
            "Open Google AI Studio (link below) and sign in with a Google account.",
            "Click 'Create API key'. The free tier needs no card; link billing later for "
            "higher limits.",
            "Copy the key and paste it here.",
        ),
        default_model="gemini-3.6-flash",
        # https://ai.google.dev/gemini-api/docs/pricing. The 3.x Flash rates are
        # promotional through 2026-12-31 and double on 2027-01-01.
        models={
            "gemini-3.8-flash":      (0.75, 3.75),
            "gemini-3.6-flash":      (0.75, 3.75),
            "gemini-3.5-flash":      (1.50, 9.00),
            "gemini-3.5-flash-lite": (0.30, 2.50),
            "gemini-3.1-flash-lite": (0.30, 2.50),
            "gemini-2.5-flash":      (0.30, 2.50),
        },
        prices_checked="2026-09-21",
        free_tier=True,
        summary="The tool was built and measured on it. Free tier to try; it refuses some "
                "pages of published books (copyright filter), which go to local OCR.",
        model_notes={
            "gemini-3.6-flash": "The measured default: about $0.003 a page, strong on scans, "
                                "tables and maths.",
            "gemini-3.8-flash": "Newer Flash at the same price; untested here.",
            "gemini-3.5-flash": "Twice the price of 3.6 for no gain measured here.",
            "gemini-3.5-flash-lite": "Cheapest Gemini; expect more slips in dense maths and "
                                     "small print.",
            "gemini-3.1-flash-lite": "Cheap and older; fine for clean text, weaker on "
                                     "notation.",
            "gemini-2.5-flash": "Older generation; a fallback if a newer model misbehaves.",
        },
    ),
    Provider(
        id="openai", name="OpenAI (ChatGPT models)", protocol="openai",
        base_url="https://api.openai.com/v1",
        key_env=("OPENAI_API_KEY",),
        key_url="https://platform.openai.com/api-keys",
        key_steps=(
            "A ChatGPT Plus or Pro subscription does not include API access; the API is "
            "billed separately.",
            "Open the OpenAI platform (link below), sign in, and add a payment method "
            "under Billing.",
            "Create a new secret key, copy it (it is shown once) and paste it here.",
        ),
        default_model="gpt-5.4-mini",
        # https://openai.com/index/introducing-gpt-5-4-mini-and-nano/ (both take images)
        models={
            "gpt-5.4-mini": (0.75, 4.50),
            "gpt-5.4-nano": (0.20, 1.25),
        },
        prices_checked="2026-10-27",
        summary="Widely used, reliable service; untested here, so convert a few pages first.",
        model_notes={
            "gpt-5.4-mini": "Balanced; list price close to Gemini Flash, though reasoning "
                            "tokens can add to it. Untested here.",
            "gpt-5.4-nano": "Cheapest OpenAI option; expect more mistakes on maths and "
                            "complex layouts. Untested here.",
        },
        # GPT-5 models refuse `max_tokens` and any temperature but the default.
        token_param="max_completion_tokens",
        send_temperature=False,
    ),
    Provider(
        id="anthropic", name="Anthropic (Claude)", protocol="anthropic",
        base_url="https://api.anthropic.com",
        key_env=("ANTHROPIC_API_KEY",),
        key_url="https://console.anthropic.com/settings/keys",
        key_steps=(
            "A Claude Pro or Max subscription does not include API access; the API is "
            "billed separately.",
            "Open the Claude Console (link below), sign in, and buy credits under Billing.",
            "Create a key, copy it (it is shown once) and paste it here.",
        ),
        default_model="claude-opus-5-5",
        # Anthropic's published rates; Haiku's apply to prompts up to 100K tokens.
        models={
            "claude-opus-5-5":   (4.00, 20.00),
            "claude-sonnet-5-5": (2.00, 10.00),
            "claude-haiku-5-5":  (0.10, 0.50),
        },
        prices_checked="2026-10-06",
        pip_extra="anthropic",
        summary="Strong at reading difficult pages; the larger models cost more. Untested "
                "here, so convert a few pages first.",
        model_notes={
            "claude-opus-5-5": "Most capable Claude, for hard pages (dense maths, messy "
                               "scans); roughly 5-6x Gemini Flash per page. Untested here.",
            "claude-sonnet-5-5": "Half Opus's price; a sensible middle ground. Untested here.",
            "claude-haiku-5-5": "The cheapest model in this list; fine for clean text, "
                                "expect slips on dense notation. Untested here.",
        },
    ),
    Provider(
        id="kimi", name="Moonshot Kimi", protocol="openai",
        base_url="https://api.moonshot.ai/v1",
        key_env=("MOONSHOT_API_KEY", "KIMI_API_KEY"),
        key_url="https://platform.kimi.ai",
        key_steps=(
            "Open the Kimi platform (link below), sign in, and add credit.",
            "Create an API key, copy it and paste it here.",
            "Keys from the China-mainland platform use https://api.moonshot.cn/v1 instead; "
            "choose 'Custom' for those.",
        ),
        summary="Pick a vision model from its list; prices unverified, so set "
                "--price-in / --price-out for a real cost figure.",
        # No default and no prices: Kimi's pricing page did not publish figures we
        # could verify, and its K2 models retire at the end of 2026. Pick a vision
        # model from the live list.
    ),
    Provider(
        id="openrouter", name="OpenRouter (many models, one key)", protocol="openai",
        base_url="https://openrouter.ai/api/v1",
        key_env=("OPENROUTER_API_KEY",),
        key_url="https://openrouter.ai/keys",
        key_steps=(
            "Open OpenRouter (link below), sign in, and add credit.",
            "Create a key, copy it and paste it here.",
            "Pick a model that accepts images; each model's page lists its price.",
        ),
        default_model="qwen/qwen3-vl-8b-instruct",
        summary="One key for hundreds of models; quality and data handling vary by model, "
                "so check each model's page.",
    ),
    Provider(
        id="ollama", name="Ollama (on this computer)", protocol="openai",
        base_url=OLLAMA_BASE_URL, default_model="qwen3-vl:8b-instruct",
        needs_key=False, local=True,
        summary="Private, free and unlimited. Slower, and small models make more mistakes "
                "in maths and complex layouts.",
    ),
    Provider(
        id="custom", name="Other OpenAI-compatible server", protocol="openai",
        base_url=None, key_env=("BMID_API_KEY", "OPENAI_API_KEY"), needs_key=False,
        summary="LM Studio, llama.cpp, vLLM or any other server that speaks the OpenAI "
                "protocol; the model must accept images.",
    ),
)}

DEFAULT_PROVIDER = "gemini"


def get_provider(provider_id: str) -> Provider:
    try:
        return PROVIDERS[provider_id.strip().lower()]
    except KeyError:
        known = ", ".join(PROVIDERS)
        raise ValueError(f"Unknown provider '{provider_id}'. Known: {known}") from None


def infer_provider(base_url: str) -> Provider:
    """The provider an endpoint belongs to; `custom` when it is none of ours."""
    wanted = base_url.strip().rstrip("/").lower()
    for provider in PROVIDERS.values():
        if provider.base_url and provider.base_url.rstrip("/").lower() == wanted:
            return provider
    if wanted.endswith((":11434/v1", ":11434")):
        return PROVIDERS["ollama"]
    if "api.anthropic.com" in wanted:
        return PROVIDERS["anthropic"]
    return PROVIDERS["custom"]


def known_price(model: str) -> tuple[float, float] | None:
    """Model ids are unique across providers, so one lookup serves them all."""
    for provider in PROVIDERS.values():
        if model in provider.models:
            return provider.models[model]
    return None


def model_note(model: str) -> str:
    for provider in PROVIDERS.values():
        if model in provider.model_notes:
            return provider.model_notes[model]
    return ""


def make_client(provider: Provider, api_key: str | None, base_url: str | None = None,
                timeout: float = 180.0) -> VisionClient:
    """A client for `provider`. `base_url` overrides the provider's own endpoint."""
    url = base_url or provider.base_url
    if provider.protocol == "anthropic":
        from .anthropic_sdk import AnthropicClient
        return AnthropicClient(api_key=api_key, base_url=url, timeout=timeout)
    if not url:
        raise ValueError(f"{provider.name} needs an endpoint: pass --base-url.")
    from .openai_compat import OpenAICompatible
    return OpenAICompatible(provider, api_key=api_key, base_url=url, timeout=timeout)


def as_vision_client(client) -> VisionClient:
    """Accept a raw `openai.OpenAI` client too, as the library did before 1.5."""
    if hasattr(client, "describe"):
        return client
    from .openai_compat import OpenAICompatible
    return OpenAICompatible(PROVIDERS["custom"], sdk=client)


__all__ = [
    "DEFAULT_PROVIDER", "GEMINI_BASE_URL", "OLLAMA_BASE_URL", "PROVIDERS",
    "DailyQuotaExceeded", "Provider", "RateLimited", "Reply", "Usage", "VisionClient",
    "as_vision_client", "get_provider", "infer_provider", "known_price", "make_client",
    "model_note",
]
