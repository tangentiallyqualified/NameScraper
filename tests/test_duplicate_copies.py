"""RC28: same-title tied claimants are duplicate copies, not conflicts."""

from pathlib import Path

from plex_renamer.engine._episode_projection import project_preview_items
from plex_renamer.engine._episode_resolution import (
    CONF_AGREE,
    CONF_SPECIAL_NUMBER_ONLY,
    CONF_TITLE_WINS,
    resolve_table_conflicts,
)
from plex_renamer.engine.episode_assignments import (
    REASON_DUPLICATE_COPY,
    EpisodeAssignmentTable,
    EpisodeSlot,
)


def _dexter_table():
    table = EpisodeAssignmentTable()
    table.add_slot(EpisodeSlot(season=1, episode=7, title="Dexter's Rival"))
    table.add_slot(EpisodeSlot(season=1, episode=8, title="Dee Dee's Room"))
    agreeing = table.add_file(
        Path("S01E07 - Dexter's Rival.mkv"),
        parsed_episodes=(7,),
        raw_title="Dexter's Rival",
        is_season_relative=True,
        season_hint=1,
        folder_season=1,
    )
    mislabeled = table.add_file(
        Path("S01E34 - Dexter's Rival.mkv"),
        parsed_episodes=(34,),
        raw_title="Dexter's Rival",
        is_season_relative=True,
        season_hint=1,
        folder_season=1,
    )
    table.assign(
        agreeing.file_id,
        1,
        [7],
        origin="auto",
        confidence=CONF_AGREE,
        evidence=frozenset({"number", "title-agree"}),
    )
    table.assign(
        mislabeled.file_id,
        1,
        [7],
        origin="auto",
        confidence=CONF_TITLE_WINS,
        evidence=frozenset({"title-strong", "number-disagree"}),
    )
    return table, agreeing, mislabeled


def test_differing_numbers_same_title_resolve_as_duplicates():
    table, agreeing, mislabeled = _dexter_table()
    resolve_table_conflicts(table)
    assert table.conflicts() == {}
    assignment = table.assignment_for(agreeing.file_id)
    assert assignment is not None and assignment.episodes == (7,)
    reason = table.unassigned_reasons[mislabeled.file_id]
    assert reason.startswith(REASON_DUPLICATE_COPY)


def test_branded_copy_resolves_as_duplicate():
    # RC43 follow-up: one copy carries the season branding in its title
    # ('Danger Island Comparative Wickedness...'); still the same episode.
    table = EpisodeAssignmentTable()
    title = "Comparative Wickedness of Civilized and Unenlightened Peoples"
    table.add_slot(EpisodeSlot(season=9, episode=7, title=title))
    clean = table.add_file(
        Path("Archer.S09E07.Comparative.Wickedness.mkv"),
        parsed_episodes=(7,),
        raw_title=title,
        is_season_relative=True,
        season_hint=9,
        folder_season=9,
    )
    branded = table.add_file(
        Path("Archer.S09E07.Danger.Island.Comparative.Wickedness.mkv"),
        parsed_episodes=(7,),
        raw_title=f"Danger Island {title}",
        is_season_relative=True,
        season_hint=9,
        folder_season=9,
    )
    for entry in (clean, branded):
        table.assign(
            entry.file_id,
            9,
            [7],
            origin="auto",
            confidence=CONF_AGREE,
            evidence=frozenset({"number", "title-agree"}),
        )
    resolve_table_conflicts(table)
    assert table.conflicts() == {}
    winners = [
        entry for entry in (clean, branded) if table.assignment_for(entry.file_id) is not None
    ]
    assert len(winners) == 1
    loser = clean if winners[0] is branded else branded
    assert table.unassigned_reasons[loser.file_id].startswith(REASON_DUPLICATE_COPY)


def test_variant_tagged_copies_resolve_as_duplicates():
    # RC51: the Powerpuff pilot exists as '(Color)' and '(Pencil)' prints —
    # one episode behind two trailing version tags, not two episodes. The
    # first-registered print wins; the other queues as a duplicate copy.
    table = EpisodeAssignmentTable()
    table.add_slot(EpisodeSlot(season=0, episode=1, title="Whoopass Stew! A Sticky Situation!"))
    color = table.add_file(
        Path("S00E01 - The Whoopass Girls - A Sticky Situation! (Color).mkv"),
        parsed_episodes=(1,),
        raw_title="The Whoopass Girls - A Sticky Situation! (Color)",
        is_season_relative=True,
        season_hint=0,
        folder_season=0,
    )
    pencil = table.add_file(
        Path("S00E01 - The Whoopass Girls - A Sticky Situation! (Pencil).mkv"),
        parsed_episodes=(1,),
        raw_title="The Whoopass Girls - A Sticky Situation! (Pencil)",
        is_season_relative=True,
        season_hint=0,
        folder_season=0,
    )
    for entry in (color, pencil):
        table.assign(
            entry.file_id,
            0,
            [1],
            origin="auto",
            confidence=CONF_SPECIAL_NUMBER_ONLY,
            evidence=frozenset({"number", "special-number-only"}),
        )
    resolve_table_conflicts(table)
    assert table.conflicts() == {}
    assignment = table.assignment_for(color.file_id)
    assert assignment is not None and assignment.episodes == (1,)
    reason = table.unassigned_reasons[pencil.file_id]
    assert reason.startswith(REASON_DUPLICATE_COPY)


def test_numeric_parenthetical_is_not_a_variant_tag():
    # '(1)' vs '(2)' are part numbers — two different episodes squeezed
    # onto one slot must stay a visible conflict, never fold to one copy.
    table = EpisodeAssignmentTable()
    table.add_slot(EpisodeSlot(season=0, episode=1, title="Punchline"))
    part1 = table.add_file(
        Path("S00E01 - Punchline (1).mkv"),
        parsed_episodes=(1,),
        raw_title="Punchline (1)",
        is_season_relative=True,
        season_hint=0,
        folder_season=0,
    )
    part2 = table.add_file(
        Path("S00E01 - Punchline (2).mkv"),
        parsed_episodes=(1,),
        raw_title="Punchline (2)",
        is_season_relative=True,
        season_hint=0,
        folder_season=0,
    )
    for entry in (part1, part2):
        table.assign(
            entry.file_id,
            0,
            [1],
            origin="auto",
            confidence=CONF_SPECIAL_NUMBER_ONLY,
            evidence=frozenset({"number", "special-number-only"}),
        )
    resolve_table_conflicts(table)
    assert (0, 1) in table.conflicts()


def test_duplicate_projects_with_duplicate_status(tmp_path):
    table, _agreeing, _mislabeled = _dexter_table()
    resolve_table_conflicts(table)
    items = project_preview_items(
        table,
        show_info={"name": "Dexter's Laboratory", "year": "1996"},
        root=tmp_path,
        media_fields={},
    )
    duplicate_items = [item for item in items if item.status.startswith("DUPLICATE")]
    assert len(duplicate_items) == 1
    assert duplicate_items[0].is_duplicate
    assert duplicate_items[0].new_name is None
