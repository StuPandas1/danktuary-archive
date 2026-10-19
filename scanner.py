#!/usr/bin/env python3
"""
scanner.py - Catalogue the band's recordings into band_archive.csv

Works in two phases so nothing is changed before you've seen it:

  1. PLAN   Compare the CSV with what's on disk and work out what would change:
              - placeholder swaps  a .bmp placeholder whose same-named audio file
                                   now exists is updated IN PLACE (it keeps its
                                   track number, take, and any share-link columns)
              - new files          brand-new tracks to add
              - missing files      rows whose file is gone (you decide: remove or
                                   keep flagged "missing")
              - restored files     rows flagged missing whose file is back
  2. APPLY  Show you the plan (a dialog when launched from update.py / gui.py, a
            prompt in a terminal), then write the CSV -- backing up the old one
            first and swapping the new one in atomically.

Usage (normally launched by update.py):
    python scanner.py                    review the plan, then apply it
    python scanner.py --dry-run          show the plan only; write nothing
    python scanner.py --review decisions only stop to ask when a file is missing
    python scanner.py --yes              never ask; add new files, keep missing flagged

Environment overrides (handy for testing):
    DANKAPP_CSV             path to the CSV (default band_archive.csv)
    DANKAPP_ARCHIVE_PATHS   archive folders, separated by the OS path separator
    DANKAPP_PROMPT_VIA_PIPE set by update.py: ask for decisions over stdin/stdout
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import re
import string
import sys
from collections import defaultdict
from dataclasses import dataclass, field

import pandas as pd  # type: ignore
from mutagen import File as MutagenFile

import archive_tools as at
from shared import manual_fixes, junk_terms, segue_fixes, local_path_to_onedrive_url

PROMPT_PREFIX = "@PROMPT@"
RESULT_PREFIX = "@RESULT@"
PROGRESS_PREFIX = "@PROGRESS@"
EXIT_ABORTED = 3          # the user declined the review -- nothing was written
EXIT_BAD_CSV = 2

DEFAULT_ARCHIVE_PATHS = [
    r"C:\Users\Administrator\OneDrive\LoveDeep\Audio Recordings\Gig Recordings",
    r"C:\Users\Administrator\OneDrive\LoveDeep\Audio Recordings\Jam Session Recordings 2015-2020",
    r"C:\Users\Administrator\OneDrive\LoveDeep\Audio Recordings\Jam Session Recordings 2021-",
    r"C:\Users\Administrator\OneDrive\LoveDeep\Audio Recordings\Trips",
]

CSV_PATH = os.environ.get("DANKAPP_CSV", "band_archive.csv")


def archive_paths() -> list:
    override = os.environ.get("DANKAPP_ARCHIVE_PATHS")
    if override:
        return [p for p in override.split(os.pathsep) if p]
    return list(DEFAULT_ARCHIVE_PATHS)


# ----------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------

def stem_of(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def norm(path: str) -> str:
    """Case/slash-insensitive form of a path, for comparisons."""
    return path.replace("\\", "/").rstrip("/").lower()


def is_under(path: str, root: str) -> bool:
    return norm(path).startswith(norm(root) + "/")


def get_duration(filepath):
    try:
        audio = MutagenFile(filepath)
        if audio is not None and audio.info is not None:
            seconds = int(audio.info.length)
            minutes, secs = divmod(seconds, 60)
            if minutes >= 60:
                hours, minutes = divmod(minutes, 60)
                return f"{hours}:{minutes:02d}:{secs:02d}"
            return f"{minutes}:{secs:02d}"
    except Exception:
        pass
    return "N/A"


def emit_progress(current: int, total: int, label: str = "") -> None:
    print(PROGRESS_PREFIX + json.dumps({"current": current, "total": total, "label": label}), flush=True)


def emit_result(result: dict) -> None:
    print(RESULT_PREFIX + json.dumps(result), flush=True)


# ----------------------------------------------------------------------
# Filename / folder parsing (same rules the scanner has always used)
# ----------------------------------------------------------------------

def parse_filename(file: str):
    """-> (raw_name, file_track_number, [song titles]) -- a segue file yields several titles."""
    raw_name = os.path.splitext(file)[0]
    match = re.match(r"^(\d+)[_ -]*(.*)", raw_name)
    if match:
        track_number = match.group(1)
        raw_title = match.group(2).strip()
    else:
        track_number = ""
        raw_title = raw_name

    raw_title = raw_title.lower()
    for old, new in segue_fixes.items():
        raw_title = raw_title.replace(old, new)
    for term in junk_terms:
        raw_title = raw_title.replace(term, "")

    titles = []
    for raw_song in (s.strip() for s in raw_title.split("_")):
        cleaned = raw_song.strip().lower().replace("  ", " ")
        cleaned = re.sub(r"\s+jam$", "", cleaned)
        if cleaned in manual_fixes:
            cleaned = manual_fixes[cleaned]
        titles.append(string.capwords(cleaned))
    return raw_name, track_number, titles


@functools.lru_cache(maxsize=None)
def show_info(root: str):
    """-> (date, recording_type, location) for a show folder."""
    folder_name = os.path.basename(root)
    date = folder_name[:10]
    lower_root = root.lower()

    def place_from_name() -> str:
        parts = folder_name.split(" _ ", 1)
        if len(parts) == 2:
            return parts[1]
        print(f"Warning: folder '{folder_name}' has no ' _ ' separator; "
              f"using the rest of the name as the location.")
        return folder_name[10:].strip(" _-") or "Unknown"

    if "gig" in lower_root:
        return date, "live", place_from_name()
    if "trips" in lower_root:
        return date, "trip", place_from_name()
    if date >= "2024-06-26":
        place = "Danktuary Studios"
    elif date >= "2020-03-10":
        place = "Studio Chill"
    else:
        place = "The Music Building"
    return date, "practice", place


def show_label(root: str) -> str:
    date, _, place = show_info(root)
    return f"{date} — {place}"


# ----------------------------------------------------------------------
# Loading the existing CSV
# ----------------------------------------------------------------------

def load_existing_rows():
    """-> (rows as dicts, column names). Refuses to carry on if the CSV exists but can't be read."""
    if not os.path.exists(CSV_PATH):
        print(f"No existing {CSV_PATH} - starting a new catalogue.")
        return [], []
    try:
        df = at.load_archive(CSV_PATH)
        if "File Path" not in df.columns:
            raise ValueError("no 'File Path' column")
    except Exception as e:
        print(f"ERROR: could not read the existing {CSV_PATH} ({e}).")
        print("Refusing to carry on, because writing a fresh file would throw away your Internet "
              "Archive links and share links. Fix the file, or restore the newest copy from the "
              "backups folder, then run again.")
        sys.exit(EXIT_BAD_CSV)

    rows = df.to_dict("records")
    n_files = len({r["File Path"] for r in rows if r.get("File Path")})
    print(f"Loaded {len(rows)} existing row(s); {n_files} file(s) already catalogued and will be skipped.")
    extra = [c for c in df.columns if c not in at.BASE_FIELDNAMES]
    if extra:
        print(f"Found extra column(s) in {CSV_PATH} added by another script: {extra}. Preserving them.")
    return rows, list(df.columns)


# ----------------------------------------------------------------------
# PLAN phase (read-only)
# ----------------------------------------------------------------------

@dataclass
class Plan:
    swaps: list = field(default_factory=list)              # {"old_path", "new_path"}
    missing: list = field(default_factory=list)            # {"path", "already_flagged"}
    restored: list = field(default_factory=list)           # paths
    new_files: list = field(default_factory=list)          # {"path", "root", "file"}
    deleted_folders: list = field(default_factory=list)
    unreachable_roots: list = field(default_factory=list)
    warning: str = ""

    @property
    def new_missing(self) -> list:
        return [m for m in self.missing if not m["already_flagged"]]

    @property
    def has_changes(self) -> bool:
        return bool(self.swaps or self.new_missing or self.restored or self.new_files)


def build_plan(rows: list, roots: list) -> Plan:
    plan = Plan()

    reachable = []
    for ap in roots:
        if os.path.isdir(ap):
            reachable.append(ap)
        else:
            plan.unreachable_roots.append(ap)
            print(f"Warning: archive folder not found (is OneDrive offline?): {ap}")

    disk = []                                   # (filepath, root, file) in walk order
    for ap in reachable:
        for root, _dirs, files in os.walk(ap):
            for f in sorted(files):
                if f.lower().endswith(at.TRACKED_EXTS):
                    disk.append((os.path.join(root, f), root, f))

    catalogued = {r["File Path"] for r in rows if r.get("File Path")}
    flagged = {r["File Path"] for r in rows
               if r.get("File Path") and r.get("Status", "").strip().lower() == "missing"}
    known_folders = {os.path.dirname(p) for p in catalogued}

    def unverifiable(p: str) -> bool:
        return any(is_under(p, ap) for ap in plan.unreachable_roots)

    # Missing / restored files. Rows under an unreachable archive folder are left
    # alone -- otherwise an offline OneDrive would look like "everything was deleted".
    for fp in sorted(catalogued):
        if unverifiable(fp):
            continue
        if not os.path.exists(fp):
            plan.missing.append({"path": fp, "already_flagged": fp in flagged})
        elif fp in flagged:
            plan.restored.append(fp)

    for folder in sorted(known_folders):
        if not unverifiable(folder) and not os.path.isdir(folder):
            plan.deleted_folders.append(folder)
            print(f"Folder removed: '{folder}' no longer exists on disk.")

    # Placeholder swaps: catalogued .bmp whose same-named audio file now exists.
    audio_by_key = defaultdict(list)
    for fp, root, f in disk:
        if at.is_audio(fp):
            audio_by_key[(norm(root), stem_of(f).lower())].append(fp)

    swapped_new = set()
    for pp in sorted(p for p in catalogued if at.is_placeholder(p)):
        key = (norm(os.path.dirname(pp)), stem_of(pp).lower())
        cands = [a for a in audio_by_key.get(key, []) if a not in catalogued and a not in swapped_new]
        if cands:
            best = sorted(cands, key=lambda a: at.AUDIO_EXTS.index(os.path.splitext(a)[1].lower()))[0]
            plan.swaps.append({"old_path": pp, "new_path": best})
            swapped_new.add(best)

    swap_old = {s["old_path"] for s in plan.swaps}
    plan.missing = [m for m in plan.missing if m["path"] not in swap_old]
    plan.restored = [p for p in plan.restored if p not in swap_old]

    # New files. A placeholder that has a same-named audio file beside it is
    # superseded, so a leftover .bmp doesn't get catalogued again.
    announced = set()
    for fp, root, f in disk:
        if fp in catalogued or fp in swapped_new:
            continue
        if at.is_placeholder(fp) and audio_by_key.get((norm(root), stem_of(f).lower())):
            continue
        if root not in known_folders and root not in announced:
            announced.add(root)
            print(f"New folder detected: '{root}'")
        print(f"New file detected: '{fp}'")
        plan.new_files.append({"path": fp, "root": root, "file": f})

    n = len(plan.new_missing)
    if n >= 10 and n > 0.25 * max(len(catalogued), 1):
        plan.warning = (f"{n} of {len(catalogued)} catalogued files look missing at once. That usually "
                        f"means OneDrive isn't fully synced or a folder was moved, not that you deleted "
                        f"them - nothing is pre-selected for removal.")
    return plan


def build_payload(plan: Plan, rows: list, preview_only: bool = False) -> dict:
    titles = defaultdict(list)
    has_ia = set()
    for r in rows:
        fp = r.get("File Path")
        if fp:
            titles[fp].append(r.get("Title", ""))
            if r.get("IA URL", "").strip():
                has_ia.add(fp)

    def label(path: str) -> str:
        return f"{show_label(os.path.dirname(path))}  /  {os.path.basename(path)}"

    groups: dict = {}
    for nf in plan.new_files:
        _raw, _num, parsed = parse_filename(nf["file"])
        groups.setdefault(show_label(nf["root"]), []).append(
            {"name": nf["file"], "titles": parsed, "placeholder": at.is_placeholder(nf["path"])})

    return {
        "kind": "scan_review",
        "preview_only": preview_only,
        "warning": plan.warning,
        "unreachable_roots": plan.unreachable_roots,
        "deleted_folders": plan.deleted_folders,
        "swaps": [{
            "label": f"{show_label(os.path.dirname(s['new_path']))}: {' / '.join(titles[s['old_path']])}",
            "old": os.path.basename(s["old_path"]),
            "new": os.path.basename(s["new_path"]),
        } for s in plan.swaps],
        "new_files": [{"show": show, "files": files} for show, files in groups.items()],
        "restored": [{"path": p, "label": label(p)} for p in plan.restored],
        "missing": [{
            "path": m["path"],
            "label": f"{label(m['path'])}  ({' / '.join(titles[m['path']])})",
            "already_flagged": m["already_flagged"],
            "has_ia_url": m["path"] in has_ia,
            "preselect": (not plan.warning) and (not m["already_flagged"]) and (m["path"] not in has_ia),
        } for m in plan.missing],
    }


# ----------------------------------------------------------------------
# Asking the user
# ----------------------------------------------------------------------

def ask_via_pipe(payload: dict):
    """Ask update.py (and through it, the GUI) over stdin/stdout. None = no usable answer."""
    print(PROMPT_PREFIX + json.dumps(payload), flush=True)
    line = sys.stdin.readline()
    if not line:
        return None
    try:
        reply = json.loads(line)
    except ValueError:
        return None
    return reply if isinstance(reply, dict) else None


def decide(args, plan: Plan, payload: dict):
    """-> {"apply": bool, "remove": [paths]}, or None if the user cancelled."""
    default = {"apply": True, "remove": []}          # additions only; missing files stay, flagged
    needs_review = args.review == "always" or bool(plan.new_missing)
    if args.review == "never" or not needs_review:
        return default
    if os.environ.get("DANKAPP_PROMPT_VIA_PIPE") == "1":
        reply = ask_via_pipe(payload)
        return reply if reply and reply.get("apply") else None
    if sys.stdin is not None and sys.stdin.isatty():
        try:
            return at.console_review(payload)
        except (EOFError, KeyboardInterrupt):
            return None
    print("No interactive input available - adding new files and keeping missing files flagged.")
    return default


# ----------------------------------------------------------------------
# APPLY phase
# ----------------------------------------------------------------------

def build_state(rows: list) -> dict:
    """
    Per-folder numbering state, rebuilt from the rows that will be in the CSV:
    the next Track Number, and the highest Take seen per song title.
    Placeholder (.bmp) rows are counted separately, so a placeholder never uses
    up "take 1" before the real recording arrives.
    """
    state: dict = {}
    for row in rows:
        fp = row.get("File Path", "")
        if not fp:
            continue
        st = state.setdefault(os.path.dirname(fp), {"next_track": 1, "seen_songs": {}, "seen_placeholders": {}})
        try:
            st["next_track"] = max(st["next_track"], int(row.get("Track Number", "")) + 1)
        except (TypeError, ValueError):
            pass
        title, take = row.get("Title", ""), row.get("Take", "")
        if title and take:
            base = re.sub(r"\s\(\d+\)$", "", title)
            bucket = st["seen_placeholders"] if at.is_placeholder(fp) else st["seen_songs"]
            try:
                bucket[base] = max(bucket.get(base, 0), int(take))
            except ValueError:
                pass
    return state


def make_rows_for_file(filepath: str, root: str, file: str, state: dict) -> list:
    raw_name, track_number, titles = parse_filename(file)
    date, rec_type, place = show_info(root)
    duration = get_duration(filepath)
    onedrive_url = local_path_to_onedrive_url(filepath) or ""
    bucket = state["seen_placeholders"] if at.is_placeholder(filepath) else state["seen_songs"]

    rows = []
    for title in titles:
        if title not in bucket:
            take, display = 1, title
        else:
            take = bucket[title] + 1
            display = f"{title} ({take})"
        rows.append({
            "Track Number": str(state["next_track"]),
            "File Track": track_number,
            "Title": display,
            "Date": date,
            "Location": place,
            "Type": rec_type,
            "Duration": duration,
            "Raw Title": raw_name,
            "File Path": filepath,
            "Take": str(take),
            "IA URL": "",
            "OneDrive URL": onedrive_url,
            "Status": "",
        })
        bucket[title] = take
        state["next_track"] += 1
    return rows


def apply_plan(rows: list, plan: Plan, remove: set):
    """-> (final rows, stats). `remove` = missing paths the user chose to drop."""
    swap_map = {s["old_path"]: s["new_path"] for s in plan.swaps}
    missing_set = {m["path"] for m in plan.missing}
    restored_set = set(plan.restored)
    stats = {"swapped": 0, "removed": 0, "flagged": 0, "restored": 0}
    total = len(plan.swaps) + len(plan.new_files)
    done = 0
    shows_touched = []

    def touch(root: str) -> None:
        label = show_label(root)
        if label not in shows_touched:
            shows_touched.append(label)

    final = []
    swapped_seen = set()
    for row in rows:
        fp = row.get("File Path", "")
        if fp in swap_map:
            new = swap_map[fp]
            if new not in swapped_seen:               # one duration lookup per file, not per segue row
                swapped_seen.add(new)
                done += 1
                emit_progress(done, total, os.path.basename(new))
                touch(os.path.dirname(new))
                stats["swapped"] += 1
                print(f"Placeholder replaced: '{fp}' -> '{new}' (row kept in place)")
            row["File Path"] = new
            row["Raw Title"] = stem_of(new)
            row["Duration"] = get_duration(new)
            row["OneDrive URL"] = local_path_to_onedrive_url(new) or ""
            if row.get("Status", "").strip().lower() == "missing":
                row["Status"] = ""
        elif fp in missing_set:
            if fp in remove:
                print(f"File removed: '{fp}' dropped from CSV.")
                stats["removed"] += 1
                continue
            if row.get("Status", "").strip().lower() != "missing":
                stats["flagged"] += 1
                print(f"File kept in CSV, labeled Status: missing -> '{fp}'")
            row["Status"] = "missing"
        elif fp in restored_set:
            if row.get("Status", "").strip().lower() == "missing":
                row["Status"] = ""
                stats["restored"] += 1
        final.append(row)

    state = build_state(final)
    new_rows = []
    new_file_count = 0
    for nf in plan.new_files:
        st = state.setdefault(nf["root"], {"next_track": 1, "seen_songs": {}, "seen_placeholders": {}})
        done += 1
        emit_progress(done, total, nf["file"])
        new_rows += make_rows_for_file(nf["path"], nf["root"], nf["file"], st)
        new_file_count += 1
        touch(nf["root"])

    emit_progress(0, 0, "")
    stats.update({"added": len(new_rows), "added_files": new_file_count, "new_shows": shows_touched})
    return final + new_rows, stats


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="Catalogue recordings into band_archive.csv")
    ap.add_argument("--dry-run", action="store_true", help="show what would change; write nothing")
    ap.add_argument("--review", choices=["always", "decisions", "never"], default="always",
                    help="when to stop and show the plan (default: always)")
    ap.add_argument("--yes", action="store_true", help="never ask (same as --review never)")
    args = ap.parse_args(argv)
    if args.yes:
        args.review = "never"
    return args


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    args = parse_args(argv)
    print("Let's a-gooooo!")

    rows, columns = load_existing_rows()
    fieldnames = list(at.BASE_FIELDNAMES) + [c for c in columns if c not in at.BASE_FIELDNAMES]

    plan = build_plan(rows, archive_paths())
    payload = build_payload(plan, rows, preview_only=args.dry_run)

    if args.dry_run:
        if os.environ.get("DANKAPP_PROMPT_VIA_PIPE") == "1":
            ask_via_pipe(payload)                       # shown read-only; the answer is ignored
        else:
            print(at.format_review(payload))
        emit_result({"preview": True, "added_files": len(plan.new_files), "swapped": len(plan.swaps),
                     "missing": len(plan.new_missing), "restored": len(plan.restored),
                     "total": len(rows)})
        print("Preview only - nothing was written.")
        return 0

    if not plan.has_changes:
        print("No changes - the archive is already up to date.")
        emit_result({"added": 0, "added_files": 0, "swapped": 0, "removed": 0, "flagged": 0,
                     "restored": 0, "total": len(rows), "new_shows": []})
        return 0

    reply = decide(args, plan, payload)
    if reply is None:
        print("Scan cancelled - no changes were written.")
        return EXIT_ABORTED

    remove = set(reply.get("remove", [])) & {m["path"] for m in plan.missing}
    final_rows, stats = apply_plan(rows, plan, remove)

    df = pd.DataFrame(final_rows).reindex(columns=fieldnames).fillna("").astype(str)
    at.save_archive(df, CSV_PATH, columns=fieldnames)

    if stats["removed"]:
        print(f"Removed {stats['removed']} row(s) for file(s) no longer found on disk.")
    if stats["flagged"]:
        print(f"Flagged {stats['flagged']} row(s) as Status: missing.")
    if stats["restored"]:
        print(f"{stats['restored']} row(s) are back on disk and no longer flagged missing.")
    print(f"Added {stats['added']} new row(s) from {stats['added_files']} file(s); "
          f"updated {stats['swapped']} placeholder(s) in place. CSV now has {len(df)} total row(s).")

    stats["total"] = len(df)
    emit_result(stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())