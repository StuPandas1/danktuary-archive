#!/usr/bin/env python3
"""
gui.py - Controller window for the DankApp update pipeline

A small desktop window with a button that runs update.py's pipeline in
the background and streams its log output live, plus a Cancel button
that stops the run at the next safe checkpoint.

Requires update.py to be in the same folder.

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


class ControllerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("DankApp Update Controller")
        self.root.geometry("640x480")
        self.root.minsize(480, 360)

        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.worker_thread: threading.Thread | None = None

        self._build_widgets()
        self._wire_logging()
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
        self._append_log("--- Starting update ---")

        self.worker_thread = threading.Thread(target=self._run_pipeline, daemon=True)
        self.worker_thread.start()

    def _on_cancel(self):
        self.status_label.config(text="Cancelling...", foreground="#b22222")
        self.cancel_button.config(state="disabled")
        update.cancel_event.set()

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
        if update.cancel_event.is_set():
            self.status_label.config(text="Cancelled", foreground="#b22222")
        elif failed:
            self.status_label.config(text="Failed - see log", foreground="#b22222")
        else:
            self.status_label.config(text="Done", foreground="#2e7d32")

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