"""Keep every test away from real keys and choices: the machine's password store,
the key variables in its environment, and the saved settings are replaced for
each test."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class FakeKeyring:
    def __init__(self):
        self.saved: dict[tuple[str, str], str] = {}

    def get_password(self, service, user):
        return self.saved.get((service, user))

    def set_password(self, service, user, password):
        self.saved[(service, user)] = password

    def delete_password(self, service, user):
        del self.saved[(service, user)]


@pytest.fixture(autouse=True)
def isolated_keys(monkeypatch, tmp_path_factory):
    from bettermarkitdown import credentials
    from bettermarkitdown.providers import PROVIDERS

    fake = FakeKeyring()
    monkeypatch.setattr(credentials, "_backend", lambda: fake)
    monkeypatch.setenv("BMID_CONFIG_DIR", str(tmp_path_factory.mktemp("config")))
    names = {name for spec in PROVIDERS.values() for name in spec.key_env}
    for name in names | {"BMID_PROVIDER", "BMID_BASE_URL", "OPENAI_BASE_URL", "BMID_MODEL"}:
        monkeypatch.delenv(name, raising=False)
    return fake
