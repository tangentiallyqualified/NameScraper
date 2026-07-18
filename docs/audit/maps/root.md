<!-- audit:generated:start map-root -->
### Entry points (nothing imports these)
- `plex_renamer/__init__.py` — fan-in 0, fan-out 0, LOC 7
- `plex_renamer/__main__.py` — fan-in 0, fan-out 1, LOC 37

### Core (widely depended upon)
- `plex_renamer/_lang_normalize.py` — fan-in 3, fan-out 0, LOC 56
- `plex_renamer/_mkv_locate.py` — fan-in 6, fan-out 0, LOC 65
- `plex_renamer/_parsing_titles.py` — fan-in 6, fan-out 1, LOC 275
- `plex_renamer/constants.py` — fan-in 49, fan-out 0, LOC 117
- `plex_renamer/job_store.py` — fan-in 16, fan-out 5, LOC 644
- `plex_renamer/keys.py` — fan-in 4, fan-out 1, LOC 78
- `plex_renamer/parsing.py` — fan-in 24, fan-out 6, LOC 60
- `plex_renamer/thread_pool.py` — fan-in 12, fan-out 0, LOC 66
- `plex_renamer/tmdb.py` — fan-in 7, fan-out 6, LOC 591

### Support
- `plex_renamer/_job_execution_filesystem.py` — fan-in 2, fan-out 3, LOC 219
- `plex_renamer/_job_execution_metadata.py` — fan-in 1, fan-out 4, LOC 277
- `plex_renamer/_job_execution_remux.py` — fan-in 1, fan-out 4, LOC 158
- `plex_renamer/_job_path_propagation.py` — fan-in 1, fan-out 0, LOC 84
- `plex_renamer/_job_store_codec.py` — fan-in 1, fan-out 0, LOC 70
- `plex_renamer/_job_store_db.py` — fan-in 1, fan-out 1, LOC 111
- `plex_renamer/_job_store_ordering.py` — fan-in 1, fan-out 0, LOC 114
- `plex_renamer/_mkv_command.py` — fan-in 2, fan-out 1, LOC 95
- `plex_renamer/_mkv_probe.py` — fan-in 2, fan-out 1, LOC 131
- `plex_renamer/_mkv_tags_render.py` — fan-in 1, fan-out 0, LOC 89
- `plex_renamer/_nfo_render.py` — fan-in 1, fan-out 0, LOC 134
- `plex_renamer/_parsing_episodes.py` — fan-in 1, fan-out 2, LOC 289
- `plex_renamer/_parsing_names.py` — fan-in 1, fan-out 1, LOC 195
- `plex_renamer/_parsing_seasons.py` — fan-in 2, fan-out 1, LOC 153
- `plex_renamer/_parsing_subtitles.py` — fan-in 1, fan-out 1, LOC 88
- `plex_renamer/_parsing_tv.py` — fan-in 1, fan-out 3, LOC 294
- `plex_renamer/_tmdb_batch_search.py` — fan-in 1, fan-out 0, LOC 72
- `plex_renamer/_tmdb_image_cache.py` — fan-in 1, fan-out 0, LOC 237
- `plex_renamer/_tmdb_metadata_builder.py` — fan-in 2, fan-out 0, LOC 135
- `plex_renamer/_tmdb_metadata_cache.py` — fan-in 1, fan-out 0, LOC 218
- `plex_renamer/_tmdb_search_helpers.py` — fan-in 1, fan-out 0, LOC 36
- `plex_renamer/_tmdb_transport.py` — fan-in 1, fan-out 0, LOC 166
- `plex_renamer/job_executor.py` — fan-in 2, fan-out 6, LOC 891

_Generated from audit input cac629f7ebb9 by scripts\audit.cmd._
<!-- audit:generated:end map-root -->
