<!-- audit:generated:start map-app -->
### Entry points (nothing imports these)
- `plex_renamer/app/__init__.py` — fan-in 0, fan-out 3, LOC 37

### Core (widely depended upon)
- `plex_renamer/app/controllers/_controller_match_helpers.py` — fan-in 3, fan-out 6, LOC 138
- `plex_renamer/app/controllers/_tv_batch_helpers.py` — fan-in 3, fan-out 6, LOC 383
- `plex_renamer/app/models/__init__.py` — fan-in 23, fan-out 1, LOC 39
- `plex_renamer/app/models/state_models.py` — fan-in 4, fan-out 0, LOC 241
- `plex_renamer/app/services/automux_service.py` — fan-in 5, fan-out 5, LOC 196
- `plex_renamer/app/services/cache_service.py` — fan-in 3, fan-out 3, LOC 275
- `plex_renamer/app/services/command_gating_service.py` — fan-in 10, fan-out 4, LOC 268
- `plex_renamer/app/services/episode_mapping_service.py` — fan-in 5, fan-out 5, LOC 500
- `plex_renamer/app/services/refresh_policy_service.py` — fan-in 4, fan-out 2, LOC 156
- `plex_renamer/app/services/settings_service.py` — fan-in 8, fan-out 3, LOC 521
- `plex_renamer/app/services/tv_library_discovery_service.py` — fan-in 3, fan-out 2, LOC 193

### Support
- `plex_renamer/app/controllers/__init__.py` — fan-in 1, fan-out 5, LOC 24
- `plex_renamer/app/controllers/_controller_event_helpers.py` — fan-in 2, fan-out 5, LOC 93
- `plex_renamer/app/controllers/_controller_lifecycle_workflow.py` — fan-in 1, fan-out 2, LOC 60
- `plex_renamer/app/controllers/_controller_movie_workflows.py` — fan-in 1, fan-out 5, LOC 73
- `plex_renamer/app/controllers/_controller_projection_workflow.py` — fan-in 1, fan-out 3, LOC 39
- `plex_renamer/app/controllers/_controller_session_models.py` — fan-in 1, fan-out 2, LOC 35
- `plex_renamer/app/controllers/_controller_state_helpers.py` — fan-in 2, fan-out 4, LOC 88
- `plex_renamer/app/controllers/_controller_tv_workflows.py` — fan-in 1, fan-out 6, LOC 110
- `plex_renamer/app/controllers/_job_projection_helpers.py` — fan-in 1, fan-out 2, LOC 216
- `plex_renamer/app/controllers/_match_state_helpers.py` — fan-in 1, fan-out 3, LOC 190
- `plex_renamer/app/controllers/_movie_batch_helpers.py` — fan-in 2, fan-out 4, LOC 198
- `plex_renamer/app/controllers/_movie_state_helpers.py` — fan-in 2, fan-out 3, LOC 145
- `plex_renamer/app/controllers/_queue_history_helpers.py` — fan-in 1, fan-out 3, LOC 58
- `plex_renamer/app/controllers/_queue_submission_helpers.py` — fan-in 1, fan-out 7, LOC 245
- `plex_renamer/app/controllers/_scan_operation_helpers.py` — fan-in 1, fan-out 2, LOC 62
- `plex_renamer/app/controllers/_single_show_scan_helpers.py` — fan-in 1, fan-out 5, LOC 117
- `plex_renamer/app/controllers/_tab_session_helpers.py` — fan-in 2, fan-out 2, LOC 128
- `plex_renamer/app/controllers/_tv_state_helpers.py` — fan-in 2, fan-out 5, LOC 84
- `plex_renamer/app/controllers/media_controller.py` — fan-in 2, fan-out 19, LOC 546
- `plex_renamer/app/controllers/queue_controller.py` — fan-in 2, fan-out 7, LOC 259
- `plex_renamer/app/services/__init__.py` — fan-in 1, fan-out 7, LOC 19
- `plex_renamer/app/services/_movie_library_classification.py` — fan-in 1, fan-out 3, LOC 184
- `plex_renamer/app/services/_settings_schema.py` — fan-in 1, fan-out 0, LOC 126
- `plex_renamer/app/services/_tv_library_classification.py` — fan-in 1, fan-out 3, LOC 345
- `plex_renamer/app/services/episode_projection_cache.py` — fan-in 1, fan-out 4, LOC 211
- `plex_renamer/app/services/metadata_service.py` — fan-in 2, fan-out 7, LOC 403
- `plex_renamer/app/services/movie_library_discovery_service.py` — fan-in 1, fan-out 2, LOC 124
- `plex_renamer/app/services/output_destination_service.py` — fan-in 2, fan-out 0, LOC 108

_Generated from audit input 8b6d50a0f713 by scripts\audit.cmd._
<!-- audit:generated:end map-app -->
