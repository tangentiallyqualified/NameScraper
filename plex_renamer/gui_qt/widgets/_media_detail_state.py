"""Selection and cache bookkeeping helpers for MediaDetailPanel."""

from __future__ import annotations

from collections import OrderedDict

from ...engine import PreviewItem, ScanState


def make_detail_token(
    state: ScanState,
    preview: PreviewItem | None,
    queue_reason: str,
    folder_plan: str,
) -> str:
    preview_part = ""
    if preview is not None:
        preview_part = f":{preview.original}"
    return f"{state.show_id}:{state.folder}{preview_part}:{queue_reason}:{folder_plan}"


def selection_preview_pending(
    state: ScanState,
    preview: PreviewItem | None,
) -> bool:
    return state.scanning or (not state.scanned and preview is None and not state.preview_items)


def clear_detail_metadata_cache(
    metadata_cache: OrderedDict,
    loading_tokens: set[str],
) -> None:
    metadata_cache.clear()
    loading_tokens.clear()


def get_cached_detail_payload(
    metadata_cache: OrderedDict,
    token: str,
):
    cached = metadata_cache.get(token)
    if cached is not None:
        metadata_cache.move_to_end(token)
    return cached


def begin_detail_payload_load(
    loading_tokens: set[str],
    token: str,
) -> bool:
    if token in loading_tokens:
        return False
    loading_tokens.add(token)
    return True


def cache_detail_payload(
    metadata_cache: OrderedDict,
    token: str,
    payload,
    pixmap,
    *,
    max_entries: int,
) -> None:
    metadata_cache[token] = (payload, pixmap)
    metadata_cache.move_to_end(token)
    while len(metadata_cache) > max_entries:
        metadata_cache.popitem(last=False)
