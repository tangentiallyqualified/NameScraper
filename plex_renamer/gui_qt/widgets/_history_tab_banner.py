"""Revert-banner presentation helpers for HistoryTab."""

from __future__ import annotations


def show_revert_banner(
    revert_button,
    confirm_button,
    cancel_button,
    info_label,
    *,
    info_text: str,
) -> None:
    info_label.setText(info_text)
    revert_button.hide()
    confirm_button.show()
    cancel_button.show()
    info_label.show()


def hide_revert_banner(
    revert_button,
    confirm_button,
    cancel_button,
    info_label,
) -> None:
    confirm_button.hide()
    cancel_button.hide()
    info_label.hide()
    revert_button.show()
