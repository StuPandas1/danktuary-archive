import os
import sys
import time
import re
import pandas as pd  # type: ignore
import requests  # type: ignore
from internetarchive import get_item  # type: ignore

# -------------------------
# CONFIG
# -------------------------

ACCESS_KEY = os.environ.get("IA_ACCESS_KEY")
SECRET_KEY = os.environ.get("IA_SECRET_KEY")

COLLECTION = "opensource_audio"  # IA collection for self-uploaded audio
UPLOAD_DELAY_SECONDS = 250  # be polite to the rate limiter between items

# -------------------------
# HELPERS
# -------------------------

def make_identifier(date_str, location):
    """Build a safe, unique IA item identifier from date + location."""
    safe_location = re.sub(r"[^a-zA-Z0-9]+", "-", location).strip("-").lower()
    return f"dankweight-{date_str}-{safe_location}"


def upload_show(identifier, filepaths, date_str, location):
    item = get_item(identifier)

    if item.exists:
        print(f"  Skipping {identifier} (already uploaded)")
        return item

    metadata = {
        "title": f"{location} — {date_str}",
        "mediatype": "audio",
        "collection": COLLECTION,
        "date": date_str,
    }

    print(f"  Uploading {len(filepaths)} file(s) to {identifier}...")
    item.upload(
        filepaths,
        metadata=metadata,
        access_key=ACCESS_KEY,
        secret_key=SECRET_KEY,
        verbose=True,
        queue_derive=False,
    )
    return item


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
    is_recent_practice = (full_df["Type"] == "practice") & (full_df["Date"].dt.year.isin([2025, 2026]))
    upload_candidates = full_df[is_gig | is_recent_practice]

    if upload_candidates.empty:
        print("No rows match the filter (gigs + 2025-2026 practices). Nothing to upload.")
        return

    grouped = upload_candidates.groupby(["Date", "Location"])

    for (date, location), group in grouped:
        date_str = date.strftime("%Y-%m-%d")
        identifier = make_identifier(date_str, location)

        filepaths = list(dict.fromkeys(group["File Path"].dropna().tolist()))
        filepaths = [fp for fp in filepaths if not fp.lower().endswith(".bmp")]
        if not filepaths:
            continue

        # skip shows that already have IA URLs recorded
        already_done = group["IA URL"].notna().all()
        if already_done:
            continue

        print(f"{date_str} — {location}")

        try:
            item = upload_show(identifier, filepaths, date_str, location)
        except requests.exceptions.HTTPError as e:
            print(f"\nSTOPPED: hit an upload error on {identifier}.")
            print(f"  {e}")
            print("\nThis is likely IA's rate limiter. Progress so far is saved.")
            print("Wait at least an hour (longer if possible) before re-running this script.")
            full_df.to_csv("band_archive.csv", index=False)
            sys.exit(1)

        for idx, row in group.iterrows():
            if pd.isna(row["File Path"]):
                continue
            filename = os.path.basename(row["File Path"])
            ia_url = f"https://archive.org/download/{identifier}/{filename}"
            full_df.at[idx, "IA URL"] = ia_url

        full_df.to_csv("band_archive.csv", index=False)
        time.sleep(UPLOAD_DELAY_SECONDS)

    print("Done. band_archive.csv updated with IA URLs.")

time.sleep(7200)  # wait 2 hours before starting the upload to avoid rate limiting
if __name__ == "__main__":
    main()