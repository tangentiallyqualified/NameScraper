"""Tests for episode parsing extensions and the resolution policy."""

from plex_renamer.parsing import extract_episode


class TestMultiEpisodeRuns:
    def test_three_episode_e_run(self):
        eps, title, rel = extract_episode("Show S01E01E02E03.mkv")
        assert eps == [1, 2, 3]
        assert rel is True

    def test_five_episode_e_run(self):
        eps, _, rel = extract_episode("Show S01E01E02E03E04E05.mkv")
        assert eps == [1, 2, 3, 4, 5]
        assert rel is True

    def test_sxx_exx_dash_range(self):
        eps, _, rel = extract_episode("Show S01E01-E04.mkv")
        assert eps == [1, 2, 3, 4]
        assert rel is True

    def test_sxx_exx_dash_range_bare_end(self):
        eps, _, rel = extract_episode("Show S01E01-04.mkv")
        assert eps == [1, 2, 3, 4]
        assert rel is True

    def test_xx_format_range(self):
        eps, _, rel = extract_episode("Show 1x01-1x04.mkv")
        assert eps == [1, 2, 3, 4]
        assert rel is True

    def test_range_span_cap_rejected(self):
        # Span > 12 is a parse artifact, not a real run: keep endpoints only.
        eps, _, _ = extract_episode("Show S01E01-E80.mkv")
        assert eps == [1, 80]

    def test_two_episode_format_unchanged(self):
        eps, title, rel = extract_episode("Show S01E01E02 - Pilot.mkv")
        assert eps == [1, 2]
        assert rel is True

    def test_single_episode_with_title_unchanged(self):
        eps, title, rel = extract_episode("Show S02E05 - The One.mkv")
        assert eps == [5]
        assert title == "The One"
        assert rel is True

    def test_resolution_number_not_an_episode(self):
        eps, _, _ = extract_episode("Show S01E01 1080p.mkv")
        assert eps == [1]

    # --- keep-working: spaced dash WITH E prefix is still a range ---
    def test_sxx_exx_spaced_dash_e_range(self):
        eps, _, rel = extract_episode("Show S01E01 - E04.mkv")
        assert eps == [1, 2, 3, 4]
        assert rel is True

    def test_chained_dash_e_run_three(self):
        eps, _, rel = extract_episode("ChalkZone.S01E01-E02-E03.DVDRip.1080p.mkv")
        assert eps == [1, 2, 3]
        assert rel is True

    def test_chained_dash_e_run_four(self):
        eps, _, rel = extract_episode("Show S01E01-E02-E03-E04.mkv")
        assert eps == [1, 2, 3, 4]
        assert rel is True

    def test_chained_nxnn_run_three(self):
        eps, _, rel = extract_episode("Show 1x01-1x02-1x03.mkv")
        assert eps == [1, 2, 3]
        assert rel is True

    def test_chained_nxnn_bare_run_three(self):
        eps, _, rel = extract_episode("Show 1x01-02-03.mkv")
        assert eps == [1, 2, 3]
        assert rel is True

    def test_mixed_prefix_and_bare_range_end(self):
        # Documented deviation: a multi-episode E-prefix followed by a bare
        # range-end appends the endpoint as an explicit point rather than
        # expanding from the first episode (S01E01E02-04 -> [1, 2, 4], not
        # [1, 2, 3, 4]). A non-contiguous run like this is rejected downstream.
        eps, _, rel = extract_episode("Show S01E01E02-04.mkv")
        assert eps == [1, 2, 4]
        assert rel is True


class TestRangeFalsePositives:
    """Regression tests: digit-leading titles must NOT be parsed as range ends."""

    def test_digit_leading_title_12_angry_men(self):
        eps, title, rel = extract_episode("Show S01E01 - 12 Angry Men.mkv")
        assert eps == [1]
        assert title == "12 Angry Men"
        assert rel is True

    def test_digit_leading_title_2_broke_girls(self):
        eps, title, rel = extract_episode("Show S01E01 - 2 Broke Girls.mkv")
        assert eps == [1]
        assert title == "2 Broke Girls"
        assert rel is True

    def test_digit_leading_title_7_minutes(self):
        eps, title, rel = extract_episode("Breaking Bad S01E01 - 7 Minutes.mkv")
        assert eps == [1]
        assert title == "7 Minutes"
        assert rel is True

    def test_digit_leading_title_23rd_psalm(self):
        eps, title, rel = extract_episode("Lost S02E03 - 23rd Psalm.mkv")
        assert eps == [3]
        assert title == "23rd Psalm"
        assert rel is True

    def test_resolution_720p_not_range(self):
        eps, _, _ = extract_episode("Show S01E01-720p.mkv")
        assert eps == [1]

    def test_nxnn_digit_leading_title_9_lives(self):
        eps, title, rel = extract_episode("Show 3x07 - 9 Lives.mkv")
        assert eps == [7]
        assert title == "9 Lives"
        assert rel is True

    # --- keep-working: ranges that must still parse correctly ---
    def test_sxx_exx_no_space_e_range_still_works(self):
        eps, _, _ = extract_episode("Show S01E01-E04.mkv")
        assert eps == [1, 2, 3, 4]

    def test_sxx_exx_no_space_bare_range_still_works(self):
        eps, _, _ = extract_episode("Show S01E01-04.mkv")
        assert eps == [1, 2, 3, 4]

    def test_sxx_exx_spaced_e_range_still_works(self):
        eps, _, _ = extract_episode("Show S01E01 - E04.mkv")
        assert eps == [1, 2, 3, 4]

    def test_xx_format_range_still_works(self):
        eps, _, _ = extract_episode("Show 1x01-1x04.mkv")
        assert eps == [1, 2, 3, 4]

    def test_range_span_cap_still_works(self):
        eps, _, _ = extract_episode("Show S01E01-E80.mkv")
        assert eps == [1, 80]


class TestDescriptiveParentheticals:
    def test_pilot_parenthetical_preserved(self):
        _eps, title, _rel = extract_episode(
            "Adventure Time (2008) - S00E01 - Adventure Time (Pilot) (480p TVRip x265 ImE).mkv"
        )
        assert title == "Adventure Time (Pilot)"

    def test_again_parenthetical_preserved(self):
        _eps, title, _rel = extract_episode(
            "Adventure Time (2008) - S00E13 - Frog Seasons Spring (Again) (1080p BluRay x265 ImE).mkv"
        )
        assert title == "Frog Seasons Spring (Again)"

    def test_quality_parenthetical_stripped(self):
        _eps, title, _rel = extract_episode(
            "Show - S01E05 - The Wizard Hunt (1080p BluRay x265 ImE).mkv"
        )
        assert title == "The Wizard Hunt"


# ─── Direct unit tests for _strip_quality_parens / clean_title_evidence ───────

from plex_renamer._parsing_titles import _strip_quality_parens, clean_title_evidence


class TestStripQualityParens:
    """Unit tests for Finding 1 (year stripping) and Finding 2 (noise via token)."""

    # Finding 1 — year-only group is stripped
    def test_year_group_stripped(self):
        result = _strip_quality_parens("Some Title (2008)")
        assert "(2008)" not in result

    def test_year_group_stripped_mid_stem(self):
        # year appearing before episode title segment
        result = clean_title_evidence("My Show (2008) - The (2009) Pilot (480p DVD x265 Ghost)")
        assert "2008" not in result
        assert "2009" not in result
        assert "480p" not in result
        assert "Pilot" in result

    def test_year_not_in_clean_title_evidence(self):
        result = clean_title_evidence("My Show (2008) - The Pilot")
        assert "(2008)" not in result

    # Descriptive / part groups must survive (Finding 1 must not over-strip)
    def test_pilot_survives(self):
        result = clean_title_evidence("Adventure Time (Pilot)")
        assert "(Pilot)" in result

    def test_again_survives(self):
        result = clean_title_evidence("Show (Again)")
        assert "(Again)" in result

    def test_part_2_survives(self):
        result = clean_title_evidence("Episode (Part 2)")
        assert "(Part 2)" in result

    def test_single_digit_1_survives(self):
        result = _strip_quality_parens("Episode (1)")
        assert "(1)" in result

    def test_single_digit_2_survives(self):
        result = _strip_quality_parens("Episode (2)")
        assert "(2)" in result

    # Finding 2 — group of exactly "(it)" (lowercase) is NOT stripped as noise
    def test_it_lowercase_not_stripped(self):
        result = clean_title_evidence("Show (it)")
        assert "(it)" in result

    # Regression — quality groups still stripped
    def test_complex_quality_group_still_stripped(self):
        result = clean_title_evidence("Show (480p DVD x265 HEVC 10bit AAC 2.0 Ghost)")
        assert "480p" not in result

    def test_bluray_quality_group_still_stripped(self):
        result = clean_title_evidence("Show (1080p BluRay x265 ImE)")
        assert "1080p" not in result


from plex_renamer.engine._episode_resolution import (
    CONF_AGREE,
    CONF_NUMBER_INFERRED,
    CONF_NUMBER_RELATIVE,
    CONF_SPECIAL_NUMBER_ONLY,
    CONF_TITLE_ONLY,
    CONF_TITLE_WINS,
    CONF_TITLE_WINS_INEXACT,
    CONF_WEAK_TITLE_NUMBER_CAP,
    STRONG_TITLE_STRENGTH,
    match_title_in_titles,
    resolve_file,
)
from plex_renamer.engine._state import DEFAULT_EPISODE_AUTO_ACCEPT_THRESHOLD

S0_TITLES = {1: "Inauguration Part 1", 2: "Special A", 3: "Special C"}
S1_TITLES = {1: "Pilot", 2: "The Heist", 3: "Endgame", 4: "Coda"}


class TestTitleStrength:
    def test_exact_normalized_match_is_full_strength(self):
        match = match_title_in_titles("Special A", S0_TITLES)
        assert match is not None
        assert match.episode == 2
        assert match.strength == 1.0

    def test_unique_substring_is_strong(self):
        match = match_title_in_titles("The Heist 720p extended", S1_TITLES)
        assert match is not None
        assert match.episode == 2
        assert match.strength >= STRONG_TITLE_STRENGTH

    def test_ambiguous_returns_none(self):
        titles = {1: "Part 1", 2: "Part 2"}
        assert match_title_in_titles("Part", titles) is None

    def test_no_match_returns_none(self):
        assert match_title_in_titles("Completely Unrelated", S1_TITLES) is None


class TestResolutionRules:
    def test_rule1_number_and_title_agree(self):
        res = resolve_file(
            parsed_episodes=(2,),
            raw_title="The Heist",
            is_season_relative=True,
            season_titles=S1_TITLES,
        )
        assert res.episodes == (2,)
        assert res.confidence >= CONF_AGREE
        assert res.reason is None

    def test_rule2_strong_title_beats_number(self):
        # The user-reported case: s00e03 named "Special A" must map to e02.
        res = resolve_file(
            parsed_episodes=(3,),
            raw_title="Special A",
            is_season_relative=True,
            season_titles=S0_TITLES,
        )
        assert res.episodes == (2,)
        assert res.confidence == CONF_TITLE_WINS

    def test_rule3_weak_title_keeps_number_capped(self):
        # Title fuzzy-misses; the valid number wins but lands in review range.
        res = resolve_file(
            parsed_episodes=(3,),
            raw_title="Endgame Part",
            is_season_relative=True,
            season_titles={1: "Pilot", 2: "Endgame Part One", 3: "Endgame Part Two"},
        )
        assert res.episodes == (3,)
        assert res.confidence <= CONF_WEAK_TITLE_NUMBER_CAP

    def test_rule4_number_only_relative(self):
        res = resolve_file(
            parsed_episodes=(4,),
            raw_title=None,
            is_season_relative=True,
            season_titles=S1_TITLES,
        )
        assert res.episodes == (4,)
        assert res.confidence == CONF_NUMBER_RELATIVE

    def test_rule4_number_only_inferred(self):
        res = resolve_file(
            parsed_episodes=(4,),
            raw_title=None,
            is_season_relative=False,
            season_titles=S1_TITLES,
        )
        assert res.episodes == (4,)
        assert res.confidence == CONF_NUMBER_INFERRED

    def test_rule5_title_only_strong(self):
        res = resolve_file(
            parsed_episodes=(),
            raw_title="Endgame",
            is_season_relative=False,
            season_titles=S1_TITLES,
        )
        assert res.episodes == (3,)
        assert res.confidence == CONF_TITLE_ONLY

    def test_rule5_title_only_weak_is_unassigned(self):
        res = resolve_file(
            parsed_episodes=(),
            raw_title="Bloopers Reel",
            is_season_relative=False,
            season_titles=S1_TITLES,
        )
        assert res.episodes == ()
        assert res.reason == "no TMDB title match"

    def test_rule6_nothing_is_unassigned(self):
        res = resolve_file(
            parsed_episodes=(),
            raw_title=None,
            is_season_relative=False,
            season_titles=S1_TITLES,
        )
        assert res.episodes == ()
        assert res.reason == "could not parse episode number"

    def test_number_not_in_season_is_unassigned(self):
        res = resolve_file(
            parsed_episodes=(99,),
            raw_title=None,
            is_season_relative=True,
            season_titles=S1_TITLES,
        )
        assert res.episodes == ()
        assert res.reason == "episode not in TMDB season"

    def test_multi_episode_run_validated(self):
        res = resolve_file(
            parsed_episodes=(1, 2, 3),
            raw_title=None,
            is_season_relative=True,
            season_titles=S1_TITLES,
        )
        assert res.episodes == (1, 2, 3)
        assert res.confidence == CONF_NUMBER_RELATIVE

    def test_rule4_unaffected_when_no_title_evidence(self):
        res = resolve_file(
            parsed_episodes=(3,),
            raw_title="Completely Unrelated Thing",
            is_season_relative=True,
            season_titles=S1_TITLES,
        )
        assert res.episodes == (3,)
        assert res.confidence == CONF_NUMBER_RELATIVE

    def test_substring_offnumber_overrides_into_review(self):
        # Parsed E2 is valid; title substring-matches E3 only. Title wins,
        # but lands in review (below threshold) rather than auto-accepting.
        res = resolve_file(
            parsed_episodes=(2,),
            raw_title="Endgame",
            is_season_relative=True,
            season_titles={1: "Pilot", 2: "The Heist", 3: "Endgame Saga"},
        )
        assert res.episodes == (3,)
        assert res.confidence == CONF_TITLE_WINS_INEXACT
        assert res.confidence < DEFAULT_EPISODE_AUTO_ACCEPT_THRESHOLD
        assert "title-strong-inexact" in res.evidence

    def test_title_matching_own_number_is_not_overridden(self):
        # When a title matches its OWN parsed number it is rule-1 agreement,
        # NOT a rule-2b inexact override. (Generic principle guard; the real
        # As Told By Ginger S02E06 release is title-offset and handled by the
        # conflict-resolution path, not this rule.)
        res = resolve_file(
            parsed_episodes=(6,),
            raw_title="Sibling Revile-ry",
            is_season_relative=True,
            season_titles={
                5: "Hello Stranger",
                6: "Sibling Revile-ry",
                7: "Of Lice and Friends",
            },
        )
        assert res.episodes == (6,)
        assert res.confidence == CONF_AGREE
        assert "title-agree" in res.evidence


class TestMultiSegmentTitleRun:
    """Combined-title multi-episode files (CatDog/Rugrats) must resolve by
    segment titles, not by the (often mis-numbered) source episode numbers.

    Each segment of the combined title is one episode's exact title; the run
    is assigned by those titles when they form a unique contiguous run.
    """

    # TMDB Season 1 where the source's numbering is shuffled vs TMDB order.
    CATDOG_S1 = {
        1: "Dog Gone",
        2: "All You Can't Eat",
        5: "Full Moon Fever",
        6: "War of the CatDog",
        13: "The Island",
        14: "All You Need is Lube",
        25: "Armed and Dangerous",
        26: "Fistful of Mail!",
    }

    def test_number_maps_wrong_but_segment_titles_win(self):
        # The doc's case: file labelled E05-E06 but its titles live at E13-E14.
        res = resolve_file(
            parsed_episodes=(5, 6),
            raw_title="The Island and All You Need is Lube",
            is_season_relative=True,
            season_titles=self.CATDOG_S1,
            season=1,
        )
        assert res.episodes == (13, 14)
        assert res.confidence >= DEFAULT_EPISODE_AUTO_ACCEPT_THRESHOLD

    def test_internal_and_in_segment_title_disambiguated(self):
        # "Armed and Dangerous" is ONE title containing "and"; the constrained
        # partition must pick {Armed and Dangerous}{Fistful of Mail}, not
        # {Armed}{Dangerous and Fistful of Mail}.
        res = resolve_file(
            parsed_episodes=(13, 14),
            raw_title="Armed and Dangerous and Fistful of Mail",
            is_season_relative=True,
            season_titles=self.CATDOG_S1,
            season=1,
        )
        assert res.episodes == (25, 26)

    def test_segments_agreeing_with_number_are_high_confidence(self):
        # Correct file: titles match the parsed numbers -> rule-1-like agreement.
        res = resolve_file(
            parsed_episodes=(1, 2),
            raw_title="Dog Gone and All You Can't Eat",
            is_season_relative=True,
            season_titles=self.CATDOG_S1,
            season=1,
        )
        assert res.episodes == (1, 2)
        assert res.confidence >= CONF_AGREE
        assert "title-agree" in res.evidence

    def test_three_segment_run(self):
        titles = {
            1: "Send in the CatDog",
            2: "Fishing For Trouble",
            3: "Fetch",
            10: "Decoy",
            11: "Decoy 2",
            12: "Decoy 3",
        }
        res = resolve_file(
            parsed_episodes=(10, 11, 12),
            raw_title="Send in the CatDog and Fishing For Trouble and Fetch",
            is_season_relative=True,
            season_titles=titles,
            season=2,
        )
        assert res.episodes == (1, 2, 3)

    def test_typo_segment_resolves_fuzzily_at_review(self):
        # Source typo "Curiousity" can't exact-match, but the bounded fuzzy
        # tier (RC20-2) bridges it: the run resolves to (37, 38) at REVIEW
        # confidence with review-locked "title-fuzzy" evidence — never
        # auto-accept.
        titles = {
            31: "Decoy A",
            32: "Decoy B",
            37: "Neferkitty",
            38: "Curiosity Almost Killed The Cat",
        }
        res = resolve_file(
            parsed_episodes=(31, 32),
            raw_title="Neferkitty and Curiousity Almost Killed The Cat",
            is_season_relative=True,
            season_titles=titles,
            season=1,
        )
        assert res.episodes == (37, 38)
        assert "title-fuzzy" in res.evidence
        assert res.confidence < DEFAULT_EPISODE_AUTO_ACCEPT_THRESHOLD

    def test_noncontiguous_title_run_falls_back_to_number(self):
        # Segments map to non-adjacent episodes -> not a valid run -> number.
        titles = {1: "Alpha", 2: "Beta", 5: "Gamma"}
        res = resolve_file(
            parsed_episodes=(1, 2),
            raw_title="Alpha and Gamma",
            is_season_relative=True,
            season_titles=titles,
            season=1,
        )
        assert res.episodes == (1, 2)

    def test_ambiguous_partition_falls_back_to_number(self):
        # Two different partitions each match -> ambiguous -> keep number.
        titles = {1: "A", 2: "B and C", 3: "A and B", 4: "C"}
        res = resolve_file(
            parsed_episodes=(1, 2),
            raw_title="A and B and C",
            is_season_relative=True,
            season_titles=titles,
            season=1,
        )
        assert res.episodes == (1, 2)


class TestSingleNumberSegmentedRun:
    """Disc-grouped files carry ONE episode number but a multi-segment title
    (Animaniacs 1993, Catscratch): TMDB indexes each segment as its own
    episode, so the segment titles must drive the run even though only one
    number parsed. When the segments can't fully resolve, the bare number
    must stay reviewable — not get floored to auto-accept.
    """

    # Segment-indexed TMDB season; source discs number files 1..N.
    ANIMANIACS_S1 = {
        5: "Piano Rag",
        6: "Win Big",
        12: "Taming of the Screwy",
        16: "Flipper Parody",
        17: "Temporary Insanity",
        18: "Operation Lollipop",
    }

    def test_single_number_with_full_segment_titles_resolves_run(self):
        res = resolve_file(
            parsed_episodes=(6,),
            raw_title="Flipper Parody & Temporary Insanity & Operation Lollipop",
            is_season_relative=True,
            season_titles=self.ANIMANIACS_S1,
            season=1,
        )
        assert res.episodes == (16, 17, 18)
        assert "title-segmented" in res.evidence

    def test_single_number_inside_resolved_run_is_agreement(self):
        res = resolve_file(
            parsed_episodes=(16,),
            raw_title="Flipper Parody & Temporary Insanity",
            is_season_relative=True,
            season_titles=self.ANIMANIACS_S1,
            season=1,
        )
        assert res.episodes == (16, 17)
        assert "title-agree" in res.evidence
        assert res.confidence >= CONF_AGREE

    def test_partial_segment_titles_fill_positionally_at_review(self):
        # Two segments match E16/E17 and the third is a retitled variant
        # sharing a token with E18: RC31 fills the run positionally at
        # review confidence instead of keeping the bare (wrong) disc number
        # — still never auto-accepted. (A fill with NO shared tokens is
        # rejected outright since RC42.)
        res = resolve_file(
            parsed_episodes=(6,),
            raw_title="Flipper Parody & Temporary Insanity & Operation Thing",
            is_season_relative=True,
            season_titles=self.ANIMANIACS_S1,
            season=1,
        )
        assert res.episodes == (16, 17, 18)
        assert res.confidence < DEFAULT_EPISODE_AUTO_ACCEPT_THRESHOLD

    def test_partial_segment_titles_with_alien_atom_do_not_fill(self):
        # RC42: 'Missing Thing' shares nothing with E18 'Operation
        # Lollipop'; presuming it IS E18 produced wrong runs and killed the
        # correct decompositions (Animaniacs E06, Rugrats S7).
        res = resolve_file(
            parsed_episodes=(6,),
            raw_title="Flipper Parody & Temporary Insanity & Missing Thing",
            is_season_relative=True,
            season_titles=self.ANIMANIACS_S1,
            season=1,
        )
        assert res.episodes != (16, 17, 18)

    def test_multi_segment_number_claim_not_floored_to_auto_accept(self):
        # End-to-end through apply_confidence_adjustments: season-relative +
        # compatible source prefix floors must NOT lift the ambiguous
        # multi-segment number claim to 0.88 (the reproduced Animaniacs bug).
        from pathlib import Path

        from plex_renamer.engine._episode_resolution import (
            apply_confidence_adjustments,
        )
        from plex_renamer.engine.episode_assignments import (
            EpisodeAssignmentTable,
            EpisodeSlot,
        )

        raw_title = "Flipper Parody & Temporary Insanity & Missing Thing"
        res = resolve_file(
            parsed_episodes=(6,),
            raw_title=raw_title,
            is_season_relative=True,
            season_titles=self.ANIMANIACS_S1,
            season=1,
        )
        table = EpisodeAssignmentTable()
        for episode, title in self.ANIMANIACS_S1.items():
            table.add_slot(EpisodeSlot(season=1, episode=episode, title=title))
        entry = table.add_file(
            Path(f"Demo Show - S01E06 - {raw_title}.mkv"),
            parsed_episodes=(6,),
            raw_title=raw_title,
            is_season_relative=True,
            season_hint=1,
            folder_season=1,
        )
        table.assign(
            entry.file_id,
            1,
            list(res.episodes),
            origin="auto",
            confidence=res.confidence,
            evidence=res.evidence,
        )
        apply_confidence_adjustments(
            table,
            show_info={"id": 3, "name": "Demo Show", "year": "1993"},
        )
        assert (
            table.assignment_for(entry.file_id).confidence < DEFAULT_EPISODE_AUTO_ACCEPT_THRESHOLD
        )

    def test_exact_full_title_match_beats_segmentation(self):
        # TMDB lists the combined title as ONE episode and the segments
        # separately: the exact full-title agreement must win.
        titles = {
            6: "Cat Tales & Dog Tales",
            16: "Cat Tales",
            17: "Dog Tales",
        }
        res = resolve_file(
            parsed_episodes=(6,),
            raw_title="Cat Tales & Dog Tales",
            is_season_relative=True,
            season_titles=titles,
            season=1,
        )
        assert res.episodes == (6,)
        assert "title-agree" in res.evidence

    def test_unresolvable_segments_fall_back_to_number(self):
        # Conflicting partitions across grouping sizes: no unique run, keep
        # the number at review with the multi-segment marker.
        titles = {
            1: "Alpha",
            2: "Beta & Gamma",
            6: "Win",
            11: "Alpha & Beta",
            12: "Gamma",
        }
        res = resolve_file(
            parsed_episodes=(6,),
            raw_title="Alpha & Beta & Gamma",
            is_season_relative=True,
            season_titles=titles,
            season=1,
        )
        assert res.episodes == (6,)
        assert "title-multi-segment" in res.evidence
        assert res.confidence < DEFAULT_EPISODE_AUTO_ACCEPT_THRESHOLD

    def test_single_atom_title_unaffected(self):
        # Plain single-title files keep the existing rule flow (rule 2 exact
        # override here), no segmentation attempt.
        res = resolve_file(
            parsed_episodes=(5,),
            raw_title="Taming of the Screwy",
            is_season_relative=True,
            season_titles=self.ANIMANIACS_S1,
            season=1,
        )
        assert res.episodes == (12,)
        assert res.evidence == frozenset({"title-strong", "number-disagree"})


class TestSpecialsTrust:
    def test_special_number_only_forces_review(self):
        res = resolve_file(
            parsed_episodes=(8,),
            raw_title=None,
            is_season_relative=True,
            season_titles={8: "How to Draw Eddy"},
            season=0,
        )
        assert res.episodes == (8,)
        assert res.confidence == CONF_SPECIAL_NUMBER_ONLY
        assert res.confidence < DEFAULT_EPISODE_AUTO_ACCEPT_THRESHOLD

    def test_special_strong_title_still_wins(self):
        # Exact title for E12 overrides the parsed S00E08 number.
        res = resolve_file(
            parsed_episodes=(8,),
            raw_title="The Grim Adventures of the KND",
            is_season_relative=True,
            season_titles={8: "How to Draw Eddy", 12: "The Grim Adventures of the KND"},
            season=0,
        )
        assert res.episodes == (12,)
        assert res.confidence == CONF_TITLE_WINS

    def test_regular_season_number_only_unchanged(self):
        res = resolve_file(
            parsed_episodes=(4,),
            raw_title=None,
            is_season_relative=True,
            season_titles=S1_TITLES,
            season=1,
        )
        assert res.confidence == CONF_NUMBER_RELATIVE


from pathlib import Path

from plex_renamer.engine._episode_resolution import (
    CONF_TITLE_ONLY,
    CONF_TITLE_WINS_INEXACT,
    CONTRADICTORY_PREFIX_CAP,
    EPISODE_TITLE_MATCH_FLOOR,
    EXACT_COVERAGE_FLOOR,
    EXPLICIT_EPISODE_FLOOR,
    apply_confidence_adjustments,
)
from plex_renamer.engine.episode_assignments import (
    ORIGIN_AUTO,
    ORIGIN_MANUAL,
    REASON_LOST_CONFLICT,
    EpisodeAssignmentTable,
    EpisodeSlot,
)

SHOW = {"id": 7, "name": "Demo Show", "year": "2020"}


def coverage_table(count: int = 3) -> EpisodeAssignmentTable:
    table = EpisodeAssignmentTable()
    for episode in range(1, count + 1):
        table.add_slot(EpisodeSlot(season=1, episode=episode, title=f"Ep {episode}"))
    return table


class TestConfidenceAdjustments:
    def test_explicit_episode_floor(self):
        table = coverage_table()
        entry = table.add_file(
            Path("Demo Show S01E01.mkv"),
            is_season_relative=True,
        )
        table.assign(entry.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=0.5)
        apply_confidence_adjustments(table, show_info=SHOW)
        assert table.assignment_for(entry.file_id).confidence >= EXPLICIT_EPISODE_FLOOR

    def test_title_match_floor(self):
        table = coverage_table()
        entry = table.add_file(
            Path("Demo Show S01E02 - Ep 2.mkv"),
            is_season_relative=True,
            raw_title="Ep 2",
        )
        table.assign(entry.file_id, 1, [2], origin=ORIGIN_AUTO, confidence=0.5)
        apply_confidence_adjustments(table, show_info=SHOW)
        assert table.assignment_for(entry.file_id).confidence >= EPISODE_TITLE_MATCH_FLOOR

    def test_exact_coverage_floor(self):
        table = coverage_table(3)
        for episode in range(1, 4):
            entry = table.add_file(
                Path(f"demo - {episode}.mkv"),
                is_season_relative=False,
            )
            table.assign(entry.file_id, 1, [episode], origin=ORIGIN_AUTO, confidence=0.5)
        apply_confidence_adjustments(table, show_info=SHOW)
        for assignment in table.assignments():
            assert assignment.confidence >= EXACT_COVERAGE_FLOOR

    def test_conflicted_season_gets_no_coverage_floor(self):
        table = coverage_table(3)
        first = table.add_file(Path("a.mkv"), is_season_relative=False)
        second = table.add_file(Path("b.mkv"), is_season_relative=False)
        table.assign(first.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=0.5)
        table.assign(second.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=0.5)
        apply_confidence_adjustments(table, show_info=SHOW)
        assert table.assignment_for(first.file_id).confidence == 0.5

    def test_contradictory_source_prefix_caps(self):
        table = coverage_table()
        entry = table.add_file(
            Path("Totally Different Show S01E01.mkv"),
            is_season_relative=True,
        )
        table.assign(entry.file_id, 1, [1], origin=ORIGIN_AUTO, confidence=0.9)
        apply_confidence_adjustments(table, show_info=SHOW)
        assert table.assignment_for(entry.file_id).confidence <= CONTRADICTORY_PREFIX_CAP

    def test_franchise_prefix_source_is_not_contradictory(self):
        """Andor S2 regression: files named "Star.Wars.Andor.S02E01..." match
        the TMDB show "Andor". The franchise prefix "Star Wars" must NOT make
        the source title contradictory — the show name appears as a trailing
        token group, so confidence must stay at the explicit-episode floor
        (auto-acceptable), not be capped at CONTRADICTORY_PREFIX_CAP.
        """
        show = {"id": 9, "name": "Andor", "year": "2022"}
        table = EpisodeAssignmentTable()
        table.add_slot(EpisodeSlot(season=2, episode=1, title="Ep 1"))
        entry = table.add_file(
            Path("Star.Wars.Andor.S02E01.2160p.DSNP.WEB-DL.mkv"),
            is_season_relative=True,
        )
        table.assign(entry.file_id, 2, [1], origin=ORIGIN_AUTO, confidence=0.86)
        apply_confidence_adjustments(table, show_info=show)
        assert table.assignment_for(entry.file_id).confidence >= EXPLICIT_EPISODE_FLOOR

    def test_season0_title_only_not_capped_by_prefix(self):
        # Real Animaniacs featurette: the "(480p ...)" quality suffix makes
        # extract_source_title_prefix latch the "480" and return the episode
        # TITLE itself as a bogus show prefix, which does not match
        # SHOW["name"] == "Demo Show". Without the season-0 guard the
        # contradictory-prefix cap fires and drops confidence to
        # CONTRADICTORY_PREFIX_CAP (0.45); with the guard it must stay
        # >= CONF_TITLE_ONLY.
        table = EpisodeAssignmentTable()
        table.add_slot(
            EpisodeSlot(
                season=0,
                episode=2,
                title="The Writers Flipped, They Have No Script",
            )
        )
        entry = table.add_file(
            Path(
                "The Writers Flipped, They Have No Script "
                "(480p DVD x265 HEVC 10bit AAC 2.0 Ghost).mkv"
            ),
            is_season_relative=False,
            raw_title="The Writers Flipped, They Have No Script",
            folder_season=0,
        )
        table.assign(
            entry.file_id,
            0,
            [2],
            origin=ORIGIN_AUTO,
            confidence=CONF_TITLE_ONLY,
            evidence=frozenset({"title-strong"}),
        )
        apply_confidence_adjustments(table, show_info=SHOW)
        assert table.assignment_for(entry.file_id).confidence >= CONF_TITLE_ONLY

    def test_special_number_only_survives_adjustments(self):
        from plex_renamer.engine._episode_resolution import CONF_SPECIAL_NUMBER_ONLY
        from plex_renamer.engine._state import DEFAULT_EPISODE_AUTO_ACCEPT_THRESHOLD

        table = EpisodeAssignmentTable()
        table.add_slot(EpisodeSlot(season=0, episode=8, title="How to Draw Eddy"))
        entry = table.add_file(
            Path("Demo Show - S00E08 - Some Special.mkv"),
            is_season_relative=True,
            raw_title="Some Special",
        )
        table.assign(
            entry.file_id,
            0,
            [8],
            origin=ORIGIN_AUTO,
            confidence=CONF_SPECIAL_NUMBER_ONLY,
            evidence=frozenset({"number", "special-number-only"}),
        )
        apply_confidence_adjustments(table, show_info=SHOW)
        assert (
            table.assignment_for(entry.file_id).confidence < DEFAULT_EPISODE_AUTO_ACCEPT_THRESHOLD
        )

    def test_inexact_title_override_survives_floors(self):
        table = EpisodeAssignmentTable()
        for ep in range(1, 4):
            table.add_slot(EpisodeSlot(season=1, episode=ep, title=f"Ep {ep}"))
        entry = table.add_file(
            Path("Demo Show - S01E02 - Ep 1 extras.mkv"),
            is_season_relative=True,
            raw_title="Ep 1 extras",
        )
        table.assign(
            entry.file_id,
            1,
            [1],
            origin=ORIGIN_AUTO,
            confidence=CONF_TITLE_WINS_INEXACT,
            evidence=frozenset({"title-strong-inexact", "number-disagree"}),
        )
        apply_confidence_adjustments(table, show_info=SHOW, show_match_confidence=1.0)
        capped = table.assignment_for(entry.file_id).confidence
        # The compatible-prefix / explicit-episode floors (0.86-0.88) would
        # otherwise lift it above threshold; the cap-last loop pins it to
        # exactly CONF_TITLE_WINS_INEXACT.
        assert capped == CONF_TITLE_WINS_INEXACT
        assert capped < DEFAULT_EPISODE_AUTO_ACCEPT_THRESHOLD


from plex_renamer.engine._episode_resolution import rescue_cross_season_titles
from plex_renamer.engine.episode_assignments import REASON_NO_TITLE_MATCH, REASON_NOT_IN_SEASON


class TestCrossSeasonTitleRescue:
    """As Told By Ginger: the source's Season 1 folder holds episodes TMDB
    lists under Season 2 (S01E17 'I Spy a Witch' == TMDB S2E1). They SKIP as
    'not in TMDB season'; rescue them by exact title into the unclaimed
    regular-season slot, at review confidence (the source numbering is wrong).
    """

    def _ginger_table(self) -> EpisodeAssignmentTable:
        table = EpisodeAssignmentTable()
        for episode in range(1, 14):
            table.add_slot(EpisodeSlot(season=1, episode=episode, title=f"S1 Ep {episode}"))
        table.add_slot(EpisodeSlot(season=2, episode=1, title="I Spy a Witch"))
        table.add_slot(EpisodeSlot(season=2, episode=2, title="Deja Who?"))
        table.add_slot(EpisodeSlot(season=2, episode=3, title="An Even Steven Holiday Special"))
        return table

    def test_rescues_exact_title_into_other_regular_season(self):
        table = self._ginger_table()
        entry = table.add_file(
            Path("ATBG - S01E17 - I Spy a Witch.mkv"),
            parsed_episodes=(17,),
            raw_title="I Spy a Witch",
            folder_season=1,
            is_season_relative=True,
        )
        table.mark_unassigned(entry.file_id, REASON_NOT_IN_SEASON)
        rescue_cross_season_titles(table)
        assignment = table.assignment_for(entry.file_id)
        assert assignment is not None
        assert assignment.season == 2
        assert assignment.episodes == (1,)
        assert assignment.confidence < DEFAULT_EPISODE_AUTO_ACCEPT_THRESHOLD

    def test_rescue_tolerates_trailing_punctuation(self):
        # Source "Deja Who" (no '?') must still match TMDB "Deja Who?".
        table = self._ginger_table()
        entry = table.add_file(
            Path("ATBG - S01E18 - Deja Who.mkv"),
            parsed_episodes=(18,),
            raw_title="Deja Who",
            folder_season=1,
            is_season_relative=True,
        )
        table.mark_unassigned(entry.file_id, REASON_NOT_IN_SEASON)
        rescue_cross_season_titles(table)
        assignment = table.assignment_for(entry.file_id)
        assert assignment is not None and assignment.episodes == (2,)

    def test_does_not_rescue_when_target_slot_claimed(self):
        table = self._ginger_table()
        claimer = table.add_file(Path("other - S02E01.mkv"), is_season_relative=True)
        table.assign(claimer.file_id, 2, [1], origin=ORIGIN_AUTO, confidence=0.9)
        entry = table.add_file(
            Path("ATBG - S01E17 - I Spy a Witch.mkv"),
            parsed_episodes=(17,),
            raw_title="I Spy a Witch",
            folder_season=1,
        )
        table.mark_unassigned(entry.file_id, REASON_NOT_IN_SEASON)
        rescue_cross_season_titles(table)
        assert table.assignment_for(entry.file_id) is None

    def test_does_not_rescue_when_title_ambiguous_across_seasons(self):
        table = self._ginger_table()
        # Same title appears unclaimed in two regular seasons -> ambiguous.
        table.add_slot(EpisodeSlot(season=3, episode=5, title="I Spy a Witch"))
        entry = table.add_file(
            Path("ATBG - S01E17 - I Spy a Witch.mkv"),
            parsed_episodes=(17,),
            raw_title="I Spy a Witch",
            folder_season=1,
        )
        table.mark_unassigned(entry.file_id, REASON_NOT_IN_SEASON)
        rescue_cross_season_titles(table)
        assert table.assignment_for(entry.file_id) is None

    def test_does_not_rescue_other_unassigned_reasons(self):
        table = self._ginger_table()
        entry = table.add_file(
            Path("ATBG - S01E17 - I Spy a Witch.mkv"),
            parsed_episodes=(17,),
            raw_title="I Spy a Witch",
            folder_season=1,
        )
        table.mark_unassigned(entry.file_id, REASON_NO_TITLE_MATCH)
        rescue_cross_season_titles(table)
        assert table.assignment_for(entry.file_id) is None

    def test_does_not_rescue_into_specials(self):
        table = self._ginger_table()
        table.add_slot(EpisodeSlot(season=0, episode=4, title="A Bonus Special"))
        entry = table.add_file(
            Path("ATBG - S01E21 - A Bonus Special.mkv"),
            parsed_episodes=(21,),
            raw_title="A Bonus Special",
            folder_season=1,
        )
        table.mark_unassigned(entry.file_id, REASON_NOT_IN_SEASON)
        rescue_cross_season_titles(table)
        assert table.assignment_for(entry.file_id) is None


class TestConflictResolution:
    def _two_claimants(self, *, title_ev, num_ev, num_origin=ORIGIN_AUTO):
        table = EpisodeAssignmentTable()
        table.add_slot(EpisodeSlot(season=2, episode=10, title="Sibling Revile-ry"))
        title_file = table.add_file(
            Path("ATBG - S02E06 - Sibling Revile-ry.mkv"),
            raw_title="Sibling Revile-ry",
        )
        num_file = table.add_file(
            Path("ATBG - S02E10 - April's Fools.mkv"),
            is_season_relative=True,
        )
        table.assign(
            title_file.file_id,
            2,
            [10],
            origin=ORIGIN_AUTO,
            confidence=CONF_TITLE_WINS,
            evidence=frozenset(title_ev),
        )
        table.assign(
            num_file.file_id,
            2,
            [10],
            origin=num_origin,
            confidence=CONF_NUMBER_RELATIVE,
            evidence=frozenset(num_ev),
        )
        return table, title_file, num_file

    def test_exact_title_beats_number_only(self):
        table, title_file, num_file = self._two_claimants(
            title_ev={"title-strong", "number-disagree"},
            num_ev={"number", "season-relative"},
        )
        apply_confidence_adjustments(table, show_info=SHOW)
        assert table.assignment_for(title_file.file_id) is not None
        assert table.assignment_for(title_file.file_id).episodes == (10,)
        assert table.assignment_for(num_file.file_id) is None
        assert table.unassigned_reasons[num_file.file_id].startswith(REASON_LOST_CONFLICT)
        assert (2, 10) not in table.conflicts()

    def test_title_agree_also_wins(self):
        table, title_file, num_file = self._two_claimants(
            title_ev={"number", "title-agree"},
            num_ev={"number", "season-relative"},
        )
        apply_confidence_adjustments(table, show_info=SHOW)
        assert table.assignment_for(num_file.file_id) is None
        assert (2, 10) not in table.conflicts()

    def test_two_number_only_stays_conflict(self):
        table, title_file, num_file = self._two_claimants(
            title_ev={"number", "season-relative"},
            num_ev={"number", "season-relative"},
        )
        apply_confidence_adjustments(table, show_info=SHOW)
        assert (2, 10) in table.conflicts()

    def test_inexact_title_does_not_evict(self):
        table, title_file, num_file = self._two_claimants(
            title_ev={"title-strong-inexact", "number-disagree"},
            num_ev={"number", "season-relative"},
        )
        apply_confidence_adjustments(table, show_info=SHOW)
        assert (2, 10) in table.conflicts()

    def test_manual_claim_not_evicted(self):
        table, title_file, num_file = self._two_claimants(
            title_ev={"title-strong", "number-disagree"},
            num_ev={"number"},
            num_origin=ORIGIN_MANUAL,
        )
        apply_confidence_adjustments(table, show_info=SHOW)
        assert (2, 10) in table.conflicts()
