#!/usr/bin/env python3
"""
update.py - DankApp Database Update

Orchestrates the full band-archive update pipeline:
  1. Scan local files -> band_archive.csv
  2. Upload new recordings to the Internet Archive (with rate-limit retry)
  3. Analyze data
  4. Build metadata
  5. Generate share links
  6. Commit + push changed data files to GitHub (Streamlit Cloud auto-redeploys)

Replaces update_database.bat. Same steps, same order, same retry behavior --
just one process, real logging, and it runs on any OS (Windows/Mac/Linux).

Usage:
    python update.py
"""

import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------

# Set this from another thread (e.g. a GUI's Cancel button) to stop the
# pipeline at the next safe checkpoint -- between steps, or during the
# upload retry wait.
cancel_event = threading.Event()

if getattr(sys, "frozen", False):
    # Running as a bundled exe -- __file__ would point into PyInstaller's
    # temporary extraction folder, not where the exe actually lives.
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parent

# Files the Streamlit app actually reads. These get committed + pushed.
DATA_FILES = [
    "band_archive.csv",
    "song_stats.csv",
    "song_metadata.csv",
    "metadata_jam.csv",
]

# Internal bookkeeping the scripts use between runs. NOT committed --
# add these to .gitignore so a cache-only change doesn't trigger a
# pointless Streamlit Cloud redeploy.
CACHE_FILES = [
    "uploaded_shows_cache.json",
    "last_known_shows.csv",
]

UPLOAD_MAX_RETRIES = 3
UPLOAD_WAIT_SECONDS = 3600  # 1 hour, matches the old .bat's IA rate-limit backoff

LOG_FILE = ROOT / "update.log"

# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------

def setup_logging() -> logging.Logger:
    logger = logging.getLogger("update")
    logger.setLevel(logging.INFO)

    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s", "%Y-%m-%d %H:%M:%S")

    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(fmt)
    logger.addHandler(console_handler)

    return logger


log = setup_logging()

# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

class StepError(Exception):
    """Raised when a pipeline step fails and the run should stop."""


def _python_executable() -> str:
    """
    Find a real Python interpreter to run the pipeline's helper scripts with.

    sys.executable is normally correct, but if this module is running
    inside a frozen exe (e.g. gui.py bundled with PyInstaller),
    sys.executable points at the exe itself, not at python.exe -- so a
    frozen build has to look one up on PATH instead.
    """
    if not getattr(sys, "frozen", False):
        return sys.executable

    import shutil

    for candidate in ("python", "python3", "py"):
        found = shutil.which(candidate)
        if found:
            return found

    raise StepError(
        "Running as a bundled exe, but no Python interpreter was found on PATH. "
        "scanner.py, upload_to_archive.py, and the other steps still need a "
        "real Python install (with their dependencies) on this machine -- "
        "this exe is just a launcher, not a fully standalone build."
    )


def run_script(script_name: str) -> None:
    """Run a Python script from this repo and raise if it fails."""
    script_path = ROOT / script_name
    if not script_path.exists():
        raise StepError(f"{script_name} not found at expected path: {script_path}")

    # Force UTF-8 for the child script's own stdout/stderr. When a script is
    # attached to a real console, Python defaults to UTF-8 there -- but once
    # we pipe its output (to capture it here), Python falls back to the
    # system codepage (cp1252 on most Windows installs), which chokes on
    # characters like the checkmarks generate_share_links.py prints.
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [_python_executable(), str(script_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )

    if result.stdout.strip():
        for line in result.stdout.rstrip().splitlines():
            log.info(f"  {script_name} | {line}")
    if result.stderr.strip():
        for line in result.stderr.rstrip().splitlines():
            log.warning(f"  {script_name} | {line}")

    if result.returncode != 0:
        raise StepError(f"{script_name} exited with code {result.returncode}")


def run_git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def notify(message: str) -> None:
    """
    Hook for an external notification (Discord/Slack webhook, email, etc.)
    so a hands-off overnight run can tell you it's done or stuck.
    No-op by default -- wire this up later if you want it. For example, with
    a Discord webhook:

        import requests
        requests.post(WEBHOOK_URL, json={"content": message})
    """
    log.info(f"[notify] {message}")


# ----------------------------------------------------------------------
# Pipeline steps
# ----------------------------------------------------------------------

def step_scan():
    log.info("[1/6] Scanning files to update band_archive.csv...")
    run_script("scanner.py")


def step_upload():
    log.info("[2/6] Uploading new recordings to the Internet Archive...")
    attempt = 0
    while True:
        attempt += 1
        try:
            run_script("upload_to_archive.py")
            return
        except StepError as e:
            if attempt >= UPLOAD_MAX_RETRIES:
                notify(f"Upload failed after {UPLOAD_MAX_RETRIES} attempts: {e}")
                raise
            log.warning(
                f"upload_to_archive.py failed on attempt {attempt}/{UPLOAD_MAX_RETRIES} ({e}). "
                f"This could be Internet Archive's rate limiter, or something else -- "
                f"the retry can't tell the difference, so if it's something else it'll "
                f"just fail fast again next attempt."
            )
            log.info(f"Waiting {UPLOAD_WAIT_SECONDS} seconds before retrying...")
            waited = 0
            chunk = 5
            while waited < UPLOAD_WAIT_SECONDS:
                if cancel_event.is_set():
                    raise StepError("Cancelled during upload retry wait.")
                time.sleep(min(chunk, UPLOAD_WAIT_SECONDS - waited))
                waited += chunk


def step_analyze():
    log.info("[3/6] Analyzing data...")
    run_script("analyze.py")


def step_build_metadata():
    log.info("[4/6] Building metadata...")
    run_script("build_metadata.py")


def step_share_links():
    log.info("[5/6] Adding share links...")
    run_script("generate_share_links.py")


def step_commit_and_push():
    log.info("[6/6] Checking for changes...")

    run_git("add", *DATA_FILES)

    diff = run_git("diff", "--cached", "--quiet")
    if diff.returncode == 0:
        log.info("No changes to the data files. Nothing to push.")
        log.info("Done - database was already up to date.")
        return

    log.info("Changes detected. Committing...")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    commit = run_git("commit", "-m", f"Update archive data - {timestamp}")
    if commit.returncode != 0:
        raise StepError(f"git commit failed:\n{commit.stderr}")

    log.info("Pushing to GitHub...")
    push = run_git("push")
    if push.returncode != 0:
        raise StepError(f"git push failed:\n{push.stderr}")

    log.info("Done! Streamlit Cloud will redeploy automatically in a minute or two.")


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

STEPS = [
    step_scan,
    step_upload,
    step_analyze,
    step_build_metadata,
    step_share_links,
    step_commit_and_push,
]


def main():
    cancel_event.clear()
    log.info("=" * 50)
    log.info("  DankApp Database Update")
    log.info("=" * 50)
    log.info(f"Working directory: {ROOT}")

    for step in STEPS:
        if cancel_event.is_set():
            log.warning(f"Cancelled before {step.__name__}.")
            return
        try:
            step()
        except StepError as e:
            log.error(f"Stopping: {e}")
            notify(f"Update pipeline failed: {e}")
            sys.exit(1)
        except Exception as e:
            log.exception(f"Unexpected error in {step.__name__}: {e}")
            notify(f"Update pipeline crashed: {e}")
            sys.exit(1)

    log.info("Pipeline finished successfully.")


if __name__ == "__main__":
    main()