import os
import sys
import time
import re
import json
import tomllib
import pandas as pd  # type: ignore
import requests  # type: ignore
from urllib.parse import quote
from internetarchive import get_item  # type: ignore

# -------------------------
# CONFIG
# -------------------------

def load_ia_credentials():
    """Reads IA credentials from .streamlit/secrets.toml if present (same
    pattern generate_share_links.py uses for Microsoft credentials),
    falling back to environment variables otherwise."""
    secrets_path = ".streamlit/secrets.toml"
    access_key = None
    secret_key = None

    if os.path.exists(secrets_path):
        with open(secrets_path, "rb") as f:
            secrets = tomllib.load(f)
        ia_secrets = secrets.get("internet_archive", {})
        access_key = ia_secrets.get("access_key")
        secret_key = ia_secrets.get("secret_key")

    access_key = access_key or os.environ.get("IA_ACCESS_KEY")
    secret_key = secret_key or os.environ.get("IA_SECRET_KEY")
    return access_key, secret_key


ACCESS_KEY, SECRET_KEY = load_ia_credentials()

COLLECTION = "opensource_audio"  # IA collection for self-uploaded audio
UPLOAD_DELAY_SECONDS = 60  # be polite to the rate limiter, only after a REAL upload
CACHE_PATH = "uploaded_shows_cache.json"
CSV_PATH = "band_archive.csv"
PLAN_PATH = "upload_plan.json"

IDENTIFIER_COL = "_identifier"  # internal-only helper column, never written to disk

# Printed before each individual file upload so a parent process (update.py)
# can show live progress. Deliberately distinct from ordinary print() output
# so it's easy for a caller to pick these lines out and not log them as text.
PROGRESS_PREFIX = "@PROGRESS@"


def emit_progress(current, total, label):
    print(f"{PROGRESS_PREFIX}{json.dumps({'current': current, 'total': total, 'label': label})}", flush=True)


# -------------------------
# LOCAL CACHE
# -------------------------
# The cache maps identifier -> set of filenames CONFIRMED present on that IA
# item (i.e. we either just uploaded them or IA's API told us they're there).
# It's file-level, not show-level: a show being "in the cache" doesn't mean
# every file for that show is uploaded, only that the specific filenames
# listed are. This matters because band_archive.csv is append-only now
# (scanner.py doesn't wipe it) -- a new take can be added to an
# already-uploaded show at any time, and it needs its own upload, not a
# fabricated URL just because its show identifier looks "done".
#
# Old cache files (a flat JSON list of identifiers, from before this file-
# level tracking existed) are migrated automatically: each identifier is
# loaded with an empty confirmed-file set, so the first run after upgrading
# will re-check that show's files against IA once (via upload_show's
# get_uploaded_filenames call) and then remember them correctly from then on.

def load_cache():
    if not os.path.exists(CACHE_PATH):
        return {}
    with open(CACHE_PATH, "r") as f:
        data = json.load(f)

    if isinstance(data, list):
        print("Migrating old show-level cache to per-file cache "
              "(shows will be re-checked against IA once)...")
        return {identifier: set() for identifier in data}

    return {identifier: set(filenames) for identifier, filenames in data.items()}


def save_cache(cache):
    with open(CACHE_PATH, "w") as f:
        json.dump(
            {identifier: sorted(filenames) for identifier, filenames in cache.items()},
            f, indent=2,
        )


def save_df(df):
    df.drop(columns=[IDENTIFIER_COL], errors="ignore").to_csv(CSV_PATH, index=False)


# -------------------------
# HELPERS
# -------------------------

def make_identifier(date_str, location):
    """Build a safe, unique IA item identifier from date + location."""
    safe_location = re.sub(r"[^a-zA-Z0-9]+", "-", location.strip()).strip("-").lower()
    identifier = f"deadweight-{date_str}-{safe_location}"
    return IDENTIFIER_OVERRIDES.get(identifier, identifier)


# manual overrides for identifiers that differ from what make_identifier generates
# (e.g. items created with a typo or trailing character that can't be renamed)
IDENTIFIER_OVERRIDES = {
    "deadweight-2015-02-21-leftfield": "deadweight-2015-02-21-leftfield-",
}


def compute_identifier(row):
    if pd.isna(row["Date"]) or pd.isna(row["Location"]):
        return None
    date_str = row["Date"].strftime("%Y-%m-%d")
    return make_identifier(date_str, row["Location"])


def get_uploaded_filenames(item, retries=3, retry_delay=10):
    """Returns the set of filenames already present on this IA item.
    Returns an empty set if the item genuinely doesn't exist.
    Retries if the item exists but reports no files yet, since IA's
    backend can lag behind a recent upload before files are listed."""
    try:
        if not item.exists:
            return set()
    except Exception:
        return set()

    for attempt in range(retries):
        try:
            filenames = {f.name for f in item.get_files()}
        except Exception:
            filenames = set()

        if filenames:
            return filenames

        if attempt < retries - 1:
            print(f"    (item exists but no files listed yet, retrying in {retry_delay}s...)")
            time.sleep(retry_delay)

    return set()


# -------------------------
# PLAN COMPUTATION
# -------------------------
# Shared by --plan mode (for GUI confirmation) and the real upload run, so
# the two can never drift apart -- what gets shown for confirmation is
# exactly what would be uploaded.

def compute_upload_plan(full_df, cache):
    """Returns a list of dicts, one per show that has something left to
    upload: {identifier, date_str, location, filepaths (all of them),
    confirmed_filenames, unconfirmed_filepaths, group_df}.
    Shows that are fully uploaded already are left out entirely.

    Does live IA existence checks for any show with unconfirmed files, and
    updates `cache` in place with anything IA reports as already present."""

    # Filter: all gigs (any year) + practice recordings from 2025-2026 only.
    # Trips are excluded entirely regardless of year. Every row for a
    # matching show is included here regardless of Take number -- repeated
    # takes of the same song are separate physical files and all get
    # uploaded together with the rest of that show's recordings.
    is_gig = full_df["Type"] == "live"
    is_recent_practice = (full_df["Type"] == "practice") & (full_df["Date"].dt.year >= 2025)
    upload_candidates = full_df[is_gig | is_recent_practice]

    plan = []
    if upload_candidates.empty:
        return plan

    for (date, location), group in upload_candidates.groupby(["Date", "Location"]):
        date_str = date.strftime("%Y-%m-%d")
        identifier = make_identifier(date_str, location)

        filepaths = list(dict.fromkeys(group["File Path"].dropna().tolist()))
        filepaths = [fp for fp in filepaths if not fp.lower().endswith(".bmp")]
        if not filepaths:
            continue

        confirmed_filenames = cache.get(identifier, set())
        unconfirmed = [fp for fp in filepaths if os.path.basename(fp) not in confirmed_filenames]

        if unconfirmed:
            item = get_item(identifier)
            existing_on_ia = get_uploaded_filenames(item)
            confirmed_filenames = confirmed_filenames | (existing_on_ia & {os.path.basename(fp) for fp in filepaths})
            unconfirmed = [fp for fp in filepaths if os.path.basename(fp) not in confirmed_filenames]
            cache[identifier] = confirmed_filenames

        if not unconfirmed:
            continue  # every file in this group, including any new takes, is already confirmed

        plan.append({
            "identifier": identifier,
            "date_str": date_str,
            "location": location,
            "filepaths": filepaths,
            "confirmed_filenames": confirmed_filenames,
            "unconfirmed_filepaths": unconfirmed,
            "group_df": group,
        })

    return plan


def build_title_lookup(group_df):
    """Maps File Path -> Title for one show's rows, for display purposes
    (the confirmation screen and progress bar show titles, not raw filenames)."""
    return dict(zip(group_df["File Path"], group_df["Title"]))


def upload_show(identifier, filepaths, date_str, location, confirmed_filenames,
                 progress_state=None, title_lookup=None):
    """Uploads any of filepaths not yet confirmed present on IA, one file at
    a time (so progress can be reported per file instead of per show).
    Returns (confirmed_filenames: set of basenames now known present, uploaded_something: bool)."""
    item = get_item(identifier)

    unconfirmed = [fp for fp in filepaths if os.path.basename(fp) not in confirmed_filenames]
    if not unconfirmed:
        print(f"  Skipping {identifier} (all {len(filepaths)} file(s) already present)")
        return confirmed_filenames, False

    print(f"  {identifier}: {len(confirmed_filenames)} file(s) already confirmed, "
          f"uploading {len(unconfirmed)} file(s)...")

    metadata = {
        "title": f"{location} — {date_str}",
        "mediatype": "audio",
        "collection": COLLECTION,
        "date": date_str,
    }

    for fp in unconfirmed:
        if progress_state is not None:
            progress_state["current"] += 1
            label = (title_lookup or {}).get(fp, os.path.basename(fp))
            emit_progress(progress_state["current"], progress_state["total"], label)

        item.upload(
            [fp],
            metadata=metadata,
            access_key=ACCESS_KEY,
            secret_key=SECRET_KEY,
            verbose=True,
            queue_derive=False,
        )
        confirmed_filenames = confirmed_filenames | {os.path.basename(fp)}

    return confirmed_filenames, True


def fill_ia_url(full_df, idx, identifier, filepath):
    filename = os.path.basename(filepath)
    full_df.at[idx, "IA URL"] = f"https://archive.org/download/{identifier}/{quote(filename)}"


def run_backfill_pass(full_df, cache):
    """Fill IA URL for any row whose exact filename is confirmed present in
    the cache for its show. File-level, so a row for a take that hasn't
    actually been uploaded yet is correctly left blank even if other
    takes/files for the same show are confirmed."""
    full_df[IDENTIFIER_COL] = full_df.apply(compute_identifier, axis=1)
    is_real_file = full_df["File Path"].notna() & ~full_df["File Path"].str.lower().str.endswith(".bmp", na=False)
    needs_url = full_df["IA URL"].isna()

    for idx in full_df.index[is_real_file & needs_url]:
        row = full_df.loc[idx]
        identifier = row[IDENTIFIER_COL]
        if identifier is None:
            continue
        filename = os.path.basename(row["File Path"])
        if filename in cache.get(identifier, set()):
            fill_ia_url(full_df, idx, identifier, row["File Path"])


def load_and_prepare():
    full_df = pd.read_csv(CSV_PATH)
    if "File Path" not in full_df.columns:
        print(f"ERROR: {CSV_PATH} has no 'File Path' column. Run scanner.py first.")
        sys.exit(1)

    full_df["IA URL"] = full_df.get("IA URL", pd.NA)
    full_df["Date"] = pd.to_datetime(full_df["Date"])
    return full_df


def main():
    plan_only = "--plan" in sys.argv

    if not ACCESS_KEY or not SECRET_KEY:
        print("ERROR: IA_ACCESS_KEY and IA_SECRET_KEY environment variables must be set.")
        sys.exit(1)

    full_df = load_and_prepare()
    cache = load_cache()

    run_backfill_pass(full_df, cache)
    plan = compute_upload_plan(full_df, cache)
    save_df(full_df)
    save_cache(cache)  # persist anything the plan's live IA checks confirmed

    if plan_only:
        plan_out = []
        for p in plan:
            title_lookup = build_title_lookup(p["group_df"])
            plan_out.append({
                "identifier": p["identifier"],
                "date": p["date_str"],
                "location": p["location"],
                "files": [
                    {
                        "filename": os.path.basename(fp),
                        "title": title_lookup.get(fp, os.path.basename(fp)),
                    }
                    for fp in p["unconfirmed_filepaths"]
                ],
            })
        with open(PLAN_PATH, "w", encoding="utf-8") as f:
            json.dump(plan_out, f, indent=2)
        total_files = sum(len(show["files"]) for show in plan_out)
        print(f"Wrote upload plan: {len(plan_out)} show(s), {total_files} file(s) to upload.")
        return

    if not plan:
        print("No rows match the filter (gigs + 2025-2026 practices), or everything is already uploaded.")
        return

    total_files = sum(len(p["unconfirmed_filepaths"]) for p in plan)
    progress_state = {"current": 0, "total": total_files}

    for p in plan:
        identifier = p["identifier"]
        date_str = p["date_str"]
        location = p["location"]
        filepaths = p["filepaths"]
        confirmed_filenames = p["confirmed_filenames"]

        print(f"{date_str} — {location}")

        try:
            title_lookup = build_title_lookup(p["group_df"])
            confirmed_filenames, uploaded_something = upload_show(
                identifier, filepaths, date_str, location, confirmed_filenames,
                progress_state=progress_state, title_lookup=title_lookup,
            )
        except requests.exceptions.HTTPError as e:
            print(f"\nSTOPPED: hit an upload error on {identifier}.")
            print(f"  {e}")
            print("\nThis is likely IA's rate limiter. Progress so far is saved.")
            print("Wait at least an hour (longer if possible) before re-running this script.")
            cache[identifier] = confirmed_filenames
            save_df(full_df)
            save_cache(cache)
            sys.exit(1)

        cache[identifier] = confirmed_filenames

        for idx, row in p["group_df"].iterrows():
            if pd.isna(row["File Path"]):
                continue
            if os.path.basename(row["File Path"]) in confirmed_filenames:
                fill_ia_url(full_df, idx, identifier, row["File Path"])

        save_df(full_df)
        save_cache(cache)

        if uploaded_something:
            time.sleep(UPLOAD_DELAY_SECONDS)

    save_df(full_df)
    print(f"Done. {CSV_PATH} updated with IA URLs.")


if __name__ == "__main__":
    main()