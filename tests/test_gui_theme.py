"""Theme token module and stylesheet rendering guards."""
from __future__ import annotations

import pytest

from plex_renamer.gui_qt import theme


def test_color_returns_hex():
    assert theme.color("accent") == "#00a4dc"
    assert theme.color("bg") == "#101010"


def test_color_unknown_token_raises():
    with pytest.raises(KeyError):
        theme.color("nope")


def test_qcolor_matches_color():
    assert theme.qcolor("error").name() == theme.color("error")


def test_radius_tokens():
    assert theme.radius("sm") == 4
    assert theme.radius("md") == 8
    assert theme.radius("lg") == 12
    assert theme.radius("pill") == 10


def test_rgba_renders_qss_rgba():
    assert theme.rgba("success", 0.12) == "rgba(63, 185, 80, 0.12)"


def test_render_template_substitutes_colors_and_radii():
    rendered = theme.render_template("a ${accent} b ${radius_md}px")
    assert rendered == "a #00a4dc b 8px"


def test_render_template_unknown_token_raises():
    with pytest.raises(KeyError):
        theme.render_template("${not_a_token}")
