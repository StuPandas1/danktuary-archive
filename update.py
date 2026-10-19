#!/usr/bin/env python3
"""
update.py - DankApp Database Update

Orchestrates the full band-archive update pipeline:
  1. Scan local files -> band_archive.csv   (shows you the changes first)
  2. Check the scan result
  3. Plan + confirm + upload new recordings to the Internet Archive (with rate-limit retry)
  4. Analyze data
  5. Build metadata
  6. Prompt for any missing artist names
  7. Generate share links
  8. Final check -- stops here if the data would break the app
  9. Commit + push changed data files to GitHub (Streamlit Cloud auto-redeploys)

Run controls (also available as GUI checkboxes):
    python update.py                     full run
    python update.py --preview           show what the scan would change; write nothing
    python update.py --skip-upload       everything except the Internet Archive upload
    python update.py --no-push           dry run: do the work locally, don't commit or push
    python update.py --start-from NAME   begin at a step (scan, check_scan, upload, analyze,
                                         metadata, artists, share, check_final, push)
    python update.py --resume            continue from the step the last run stopped at
    python update.py --review decisions  only stop to ask about the scan when a file is missing

When a run finishes (or fails) it can send you a message -- see notifier.py.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd  # type: ignore

import archive_tools as at
import notifier

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

ARCHIVE_CSV = ROOT / "band_archive.csv"
METADATA_PATH = ROOT / "song_metadata.csv"
UPLOAD_PLAN_PATH = ROOT / "upload_plan.json"
STATE_FILE = ROOT / ".update_state.json"

UPLOAD_MAX_RETRIES = 3
UPLOAD_WAIT_SECONDS = 3600  # 1 hour, matches the old .bat's IA rate-limit backoff

LOG_FILE = ROOT / "update.log"

EXIT_ABORTED = 3            # scanner.py: the user declined the scan review

# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------

# The last few log lines are kept so a failure notification can include them.
_log_tail: deque = deque(maxlen=40)


class _TailHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            _log_tail.append(self.format(record))
        except Exception:
            pass


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("update")
    logger.setLevel(logging.INFO)
    if logger.handlers:                      # already set up (module imported twice)
        return logger

    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s", "%Y-%m-%d %H:%M:%S")

    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    if sys.stdout is not None:               # pythonw.exe has no stdout
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(fmt)
        logger.addHandler(console_handler)

    tail = _TailHandler()
    tail.setFormatter(fmt)
    logger.addHandler(tail)
    return logger


log = setup_logging()

# ----------------------------------------------------------------------
# Run options / state
# ----------------------------------------------------------------------

@dataclass
class RunOptions:
    start_from: str = "scan"        # a step name from STEPS
    skip_upload: bool = False
    push: bool = True               # False = dry run: do everything except commit + push
    preview_only: bool = False      # just show what the scan would change
    review: str = "always"          # "always" | "decisions" -- when the scan stops to show its plan


_options = RunOptions()
_summary: dict = {}


def read_state() -> dict:
    """What the last unfinished run left behind: {"failed_step", "reason", "time"} or {}."""
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(step_name: str, reason: str) -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"failed_step": step_name, "reason": reason,
                       "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}, f)
    except OSError:
        pass


def _clear_state() -> None:
    try:
        STATE_FILE.unlink()
    except OSError:
        pass


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

class StepError(Exception):
    """Raised when a pipeline step fails and the run should stop."""


class UserAbort(StepError):
    """The user declined to go ahead (e.g. cancelled the scan review). Nothing was changed."""


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


def run_script(script_name: str, extra_args: list | None = None, interactive: bool = False) -> dict | None:
    """
    Run a Python script from this repo, streaming its output live, and raise if it fails.
    Returns the script's "@RESULT@" summary dict, if it printed one.
    """
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
    if interactive:
        env["DANKAPP_PROMPT_VIA_PIPE"] = "1"

    command = [_python_executable(), str(script_path), *(extra_args or [])]

    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=env,
        stdin=subprocess.PIPE if interactive else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,  # merge streams so log lines stay in the order they were printed
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    _current_process = process
    result = None

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

            if line.startswith(RESULT_PREFIX):
                try:
                    result = json.loads(line[len(RESULT_PREFIX):])
                except ValueError:
                    pass
                continue

            if line.startswith(PROMPT_PREFIX):
                # The script is asking a question and waiting on its stdin for the answer.
                reply = {"apply": False, "remove": []}       # if anything goes wrong: change nothing
                try:
                    request = json.loads(line[len(PROMPT_PREFIX):])
                    if request.get("kind") == "scan_review":
                        handler = review_scan_callback or _default_review_scan
                        answer = handler(request)
                        if isinstance(answer, dict):
                            reply = answer
                except Exception:
                    log.exception("Couldn't resolve prompt from %s", script_name)
                try:
                    process.stdin.write(json.dumps(reply) + "\n")
                    process.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass  # child died (e.g. Cancel) while the dialog was open
                continue

            if _is_noisy_line(line):
                continue  # harmless Streamlit bare-mode warnings -- see NOISY_LINE_MARKERS above
            log.info(f"  {script_name} | {line}")
        process.wait()
    finally:
        _current_process = None

    if cancel_event.is_set():
        raise StepError(f"Cancelled during {script_name}.")

    if process.returncode == EXIT_ABORTED and script_name == "scanner.py":
        raise UserAbort("Scan cancelled - nothing was changed.")

    if process.returncode != 0:
        raise StepError(f"{script_name} exited with code {process.returncode}")
    return result


def run_git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


# ----------------------------------------------------------------------
# UI bridge
# ----------------------------------------------------------------------
# A GUI (gui.py) sets these before running the pipeline. If left unset, each
# falls back to a plain console interaction so update.py still works
# standalone from a terminal.
#
#   confirm_upload_callback(plan: list[dict]) -> bool
#   request_artists_callback(titles: list[str]) -> dict[str, str]
#   review_scan_callback(payload: dict) -> {"apply": bool, "remove": [paths]}
#   progress_callback(current: int, total: int, label: str) -> None

confirm_upload_callback = None
request_artists_callback = None
review_scan_callback = None
progress_callback = None

PROGRESS_PREFIX = "@PROGRESS@"
PROMPT_PREFIX = "@PROMPT@"
RESULT_PREFIX = "@RESULT@"

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


def _default_review_scan(payload: dict) -> dict:
    try:
        reply = at.console_review(payload)
    except (EOFError, KeyboardInterrupt):
        reply = None
    return reply if reply else {"apply": False, "remove": []}


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


def notify(subject: str, body: str = "", event: str = "info") -> None:
    """Send a notification through notifier.py (Gmail, if configured). Never raises."""
    sent, message = notifier.send(subject, body, event=event)
    if sent:
        log.info(f"[notify] sent: {subject}")
    elif not message.startswith(("Notifications are turned off", "Success alerts", "Failure alerts")):
        log.warning(f"[notify] could not send '{subject}': {message}")


# ----------------------------------------------------------------------
# Pipeline steps
# ----------------------------------------------------------------------

def step_scan():
    args = ["--review", _options.review]
    if _options.preview_only:
        args.append("--dry-run")
    result = run_script("scanner.py", extra_args=args, interactive=True)
    if result is not None:
        _summary["scan"] = result


def _check_archive(final: bool) -> None:
    issues = at.validate_archive(ARCHIVE_CSV)
    errors = [i for i in issues if i.level == "error"]
    warnings = [i for i in issues if i.level == "warning"]

    if final:
        for name in DATA_FILES:
            if not (ROOT / name).exists():
                warnings.append(at.Issue("warning", f"{name} not found - it won't be pushed."))

    for w in warnings:
        log.warning(f"Check: {w.message}")
    _summary["check_warnings"] = len(warnings)

    if errors:
        for e in errors:
            log.error(f"Check: {e.message}")
        raise StepError(
            f"band_archive.csv failed its check ({len(errors)} problem(s), listed above), "
            f"so {'nothing was pushed' if final else 'the run was stopped before uploading'}. "
            f"Fix it with Tools > Edit archive CSV, then use Resume."
        )
    log.info(f"Check passed ({len(warnings)} warning(s)).")


def step_check_scan():
    _check_archive(final=False)


def step_upload():
    if _options.skip_upload:
        log.info("Skipping the Internet Archive upload (as requested).")
        _summary["upload"] = "skipped"
        return

    log.info("Checking what needs uploading to the Internet Archive...")
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
        _summary["upload"] = "not confirmed"
        return

    log.info("Uploading...")
    attempt = 0
    while True:
        attempt += 1
        try:
            run_script("upload_to_archive.py")
            if progress_callback:
                progress_callback(0, 0, "")  # reset the bar once the step is done
            _summary["upload"] = (total_files, len(plan))
            return
        except StepError as e:
            if attempt >= UPLOAD_MAX_RETRIES:
                raise
            log.warning(
                f"upload_to_archive.py failed on attempt {attempt}/{UPLOAD_MAX_RETRIES} ({e}). "
                f"This could be Internet Archive's rate limiter, or something else -- "
                f"the retry can't tell the difference, so if it's something else it'll "
                f"just fail fast again next attempt."
            )
            notify("Upload hit a problem - retrying",
                   f"Attempt {attempt}/{UPLOAD_MAX_RETRIES} failed: {e}\n"
                   f"Retrying in {UPLOAD_WAIT_SECONDS // 60} minutes.", event="failure")
            log.info(f"Waiting {UPLOAD_WAIT_SECONDS} seconds before retrying...")
            waited = 0
            chunk = 5
            while waited < UPLOAD_WAIT_SECONDS:
                if cancel_event.is_set():
                    raise StepError("Cancelled during upload retry wait.")
                time.sleep(min(chunk, UPLOAD_WAIT_SECONDS - waited))
                waited += chunk


def step_analyze():
    run_script("analyze.py")


def step_build_metadata():
    run_script("build_metadata.py")


def step_fill_missing_artists():
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
    _summary["artists_filled"] = filled
    log.info(f"Filled in {filled} of {len(missing_titles)} artist name(s).")


def step_share_links():
    run_script("generate_share_links.py")


def step_check_final():
    _check_archive(final=True)


def step_commit_and_push():
    existing = [f for f in DATA_FILES if (ROOT / f).exists()]
    if not existing:
        raise StepError("None of the data files exist, so there is nothing to commit.")

    if not _options.push:
        log.info("Dry run - not committing or pushing. Local changes to the data files:")
        status = run_git("status", "--short", "--", *existing)
        lines = [ln for ln in status.stdout.splitlines() if ln.strip()]
        for ln in lines or ["(none)"]:
            log.info(f"  {ln}")
        _summary["push"] = "dry run (not pushed)"
        return

    add = run_git("add", *existing)
    if add.returncode != 0:
        raise StepError(f"git add failed:\n{add.stderr}")

    diff = run_git("diff", "--cached", "--quiet")
    if diff.returncode == 0:
        log.info("No changes to the data files. Nothing to push.")
        log.info("Done - database was already up to date.")
        _summary["push"] = "nothing to push (already up to date)"
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

    short = run_git("rev-parse", "--short", "HEAD").stdout.strip()
    _summary["push"] = f"pushed commit {short}" if short else "pushed"
    log.info("Done! Streamlit Cloud will redeploy automatically in a minute or two.")


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

STEPS = [
    ("scan", "Scan files", step_scan),
    ("check_scan", "Check the scan result", step_check_scan),
    ("upload", "Upload to Internet Archive", step_upload),
    ("analyze", "Analyze data", step_analyze),
    ("metadata", "Build metadata", step_build_metadata),
    ("artists", "Fill missing artists", step_fill_missing_artists),
    ("share", "Generate share links", step_share_links),
    ("check_final", "Final check before push", step_check_final),
    ("push", "Commit and push", step_commit_and_push),
]
STEP_NAMES = [name for name, _label, _fn in STEPS]
STEP_LABELS = {name: label for name, label, _fn in STEPS}


def _format_duration(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def _format_summary(elapsed: float) -> str:
    lines = []
    scan = _summary.get("scan")
    if scan and not scan.get("preview"):
        bits = []
        if scan.get("added"):
            bits.append(f"{scan['added']} new track row(s) from {scan.get('added_files', 0)} file(s)")
        if scan.get("swapped"):
            bits.append(f"{scan['swapped']} placeholder(s) replaced by recordings")
        if scan.get("removed"):
            bits.append(f"{scan['removed']} row(s) removed")
        if scan.get("flagged"):
            bits.append(f"{scan['flagged']} flagged missing")
        if scan.get("restored"):
            bits.append(f"{scan['restored']} restored")
        lines.append("Scan: " + (", ".join(bits) if bits else "no changes"))
        if scan.get("new_shows"):
            lines.append("Shows touched: " + "; ".join(scan["new_shows"]))
    upload = _summary.get("upload")
    if isinstance(upload, tuple):
        lines.append(f"Uploaded {upload[0]} file(s) from {upload[1]} show(s) to the Internet Archive.")
    elif upload:
        lines.append(f"Upload: {upload}")
    if _summary.get("artists_filled"):
        lines.append(f"Artist names filled in: {_summary['artists_filled']}")
    if "check_warnings" in _summary:
        lines.append(f"Data check: passed with {_summary['check_warnings']} warning(s).")
    if "push" in _summary:
        lines.append(f"Git: {_summary['push']}")
    lines.append(f"Took {_format_duration(elapsed)}.")
    return "\n".join(lines)


def run_pipeline(options: RunOptions | None = None) -> str:
    """
    Run the pipeline. Returns one of:
      "ok"         finished
      "preview"    preview finished (nothing was changed)
      "failed"     a step failed
      "cancelled"  Cancel was pressed
      "aborted"    the scan review was declined (nothing was changed)
    """
    global _options, _summary
    _options = options or RunOptions()
    _summary = {}
    cancel_event.clear()
    _log_tail.clear()
    started = time.monotonic()

    if _options.start_from not in STEP_NAMES:
        log.error(f"Unknown step '{_options.start_from}'. Choose one of: {', '.join(STEP_NAMES)}")
        return "failed"

    log.info("=" * 50)
    log.info("  DankApp Database Update" + ("  (preview)" if _options.preview_only else ""))
    log.info("=" * 50)
    log.info(f"Working directory: {ROOT}")

    if _options.preview_only:
        steps = [(i, s) for i, s in enumerate(STEPS, 1) if s[0] == "scan"]
    else:
        start = STEP_NAMES.index(_options.start_from)
        steps = [(i, s) for i, s in enumerate(STEPS, 1) if i - 1 >= start]
        if start:
            log.info(f"Starting from '{STEP_LABELS[_options.start_from]}' (steps before it are skipped).")

    for number, (name, label, fn) in steps:
        if cancel_event.is_set():
            log.warning(f"Cancelled before {label}.")
            _write_state(name, "cancelled")
            return "cancelled"
        log.info(f"[{number}/{len(STEPS)}] {label}...")
        try:
            fn()
        except UserAbort as e:
            log.warning(f"Stopped: {e}")
            return "aborted"
        except StepError as e:
            if cancel_event.is_set():
                log.warning(f"Cancelled: {e}")
                _write_state(name, "cancelled")
                return "cancelled"
            log.error(f"Stopping: {e}")
            _write_state(name, str(e))
            tail = "\n".join(_log_tail)
            notify("Update FAILED", f"The update stopped at '{label}'.\n\n{e}\n\nLast log lines:\n{tail}",
                   event="failure")
            return "failed"
        except Exception as e:
            log.exception(f"Unexpected error in {label}: {e}")
            _write_state(name, f"{type(e).__name__}: {e}")
            tail = "\n".join(_log_tail)
            notify("Update CRASHED", f"Unexpected error in '{label}': {type(e).__name__}: {e}\n\n"
                                      f"Last log lines:\n{tail}", event="failure")
            return "failed"

    if _options.preview_only:
        log.info("Preview finished. Nothing was changed.")
        return "preview"

    _clear_state()
    summary = _format_summary(time.monotonic() - started)
    log.info("Pipeline finished successfully.")
    for line in summary.splitlines():
        log.info(f"  {line}")
    notify("Update finished", summary, event="success")
    return "ok"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="DankApp database update")
    ap.add_argument("--preview", action="store_true", help="show what the scan would change; write nothing")
    ap.add_argument("--skip-upload", action="store_true", help="skip the Internet Archive upload")
    ap.add_argument("--no-push", action="store_true", help="dry run: don't commit or push")
    ap.add_argument("--start-from", choices=STEP_NAMES, default="scan", help="begin at this step")
    ap.add_argument("--resume", action="store_true", help="continue from the step the last run stopped at")
    ap.add_argument("--review", choices=["always", "decisions"], default="always",
                    help="when the scan stops to show its plan")
    args = ap.parse_args(argv)

    start_from = args.start_from
    if args.resume:
        failed = read_state().get("failed_step")
        if failed in STEP_NAMES:
            start_from = failed
        else:
            print("Nothing to resume - the last run finished (or never started).")
            return 0

    status = run_pipeline(RunOptions(
        start_from=start_from, skip_upload=args.skip_upload, push=not args.no_push,
        preview_only=args.preview, review=args.review,
    ))
    return 0 if status in ("ok", "preview", "aborted") else 1


if __name__ == "__main__":
    sys.exit(main())