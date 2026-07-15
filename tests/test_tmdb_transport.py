"""Direct retry and HTTP-policy tests for TMDBTransport."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from plex_renamer._tmdb_transport import TMDBAPIError, TMDBTransport


def make_transport(*, max_retries: int = 2) -> TMDBTransport:
    return TMDBTransport(
        api_key="dummy-api-key",
        language="en-US",
        api_base="https://api.themoviedb.org/3",
        max_retries=max_retries,
    )


def test_get_json_returns_none_for_404():
    transport = make_transport()
    response = MagicMock(ok=False, status_code=404)
    transport.rate_limiter.acquire = MagicMock()
    transport.session.get = MagicMock(return_value=response)

    assert transport.get_json("/tv/123") is None
    transport.session.get.assert_called_once_with(
        "https://api.themoviedb.org/3/tv/123",
        params={"api_key": "dummy-api-key", "language": "en-US"},
        timeout=10,
    )
    transport.session.close()


def test_get_json_retries_transient_network_failure_then_succeeds():
    transport = make_transport(max_retries=1)
    response = MagicMock(ok=True)
    response.json.return_value = {"id": 123}
    transport.rate_limiter.acquire = MagicMock()
    transport.session.get = MagicMock(
        side_effect=[requests.RequestException("boom"), response],
    )

    with patch("plex_renamer._tmdb_transport.time.sleep") as sleep_mock:
        assert transport.get_json("/tv/123") == {"id": 123}

    assert transport.session.get.call_count == 2
    sleep_mock.assert_called_once_with(1.0)
    transport.session.close()


def test_get_json_raises_api_error_for_non_retryable_client_failure():
    transport = make_transport()
    response = MagicMock(ok=False, status_code=400, text="bad request")
    transport.rate_limiter.acquire = MagicMock()
    transport.session.get = MagicMock(return_value=response)

    with pytest.raises(TMDBAPIError):
        transport.get_json("/tv/123")

    transport.session.close()
