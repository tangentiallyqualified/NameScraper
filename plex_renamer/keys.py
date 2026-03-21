"""
Secure API key storage using the OS keyring.
"""

import keyring

SERVICE_NAME = "PlexRenamer"


def save_api_key(service: str, key: str) -> None:
    """Persist an API key securely using the OS keyring."""
    keyring.set_password(SERVICE_NAME, service, key)


def get_api_key(service: str) -> str | None:
    """Retrieve a stored API key from the OS keyring."""
    return keyring.get_password(SERVICE_NAME, service)
