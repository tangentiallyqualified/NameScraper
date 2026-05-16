"""Presentation helpers for QueueTab widgets."""

from __future__ import annotations

from ._queue_tab_state import remove_button_css_class


def apply_remove_button_state(button, *, enabled: bool) -> None:
    css_class = remove_button_css_class(enabled=enabled)
    if button.property("cssClass") != css_class:
        button.setProperty("cssClass", css_class)
        style = button.style()
        style.unpolish(button)
        style.polish(button)
    button.setEnabled(enabled)
