"""
Queue and History panels — built as separate top-level tabs.

build_queue_tab:  Pending/running jobs with Start/Stop, Up/Down/Remove.
build_history_tab: Completed/failed/reverted jobs with Revert/Clear.

Both use Treeview with poster thumbnails in tree column #0.
Action bars and detail panels are packed BEFORE the treeview so
they always remain visible (treeview expands to fill remaining space).
"""

from __future__ import annotations

import logging
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

from ..constants import JobKind, JobStatus
from ..job_executor import QueueExecutor, revert_job
from ..job_store import JobStore, RenameJob
from ..styles import COLORS

if TYPE_CHECKING:
    from .app import PlexRenamerApp

_log = logging.getLogger(__name__)

# ─── Display helpers ─────────────────────────────────────────────────────────

_STATUS_LABELS = {
    JobStatus.PENDING: "⏳ Pending",
    JobStatus.RUNNING: "▶ Running",
    JobStatus.COMPLETED: "✓ Completed",
    JobStatus.FAILED: "✗ Failed",
    JobStatus.CANCELLED: "— Cancelled",
    JobStatus.REVERTED: "↩ Reverted",
}
_STATUS_COLORS = {
    JobStatus.PENDING: COLORS["text_dim"],
    JobStatus.RUNNING: COLORS["accent"],
    JobStatus.COMPLETED: COLORS["success"],
    JobStatus.FAILED: COLORS["error"],
    JobStatus.CANCELLED: COLORS["text_muted"],
    JobStatus.REVERTED: COLORS["info"],
}
_KIND_LABELS = {"rename": "Rename", "subtitle": "Subtitles", "metadata": "Metadata"}

_POSTER_W = 60
_POSTER_H = 90


def _fmt(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%b %d, %H:%M")
    except (ValueError, TypeError):
        return iso[:16] if iso else ""


def _mtype(mt: str) -> str:
    return {"tv": "TV", "movie": "Movie"}.get(mt, mt.title())


# ─── Poster cache ────────────────────────────────────────────────────────────

def _poster(app, job: RenameJob):
    cache = getattr(app, "_qp_cache", None)
    if cache is None:
        cache = {}
        app._qp_cache = cache
    key = (job.media_type, job.tmdb_id)
    if key in cache:
        return cache[key]
    tmdb = app._ensure_tmdb()
    if not tmdb:
        return None
    try:
        img = tmdb.fetch_poster(job.tmdb_id, job.media_type,
                                target_width=_POSTER_W * 2)
        if img:
            from PIL import ImageTk
            img = img.resize((_POSTER_W, _POSTER_H))
            photo = ImageTk.PhotoImage(img)
            cache[key] = photo
            return photo
    except Exception:
        pass
    return None


# ─── Treeview factory ────────────────────────────────────────────────────────

def _make_tree(parent: ttk.Frame, columns: tuple) -> ttk.Treeview:
    """Create treeview with poster column + data columns + scrollbar.

    Returns the Treeview.  The enclosing frame is packed with
    fill=both expand=True so it takes remaining space AFTER any
    widgets that were packed before it in *parent*.
    """
    frame = ttk.Frame(parent)
    frame.pack(fill="both", expand=True, padx=4, pady=(4, 0))

    tree = ttk.Treeview(
        frame, columns=columns, show="tree headings",
        selectmode="extended")
    tree.heading("#0", text="", anchor="w")
    tree.column("#0", width=_POSTER_W + 16, minwidth=_POSTER_W + 8,
                stretch=False)

    scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    tree.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")

    for s, clr in _STATUS_COLORS.items():
        tree.tag_configure(f"st_{s}", foreground=clr)

    return tree


def _configure_columns(tree, cols_cfg):
    """Configure headings and columns from a list of (id, heading, width, anchor)."""
    for col_id, heading, width, anchor in cols_cfg:
        tree.heading(col_id, text=heading, anchor=anchor)
        tree.column(col_id, width=width, minwidth=int(width * 0.6),
                    anchor=anchor)


def _sel_jobs(store, tree, ids):
    out = []
    for item in tree.selection():
        idx = tree.index(item)
        if idx < len(ids):
            j = store.get_job(ids[idx])
            if j:
                out.append((ids[idx], j))
    return out


def _job_detail(job, lbl):
    lines = [job.media_name]
    lines.append(
        f"Status: {_STATUS_LABELS.get(job.status, job.status)}"
        f"    •    {_mtype(job.media_type)}"
        f"    •    {_KIND_LABELS.get(job.job_kind, job.job_kind.title())}")
    lines.append(f"Source: {job.source_folder}")
    if job.show_folder_rename:
        lines.append(f"Folder rename → {job.show_folder_rename}")
    lines.append(
        f"Files: {job.selected_count}/{len(job.rename_ops)} selected")
    if job.error_message:
        lines.append(f"Error: {job.error_message}")
    if job.undo_data:
        rn = len(job.undo_data.get("renames", []))
        dr = len(job.undo_data.get("renamed_dirs", []))
        ps = []
        if rn:
            ps.append(f"{rn} file(s)")
        if dr:
            ps.append(f"{dr} dir(s)")
        if ps:
            lines.append(f"Result: {', '.join(ps)} renamed")
    if job.depends_on:
        lines.append(f"Depends on: {job.depends_on[:8]}…")
    lbl.configure(text="\n".join(lines))


# ══════════════════════════════════════════════════════════════════════════════
#  QUEUE TAB
# ══════════════════════════════════════════════════════════════════════════════

def build_queue_tab(app: PlexRenamerApp, parent: ttk.Frame) -> None:
    c = COLORS
    store = app.job_store
    executor = app.queue_executor
    job_ids: list[str] = []
    _listeners_registered = False

    # ── Toolbar (top) ─────────────────────────────────────────────
    toolbar = ttk.Frame(parent, style="Mid.TFrame")
    toolbar.pack(fill="x", side="top")
    tb = ttk.Frame(toolbar, style="Mid.TFrame")
    tb.pack(fill="x", padx=16, pady=10)

    btn_start = ttk.Button(tb, text="▶  Start Queue", style="Accent.TButton")
    btn_start.pack(side="left", padx=(0, 20))

    lbl_status = ttk.Label(
        tb, text="Queue empty", foreground=c["text_dim"],
        background=c["bg_mid"], font=("Helvetica", 10))
    lbl_status.pack(side="left", fill="x", expand=True)

    ttk.Button(tb, text="↻  Refresh", style="Small.TButton",
               command=lambda: _refresh()).pack(side="right")

    ttk.Separator(parent, orient="horizontal").pack(fill="x", side="top")

    # ── Detail panel (bottom, packed first so it stays visible) ───
    det_fr = ttk.Frame(parent, style="Mid.TFrame")
    det_fr.pack(fill="x", side="bottom", padx=8, pady=(0, 6))
    det_lbl = ttk.Label(
        det_fr, text="Select a job to see details",
        foreground=c["text_dim"], background=c["bg_mid"],
        font=("Helvetica", 10), wraplength=900, justify="left")
    det_lbl.pack(fill="x", padx=12, pady=8)

    # ── Action bar (above detail, packed second from bottom) ──────
    bar = ttk.Frame(parent)
    bar.pack(fill="x", side="bottom", padx=8, pady=(4, 0))

    btn_up = ttk.Button(bar, text="▲ Up", style="Small.TButton",
                        state="disabled", command=lambda: _move(-1))
    btn_up.pack(side="left", padx=(0, 4))
    btn_down = ttk.Button(bar, text="▼ Down", style="Small.TButton",
                          state="disabled", command=lambda: _move(1))
    btn_down.pack(side="left")

    info_lbl = ttk.Label(bar, text="", foreground=c["text_dim"])
    info_lbl.pack(side="left", fill="x", expand=True, padx=12)

    btn_rm = ttk.Button(bar, text="✕  Remove Selected",
                        style="Danger.TButton", state="disabled",
                        command=lambda: _remove())
    btn_rm.pack(side="right")

    # ── Treeview (fills remaining space) ──────────────────────────
    tree = _make_tree(parent, ("status", "name", "type", "action", "files", "added"))
    _configure_columns(tree, [
        ("status", "Status", 110, "center"),
        ("name", "Name", 320, "w"),
        ("type", "Type", 55, "center"),
        ("action", "Action", 75, "center"),
        ("files", "Files", 50, "center"),
        ("added", "Added", 120, "center"),
    ])

    # ── Selection ─────────────────────────────────────────────────

    def _on_sel(_e):
        sel = tree.selection()
        n = len(sel)
        if not n:
            info_lbl.configure(text="")
            det_lbl.configure(text="Select a job to see details")
            btn_rm.configure(state="disabled")
            btn_up.configure(state="disabled")
            btn_down.configure(state="disabled")
            return
        jobs = _sel_jobs(store, tree, job_ids)
        btn_rm.configure(state="normal" if any(
            j.status == JobStatus.PENDING for _, j in jobs) else "disabled")
        btn_up.configure(state="normal" if any(
            j.status == JobStatus.PENDING for _, j in jobs) else "disabled")
        btn_down.configure(state="normal" if any(
            j.status == JobStatus.PENDING for _, j in jobs) else "disabled")
        if n > 1:
            info_lbl.configure(text=f"{n} jobs selected")
            det_lbl.configure(text=f"{n} jobs selected")
        else:
            info_lbl.configure(text="")
            idx = tree.index(sel[0])
            if idx < len(job_ids):
                j = store.get_job(job_ids[idx])
                if j:
                    _job_detail(j, det_lbl)

    tree.bind("<<TreeviewSelect>>", _on_sel)

    # ── Refresh ───────────────────────────────────────────────────

    def _refresh():
        nonlocal job_ids
        tree.delete(*tree.get_children())
        job_ids = []
        for job in store.get_queue():
            tag = f"st_{job.status}"
            p = _poster(app, job)
            kw = {"image": p} if p else {}
            tree.insert("", "end", **kw, values=(
                _STATUS_LABELS.get(job.status, job.status),
                job.media_name,
                _mtype(job.media_type),
                _KIND_LABELS.get(job.job_kind, job.job_kind.title()),
                str(job.selected_count),
                _fmt(job.created_at),
            ), tags=(tag,))
            job_ids.append(job.job_id)

        counts = store.count_by_status()
        pend = counts.get(JobStatus.PENDING, 0)
        run = counts.get(JobStatus.RUNNING, 0)
        parts = []
        if run: parts.append(f"{run} running")
        if pend: parts.append(f"{pend} pending")
        lbl_status.configure(
            text="  ·  ".join(parts) if parts else "Queue empty")
        btn_start.configure(
            text="■  Stop Queue" if executor.is_running
            else "▶  Start Queue")

        btn_rm.configure(state="disabled")
        btn_up.configure(state="disabled")
        btn_down.configure(state="disabled")
        app._update_queue_badge()

    app._queue_tab_refresh = _refresh

    # ── Actions ───────────────────────────────────────────────────

    def _toggle():
        if executor.is_running:
            executor.stop(); _refresh()
        else:
            _start()
    btn_start.configure(command=_toggle)

    def _start():
        nonlocal _listeners_registered
        if _listeners_registered:
            executor.clear_listeners()
            def _b(*_a):
                app.root.after(0, app._update_queue_badge)
                app.root.after(0, app._refresh_queue_tab)
                if hasattr(app, '_history_tab_refresh'):
                    app.root.after(0, app._refresh_history_tab)
            executor.add_listener(
                on_started=lambda j: _b(),
                on_completed=lambda j, r: _b(),
                on_failed=lambda j, e: _b(),
                on_finished=lambda: _b())
        executor.add_listener(
            on_started=lambda j: app.root.after(0, _refresh),
            on_completed=lambda j, r: app.root.after(0, _refresh),
            on_failed=lambda j, e: app.root.after(0, _refresh),
            on_finished=lambda: app.root.after(0, _refresh))
        _listeners_registered = True
        executor.start()
        _refresh()

    def _remove():
        jobs = _sel_jobs(store, tree, job_ids)
        ok = [(i, j) for i, j in jobs if j.status == JobStatus.PENDING]
        run = [(i, j) for i, j in jobs if j.status == JobStatus.RUNNING]
        if not ok and run:
            messagebox.showinfo("Cannot Remove",
                f"{len(run)} running. Stop the queue first.")
            return
        if not ok: return
        names = [j.media_name for _, j in ok[:5]]
        sfx = f"\n… +{len(ok)-5} more" if len(ok) > 5 else ""
        if not messagebox.askyesno("Remove Jobs",
            f"Remove {len(ok)} job(s)?\n\n"
            + "\n".join(f"  • {n}" for n in names) + sfx):
            return
        for jid, _ in ok: store.update_status(jid, JobStatus.CANCELLED)
        store.remove_jobs([jid for jid, _ in ok])
        _refresh()
        _lib_refresh(app, ok)

    def _move(d):
        jobs = _sel_jobs(store, tree, job_ids)
        ids = [jid for jid, j in jobs if j.status == JobStatus.PENDING]
        if not ids: return
        store.move_jobs(ids, d)
        _refresh()
        for ch in tree.get_children():
            idx = tree.index(ch)
            if idx < len(job_ids) and job_ids[idx] in ids:
                tree.selection_add(ch)

    _refresh()


# ══════════════════════════════════════════════════════════════════════════════
#  HISTORY TAB
# ══════════════════════════════════════════════════════════════════════════════

def build_history_tab(app: PlexRenamerApp, parent: ttk.Frame) -> None:
    c = COLORS
    store = app.job_store
    job_ids: list[str] = []

    # ── Detail (bottom, packed first) ─────────────────────────────
    det_fr = ttk.Frame(parent, style="Mid.TFrame")
    det_fr.pack(fill="x", side="bottom", padx=8, pady=(0, 6))
    det_lbl = ttk.Label(
        det_fr, text="Select a job to see details",
        foreground=c["text_dim"], background=c["bg_mid"],
        font=("Helvetica", 10), wraplength=900, justify="left")
    det_lbl.pack(fill="x", padx=12, pady=8)

    # ── Action bar ────────────────────────────────────────────────
    bar = ttk.Frame(parent)
    bar.pack(fill="x", side="bottom", padx=8, pady=(4, 0))

    btn_revert = ttk.Button(bar, text="↩  Revert Selected",
                            style="Small.TButton", state="disabled",
                            command=lambda: _revert())
    btn_revert.pack(side="left")

    h_info = ttk.Label(bar, text="", foreground=c["text_dim"])
    h_info.pack(side="left", fill="x", expand=True, padx=12)

    btn_clear = ttk.Button(bar, text="🗑  Clear All History",
                           style="Danger.TButton",
                           command=lambda: _clear())
    btn_clear.pack(side="right")

    # ── Treeview ──────────────────────────────────────────────────
    tree = _make_tree(parent, ("status", "name", "type", "action", "files", "done"))
    _configure_columns(tree, [
        ("status", "Status", 110, "center"),
        ("name", "Name", 320, "w"),
        ("type", "Type", 55, "center"),
        ("action", "Action", 75, "center"),
        ("files", "Files", 50, "center"),
        ("done", "Completed", 120, "center"),
    ])

    # ── Selection ─────────────────────────────────────────────────

    def _on_sel(_e):
        sel = tree.selection()
        n = len(sel)
        if not n:
            h_info.configure(text="")
            det_lbl.configure(text="Select a job to see details")
            btn_revert.configure(state="disabled")
            return
        jobs = _sel_jobs(store, tree, job_ids)
        ok = any(j.status == JobStatus.COMPLETED and j.undo_data
                 for _, j in jobs)
        btn_revert.configure(state="normal" if ok else "disabled")
        if n > 1:
            h_info.configure(text=f"{n} jobs selected")
            det_lbl.configure(text=f"{n} jobs selected")
        else:
            h_info.configure(text="")
            idx = tree.index(sel[0])
            if idx < len(job_ids):
                j = store.get_job(job_ids[idx])
                if j:
                    _job_detail(j, det_lbl)

    tree.bind("<<TreeviewSelect>>", _on_sel)

    # ── Refresh ───────────────────────────────────────────────────

    def _refresh():
        nonlocal job_ids
        tree.delete(*tree.get_children())
        job_ids = []
        for job in store.get_history():
            tag = f"st_{job.status}"
            p = _poster(app, job)
            kw = {"image": p} if p else {}
            tree.insert("", "end", **kw, values=(
                _STATUS_LABELS.get(job.status, job.status),
                job.media_name,
                _mtype(job.media_type),
                _KIND_LABELS.get(job.job_kind, job.job_kind.title()),
                str(job.selected_count),
                _fmt(job.updated_at),
            ), tags=(tag,))
            job_ids.append(job.job_id)

        counts = store.count_by_status()
        hist_n = sum(counts.get(s, 0) for s in (
            JobStatus.COMPLETED, JobStatus.FAILED,
            JobStatus.CANCELLED, JobStatus.REVERTED))
        btn_clear.configure(state="normal" if hist_n else "disabled")
        btn_revert.configure(state="disabled")
        app._update_queue_badge()

    app._history_tab_refresh = _refresh

    # ── Actions ───────────────────────────────────────────────────

    def _revert():
        jobs = _sel_jobs(store, tree, job_ids)
        ok = [(i, j) for i, j in jobs
              if j.status == JobStatus.COMPLETED and j.undo_data]
        if not ok:
            messagebox.showinfo("Cannot Revert",
                "Only completed jobs with undo data can be reverted.")
            return
        tot = sum(len(j.undo_data.get("renames", [])) for _, j in ok)
        names = [j.media_name for _, j in ok[:5]]
        sfx = f"\n… +{len(ok)-5} more" if len(ok) > 5 else ""
        if not messagebox.askyesno("Revert Jobs",
            f"Revert {len(ok)} job(s) ({tot} renames)?\n\n"
            + "\n".join(f"  • {n}" for n in names) + sfx
            + "\n\nFiles will be restored to original locations."):
            return
        errs = []
        for jid, job in ok:
            _, e = revert_job(job)
            store.update_status(jid, JobStatus.REVERTED,
                error_message="; ".join(e[:3]) if e else None)
            errs.extend(e)
        if errs:
            messagebox.showwarning("Partial Revert",
                f"Done with errors:\n" + "\n".join(errs[:8]))
        else:
            messagebox.showinfo("Reverted", f"Reverted {len(ok)} job(s).")
        _refresh()

    def _clear():
        counts = store.count_by_status()
        n = sum(counts.get(s, 0) for s in (
            JobStatus.COMPLETED, JobStatus.FAILED,
            JobStatus.CANCELLED, JobStatus.REVERTED))
        if not n: return
        if not messagebox.askyesno("Clear History",
            f"Delete {n} entries?\nAll revert data will be lost."):
            return
        store.clear_history()
        _refresh()

    _refresh()


# ─── Shared helper ───────────────────────────────────────────────────────────

def _lib_refresh(app, removed):
    if not app.batch_mode or not app.batch_states:
        return
    ids = {j.tmdb_id for _, j in removed}
    for s in app.batch_states:
        if s.queued and s.show_id in ids:
            s.queued = False
    try:
        from . import library_panel
        library_panel.display_library(app)
    except Exception:
        pass
