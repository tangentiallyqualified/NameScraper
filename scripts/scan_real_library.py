"""Real-library TV batch scan harness (validation, not a test).

Runs the real BatchTVOrchestrator discover + scan_all pipeline against the
library root and dumps per-show evidence (preview items, assignment table,
conflicts, unclaimed slots, TMDB slots) plus a discovery summary. Used to
root-cause and re-validate batch TV bugs against real files — see
docs/superpowers/plans/2026-07-01-batch-tv-bug-investigation.md and
2026-07-02-batch-tv-bug-investigation-round2.md.

Usage (from the repo root, always via the venv):
    .venv\\Scripts\\python.exe scripts\\scan_real_library.py
    .venv\\Scripts\\python.exe scripts\\scan_real_library.py --targets frieren catdog
    .venv\\Scripts\\python.exe scripts\\scan_real_library.py --discover-only

Requires the library drive to be mounted and a TMDB API key resolvable via
plex_renamer.keys.get_api_key("TMDB"). Output goes to .scan-dumps\\
(gitignored); each run overwrites the previous dumps.
"""
from __future__ import annotations

import argparse
import logging
import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

DEFAULT_ROOT = Path(r"P:\data\downloads\in progress files")
DEFAULT_OUT = REPO / ".scan-dumps"


def log_setup(out_dir: Path) -> None:
    handler = logging.FileHandler(out_dir / "engine.log", mode="w", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger("plex_renamer")
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)


def is_target(state, targets: list[str]) -> bool:
    if not targets:
        return True
    hay = f"{state.display_name} {state.folder}".lower()
    return any(t.lower() in hay for t in targets)


def dump_state(state, fh) -> None:
    mi = state.media_info or {}
    fh.write(f"=== {state.display_name} ===\n")
    fh.write(f"folder: {state.folder}\n")
    fh.write(f"relative_folder: {state.relative_folder}\n")
    fh.write(
        f"show_id={state.show_id} name={mi.get('name')} "
        f"first_air={mi.get('first_air_date')} confidence={state.confidence:.3f} "
        f"needs_review={getattr(state, 'needs_review', '?')} tie={state.tie_detected}\n"
    )
    fh.write(f"match_origin={state.match_origin} duplicate_of={state.duplicate_of}\n")
    fh.write(f"season_assignment={state.season_assignment}\n")
    fh.write(f"has_direct_season_subdirs={state.has_direct_season_subdirs} "
             f"direct_episode_files={state.direct_episode_file_count} "
             f"direct_videos={state.direct_video_file_count}\n")
    fh.write("season_folders:\n")
    for num, entry in sorted((state.season_folders or {}).items()):
        fh.write(f"  {num}: {entry}\n")
    fh.write(f"alternates: {[a.get('name') for a in state.alternate_matches][:5]}\n")
    fh.write(f"top search_results: "
             f"{[(r.get('name'), (r.get('first_air_date') or '')[:4], r.get('id')) for r in state.search_results[:6]]}\n")
    fh.write(f"scanned={state.scanned} checked={state.checked}\n")

    if state.completeness is not None:
        fh.write(f"completeness: {state.completeness!r}\n")

    fh.write("\n--- preview items ---\n")

    def sort_key(item):
        return (
            item.season if item.season is not None else 999,
            item.episodes[0] if item.episodes else 999,
            str(item.original),
        )

    for item in sorted(state.preview_items, key=sort_key):
        eps = ",".join(f"{e:02d}" for e in item.episodes) or "-"
        fh.write(
            f"S{item.season if item.season is not None else '??'}E{eps} "
            f"conf={item.episode_confidence:.2f} status={item.status}\n"
            f"    src={item.original}\n"
            f"    new={item.new_name}\n"
            f"    target={item.target_dir} srcfolder={item.source_relative_folder} file_id={item.file_id}\n"
        )

    table = state.assignments
    if table is None:
        fh.write("\n(no assignment table)\n\n")
        return

    fh.write("\n--- assignment table: files ---\n")
    for fid, entry in sorted(table.files.items()):
        fh.write(
            f"file {fid}: {entry.path.name}\n"
            f"    parsed={entry.parsed_episodes} raw_title={entry.raw_title!r} "
            f"season_rel={entry.is_season_relative} season_hint={entry.season_hint} "
            f"folder_season={entry.folder_season} extras={entry.from_extras_folder}\n"
            f"    folder={entry.source_relative_folder}\n"
        )

    fh.write("\n--- assignments ---\n")
    for a in sorted(table.assignments(), key=lambda a: (a.season, a.episodes)):
        entry = table.files.get(a.file_id)
        name = entry.path.name if entry else "?"
        fh.write(
            f"S{a.season:02d}E{','.join(f'{e:02d}' for e in a.episodes)} "
            f"origin={a.origin} conf={a.confidence:.2f} approved={a.approved} "
            f"evidence={sorted(a.evidence)} file={name}\n"
        )

    fh.write("\n--- unassigned files ---\n")
    for entry, reason in table.unassigned_files():
        fh.write(f"{entry.path.name}: {reason}\n")

    fh.write("\n--- conflicts ---\n")
    for (season, episode), claims in sorted(table.conflicts().items()):
        names = [table.files[c.file_id].path.name for c in claims]
        fh.write(f"S{season:02d}E{episode:02d}: {names}\n")

    fh.write("\n--- unclaimed slots ---\n")
    for slot in table.unclaimed_slots():
        fh.write(f"S{slot.season:02d}E{slot.episode:02d} {slot.title!r}\n")

    fh.write("\n--- all slots (TMDB) ---\n")
    for (season, episode), slot in sorted(table.slots.items()):
        fh.write(f"S{season:02d}E{episode:02d} {slot.title!r}\n")
    fh.write("\n\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT,
                        help=f"library root to scan (default: {DEFAULT_ROOT})")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help=f"dump directory (default: {DEFAULT_OUT})")
    parser.add_argument("--targets", nargs="*", default=[],
                        help="only dump shows whose name/folder contains one of "
                             "these substrings (default: dump all)")
    parser.add_argument("--discover-only", action="store_true",
                        help="run discovery and write discovery.txt only")
    args = parser.parse_args()

    if not args.root.exists():
        print(f"library root not found: {args.root}")
        sys.exit(2)
    args.out.mkdir(exist_ok=True)
    log_setup(args.out)

    from plex_renamer.keys import get_api_key
    from plex_renamer.tmdb import TMDBClient
    from plex_renamer.engine._batch_orchestrators import BatchTVOrchestrator
    from plex_renamer.engine import _state as engine_state

    api_key = get_api_key("TMDB")
    if not api_key:
        print("NO API KEY (plex_renamer.keys.get_api_key('TMDB') returned nothing)")
        sys.exit(2)

    tmdb = TMDBClient(api_key)
    orch = BatchTVOrchestrator(tmdb, args.root)

    print("discovering...", flush=True)
    states = orch.discover_shows()
    print(f"discovered {len(states)} states", flush=True)

    thresholds = {}
    for name in dir(engine_state):
        if "threshold" in name.lower():
            try:
                value = getattr(engine_state, name)
                thresholds[name] = value() if callable(value) else value
            except Exception as err:  # pragma: no cover
                thresholds[name] = f"err {err}"

    with open(args.out / "discovery.txt", "w", encoding="utf-8") as fh:
        fh.write(f"thresholds: {thresholds}\n\n")
        for state in states:
            fh.write(
                f"{state.display_name!r} conf={state.confidence:.3f} "
                f"needs_review={getattr(state, 'needs_review', '?')} tie={state.tie_detected} "
                f"dup_of={state.duplicate_of} show_id={state.show_id} "
                f"season_assignment={state.season_assignment}\n"
                f"    folder={state.folder}\n"
                f"    seasons={sorted((state.season_folders or {}).keys())}\n"
            )
    if args.discover_only:
        print("DONE (discover only)", flush=True)
        return

    print("scanning all...", flush=True)
    orch.scan_all()
    print("scan_all done", flush=True)

    for state in orch.states:
        if not is_target(state, args.targets):
            continue
        safe = "".join(
            c if c.isalnum() or c in " -_" else "_" for c in state.display_name
        )[:60]
        path = args.out / f"show_{safe.strip() or 'unknown'}_{id(state)}.txt"
        try:
            with open(path, "w", encoding="utf-8") as fh:
                dump_state(state, fh)
        except Exception:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write("\nDUMP ERROR:\n" + traceback.format_exc())
        print(f"dumped {path.name}", flush=True)

    print("DONE", flush=True)


if __name__ == "__main__":
    main()
