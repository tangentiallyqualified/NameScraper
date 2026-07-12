"""Language-tag normalization for AutoMux.

Canonical form is ISO 639-2/B (mkvmerge's traditional vocabulary), so
``en``, ``eng``, ``en-US`` and ``deu``/``ger`` all compare equal after
normalization.  ``und`` is a valid canonical value meaning "undefined".
"""

from __future__ import annotations

from collections.abc import Iterable

# ISO 639-1 (two letter) → ISO 639-2/B.  Covers the languages exposed in
# the GUI language options plus common media-library languages.
_ISO639_1_TO_2B = {
    "en": "eng", "fr": "fre", "de": "ger", "es": "spa", "it": "ita",
    "pt": "por", "ja": "jpn", "ko": "kor", "zh": "chi", "ru": "rus",
    "nl": "dut", "sv": "swe", "da": "dan", "no": "nor", "fi": "fin",
    "pl": "pol", "tr": "tur", "ar": "ara", "hi": "hin", "th": "tha",
    "cs": "cze", "el": "gre", "he": "heb", "hu": "hun", "id": "ind",
    "ms": "may", "ro": "rum", "sk": "slo", "uk": "ukr", "vi": "vie",
}

# ISO 639-2/T (terminology) → ISO 639-2/B (bibliographic).  mkvmerge may
# report either family; we canonicalize on /B.
_ISO639_2T_TO_2B = {
    "deu": "ger", "fra": "fre", "zho": "chi", "nld": "dut", "ces": "cze",
    "ell": "gre", "msa": "may", "ron": "rum", "slk": "slo", "sqi": "alb",
    "hye": "arm", "eus": "baq", "mya": "bur", "kat": "geo", "isl": "ice",
    "mkd": "mac", "mri": "mao", "fas": "per", "bod": "tib", "cym": "wel",
}


def normalize_lang(tag: str) -> str | None:
    """Return the canonical ISO 639-2/B code for *tag*, or None."""
    if not tag:
        return None
    base = tag.strip().lower().replace("_", "-").split("-")[0]
    if base == "und":
        return "und"
    if len(base) == 2:
        return _ISO639_1_TO_2B.get(base)
    if len(base) == 3 and base.isalpha():
        return _ISO639_2T_TO_2B.get(base, base)
    return None


def normalize_lang_list(values: Iterable[str]) -> list[str]:
    """Normalize a list of tags: order-preserving, deduped, invalid dropped."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        lang = normalize_lang(value)
        if lang is not None and lang not in seen:
            seen.add(lang)
            result.append(lang)
    return result
