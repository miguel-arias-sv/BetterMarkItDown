"""API keys in the operating system's own password store.

Windows Credential Manager, the macOS Keychain, or the Secret Service on Linux,
through the `keyring` package. A key stored here never sits in a plain file. An
environment variable or a .env file still works, and wins, so CI and scripts
need no store at all.

A provider can have several named keys, say a free one and a paid one, and one of
them is in use. The list of names lives in the store beside the keys and not in the
settings file, so `key forget all` finds every key even after the settings are gone.
A key saved before names existed is the one called Main, and stays where it was.

Which key is in use only ever changes when the person says so: adding a key does not
change it, and neither does forgetting one. Going from a free key to a paid one spends
money; going the other way can change what the provider may do with the documents.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

SERVICE = "bettermarkitdown"
MAIN = "Main"
TIERS = ("", "free", "paid")      # "": the person has not said; the tool cannot tell
_NAME = re.compile(r"\w[\w .-]{0,29}")


class KeyStoreUnavailable(RuntimeError):
    """This machine has no usable password store (common on headless Linux)."""


@dataclass(frozen=True)
class SavedKey:
    name: str
    tier: str = ""
    active: bool = False


def _backend():
    import keyring
    return keyring


def _read(account: str) -> str | None:
    """Never raises: no store means no key."""
    try:
        return _backend().get_password(SERVICE, account) or None
    except Exception:
        return None


def _write(account: str, value: str) -> None:
    try:
        _backend().set_password(SERVICE, account, value)
    except Exception as exc:
        raise KeyStoreUnavailable(
            f"Could not save to this computer's password store ({exc}). Set the key in "
            "an environment variable or a .env file instead.") from exc


def _delete(account: str) -> None:
    if _read(account) is None:
        return
    try:
        _backend().delete_password(SERVICE, account)
    except Exception as exc:
        raise KeyStoreUnavailable(f"Could not remove the key: {exc}") from exc


def _same(a: str, b: str) -> bool:
    return a.casefold() == b.casefold()


def _account(provider_id: str, name: str) -> str:
    return provider_id if _same(name, MAIN) else f"{provider_id}:{name.casefold()}"


def _load(provider_id: str) -> dict:
    """{"active": name, "keys": [{"name", "tier"}]}: "#" cannot be in a key's name."""
    raw = _read(f"{provider_id}:#keys")
    if raw:
        try:
            index = json.loads(raw)
            if isinstance(index, dict) and isinstance(index.get("keys"), list):
                return index
        except ValueError:
            pass
    if _read(provider_id):
        return {"active": MAIN, "keys": [{"name": MAIN, "tier": ""}]}
    return {"active": "", "keys": []}


def _save(provider_id: str, index: dict) -> None:
    """A single plain Main key needs no list, so the store stays as it always was for
    anyone who never names a key."""
    if index == {"active": MAIN, "keys": [{"name": MAIN, "tier": ""}]}:
        _delete(f"{provider_id}:#keys")
    else:
        _write(f"{provider_id}:#keys", json.dumps(index))


def _entry(index: dict, name: str) -> dict | None:
    return next((k for k in index["keys"] if _same(k["name"], name)), None)


def clean_name(name: str) -> str:
    name = name.strip()
    if not _NAME.fullmatch(name):
        raise ValueError("A key's name can have up to 30 letters, numbers, spaces, dots and "
                         "dashes.")
    return name


def clean_tier(tier: str) -> str:
    if tier not in TIERS:
        raise ValueError("A key is free, paid, or not set.")
    return tier


def saved_keys(provider_id: str) -> list[SavedKey]:
    index = _load(provider_id)
    return [SavedKey(k["name"], k.get("tier", ""), _same(k["name"], index.get("active", "")))
            for k in index["keys"]]


def active_key(provider_id: str) -> SavedKey | None:
    return next((k for k in saved_keys(provider_id) if k.active), None)


def named_key(provider_id: str, name: str) -> SavedKey | None:
    return next((k for k in saved_keys(provider_id) if _same(k.name, name)), None)


def stored_key(provider_id: str, name: str | None = None) -> str | None:
    """A saved key: the one in use, or the one called `name`. None if there is none."""
    index = _load(provider_id)
    entry = _entry(index, name or index.get("active", ""))
    return _read(_account(provider_id, entry["name"])) if entry else None


def store_key(provider_id: str, key: str, name: str | None = None,
              tier: str | None = None) -> None:
    """Save a key. With no name it replaces the key in use. A key new to the list is put
    in use only if it is the only one."""
    key = key.strip()
    if not key:
        raise ValueError("Empty key.")
    index = _load(provider_id)
    name = clean_name(name) if name else index.get("active") or MAIN
    entry = _entry(index, name)
    if entry is None:
        entry = {"name": name, "tier": ""}
        index["keys"].append(entry)
    if tier is not None:
        entry["tier"] = clean_tier(tier)
    if len(index["keys"]) == 1:
        index["active"] = entry["name"]
    _write(_account(provider_id, entry["name"]), key)
    _save(provider_id, index)


def use_key(provider_id: str, name: str) -> None:
    index = _load(provider_id)
    entry = _entry(index, name)
    if entry is None:
        raise ValueError(f"No saved key is called {name}.")
    index["active"] = entry["name"]
    _save(provider_id, index)


def set_tier(provider_id: str, name: str, tier: str) -> None:
    index = _load(provider_id)
    entry = _entry(index, name)
    if entry is None:
        raise ValueError(f"No saved key is called {name}.")
    entry["tier"] = clean_tier(tier)
    _save(provider_id, index)


def forget_key(provider_id: str, name: str | None = None) -> bool:
    """Delete one saved key, or with no name all of a provider's. True if there was one.
    Forgetting the key in use leaves none in use, whatever else is saved."""
    index = _load(provider_id)
    gone = index["keys"] if name is None else [k for k in index["keys"] if _same(k["name"], name)]
    if not gone:
        return False
    for entry in gone:
        _delete(_account(provider_id, entry["name"]))
    left = [k for k in index["keys"] if k not in gone]
    if left:
        if _entry({"keys": left}, index.get("active", "")) is None:
            index["active"] = ""
        index["keys"] = left
        _save(provider_id, index)
    else:
        _delete(f"{provider_id}:#keys")
    return True


def switch_note(tier: str) -> str:
    """What changes on moving to a key of this tier: said before the person switches."""
    if tier == "free":
        return "a free key: the provider may use your documents to improve its products"
    if tier == "paid":
        return "a paid key: using it costs money"
    return "check what it costs before using it"
