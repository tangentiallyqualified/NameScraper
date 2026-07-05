"""Revert-banner presentation helpers for HistoryTab."""

from __future__ import annotations


def show_revert_banner(banner, revert_button, info_label, *, info_text: str) -> None:
    info_label.setText(info_text)
    revert_button.hide()
    banner.show()


def hide_revert_banner(banner, revert_button) -> None:
    banner.hide()
    revert_button.show()
