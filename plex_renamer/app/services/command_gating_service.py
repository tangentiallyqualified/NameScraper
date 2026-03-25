"""Queue command gating extracted from widget click handlers."""

from __future__ import annotations

from collections import Counter

from ...engine import PreviewItem, ScanState, get_checked_indices_from_state
from ..models import QueueCommandState, QueueEligibility


class CommandGatingService:
    """Compute queue eligibility independently of any GUI toolkit."""

    def evaluate_preview_items(
        self,
        items: list[PreviewItem],
        *,
        selected_indices: set[int] | None = None,
        is_scanning: bool = False,
        is_queued: bool = False,
        needs_review: bool = False,
        require_resolved_review: bool = False,
    ) -> QueueEligibility:
        """Return queue command state for a flat preview item list."""
        if is_scanning:
            return QueueEligibility(
                command_state=QueueCommandState.DISABLED_SCANNING,
                reason="Scan is still running.",
            )

        if is_queued:
            return QueueEligibility(
                command_state=QueueCommandState.DISABLED_ALREADY_QUEUED,
                reason="This item already has a pending queue job.",
            )

        if require_resolved_review and needs_review:
            return QueueEligibility(
                command_state=QueueCommandState.DISABLED_UNRESOLVED_REVIEW,
                reason="Review the current match before queueing.",
            )

        if not items:
            return QueueEligibility(
                command_state=QueueCommandState.DISABLED_NO_SELECTION,
                reason="Scan and review files before queueing.",
            )

        selected = set(selected_indices or set())
        actionable = [index for index, item in enumerate(items) if self.is_actionable_item(item)]
        eligible_selected = sorted(index for index in selected if index in actionable)
        blocked_counts = self._blocked_counts(items)

        if eligible_selected:
            return QueueEligibility(
                command_state=QueueCommandState.ENABLED,
                reason=f"{len(eligible_selected)} file(s) eligible for queueing.",
                actionable_indices=actionable,
                selected_indices=eligible_selected,
                blocked_counts=blocked_counts,
                eligible_file_count=len(eligible_selected),
                eligible_job_count=1,
            )

        if actionable and not selected:
            return QueueEligibility(
                command_state=QueueCommandState.DISABLED_NO_SELECTION,
                reason="Select at least one actionable file.",
                actionable_indices=actionable,
                blocked_counts=blocked_counts,
            )

        if blocked_counts.get("conflict"):
            return QueueEligibility(
                command_state=QueueCommandState.DISABLED_CONFLICT,
                reason="Resolve conflicting targets before queueing.",
                actionable_indices=actionable,
                blocked_counts=blocked_counts,
            )

        return QueueEligibility(
            command_state=QueueCommandState.DISABLED_NO_ACTION_NEEDED,
            reason="No actionable rename operations are selected.",
            actionable_indices=actionable,
            blocked_counts=blocked_counts,
        )

    def evaluate_scan_state(
        self,
        state: ScanState,
        *,
        require_resolved_review: bool = False,
    ) -> QueueEligibility:
        """Return queue command state for a ScanState."""
        selected: set[int] = set()
        if state.check_vars:
            selected = get_checked_indices_from_state(state)
        elif state.checked:
            selected = {
                index for index, item in enumerate(state.preview_items)
                if self.is_actionable_item(item)
            }

        if not state.scanned and not state.preview_items:
            return QueueEligibility(
                command_state=QueueCommandState.DISABLED_NO_SELECTION,
                reason="Scan and review files before queueing.",
            )

        return self.evaluate_preview_items(
            state.preview_items,
            selected_indices=selected,
            is_scanning=state.scanning,
            is_queued=state.queued,
            needs_review=state.needs_review,
            require_resolved_review=require_resolved_review,
        )

    def summarize_scan_states(
        self,
        states: list[ScanState],
        *,
        require_resolved_review: bool = False,
    ) -> QueueEligibility:
        """Aggregate queue eligibility across multiple ScanState objects."""
        eligible_jobs = 0
        eligible_files = 0
        blocked = Counter()

        for state in states:
            result = self.evaluate_scan_state(
                state,
                require_resolved_review=require_resolved_review,
            )
            if result.enabled:
                eligible_jobs += 1
                eligible_files += result.eligible_file_count
            else:
                blocked[result.command_state.value] += 1

        if eligible_jobs:
            return QueueEligibility(
                command_state=QueueCommandState.ENABLED,
                reason=f"{eligible_jobs} job(s) and {eligible_files} file(s) eligible for queueing.",
                eligible_file_count=eligible_files,
                eligible_job_count=eligible_jobs,
                blocked_counts=dict(blocked),
            )

        if blocked.get(QueueCommandState.DISABLED_SCANNING.value):
            state = QueueCommandState.DISABLED_SCANNING
            reason = "At least one selected item is still scanning."
        elif blocked.get(QueueCommandState.DISABLED_UNRESOLVED_REVIEW.value):
            state = QueueCommandState.DISABLED_UNRESOLVED_REVIEW
            reason = "At least one selected item still needs review."
        elif blocked.get(QueueCommandState.DISABLED_CONFLICT.value):
            state = QueueCommandState.DISABLED_CONFLICT
            reason = "Conflicting targets block the current queue selection."
        elif blocked.get(QueueCommandState.DISABLED_ALREADY_QUEUED.value):
            state = QueueCommandState.DISABLED_ALREADY_QUEUED
            reason = "The current selection is already queued."
        else:
            state = QueueCommandState.DISABLED_NO_ACTION_NEEDED
            reason = "No actionable jobs are selected."

        return QueueEligibility(
            command_state=state,
            reason=reason,
            blocked_counts=dict(blocked),
        )

    @staticmethod
    def is_actionable_item(item: PreviewItem) -> bool:
        """True when an item can become a queued rename operation."""
        if item.new_name is None:
            return False
        if item.status != "OK" and "UNMATCHED" not in item.status:
            return False
        target_dir = item.target_dir or item.original.parent
        if item.new_name == item.original.name and target_dir == item.original.parent:
            return False
        return True

    @classmethod
    def _blocked_counts(cls, items: list[PreviewItem]) -> dict[str, int]:
        counter: Counter[str] = Counter()
        for item in items:
            if cls.is_actionable_item(item):
                continue
            status = item.status.upper()
            if status.startswith("CONFLICT"):
                counter["conflict"] += 1
            elif status.startswith("SKIP"):
                counter["skip"] += 1
            elif status.startswith("REVIEW"):
                counter["review"] += 1
            else:
                counter["other"] += 1
        return dict(counter)