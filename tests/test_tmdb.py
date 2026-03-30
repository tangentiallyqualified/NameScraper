from __future__ import annotations

import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

from PIL import Image

from plex_renamer.app.services.cache_service import PersistentCacheService
from plex_renamer.tmdb import TMDBClient, _HTTP_POOL_CONNECTIONS, _HTTP_POOL_MAXSIZE


class TMDBClientTests(unittest.TestCase):
    def test_tmdb_client_uses_expanded_connection_pool_without_changing_rate_limit(self):
        client = TMDBClient("dummy-api-key")
        try:
            api_adapter = client._session.get_adapter("https://api.themoviedb.org/3/configuration")
            image_adapter = client._session.get_adapter("https://image.tmdb.org/t/p/w500/test.jpg")

            self.assertEqual(api_adapter._pool_connections, _HTTP_POOL_CONNECTIONS)
            self.assertEqual(api_adapter._pool_maxsize, _HTTP_POOL_MAXSIZE)
            self.assertEqual(image_adapter._pool_connections, _HTTP_POOL_CONNECTIONS)
            self.assertEqual(image_adapter._pool_maxsize, _HTTP_POOL_MAXSIZE)
            self.assertEqual(client._rate_limiter._rate, 35.0)
        finally:
            client._session.close()

    def test_fetch_poster_reuses_persisted_poster_across_client_instances(self):
        with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            cache = PersistentCacheService(db_path=Path(tmp) / "cache.db")

            first_client = TMDBClient("dummy-api-key", cache_service=cache)
            first_client._get_safe = MagicMock(return_value={"poster_path": "/poster.jpg"})
            first_client.fetch_image = MagicMock(return_value=Image.new("RGB", (96, 144), color="red"))

            first_result = first_client.fetch_poster(123, media_type="movie", target_width=96)

            self.assertIsNotNone(first_result)
            first_client._get_safe.assert_called_once_with("/movie/123")
            first_client.fetch_image.assert_called_once_with("/poster.jpg", 96)
            first_client._session.close()

            second_client = TMDBClient("dummy-api-key", cache_service=cache)
            second_client._get_safe = MagicMock(side_effect=AssertionError("metadata should not be fetched"))
            second_client.fetch_image = MagicMock(side_effect=AssertionError("poster should not be redownloaded"))

            second_result = second_client.fetch_poster(123, media_type="movie", target_width=96)

            self.assertIsNotNone(second_result)
            self.assertEqual(second_result.size, (96, 144))
            second_client._session.close()

    def test_fetch_image_reuses_persisted_source_across_widths(self):
        png_buffer = io.BytesIO()
        Image.new("RGB", (200, 300), color="blue").save(png_buffer, format="PNG")
        payload = png_buffer.getvalue()

        with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            cache = PersistentCacheService(db_path=Path(tmp) / "cache.db")

            first_client = TMDBClient("dummy-api-key", cache_service=cache)
            response = MagicMock()
            response.content = payload
            first_client._session.get = MagicMock(return_value=response)

            first_result = first_client.fetch_image("/poster.jpg", target_width=96)

            self.assertIsNotNone(first_result)
            self.assertEqual(first_result.size, (96, 144))
            first_client._session.get.assert_called_once()
            first_client._session.close()

            second_client = TMDBClient("dummy-api-key", cache_service=cache)
            second_client._session.get = MagicMock(side_effect=AssertionError("source image should not be redownloaded"))

            second_result = second_client.fetch_image("/poster.jpg", target_width=42)

            self.assertIsNotNone(second_result)
            self.assertEqual(second_result.size, (42, 63))
            second_client._session.close()


if __name__ == "__main__":
    unittest.main()