"""
Uploads files for Take > 1 rows in band_archive.csv that were previously
skipped due to deduplication. Adds their IA URLs back to the CSV.

Only processes shows that are already in uploaded_shows_cache.json
(i.e. already have a corresponding IA item to add files to).
"""
import os
import sys
import json
import time
import re
import pandas as pd  # type: ignore
import requests  # type: ignore
from urllib.parse import quote
from internetarchive import get_item  # type: ignore

ACCESS_KEY = os.environ.get("IA_ACCESS_KEY")
SECRET_KEY = os.environ.get("IA_SECRET_KEY")

CACHE_PATH = "uploaded_shows_cache.json"
DELAY_SECONDS = 10


IDENTIFIER_OVERRIDES = {
    "deadweight-2015-02-21-leftfield": "deadweight-2015-02-21-leftfield-",
}


def make_identifier(date_str, location):
    safe_location = re.sub(r"[^a-zA-Z0-9]+", "-", location.strip()).strip("-").lower()
    identifier = f"deadweight-{date_str}-{safe_location}"
    return IDENTIFIER_OVERRIDES.get(identifier, identifier)


def load_cache():
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, "r") as f:
            return set(json.load(f))
    return set()


def get_existing_filenames(item):
    try:
        if not item.exists:
            return set()
        return {f.name for f in item.get_files()}
    except Exception:
        return set()


def main():
    if not ACCESS_KEY or not SECRET_KEY:
        print("ERROR: IA_ACCESS_KEY and IA_SECRET_KEY must be set.")
        sys.exit(1)

    df = pd.read_csv("band_archive.csv", dtype={"Duration": str})

    if "Take" not in df.columns:
        print("ERROR: No 'Take' column found. Run scanner.py first.")
        sys.exit(1)

    if "IA URL" not in df.columns:
        df["IA URL"] = pd.NA

    df["Date"] = pd.to_datetime(df["Date"])
    cache = load_cache()

    # find rows that are extra takes and either missing an IA URL or have one
    # pointing at the wrong filename (since they share a filepath with Take 1
    # but may need their own entry confirmed)
    extra_takes = df[df["Take"] > 1].copy()

    if extra_takes.empty:
        print("No Take > 1 rows found. Nothing to upload.")
        return

    print(f"Found {len(extra_takes)} Take > 1 row(s) across "
          f"{extra_takes.groupby(['Date', 'Location']).ngroups} show(s).\n")

    grouped = extra_takes.groupby(["Date", "Location"])

    for (date, location), group in grouped:
        date_str = date.strftime("%Y-%m-%d")
        identifier = make_identifier(date_str, location)

        if identifier not in cache:
            print(f"Skipping {date_str} — {location} (not in upload cache, "
                  f"show may not have been uploaded yet)")
            continue

        print(f"{date_str} — {location} ({identifier})")

        item = get_item(identifier)
        existing_filenames = get_existing_filenames(item)

        # collect unique filepaths for this show's extra takes
        filepaths = list(dict.fromkeys(
            fp for fp in group["File Path"].dropna()
            if not str(fp).lower().endswith(".bmp")
        ))

        missing = [fp for fp in filepaths
                   if os.path.basename(fp) not in existing_filenames]

        if missing:
            print(f"  Uploading {len(missing)} missing file(s)...")
            try:
                item.upload(
                    missing,
                    metadata={
                        "title": f"{location} — {date_str}",
                        "mediatype": "audio",
                        "collection": "opensource_audio",
                        "date": date_str,
                    },
                    access_key=ACCESS_KEY,
                    secret_key=SECRET_KEY,
                    verbose=True,
                    queue_derive=False,
                )
                time.sleep(DELAY_SECONDS)
            except requests.exceptions.HTTPError as e:
                print(f"  ERROR uploading: {e}")
                print("  Saving progress and stopping.")
                df.to_csv("band_archive.csv", index=False)
                sys.exit(1)
        else:
            print(f"  All files already present on IA.")

        # write IA URLs for all extra-take rows in this show
        for idx, row in group.iterrows():
            filepath = row.get("File Path")
            if pd.isna(filepath):
                continue
            filename = os.path.basename(filepath)
            ia_url = f"https://archive.org/download/{identifier}/{quote(filename)}"
            df.at[idx, "IA URL"] = ia_url

        df.to_csv("band_archive.csv", index=False)
        print(f"  IA URLs written for {len(group)} row(s).")

    print("\nDone.")


if __name__ == "__main__":
    main()