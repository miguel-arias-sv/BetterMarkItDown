"""API keys in the operating system's own password store.

Windows Credential Manager, the macOS Keychain, or the Secret Service on Linux,
through the `keyring` package. A key stored here never sits in a plain file. An
environment variable or a .env file still works, and wins, so CI and scripts
need no store at all.
"""

from __future__ import annotations

SERVICE = "bettermarkitdown"


class KeyStoreUnavailable(RuntimeError):
    """This machine has no usable password store (common on headless Linux)."""


def _backend():
    import keyring
    return keyring


def stored_key(provider_id: str) -> str | None:
    """The key saved for a provider, or None. Never raises: no store means no key."""
    try:
        return _backend().get_password(SERVICE, provider_id) or None
    except Exception:
        return None


def store_key(provider_id: str, key: str) -> None:
    key = key.strip()
    if not key:
        raise ValueError("Empty key.")
    try:
        _backend().set_password(SERVICE, provider_id, key)
    except Exception as exc:
        raise KeyStoreUnavailable(
            f"Could not save to this computer's password store ({exc}). Set the key in "
            "an environment variable or a .env file instead.") from exc


def forget_key(provider_id: str) -> bool:
    """Delete a saved key. True if there was one."""
    if stored_key(provider_id) is None:
        return False
    try:
        _backend().delete_password(SERVICE, provider_id)
    except Exception as exc:
        raise KeyStoreUnavailable(f"Could not remove the key: {exc}") from exc
    return True
