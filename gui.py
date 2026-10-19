#!/usr/bin/env python3
"""
gui.py - Controller window for the DankApp update pipeline

A small desktop window that runs update.py's pipeline in the background and
streams its log live, plus:
  - Update Now / Preview Changes / Resume buttons, and a Cancel button
  - run options: skip the upload, dry run (don't push), start from a later step
  - a review dialog showing what the scan is about to change (new files,
    placeholders replaced by recordings, files that went missing) before
    anything is written
  - a confirmation dialog before anything is uploaded to the Internet Archive
  - a prompt for any songs missing an artist name
  - a live progress bar
  - Tools menu: edit the archive CSV in a table, validate it, set up
    e-mail notifications, open the log

Requires update.py, scanner.py, archive_tools.py and notifier.py in the same folder.

Usage:
    python gui.py
"""

import logging
import os
import queue
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

import archive_tools as at
import notifier
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
        self.root.geometry("760x600")
        self.root.minsize(560, 420)

        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.worker_thread: threading.Thread | None = None
        self.editor_win: tk.Toplevel | None = None

        self.skip_upload_var = tk.BooleanVar(value=False)
        self.dry_run_var = tk.BooleanVar(value=False)
        self.quiet_var = tk.BooleanVar(value=False)
        self.start_var = tk.StringVar(value=update.STEP_LABELS["scan"])

        self._build_menu()
        self._build_widgets()
        self._wire_logging()
        self._wire_pipeline_callbacks()
        self._refresh_resume_button()
        self._poll_queue()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _build_menu(self):
        menubar = tk.Menu(self.root)
        tools = tk.Menu(menubar, tearoff=0)
        tools.add_command(label="Edit archive CSV...", command=self._open_editor)
        tools.add_command(label="Validate archive CSV", command=self._validate_now)
        tools.add_separator()
        tools.add_command(label="Notifications...", command=self._open_notifications)
        tools.add_command(label="Open update.log", command=self._open_log_file)
        menubar.add_cascade(label="Tools", menu=tools)
        self.root.config(menu=menubar)

    def _build_widgets(self):
        top = ttk.Frame(self.root, padding=(10, 10, 10, 4))
        top.pack(fill="x")

        self.run_button = ttk.Button(top, text="Update Now", command=self._on_run)
        self.run_button.pack(side="left")

        self.preview_button = ttk.Button(top, text="Preview Changes", command=self._on_preview)
        self.preview_button.pack(side="left", padx=(8, 0))

        self.resume_button = ttk.Button(top, text="Resume", command=self._on_resume, state="disabled")
        self.resume_button.pack(side="left", padx=(8, 0))

        self.cancel_button = ttk.Button(top, text="Cancel", command=self._on_cancel, state="disabled")
        self.cancel_button.pack(side="left", padx=(8, 0))

        self.status_label = ttk.Label(top, text="Idle", foreground="#555555")
        self.status_label.pack(side="left", padx=(16, 0))

        opts = ttk.Frame(self.root, padding=(10, 0, 10, 4))
        opts.pack(fill="x")
        ttk.Checkbutton(opts, text="Skip upload", variable=self.skip_upload_var).pack(side="left")
        ttk.Checkbutton(opts, text="Dry run (don't commit or push)", variable=self.dry_run_var).pack(
            side="left", padx=(12, 0))
        ttk.Checkbutton(opts, text="Only stop to ask if a file is missing", variable=self.quiet_var).pack(
            side="left", padx=(12, 0))

        start = ttk.Frame(self.root, padding=(10, 0, 10, 4))
        start.pack(fill="x")
        ttk.Label(start, text="Start from:").pack(side="left")
        self.start_combo = ttk.Combobox(
            start, textvariable=self.start_var, state="readonly", width=30,
            values=[update.STEP_LABELS[n] for n in update.STEP_NAMES],
        )
        self.start_combo.pack(side="left", padx=(6, 0))

        self.resume_hint = ttk.Label(start, text="", foreground="#b22222")
        self.resume_hint.pack(side="left", padx=(12, 0))

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
        # to (console + update.log) -- this just adds another destination.
        handler = QueueHandler(self.log_queue)
        handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s", "%H:%M:%S"))
        logging.getLogger("update").addHandler(handler)

    def _wire_pipeline_callbacks(self):
        update.confirm_upload_callback = self._confirm_upload
        update.request_artists_callback = self._request_artists
        update.review_scan_callback = self._review_scan
        update.progress_callback = self._on_progress

    # ------------------------------------------------------------------
    # Button actions
    # ------------------------------------------------------------------

    def _is_running(self) -> bool:
        return bool(self.worker_thread and self.worker_thread.is_alive())

    def _start_name(self) -> str:
        label = self.start_var.get()
        for name in update.STEP_NAMES:
            if update.STEP_LABELS[name] == label:
                return name
        return "scan"

    def _options(self, **overrides) -> "update.RunOptions":
        opts = update.RunOptions(
            start_from=self._start_name(),
            skip_upload=self.skip_upload_var.get(),
            push=not self.dry_run_var.get(),
            review="decisions" if self.quiet_var.get() else "always",
        )
        for key, value in overrides.items():
            setattr(opts, key, value)
        return opts

    def _on_run(self):
        self._launch(self._options(), "--- Starting update ---")

    def _on_preview(self):
        self._launch(update.RunOptions(preview_only=True), "--- Previewing changes (nothing will be written) ---")

    def _on_resume(self):
        failed = update.read_state().get("failed_step")
        if failed not in update.STEP_NAMES:
            self._refresh_resume_button()
            return
        self.start_var.set(update.STEP_LABELS[failed])
        self._launch(self._options(start_from=failed),
                     f"--- Resuming from '{update.STEP_LABELS[failed]}' ---")

    def _launch(self, options, banner: str):
        if self._is_running():
            return  # a run is already in progress
        if self.editor_win is not None and self.editor_win.winfo_exists() and not options.preview_only:
            if not messagebox.askyesno(
                "Editor is open",
                "The CSV editor is open. If it has unsaved changes, the scan will not see them, "
                "and saving afterwards could overwrite what the scan writes.\n\nStart the run anyway?",
                parent=self.root,
            ):
                return

        update.cancel_event.clear()
        for b in (self.run_button, self.preview_button, self.resume_button):
            b.config(state="disabled")
        self.cancel_button.config(state="normal")
        self.status_label.config(text="Running...", foreground="#b8860b")
        self._apply_progress(0, 0, "")
        self._append_log(banner)

        self.worker_thread = threading.Thread(target=self._run_pipeline, args=(options,), daemon=True)
        self.worker_thread.start()

    def _on_cancel(self):
        self.status_label.config(text="Cancelling...", foreground="#b22222")
        self.cancel_button.config(state="disabled")
        update.cancel_current_process()

    def _on_close(self):
        # Let a background pipeline keep running to completion even if the
        # window is closed, rather than killing it mid-git-push.
        self.root.destroy()

    def _refresh_resume_button(self):
        state = update.read_state()
        failed = state.get("failed_step")
        if failed in update.STEP_NAMES and not self._is_running():
            self.resume_button.config(state="normal")
            self.resume_hint.config(text=f"Last run stopped at: {update.STEP_LABELS[failed]}")
        else:
            self.resume_button.config(state="disabled")
            self.resume_hint.config(text="")

    # ------------------------------------------------------------------
    # Background work
    # ------------------------------------------------------------------

    def _run_pipeline(self, options):
        status = "failed"
        try:
            status = update.run_pipeline(options)
        except Exception:
            logging.getLogger("update").exception("Unexpected error running the pipeline.")
        self.root.after(0, self._on_finished, status)

    def _on_finished(self, status: str):
        self.run_button.config(state="normal")
        self.preview_button.config(state="normal")
        self.cancel_button.config(state="disabled")
        self._apply_progress(0, 0, "")
        text, color = {
            "ok": ("Done", "#2e7d32"),
            "preview": ("Preview finished", "#2e7d32"),
            "cancelled": ("Cancelled", "#b22222"),
            "aborted": ("Stopped - nothing was changed", "#b8860b"),
            "failed": ("Failed - see log", "#b22222"),
        }.get(status, ("Finished", "#555555"))
        self.status_label.config(text=text, foreground=color)
        self._refresh_resume_button()

    # ------------------------------------------------------------------
    # Pipeline callbacks -- these run on the WORKER thread and block it
    # until the dialog they schedule on the main thread is answered.
    # ------------------------------------------------------------------

    def _ask_on_main(self, show, *args, default):
        """Schedule `show(*args, result, done)` on the GUI thread and wait for the answer."""
        result: dict = {}
        done = threading.Event()
        self.root.after(0, show, *args, result, done)
        done.wait()
        return result.get("value", default)

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

    # ---- scan review ---------------------------------------------------

    def _review_scan(self, payload: dict) -> dict:
        """Shown by the scan step: what will change. Returns {"apply": bool, "remove": [paths]}."""
        return self._ask_on_main(self._show_review_dialog, payload, default={"apply": False, "remove": []})

    def _show_review_dialog(self, payload: dict, result: dict, done: threading.Event):
        preview = bool(payload.get("preview_only"))
        missing = payload.get("missing", [])

        win = tk.Toplevel(self.root)
        win.title("Preview - nothing will be written" if preview else "Review Scan Changes")
        win.geometry("760x600")
        win.minsize(520, 380)
        win.transient(self.root)
        win.grab_set()

        def finish(value: dict):
            result["value"] = value
            done.set()
            win.destroy()

        header = ("This is a preview. Nothing has been changed."
                  if preview else "Here's what the scan is about to change. Nothing is written until you click Apply.")
        ttk.Label(win, text=header, padding=(10, 10, 10, 4), wraplength=720).pack(anchor="w")

        # What's changing: one scrolling summary (new files, swaps, restored, folders).
        text = scrolledtext.ScrolledText(win, wrap="word", height=12, font=("Consolas", 10))
        text.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        text.insert("end", at.format_review(payload, include_missing=preview))
        text.configure(state="disabled")

        vars_by_path: dict = {}
        if missing and not preview:
            frame = ttk.LabelFrame(
                win, padding=6,
                text=f"{len(missing)} file(s) are in the CSV but no longer on disk - tick the ones to REMOVE",
            )
            frame.pack(fill="both", expand=True, padx=10, pady=(0, 6))
            container, inner = make_scrollable(frame)
            container.pack(fill="both", expand=True)
            for m in missing:
                var = tk.BooleanVar(value=bool(m.get("preselect")))
                note = ""
                if m.get("already_flagged"):
                    note = "   (already flagged missing)"
                elif m.get("has_ia_url"):
                    note = "   (has an Internet Archive link - removing loses it)"
                ttk.Checkbutton(inner, text=m["label"] + note, variable=var).pack(anchor="w", pady=1)
                vars_by_path[m["path"]] = var
            ttk.Label(win, foreground="#555555", padding=(10, 0),
                      text="Unticked files stay in the CSV, flagged Status: missing.").pack(anchor="w")

        btns = ttk.Frame(win, padding=10)
        btns.pack(fill="x")

        if preview:
            ttk.Button(btns, text="Close", command=lambda: finish({"apply": False, "remove": []})).pack(side="right")
            win.protocol("WM_DELETE_WINDOW", lambda: finish({"apply": False, "remove": []}))
        else:
            ttk.Button(btns, text="Cancel (change nothing)",
                       command=lambda: finish({"apply": False, "remove": []})).pack(side="right")
            ttk.Button(btns, text="Apply",
                       command=lambda: finish({"apply": True,
                                               "remove": [p for p, v in vars_by_path.items() if v.get()]})
                       ).pack(side="right", padx=(0, 8))
            win.protocol("WM_DELETE_WINDOW", lambda: finish({"apply": False, "remove": []}))

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
    # Tools menu
    # ------------------------------------------------------------------

    def _validate_now(self):
        try:
            issues = at.validate_archive(update.ARCHIVE_CSV)
        except Exception as e:
            messagebox.showerror("Validate", f"Couldn't check the file:\n{e}", parent=self.root)
            return
        errors, warns = at.summarize_issues(issues)
        self._show_text_window(
            "Validation result",
            (at.format_issues(issues) + "\n\n" if issues else "") +
            f"{update.ARCHIVE_CSV.name}: {errors} error(s), {warns} warning(s)." +
            ("" if issues else "\nEverything looks good."),
        )

    def _show_text_window(self, title: str, body: str):
        win = tk.Toplevel(self.root)
        win.title(title)
        win.geometry("720x380")
        win.transient(self.root)
        box = scrolledtext.ScrolledText(win, wrap="word", font=("Consolas", 10))
        box.pack(fill="both", expand=True, padx=10, pady=10)
        box.insert("end", body)
        box.configure(state="disabled")
        ttk.Button(win, text="Close", command=win.destroy).pack(pady=(0, 10))

    def _open_log_file(self):
        try:
            os.startfile(str(update.LOG_FILE))  # type: ignore[attr-defined]  # Windows only
        except Exception:
            messagebox.showinfo("update.log", f"The log is at:\n{update.LOG_FILE}", parent=self.root)

    # ---- notifications ---------------------------------------------------

    def _open_notifications(self):
        s = notifier.load_settings()
        win = tk.Toplevel(self.root)
        win.title("Notifications")
        win.geometry("520x430")
        win.transient(self.root)

        enabled = tk.BooleanVar(value=s.get("backend") == "gmail")
        user = tk.StringVar(value=s.get("gmail_user", ""))
        to = tk.StringVar(value=s.get("to", ""))
        on_ok = tk.BooleanVar(value=bool(s.get("on_success", True)))
        on_bad = tk.BooleanVar(value=bool(s.get("on_failure", True)))
        pw = tk.StringVar()
        status = tk.StringVar()

        f = ttk.Frame(win, padding=14)
        f.pack(fill="both", expand=True)
        ttk.Checkbutton(f, text="Send me an e-mail (Gmail) when an update finishes or fails",
                        variable=enabled).grid(row=0, column=0, columnspan=2, sticky="w")

        ttk.Label(f, text="Gmail address:").grid(row=1, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(f, textvariable=user, width=38).grid(row=1, column=1, sticky="we", pady=(12, 0))
        ttk.Label(f, text="Send to (blank = same):").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(f, textvariable=to, width=38).grid(row=2, column=1, sticky="we", pady=(6, 0))
        ttk.Label(f, text="App password:").grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(f, textvariable=pw, show="•", width=38).grid(row=3, column=1, sticky="we", pady=(6, 0))
        f.columnconfigure(1, weight=1)

        ttk.Checkbutton(f, text="Tell me when a run succeeds", variable=on_ok).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(12, 0))
        ttk.Checkbutton(f, text="Tell me when a run fails", variable=on_bad).grid(
            row=5, column=0, columnspan=2, sticky="w")

        if notifier.keyring_available():
            pw_note = "The app password is saved in Windows Credential Manager, never in a file."
        else:
            pw_note = ("To save the password here, run:  pip install keyring   (then reopen this window). "
                       f"Otherwise set the {notifier.PASSWORD_ENV} environment variable.")
        ttk.Label(f, text="Use a Google *app password* (Google Account > Security > 2-Step Verification > "
                          "App passwords), not your normal password.\n" + pw_note,
                  foreground="#555555", wraplength=470, justify="left").grid(
            row=6, column=0, columnspan=2, sticky="w", pady=(12, 0))
        ttk.Label(f, textvariable=status, wraplength=470, justify="left").grid(
            row=7, column=0, columnspan=2, sticky="w", pady=(8, 0))

        def gather() -> dict:
            return {"backend": "gmail" if enabled.get() else "off", "gmail_user": user.get().strip(),
                    "to": to.get().strip(), "on_success": on_ok.get(), "on_failure": on_bad.get()}

        def store_password() -> bool:
            if pw.get().strip():
                if notifier.set_app_password(user.get().strip(), pw.get().strip()):
                    pw.set("")
                    return True
                os.environ[notifier.PASSWORD_ENV] = pw.get().strip()      # this session only
                status.set("keyring isn't installed, so the password is only held until you close this app.")
                return False
            return True

        def on_save():
            notifier.save_settings(gather())
            store_password()
            win.destroy()

        def on_test():
            notifier.save_settings(gather())
            store_password()
            status.set("Sending a test e-mail...")
            win.update_idletasks()
            settings = gather()
            settings["backend"] = "gmail"
            sent, msg = notifier.send("Test notification", "If you can read this, notifications work.",
                                      event="test", settings=settings)
            status.set("Sent! Check your inbox." if sent else f"Couldn't send: {msg}")

        btns = ttk.Frame(f)
        btns.grid(row=8, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(btns, text="Send test e-mail", command=on_test).pack(side="left")
        ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="left", padx=(16, 0))
        ttk.Button(btns, text="Save", command=on_save).pack(side="left", padx=(8, 0))

    # ---- CSV editor --------------------------------------------------------

    def _open_editor(self):
        if self.editor_win is not None and self.editor_win.winfo_exists():
            self.editor_win.lift()
            return
        if self._is_running():
            if not messagebox.askyesno(
                "Update is running",
                "An update is running and may rewrite the CSV. Edits saved now could be overwritten.\n\n"
                "Open the editor anyway?", parent=self.root):
                return
        try:
            self.editor_win = CsvEditor(self.root, update.ARCHIVE_CSV).win
        except Exception as e:
            messagebox.showerror("Edit archive CSV", f"Couldn't open the file:\n{e}", parent=self.root)

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


class CsvEditor:
    """
    A table view of band_archive.csv: double-click a cell to edit it, then Save.
    Everything stays text, so Excel can't turn "7:58" durations into times, and
    every save is validated, backed up, and written atomically.
    """

    WIDTHS = {"Track Number": 60, "File Track": 60, "Title": 170, "Date": 90, "Location": 160,
              "Type": 60, "Duration": 70, "Raw Title": 150, "File Path": 320, "Take": 40,
              "IA URL": 200, "OneDrive URL": 200, "Status": 70}

    def __init__(self, parent: tk.Tk, path):
        self.path = path
        self.df = at.load_archive(path)
        self.loaded_mtime = os.path.getmtime(path)
        self.dirty = False
        self.entry: ttk.Entry | None = None
        self.editing = None            # (iid, column name)
        self.problem_rows: set = set()

        win = self.win = tk.Toplevel(parent)
        win.title(f"Edit archive CSV - {os.path.basename(str(path))}")
        win.geometry("1100x640")
        win.minsize(700, 400)

        bar = ttk.Frame(win, padding=(10, 8))
        bar.pack(fill="x")
        ttk.Label(bar, text="Filter:").pack(side="left")
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self._populate())
        ttk.Entry(bar, textvariable=self.filter_var, width=28).pack(side="left", padx=(4, 12))
        self.only_problems = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Only rows with problems", variable=self.only_problems,
                        command=self._populate).pack(side="left")
        self.count_label = ttk.Label(bar, text="", foreground="#555555")
        self.count_label.pack(side="left", padx=(12, 0))

        ttk.Button(bar, text="Save", command=self._save).pack(side="right")
        ttk.Button(bar, text="Check", command=self._check).pack(side="right", padx=(0, 8))
        ttk.Button(bar, text="Delete selected rows", command=self._delete_selected).pack(side="right", padx=(0, 8))
        ttk.Button(bar, text="Reload", command=self._reload).pack(side="right", padx=(0, 8))

        frame = ttk.Frame(win)
        frame.pack(fill="both", expand=True, padx=10)
        cols = list(self.df.columns)
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="extended")
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=self.WIDTHS.get(c, 120), minwidth=40, stretch=False)
        ysb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        xsb = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.tree.tag_configure("problem", background="#ffe0e0")
        self.tree.tag_configure("missing", foreground="#999999")
        self.tree.bind("<Double-1>", self._begin_edit)
        self.tree.bind("<Button-1>", lambda e: self._end_edit(commit=True), add="+")
        self.tree.bind("<MouseWheel>", lambda e: self._end_edit(commit=True), add="+")

        self.issue_label = ttk.Label(win, text="", padding=(10, 6), wraplength=1060, justify="left")
        self.issue_label.pack(fill="x")

        win.protocol("WM_DELETE_WINDOW", self._on_close)
        self._recompute_problems()
        self._populate()

    # -- helpers --

    def _recompute_problems(self):
        issues = at.validate_archive(self.df)
        self.problem_rows = {i for iss in issues for i in iss.rows}
        errors, warns = at.summarize_issues(issues)
        self.issues = issues
        self.issue_label.config(
            text=(f"{errors} error(s), {warns} warning(s) - rows with problems are shaded."
                  if issues else "No problems found."),
            foreground="#b22222" if errors else ("#b8860b" if warns else "#2e7d32"))

    def _populate(self):
        self._end_edit(commit=True)
        self.tree.delete(*self.tree.get_children())
        needle = self.filter_var.get().strip().lower()
        shown = 0
        for idx, row in self.df.iterrows():
            if self.only_problems.get() and idx not in self.problem_rows:
                continue
            if needle and needle not in " ".join(row.astype(str)).lower():
                continue
            tags = []
            if idx in self.problem_rows:
                tags.append("problem")
            if str(row.get("Status", "")).strip().lower() == "missing":
                tags.append("missing")
            self.tree.insert("", "end", iid=str(idx), values=list(row), tags=tags)
            shown += 1
        self.count_label.config(text=f"{shown} of {len(self.df)} row(s)" + ("   * unsaved changes" if self.dirty else ""))

    # -- in-place cell editing --

    def _begin_edit(self, event):
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        iid = self.tree.identify_row(event.y)
        col_id = self.tree.identify_column(event.x)
        if not iid:
            return
        col = self.tree.cget("columns")[int(col_id[1:]) - 1]
        x, y, w, h = self.tree.bbox(iid, col_id)
        self._end_edit(commit=True)
        entry = ttk.Entry(self.tree)
        entry.insert(0, self.df.at[int(iid), col])
        entry.select_range(0, "end")
        entry.place(x=x, y=y, width=max(w, 80), height=h)
        entry.focus_set()
        entry.bind("<Return>", lambda e: self._end_edit(commit=True))
        entry.bind("<Escape>", lambda e: self._end_edit(commit=False))
        self.entry, self.editing = entry, (iid, col)

    def _end_edit(self, commit: bool):
        if self.entry is None:
            return
        entry, (iid, col) = self.entry, self.editing
        self.entry, self.editing = None, None
        value = entry.get()
        entry.destroy()
        if commit and self.df.at[int(iid), col] != value:
            self.df.at[int(iid), col] = value
            self.dirty = True
            self.tree.set(iid, col, value)
            self._recompute_problems()
            self.count_label.config(text=self.count_label.cget("text").split("   *")[0] + "   * unsaved changes")

    # -- actions --

    def _delete_selected(self):
        self._end_edit(commit=True)
        sel = self.tree.selection()
        if not sel:
            return
        if not messagebox.askyesno("Delete rows", f"Delete {len(sel)} row(s) from the CSV?\n"
                                   "(You can still undo this by not saving, or from the backups folder.)",
                                   parent=self.win):
            return
        self.df = self.df.drop(index=[int(i) for i in sel])
        self.dirty = True
        self._recompute_problems()
        self._populate()

    def _check(self):
        self._end_edit(commit=True)
        self._recompute_problems()
        text = at.format_issues(self.issues) if self.issues else "No problems found."
        messagebox.showinfo("Check", text, parent=self.win)

    def _reload(self):
        if self.dirty and not messagebox.askyesno("Reload", "Discard your unsaved changes and reload from disk?",
                                                  parent=self.win):
            return
        self.df = at.load_archive(self.path)
        self.loaded_mtime = os.path.getmtime(self.path)
        self.dirty = False
        self._recompute_problems()
        self._populate()

    def _save(self):
        self._end_edit(commit=True)
        if os.path.getmtime(self.path) != self.loaded_mtime:
            if not messagebox.askyesno(
                "File changed",
                "band_archive.csv changed on disk since you opened it (an update may have run).\n"
                "Saving now will overwrite that with your version.\n\nSave anyway?", parent=self.win):
                return
        self._recompute_problems()
        errors, _ = at.summarize_issues(self.issues)
        if errors and not messagebox.askyesno(
            "Problems found",
            f"{errors} error(s) would break the app:\n\n"
            + "\n".join(i.message for i in self.issues if i.level == "error")[:1200]
            + "\n\nSave anyway? (The update's final check will still stop a push.)", parent=self.win):
            return
        try:
            backup = at.save_archive(self.df, self.path, columns=list(self.df.columns))
        except Exception as e:
            messagebox.showerror("Save failed", str(e), parent=self.win)
            return
        self.loaded_mtime = os.path.getmtime(self.path)
        self.dirty = False
        self._populate()
        messagebox.showinfo("Saved", f"Saved.\nPrevious version backed up to:\n{backup}" if backup else "Saved.",
                            parent=self.win)

    def _on_close(self):
        self._end_edit(commit=True)
        if self.dirty and not messagebox.askyesno("Unsaved changes", "Close without saving your changes?",
                                                  parent=self.win):
            return
        self.win.destroy()


def main():
    root = tk.Tk()
    ControllerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()