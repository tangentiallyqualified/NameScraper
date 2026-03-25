"""API key storage with OS keyring preference and local fallback."""

from __future__ import annotations

import json

try:
    import keyring
    from keyring.errors import KeyringError
except ImportError:  # pragma: no cover - depends on local environment
    keyring = None

    class KeyringError(Exception):
        """Fallback keyring error base when keyring is not installed."""


from .constants import LOG_DIR, ensure_log_dir


SERVICE_NAME = "PlexRenamer"
KEYS_FILE = LOG_DIR / "api_keys.json"


def _read_local_keys() -> dict[str, str]:
    """Read locally persisted API keys when keyring is unavailable."""
    ensure_log_dir()
    if not KEYS_FILE.exists():
        return {}
    try:
        return json.loads(KEYS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_local_keys(keys: dict[str, str]) -> None:
    """Persist API keys to the local fallback file."""
    ensure_log_dir()
    KEYS_FILE.write_text(
        json.dumps(keys, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _save_via_keyring(service: str, key: str) -> bool:
    """Try storing the key via OS keyring, returning success status."""
    if keyring is None:
        return False
    try:
        keyring.set_password(SERVICE_NAME, service, key)
        return True
    except (KeyringError, RuntimeError):
        return False


def _load_via_keyring(service: str) -> str | None:
    """Try reading the key from OS keyring."""
    if keyring is None:
        return None
    try:
        return keyring.get_password(SERVICE_NAME, service)
    except (KeyringError, RuntimeError):
        return None


def save_api_key(service: str, key: str) -> None:
    """Persist an API key using keyring when available, else local fallback."""
    if _save_via_keyring(service, key):
        return
    keys = _read_local_keys()
    keys[service] = key
    _write_local_keys(keys)


def get_api_key(service: str) -> str | None:
    """Retrieve a stored API key from keyring or the local fallback file."""
    key = _load_via_keyring(service)
    if key:
        return key
    return _read_local_keys().get(service)
