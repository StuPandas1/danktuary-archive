#!/usr/bin/env python3
"""
gui.py - Controller window for the DankApp update pipeline

A small desktop window with a button that runs update.py's pipeline in
the background and streams its log output live, plus:
  - a Cancel button that stops the run at the next safe checkpoint
  - a confirmation dialog before anything is uploaded to the Internet Archive
  - a prompt for any songs missing an artist name
  - a live progress bar while uploads are in progress

Requires update.py (and upload_to_archive.py, etc.) to be in the same folder.

Usage:
    python gui.py
"""

import logging
import queue
import threading
import tkinter as tk
from tkinter import scrolledtext, ttk

import update  # the orchestrator script -- must sit next to this file


class QueueHandler(logging.Handler):
    """Feeds log records into a queue so the GUI thread can display them safely.

    (Tkinter isn't thread-safe -- the pipeline runs on a background thread,
    so log lines have to cross over via a queue rather than touching
    widgets directly from that thread.)
    """

    def __init__(self, log_queue: "queue.Queue[str]"):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        self.log_queue.put(self.format(record))


def make_scrollable(parent) -> tuple[ttk.Frame, ttk.Frame]:
    """Returns (container, inner) -- pack `container`, put widgets in `inner`."""
    container = ttk.Frame(parent)
    canvas = tk.Canvas(container, highlightthickness=0)
    scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
    inner = ttk.Frame(canvas)

    inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=inner, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)

    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    return container, inner


class ControllerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("DankApp Update Controller")
        self.root.geometry("640x520")
        self.root.minsize(480, 360)

        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.worker_thread: threading.Thread | None = None

        self._build_widgets()
        self._wire_logging()
        self._wire_pipeline_callbacks()
        self._poll_queue()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _build_widgets(self):
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill="x")

        self.run_button = ttk.Button(top, text="Update Now", command=self._on_run)
        self.run_button.pack(side="left")

        self.cancel_button = ttk.Button(top, text="Cancel", command=self._on_cancel, state="disabled")
        self.cancel_button.pack(side="left", padx=(8, 0))

        self.status_label = ttk.Label(top, text="Idle", foreground="#555555")
        self.status_label.pack(side="left", padx=(16, 0))

        progress_frame = ttk.Frame(self.root, padding=(10, 0))
        progress_frame.pack(fill="x")

        self.progress_bar = ttk.Progressbar(progress_frame, mode="determinate")
        self.progress_bar.pack(fill="x")

        self.progress_label = ttk.Label(progress_frame, text="", foreground="#555555")
        self.progress_label.pack(anchor="w", pady=(2, 8))

        self.log_box = scrolledtext.ScrolledText(
            self.root, state="disabled", wrap="word", font=("Consolas", 10)
        )
        self.log_box.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _wire_logging(self):
        # Attach to the same "update" logger that update.py already writes
        # to (console + update.log) -- this just adds a third destination.
        handler = QueueHandler(self.log_queue)
        handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s", "%H:%M:%S"))
        logging.getLogger("update").addHandler(handler)

    def _wire_pipeline_callbacks(self):
        update.confirm_upload_callback = self._confirm_upload
        update.request_artists_callback = self._request_artists
        update.progress_callback = self._on_progress

    # ------------------------------------------------------------------
    # Button actions
    # ------------------------------------------------------------------

    def _on_run(self):
        if self.worker_thread and self.worker_thread.is_alive():
            return  # a run is already in progress

        update.cancel_event.clear()
        self.run_button.config(state="disabled")
        self.cancel_button.config(state="normal")
        self.status_label.config(text="Running...", foreground="#b8860b")
        self._apply_progress(0, 0, "")
        self._append_log("--- Starting update ---")

        self.worker_thread = threading.Thread(target=self._run_pipeline, daemon=True)
        self.worker_thread.start()

    def _on_cancel(self):
        self.status_label.config(text="Cancelling...", foreground="#b22222")
        self.cancel_button.config(state="disabled")
        update.cancel_current_process()

    def _on_close(self):
        # Let a background pipeline keep running to completion even if the
        # window is closed, rather than killing it mid-git-push.
        self.root.destroy()

    # ------------------------------------------------------------------
    # Background work
    # ------------------------------------------------------------------

    def _run_pipeline(self):
        failed = False
        try:
            update.main()
        except SystemExit:
            failed = True
        except Exception:
            logging.getLogger("update").exception("Unexpected error running the pipeline.")
            failed = True
        self.root.after(0, self._on_finished, failed)

    def _on_finished(self, failed: bool):
        self.run_button.config(state="normal")
        self.cancel_button.config(state="disabled")
        self._apply_progress(0, 0, "")
        if update.cancel_event.is_set():
            self.status_label.config(text="Cancelled", foreground="#b22222")
        elif failed:
            self.status_label.config(text="Failed - see log", foreground="#b22222")
        else:
            self.status_label.config(text="Done", foreground="#2e7d32")

    # ------------------------------------------------------------------
    # Pipeline callbacks -- these run on the WORKER thread and block it
    # until the dialog they schedule on the main thread is answered.
    # ------------------------------------------------------------------

    def _confirm_upload(self, plan: list) -> bool:
        result = {}
        done = threading.Event()
        self.root.after(0, self._show_confirm_dialog, plan, result, done)
        done.wait()
        return result.get("confirmed", False)

    def _show_confirm_dialog(self, plan: list, result: dict, done: threading.Event):
        win = tk.Toplevel(self.root)
        win.title("Confirm Upload")
        win.geometry("480x420")
        win.transient(self.root)
        win.grab_set()

        total_files = sum(len(show["files"]) for show in plan)
        ttk.Label(
            win,
            text=f"{total_files} file(s) across {len(plan)} show(s) are ready to upload:",
            padding=10,
            wraplength=440,
        ).pack(anchor="w")

        text = scrolledtext.ScrolledText(win, wrap="word", height=15)
        text.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        for show in plan:
            text.insert("end", f"{show['date']} — {show['location']} ({len(show['files'])} file(s))\n")
            for f in show["files"]:
                text.insert("end", f"    {f['title']}   ({f['filename']})\n")
        text.configure(state="disabled")

        btns = ttk.Frame(win, padding=10)
        btns.pack(fill="x")

        def on_confirm():
            result["confirmed"] = True
            done.set()
            win.destroy()

        def on_cancel():
            result["confirmed"] = False
            done.set()
            win.destroy()

        ttk.Button(btns, text="Cancel", command=on_cancel).pack(side="right")
        ttk.Button(btns, text="Confirm & Upload", command=on_confirm).pack(side="right", padx=(0, 8))
        win.protocol("WM_DELETE_WINDOW", on_cancel)

    def _request_artists(self, titles: list) -> dict:
        result = {}
        done = threading.Event()
        self.root.after(0, self._show_artist_dialog, titles, result, done)
        done.wait()
        return result.get("answers", {})

    def _show_artist_dialog(self, titles: list, result: dict, done: threading.Event):
        win = tk.Toplevel(self.root)
        win.title("Missing Artists")
        win.geometry("480x420")
        win.transient(self.root)
        win.grab_set()

        ttk.Label(
            win,
            text=f"{len(titles)} song(s) have no artist on file. Leave blank to skip a song.",
            padding=10,
            wraplength=440,
        ).pack(anchor="w")

        container, inner = make_scrollable(win)
        container.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        entries = {}
        for title in titles:
            row = ttk.Frame(inner)
            row.pack(fill="x", pady=2, padx=2)
            ttk.Label(row, text=title, width=28, anchor="w", wraplength=180).pack(side="left")
            entry = ttk.Entry(row)
            entry.pack(side="left", fill="x", expand=True)
            entries[title] = entry

        btns = ttk.Frame(win, padding=10)
        btns.pack(fill="x")

        def on_submit():
            result["answers"] = {title: entry.get() for title, entry in entries.items()}
            done.set()
            win.destroy()

        def on_skip_all():
            result["answers"] = {}
            done.set()
            win.destroy()

        ttk.Button(btns, text="Skip All", command=on_skip_all).pack(side="right")
        ttk.Button(btns, text="Submit", command=on_submit).pack(side="right", padx=(0, 8))
        win.protocol("WM_DELETE_WINDOW", on_skip_all)

    def _on_progress(self, current: int, total: int, label: str):
        self.root.after(0, self._apply_progress, current, total, label)

    def _apply_progress(self, current: int, total: int, label: str):
        if total <= 0:
            self.progress_bar.configure(value=0, maximum=1)
            self.progress_label.config(text="")
            return
        self.progress_bar.configure(maximum=total, value=current)
        self.progress_label.config(text=f"{current}/{total} — {label}")

    # ------------------------------------------------------------------
    # Log display
    # ------------------------------------------------------------------

    def _append_log(self, text: str):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _poll_queue(self):
        try:
            while True:
                line = self.log_queue.get_nowait()
                self._append_log(line)
        except queue.Empty:
            pass
        self.root.after(150, self._poll_queue)


def main():
    root = tk.Tk()
    ControllerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()