#!/usr/bin/env python3
"""
update.py - DankApp Database Update

Orchestrates the full band-archive update pipeline:
  1. Scan local files -> band_archive.csv
  2. Plan + confirm + upload new recordings to the Internet Archive (with rate-limit retry)
  3. Analyze data
  4. Build metadata
  5. Prompt for any missing artist names
  6. Generate share links
  7. Commit + push changed data files to GitHub (Streamlit Cloud auto-redeploys)

Replaces update_database.bat. Same steps, same order, same retry behavior --
just one process, real logging, and it runs on any OS (Windows/Mac/Linux).

Usage:
    python update.py
"""

import json
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import pandas as pd  # type: ignore

# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------

# Set this from another thread (e.g. a GUI's Cancel button) to stop the
# pipeline at the next safe checkpoint -- between steps, or during the
# upload retry wait.
cancel_event = threading.Event()

# The subprocess currently being run by run_script(), if any. Tracked so
# cancel_current_process() can actually kill it -- cancel_event alone only
# gets checked at points in our own code, not while a child process is
# off doing its own work (e.g. mid-upload).
_current_process: subprocess.Popen | None = None


def cancel_current_process() -> None:
    """Signal cancellation and kill whatever child script is running right now."""
    cancel_event.set()
    proc = _current_process
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
        except Exception:
            pass

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


def run_script(script_name: str, extra_args: list | None = None) -> None:
    """Run a Python script from this repo, streaming its output live, and raise if it fails."""
    global _current_process

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

    command = [_python_executable(), str(script_path), *(extra_args or [])]

    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,  # merge streams so log lines stay in the order they were printed
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    _current_process = process

    try:
        for line in process.stdout:
            line = line.rstrip()
            if line.startswith(PROGRESS_PREFIX):
                if progress_callback:
                    try:
                        data = json.loads(line[len(PROGRESS_PREFIX):])
                        progress_callback(data.get("current", 0), data.get("total", 0), data.get("label", ""))
                    except Exception:
                        pass
                continue  # keep raw per-file progress ticks out of the log -- the progress bar shows them instead
            if _is_noisy_line(line):
                continue  # harmless Streamlit bare-mode warnings -- see NOISY_LINE_MARKERS above
            log.info(f"  {script_name} | {line}")
        process.wait()
    finally:
        _current_process = None

    if cancel_event.is_set():
        raise StepError(f"Cancelled during {script_name}.")

    if process.returncode != 0:
        raise StepError(f"{script_name} exited with code {process.returncode}")


def run_git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


# ----------------------------------------------------------------------
# UI bridge
# ----------------------------------------------------------------------
# A GUI (gui.py) sets these before calling main(). If left unset, each
# falls back to a plain console interaction so update.py still works
# standalone from a terminal.
#
#   confirm_upload_callback(plan: list[dict]) -> bool
#   request_artists_callback(titles: list[str]) -> dict[str, str]
#   progress_callback(current: int, total: int, label: str) -> None

confirm_upload_callback = None
request_artists_callback = None
progress_callback = None

PROGRESS_PREFIX = "@PROGRESS@"

# Streamlit prints these when a script that imports it (e.g. scanner.py,
# for a shared @st.cache_data helper) runs outside of `streamlit run`.
# They're harmless -- Streamlit says so itself ("can be ignored when
# running in bare mode") -- just noisy, so they're filtered out of the log.
NOISY_LINE_MARKERS = (
    "missing ScriptRunContext",
    "No runtime found, using MemoryCacheStorageManager",
)


def _is_noisy_line(line: str) -> bool:
    return any(marker in line for marker in NOISY_LINE_MARKERS)


def _default_confirm_upload(plan: list) -> bool:
    print("\nAbout to upload:")
    for show in plan:
        print(f"  {show['date']} — {show['location']} ({len(show['files'])} file(s))")
        for f in show["files"]:
            print(f"      {f['title']}  ({f['filename']})")
    answer = input("\nProceed with upload? [y/N] ").strip().lower()
    return answer == "y"


def _default_request_artists(titles: list) -> dict:
    results = {}
    print("\nThe following songs have no artist on file:")
    for title in titles:
        results[title] = input(f"  Artist for '{title}': ").strip()
    return results


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
    log.info("[1/7] Scanning files to update band_archive.csv...")
    run_script("scanner.py")


UPLOAD_PLAN_PATH = ROOT / "upload_plan.json"


def step_upload():
    log.info("[2/7] Checking what needs uploading to the Internet Archive...")
    run_script("upload_to_archive.py", extra_args=["--plan"])

    if not UPLOAD_PLAN_PATH.exists():
        log.warning("upload_to_archive.py --plan didn't write a plan file; skipping upload this run.")
        return

    with open(UPLOAD_PLAN_PATH, "r", encoding="utf-8") as f:
        plan = json.load(f)

    total_files = sum(len(show["files"]) for show in plan)
    if not plan or total_files == 0:
        log.info("Nothing new to upload.")
        return

    log.info(f"{total_files} file(s) across {len(plan)} show(s) are ready to upload.")

    confirm = confirm_upload_callback or _default_confirm_upload
    if not confirm(plan):
        log.info("Upload skipped (not confirmed).")
        return

    log.info("Uploading...")
    attempt = 0
    while True:
        attempt += 1
        try:
            run_script("upload_to_archive.py")
            if progress_callback:
                progress_callback(0, 0, "")  # reset the bar once the step is done
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
    log.info("[3/7] Analyzing data...")
    run_script("analyze.py")


def step_build_metadata():
    log.info("[4/7] Building metadata...")
    run_script("build_metadata.py")


METADATA_PATH = ROOT / "song_metadata.csv"


def step_fill_missing_artists():
    log.info("[5/7] Checking for songs with no artist on file...")

    if not METADATA_PATH.exists():
        log.warning(f"{METADATA_PATH.name} not found; skipping artist check.")
        return

    df = pd.read_csv(METADATA_PATH)
    if "Artist" not in df.columns:
        log.warning(f"{METADATA_PATH.name} has no Artist column; skipping artist check.")
        return

    blank_mask = df["Artist"].isna() | (df["Artist"].astype(str).str.strip() == "")
    missing_titles = df.loc[blank_mask, "Title"].tolist()

    if not missing_titles:
        log.info("No missing artists.")
        return

    log.info(f"{len(missing_titles)} song(s) have no artist on file.")
    request_artists = request_artists_callback or _default_request_artists
    answers = request_artists(missing_titles)

    for title, artist in answers.items():
        artist = (artist or "").strip()
        if artist:
            df.loc[df["Title"] == title, "Artist"] = artist

    df.to_csv(METADATA_PATH, index=False)
    filled = sum(1 for a in answers.values() if (a or "").strip())
    log.info(f"Filled in {filled} of {len(missing_titles)} artist name(s).")


def step_share_links():
    log.info("[6/7] Adding share links...")
    run_script("generate_share_links.py")


def step_commit_and_push():
    log.info("[7/7] Checking for changes...")

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
    step_fill_missing_artists,
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
            if cancel_event.is_set():
                log.warning(f"Cancelled: {e}")
            else:
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