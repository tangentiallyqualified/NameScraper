"""Filename parsing and name-building utilities.

All functions are pure (no side effects, no network, no GUI). They operate
on strings and Paths only, making them easy to test and reuse across both
TV and movie workflows.
"""

from ._parsing_episodes import extract_episode, extract_season_number
from ._parsing_names import (
    build_movie_name,
    build_show_folder_name,
    build_tv_name,
    is_already_complete,
    normalize_for_match,
    normalize_for_specials,
)
from ._parsing_seasons import get_season, is_season_only_name
from ._parsing_subtitles import find_companion_subtitles
from ._parsing_titles import clean_folder_name, clean_name, extract_year, sanitize_filename
from ._parsing_tv import (
    EXTRAS_FOLDER_PATTERN,
    best_tv_match_title,
    is_extras_folder,
    is_sample_file,
    looks_like_tv_episode,
)

__all__ = [
    "EXTRAS_FOLDER_PATTERN",
    "best_tv_match_title",
    "build_movie_name",
    "build_show_folder_name",
    "build_tv_name",
    "clean_folder_name",
    "clean_name",
    "extract_episode",
    "extract_season_number",
    "extract_year",
    "find_companion_subtitles",
    "get_season",
    "is_already_complete",
    "is_extras_folder",
    "is_sample_file",
    "is_season_only_name",
    "looks_like_tv_episode",
    "normalize_for_match",
    "normalize_for_specials",
    "sanitize_filename",
]
