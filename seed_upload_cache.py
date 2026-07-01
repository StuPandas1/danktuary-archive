"""
Seed uploaded_shows_cache.json with identifiers you've manually confirmed
are already fully uploaded to Internet Archive. No API calls — pure trust.

Usage: edit CONFIRMED_SHOWS below with (date_str, location) pairs exactly as
they appear in band_archive.csv, then run this script once.
"""
import re
import json
import os

CACHE_PATH = "uploaded_shows_cache.json"

# Add every (date, location) pair you've confirmed is already on archive.org.
# date_str format: YYYY-MM-DD (matches what upload_to_archive.py generates)
CONFIRMED_SHOWS = [
    # ("2025-11-12", "Some Location"),
    # ("2025-11-19", "Some Location"),
]


IDENTIFIER_OVERRIDES = {
    "deadweight-2015-02-21-leftfield": "deadweight-2015-02-21-leftfield-",
}


def make_identifier(date_str, location):
    safe_location = re.sub(r"[^a-zA-Z0-9]+", "-", location.strip()).strip("-").lower()
    identifier = f"deadweight-{date_str}-{safe_location}"
    return IDENTIFIER_OVERRIDES.get(identifier, identifier)


def main():
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, "r") as f:
            existing = set(json.load(f))
    else:
        existing = set()

    added = 0
    for date_str, location in CONFIRMED_SHOWS:
        identifier = make_identifier(date_str, location)
        if identifier not in existing:
            existing.add(identifier)
            added += 1
            print(f"Added: {identifier}")
        else:
            print(f"Already in cache: {identifier}")

    with open(CACHE_PATH, "w") as f:
        json.dump(sorted(existing), f, indent=2)

    print(f"\nDone. Added {added} new identifier(s). Cache now has {len(existing)} total.")


if __name__ == "__main__":
    main()