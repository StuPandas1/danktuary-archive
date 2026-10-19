#!/usr/bin/env python3
"""
archive_tools.py - shared helpers for the DankApp update tools

Plain pandas/stdlib only (no Streamlit, no tkinter), so the scanner, the
pipeline, the GUI and the CSV editor can all use the same code.

  load_archive / save_archive   safe CSV reading, plus a timestamped backup
                                and an atomic write on every save
  validate_archive              the checks the push gate runs -- including the
                                one that catches a show whose tracks would all
                                be hidden from the player
  format_review / console_review
                                the "here's what the scan is about to change"
                                text, and a terminal version of that prompt

Run directly to validate a CSV:
    python archive_tools.py [band_archive.csv]
"""

from __future__ import annotations

import csv
import os
import re
import shutil
import sys
import time
import warnings
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np  # type: ignore
import pandas as pd  # type: ignore

# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------

BASE_FIELDNAMES = [
    "Track Number", "File Track", "Title", "Date", "Location",
    "Type", "Duration", "Raw Title", "File Path", "Take", "IA URL", "OneDrive URL", "Status",
]

# Columns the Streamlit app needs in order to build a show's track list.
REQUIRED_COLUMNS = ["Track Number", "Title", "Date", "Location", "Duration", "File Path", "Take"]

AUDIO_EXTS = (".mp3", ".m4a", ".wav", ".wma", ".aac")
PLACEHOLDER_EXTS = (".bmp",)          # stand-in files for shows with no recording yet
TRACKED_EXTS = AUDIO_EXTS + PLACEHOLDER_EXTS

BACKUP_KEEP = 20
_DURATION_RE = re.compile(r"^(N/A|\d+:\d{2}(:\d{2})?)$")


def is_audio(path) -> bool:
    return str(path).lower().endswith(AUDIO_EXTS)


def is_placeholder(path) -> bool:
    return str(path).lower().endswith(PLACEHOLDER_EXTS)


# ----------------------------------------------------------------------
# Loading / saving
# ----------------------------------------------------------------------

# Older versions of the scanner wrote pandas' NaN straight into the CSV, which
# shows up as the text "nan". Treat those as blank on the way in.
_BLANK_TOKENS = {"nan": "", "NaN": "", "None": ""}
_KEEP_AS_IS = ("Title", "Raw Title")


def load_archive(path) -> pd.DataFrame:
    """Read the archive CSV with every column as text and blanks as ''."""
    last_error: Exception | None = None
    df = None
    # utf-8-sig also swallows the BOM Excel's "CSV UTF-8" adds; utf-16 is
    # Excel's "Unicode Text"; cp1252 is Excel's plain "CSV".
    for encoding in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding=encoding)
            break
        except UnicodeError as e:
            last_error = e
    if df is None:
        raise last_error or ValueError("could not decode file")

    df.columns = [str(c).strip().lstrip("﻿") for c in df.columns]
    for col in df.columns:
        if col not in _KEEP_AS_IS:
            df[col] = df[col].replace(_BLANK_TOKENS)
    return df


def backup_file(path, keep: int = BACKUP_KEEP):
    """Copy `path` into a backups/ folder next to it; prune to the newest `keep`."""
    path = Path(path)
    if not path.exists():
        return None
    backup_dir = path.parent / "backups"
    backup_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backup_dir / f"{path.stem}_{stamp}{path.suffix}"
    shutil.copy2(path, dest)
    old = sorted(backup_dir.glob(f"{path.stem}_*{path.suffix}"))
    for stale in old[:-keep]:
        try:
            stale.unlink()
        except OSError:
            pass
    return dest


def save_archive(df: pd.DataFrame, path, columns=None, backup: bool = True):
    """
    Write the archive CSV safely: back up the old file, write to a temp file,
    then swap it into place, so a crash mid-write can't leave a half-written
    band_archive.csv. Returns the backup path (or None).
    """
    path = Path(path)
    cols = list(columns) if columns else list(df.columns)
    out = df.reindex(columns=cols).fillna("")
    backup_path = backup_file(path) if backup else None

    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)          # default dialect -> same CRLF endings the scanner always wrote
        writer.writerow(cols)
        for rec in out.itertuples(index=False, name=None):
            writer.writerow(["" if v is None else str(v) for v in rec])

    for attempt in range(5):
        try:
            os.replace(tmp, path)
            break
        except PermissionError:          # OneDrive sync can hold the file for a moment
            if attempt == 4:
                raise
            time.sleep(0.5)
    return backup_path


# ----------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------

@dataclass
class Issue:
    level: str                                   # "error" | "warning"
    message: str
    rows: list = field(default_factory=list)     # DataFrame index labels (the editor can jump to these)

    def __str__(self) -> str:
        return f"[{self.level.upper()}] {self.message}"


def validate_archive(source) -> list:
    """
    Check the archive for problems that would break or silently empty the app.
    `source` is a path or an already-loaded DataFrame. Errors are things that
    break the app (the push gate stops on these); warnings are worth a look.
    """
    issues: list = []

    if isinstance(source, pd.DataFrame):
        df = source
    else:
        p = Path(source)
        if not p.exists():
            return [Issue("error", f"{p.name} does not exist.")]
        try:
            df = load_archive(p)
        except Exception as e:
            return [Issue("error", f"{p.name} could not be read as a CSV ({e}).")]

    missing_cols = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_cols:
        hint = ""
        if len(df.columns) == 1:
            hint = (" The whole header was read as a single column - the file may "
                    "use a different delimiter (semicolons?).")
        found = ", ".join(map(str, df.columns))
        return [Issue("error", f"Missing required column(s): {', '.join(missing_cols)}. Found: {found}.{hint}")]
    if df.empty:
        return [Issue("error", "The archive has no rows.")]

    def desc(i) -> str:
        return f"{df.at[i, 'Date']} {df.at[i, 'Location']} / {df.at[i, 'Title']}"

    def add(level: str, message: str, idxs=None) -> None:
        idxs = list(idxs) if idxs is not None else []
        if idxs:
            sample = "; ".join(desc(i) for i in idxs[:5])
            more = f" (+{len(idxs) - 5} more)" if len(idxs) > 5 else ""
            message = f"{message} e.g. {sample}{more}"
        issues.append(Issue(level, message, idxs))

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dt = pd.to_datetime(df["Date"], errors="coerce")

    fp = df["File Path"].str.strip()
    audio = fp.map(is_audio).astype(bool)
    status = (df["Status"].str.strip().str.lower()
              if "Status" in df.columns else pd.Series("", index=df.index))
    take = pd.to_numeric(df["Take"], errors="coerce")
    track = pd.to_numeric(df["Track Number"], errors="coerce")

    # --- row-level problems the app would trip over ---
    bad = df.index[dt.isna()]
    if len(bad):
        add("error", f"{len(bad)} row(s) have a Date that can't be read as a date.", bad)

    bad = df.index[df["Location"].str.strip() == ""]
    if len(bad):
        add("error", f"{len(bad)} row(s) have no Location, so they can't be grouped into a show.", bad)

    # --- the show-level check: audio exists but nothing would reach the player ---
    key_date = dt.dt.strftime("%m/%d/%Y")
    is_candidate = audio & (status != "missing") & dt.notna()
    is_playable = is_candidate & (take == 1)
    shows = pd.DataFrame({
        "d": key_date, "l": df["Location"],
        "audio": audio & dt.notna(), "cand": is_candidate, "play": is_playable,
    }).groupby(["d", "l"]).agg(audio=("audio", "sum"), cand=("cand", "sum"), play=("play", "sum"))

    for (d, loc), r in shows[(shows.cand > 0) & (shows.play == 0)].iterrows():
        idxs = list(df.index[(key_date == d) & (df["Location"] == loc) & is_candidate])
        takes = sorted({df.at[i, "Take"] for i in idxs})[:5]
        add("error",
            f"Show {d} - {loc}: {int(r.cand)} audio row(s) but none have Take 1 "
            f"(Take values: {', '.join(t or 'blank' for t in takes)}), so the player would have nothing to show.",
            idxs)
    for (d, loc), r in shows[(shows.audio > 0) & (shows.cand == 0)].iterrows():
        idxs = list(df.index[(key_date == d) & (df["Location"] == loc) & audio])
        add("warning", f"Show {d} - {loc}: every recording is flagged missing.", idxs)

    # --- things worth a look, but that don't break the app ---
    bad = df.index[audio & take.isna()]
    if len(bad):
        add("warning", f"{len(bad)} audio row(s) have a blank or non-numeric Take, so the player skips them.", bad)

    bad = df.index[track.isna()]
    if len(bad):
        add("warning", f"{len(bad)} row(s) have a blank or non-numeric Track Number.", bad)

    bad = df.index[~status.isin(["", "missing"])]
    if len(bad):
        add("warning", f"{len(bad)} row(s) have an unrecognised Status (expected blank or 'missing').", bad)

    dur_ok = df["Duration"].str.strip().map(lambda v: bool(_DURATION_RE.match(v)))
    bad = df.index[audio & ~dur_ok]
    if len(bad):
        add("warning", f"{len(bad)} audio row(s) have a Duration that isn't M:SS or H:MM:SS "
                       f"(Excel can turn these into times).", bad)

    bad = df.index[(fp != "") & df.duplicated(subset=["File Path", "Title"], keep=False)]
    if len(bad):
        add("warning", f"{len(bad)} row(s) are duplicates (same File Path and Title).", bad)

    folder = fp.map(lambda p: os.path.dirname(p.replace("\\", "/")))
    probe = pd.DataFrame({"f": folder, "t": track})
    bad = df.index[(fp != "") & track.notna() & probe.duplicated(subset=["f", "t"], keep=False)]
    if len(bad):
        add("warning", f"{len(bad)} row(s) share a Track Number with another row in the same folder.", bad)

    issues.sort(key=lambda i: 0 if i.level == "error" else 1)
    return issues


def summarize_issues(issues) -> tuple:
    errors = sum(1 for i in issues if i.level == "error")
    return errors, len(issues) - errors


def format_issues(issues) -> str:
    return "\n".join(f"{'ERROR  ' if i.level == 'error' else 'warning'}  {i.message}" for i in issues)


# ----------------------------------------------------------------------
# Scan review (what the scanner is about to change)
# ----------------------------------------------------------------------

def format_review(payload: dict, include_missing: bool = True) -> str:
    """Plain-text rendering of the scanner's change preview (shared by the console and the GUI)."""
    out: list = []

    if payload.get("warning"):
        out += ["!! " + payload["warning"], ""]
    roots = payload.get("unreachable_roots", [])
    for r in roots:
        out.append(f"!! Archive folder not reachable (rows under it were left alone): {r}")
    if roots:
        out.append("")

    swaps = payload.get("swaps", [])
    if swaps:
        out.append(f"Placeholders replaced by recordings - updated in place ({len(swaps)}):")
        for s in swaps:
            out.append(f"  {s['label']}   [{s['old']} -> {s['new']}]")
        out.append("")

    groups = payload.get("new_files", [])
    if groups:
        n_files = sum(len(g["files"]) for g in groups)
        out.append(f"New files ({n_files} in {len(groups)} show(s)):")
        for g in groups:
            out.append(f"  {g['show']}")
            for f in g["files"]:
                tag = "   (placeholder)" if f.get("placeholder") else ""
                out.append(f"      {f['name']}  ->  {' / '.join(f['titles'])}{tag}")
        out.append("")

    restored = payload.get("restored", [])
    if restored:
        out.append(f"Back on disk - no longer flagged missing ({len(restored)}):")
        out += [f"  {r['label']}" for r in restored]
        out.append("")

    folders = payload.get("deleted_folders", [])
    if folders:
        out.append(f"Folders that no longer exist ({len(folders)}):")
        out += [f"  {f}" for f in folders]
        out.append("")

    missing = payload.get("missing", [])
    if include_missing and missing:
        out.append(f"In the CSV but no longer on disk ({len(missing)}):")
        for m in missing:
            note = "  (already flagged missing)" if m.get("already_flagged") else ""
            out.append(f"  {m['label']}{note}")
        out.append("")

    if not out:
        out.append("Nothing has changed.")
    return "\n".join(out).rstrip()


def console_review(payload: dict, ask=input):
    """
    Terminal version of the review prompt. Returns {"apply": True, "remove": [paths]},
    or None if the user declines (or it's a preview, where nothing is applied).
    """
    print(format_review(payload, include_missing=bool(payload.get("preview_only"))))
    if payload.get("preview_only"):
        return None

    missing = payload.get("missing", [])
    remove: list = []
    if missing:
        print(f"\n{len(missing)} file(s) are in the CSV but no longer on disk. "
              f"Removing a row deletes its record (including any Internet Archive link).")
    for m in missing:
        default_yes = bool(m.get("preselect"))
        answer = ask(f"  Remove '{m['label']}' from the CSV? {'[Y/n]' if default_yes else '[y/N]'} ").strip().lower()
        if (answer.startswith("y")) or (answer == "" and default_yes):
            remove.append(m["path"])

    if ask("\nApply these changes? [Y/n] ").strip().lower().startswith("n"):
        return None
    return {"apply": True, "remove": remove}


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    argv = list(sys.argv[1:] if argv is None else argv)
    path = argv[0] if argv else "band_archive.csv"
    issues = validate_archive(path)
    errors, warns = summarize_issues(issues)
    if issues:
        print(format_issues(issues))
    print(f"\n{path}: {errors} error(s), {warns} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())