"""Tests for API key storage (keyring preference + local JSON fallback)."""

from __future__ import annotations

import json

import pytest

from plex_renamer import keys


class _FakeKeyring:
    def __init__(self) -> None:
        self.passwords: dict[tuple[str, str], str] = {}

    def set_password(self, service_name: str, service: str, key: str) -> None:
        self.passwords[(service_name, service)] = key

    def get_password(self, service_name: str, service: str) -> str | None:
        return self.passwords.get((service_name, service))


class _BrokenKeyring:
    def set_password(self, service_name: str, service: str, key: str) -> None:
        raise keys.KeyringError("backend unavailable")

    def get_password(self, service_name: str, service: str) -> str | None:
        raise keys.KeyringError("backend unavailable")


@pytest.fixture
def local_store(tmp_path, monkeypatch):
    keys_file = tmp_path / "api_keys.json"
    monkeypatch.setattr(keys, "KEYS_FILE", keys_file)
    monkeypatch.setattr(keys, "ensure_log_dir", lambda: None)
    return keys_file


def test_save_and_get_roundtrip_via_keyring(local_store, monkeypatch) -> None:
    fake = _FakeKeyring()
    monkeypatch.setattr(keys, "keyring", fake)

    keys.save_api_key("TMDB", "secret")

    assert fake.passwords[(keys.SERVICE_NAME, "TMDB")] == "secret"
    assert not local_store.exists()
    assert keys.get_api_key("TMDB") == "secret"


def test_save_falls_back_to_local_file_without_keyring(local_store, monkeypatch) -> None:
    monkeypatch.setattr(keys, "keyring", None)

    keys.save_api_key("TMDB", "secret")

    assert json.loads(local_store.read_text(encoding="utf-8")) == {"TMDB": "secret"}
    assert keys.get_api_key("TMDB") == "secret"


def test_broken_keyring_backend_uses_local_fallback(local_store, monkeypatch) -> None:
    monkeypatch.setattr(keys, "keyring", _BrokenKeyring())

    keys.save_api_key("TMDB", "secret")

    assert json.loads(local_store.read_text(encoding="utf-8")) == {"TMDB": "secret"}
    assert keys.get_api_key("TMDB") == "secret"


def test_save_merges_existing_local_keys(local_store, monkeypatch) -> None:
    monkeypatch.setattr(keys, "keyring", None)
    local_store.write_text(json.dumps({"OTHER": "kept"}), encoding="utf-8")

    keys.save_api_key("TMDB", "secret")

    assert json.loads(local_store.read_text(encoding="utf-8")) == {
        "OTHER": "kept",
        "TMDB": "secret",
    }


def test_corrupt_local_file_reads_as_empty(local_store, monkeypatch) -> None:
    monkeypatch.setattr(keys, "keyring", None)
    local_store.write_text("not json", encoding="utf-8")

    assert keys.get_api_key("TMDB") is None


def test_get_returns_none_when_nothing_stored(local_store, monkeypatch) -> None:
    monkeypatch.setattr(keys, "keyring", None)

    assert keys.get_api_key("TMDB") is None


def test_empty_keyring_value_falls_through_to_local(local_store, monkeypatch) -> None:
    fake = _FakeKeyring()
    fake.passwords[(keys.SERVICE_NAME, "TMDB")] = ""
    monkeypatch.setattr(keys, "keyring", fake)
    local_store.write_text(json.dumps({"TMDB": "from-file"}), encoding="utf-8")

    assert keys.get_api_key("TMDB") == "from-file"
