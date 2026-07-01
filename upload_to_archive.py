import os
import sys
import time
import re
import json
import pandas as pd  # type: ignore
import requests  # type: ignore
from urllib.parse import quote
from internetarchive import get_item  # type: ignore

# -------------------------
# CONFIG
# -------------------------

ACCESS_KEY = os.environ.get("IA_ACCESS_KEY")
SECRET_KEY = os.environ.get("IA_SECRET_KEY")

COLLECTION = "opensource_audio"  # IA collection for self-uploaded audio
UPLOAD_DELAY_SECONDS = 60  # be polite to the rate limiter, only after a REAL upload
CACHE_PATH = "uploaded_shows_cache.json"

# -------------------------
# LOCAL CACHE (survives scanner.py wiping band_archive.csv)
# -------------------------

def load_cache():
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, "r") as f:
            return set(json.load(f))
    return set()


def save_cache(confirmed_identifiers):
    with open(CACHE_PATH, "w") as f:
        json.dump(sorted(confirmed_identifiers), f, indent=2)


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


def upload_show(identifier, filepaths, date_str, location):
    """Returns (item, uploaded_something: bool)."""
    item = get_item(identifier)
    existing_filenames = get_uploaded_filenames(item)

    missing_filepaths = [
        fp for fp in filepaths
        if os.path.basename(fp) not in existing_filenames
    ]

    if not missing_filepaths:
        print(f"  Skipping {identifier} (all {len(filepaths)} file(s) already present)")
        return item, False

    if existing_filenames:
        print(f"  {identifier}: {len(existing_filenames)} file(s) already present, "
              f"uploading {len(missing_filepaths)} missing file(s)...")
    else:
        print(f"  Uploading {len(missing_filepaths)} file(s) to {identifier}...")

    metadata = {
        "title": f"{location} — {date_str}",
        "mediatype": "audio",
        "collection": COLLECTION,
        "date": date_str,
    }

    item.upload(
        missing_filepaths,
        metadata=metadata,
        access_key=ACCESS_KEY,
        secret_key=SECRET_KEY,
        verbose=True,
        queue_derive=False,
    )
    return item, True


def main():
    if not ACCESS_KEY or not SECRET_KEY:
        print("ERROR: IA_ACCESS_KEY and IA_SECRET_KEY environment variables must be set.")
        sys.exit(1)

    full_df = pd.read_csv("band_archive.csv")

    if "File Path" not in full_df.columns:
        print("ERROR: band_archive.csv has no 'File Path' column. Run scanner.py first.")
        sys.exit(1)

    full_df["IA URL"] = full_df.get("IA URL", pd.NA)
    full_df["Date"] = pd.to_datetime(full_df["Date"])

    # Filter: all gigs (any year) + practice recordings from 2025-2026 only.
    # Trips are excluded entirely regardless of year.
    # NOTE: this filtered view selects WHICH ROWS to upload, but full_df
    # (every row, every type, every year) is what gets saved back to disk.
    is_gig = full_df["Type"] == "live"
    is_recent_practice = (full_df["Type"] == "practice") & (full_df["Date"].dt.year >= 2025)
    upload_candidates = full_df[is_gig | is_recent_practice]

    if upload_candidates.empty:
        print("No rows match the filter (gigs + 2025-2026 practices). Nothing to upload.")
        return

    grouped = upload_candidates.groupby(["Date", "Location"])
    confirmed_cache = load_cache()

    for (date, location), group in grouped:
        date_str = date.strftime("%Y-%m-%d")
        identifier = make_identifier(date_str, location)

        filepaths = list(dict.fromkeys(group["File Path"].dropna().tolist()))
        filepaths = [fp for fp in filepaths if not fp.lower().endswith(".bmp")]
        if not filepaths:
            continue

        # fast-path: skip the API entirely for shows we've already confirmed,
        # but still rebuild the IA URL since scanner.py wipes the column each run
        if identifier in confirmed_cache:
            for idx, row in group.iterrows():
                if pd.isna(row["File Path"]):
                    continue
                filename = os.path.basename(row["File Path"])
                ia_url = f"https://archive.org/download/{identifier}/{quote(filename)}"
                full_df.at[idx, "IA URL"] = ia_url
            continue

        print(f"{date_str} — {location}")

        try:
            item, uploaded_something = upload_show(identifier, filepaths, date_str, location)
        except requests.exceptions.HTTPError as e:
            print(f"\nSTOPPED: hit an upload error on {identifier}.")
            print(f"  {e}")
            print("\nThis is likely IA's rate limiter. Progress so far is saved.")
            print("Wait at least an hour (longer if possible) before re-running this script.")
            full_df.to_csv("band_archive.csv", index=False)
            save_cache(confirmed_cache)
            sys.exit(1)

        for idx, row in group.iterrows():
            if pd.isna(row["File Path"]):
                continue
            filename = os.path.basename(row["File Path"])
            ia_url = f"https://archive.org/download/{identifier}/{quote(filename)}"
            full_df.at[idx, "IA URL"] = ia_url

        confirmed_cache.add(identifier)
        full_df.to_csv("band_archive.csv", index=False)
        save_cache(confirmed_cache)

        if uploaded_something:
            time.sleep(UPLOAD_DELAY_SECONDS)

    # supplemental pass: write IA URLs for any show in the cache that wasn't
    # covered by the upload filter (e.g. newly added year, edge cases)
    # groups the full_df by show and checks against the cache
    all_grouped = full_df[full_df["File Path"].notna()].groupby(["Date", "Location"])
    for (date, location), group in all_grouped:
        date_str = date.strftime("%Y-%m-%d")
        identifier = make_identifier(date_str, location)
        if identifier not in confirmed_cache:
            continue
        for idx, row in group.iterrows():
            if pd.isna(row.get("File Path")) or str(row["File Path"]).lower().endswith(".bmp"):
                continue
            if pd.isna(full_df.at[idx, "IA URL"]):
                filename = os.path.basename(row["File Path"])
                ia_url = f"https://archive.org/download/{identifier}/{quote(filename)}"
                full_df.at[idx, "IA URL"] = ia_url

    full_df.to_csv("band_archive.csv", index=False)
    print("Done. band_archive.csv updated with IA URLs.")


if __name__ == "__main__":
    main()