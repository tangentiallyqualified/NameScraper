"""Bootstrap helpers for the main window shell."""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QTimer


class MainWindowBootstrapCoordinator:
    def __init__(self, window: Any) -> None:
        self._window = window

    def initialize_backend(
        self,
        *,
        settings_factory: Callable[[], Any],
        job_store_factory: Callable[[], Any],
        command_gating_factory: Callable[[], Any],
        refresh_policy_factory: Callable[[], Any],
        cache_service_factory: Callable[..., Any],
        queue_controller_factory: Callable[[Any], Any],
        media_controller_factory: Callable[..., Any],
        controller_bridge_installer: Callable[[Any], Any],
        queue_bridge_installer: Callable[[Any], Any],
    ) -> None:
        window = self._window
        window.settings_service = settings_factory()
        window._job_store = job_store_factory()
        window._command_gating = command_gating_factory()
        window._refresh_policy = refresh_policy_factory()
        window._cache_service = cache_service_factory(
            refresh_policy=window._refresh_policy,
            max_size_bytes=window.settings_service.cache_max_size_bytes,
        )

        window.queue_ctrl = queue_controller_factory(window._job_store)

        from ..app.services.metadata_service import make_image_fetcher
        from ..keys import get_api_key

        window.queue_ctrl.set_image_fetcher(make_image_fetcher(
            get_client=lambda: window._tmdb,
            api_key_lookup=get_api_key,
            cache_service=window._cache_service,
            language=window.settings_service.match_language,
        ))

        window.media_ctrl = media_controller_factory(
            job_store=window._job_store,
            command_gating=window._command_gating,
            settings=window.settings_service,
            cache_service=window._cache_service,
            refresh_policy=window._refresh_policy,
        )

        window._bridge = controller_bridge_installer(window)
        window._queue_bridge = queue_bridge_installer(window)

    def initialize_feedback_state(
        self,
        *,
        toast_manager_factory: Callable[[Any], Any],
        timer_factory: Callable[[Any], QTimer],
    ) -> None:
        window = self._window
        window._toast_manager = toast_manager_factory(window)
        window._queue_run_started = False
        window._queue_run_is_background = False
        window._queue_completed_count = 0
        window._queue_failed_count = 0
        window._pending_success_jobs = 0
        window._pending_success_files = 0
        window._job_poster_backfill_started = False
        window._job_poster_backfill_future = None
        window._tv_needs_queue_refresh = False
        window._movie_needs_queue_refresh = False
        window._scan_feedback_token = None

        window._success_toast_timer = timer_factory(window)
        window._success_toast_timer.setSingleShot(True)
        window._success_toast_timer.setInterval(350)
        window._success_toast_timer.timeout.connect(window._flush_success_toast_batch)
