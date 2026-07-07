"""
Migrates all dankweight-* items to deadweight-* on Internet Archive.
Files are copied server-side (no re-download/re-upload from local machine).
Old dankweight-* items are deleted after successful copy.
uploaded_shows_cache.json is updated to use the new identifiers.
"""
import os
import sys
import json
import time
import subprocess
from internetarchive import get_item  # type: ignore

ACCESS_KEY = os.environ.get("IA_ACCESS_KEY")
SECRET_KEY = os.environ.get("IA_SECRET_KEY")

CACHE_PATH = "uploaded_shows_cache.json"
DELAY_SECONDS = 111


def load_cache():
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, "r") as f:
            return set(json.load(f))
    return set()


def save_cache(identifiers):
    with open(CACHE_PATH, "w") as f:
        json.dump(sorted(identifiers), f, indent=2)


SKIP_EXTENSIONS = ('_meta.xml', '_files.xml', '_reviews.xml', '.sqlite', '.log')


def migrate_item(dank_id, dead_id):
    src_item = get_item(dank_id)
    if not src_item.exists:
        print(f"  Source {dank_id} doesn't exist, skipping.")
        return False

    dst_item = get_item(dead_id)
    if dst_item.exists:
        print(f"  Destination {dead_id} already exists, skipping copy.")
        return True

    files = list(src_item.get_files())
    audio_files = [f for f in files if not any(f.name.endswith(ext) for ext in SKIP_EXTENSIONS)]

    if not audio_files:
        print(f"  No audio files found in {dank_id}, skipping.")
        return False

    print(f"  Copying {len(audio_files)} file(s) via ia copy...")

    for f in audio_files:
        src = f"{dank_id}/{f.name}"
        dst = f"{dead_id}/{f.name}"
        print(f"    {f.name}")
        result = subprocess.run(
            ["ia", "copy", src, dst],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"    ERROR: {result.stderr.strip() or result.stdout.strip()}")
            return False
        time.sleep(1)

    print(f"  Copy complete. Deleting {dank_id}...")
    result = subprocess.run(
        ["ia", "delete", dank_id, "--all"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  WARNING: delete may have failed: {result.stderr.strip()}")

    return True


def main():
    if not ACCESS_KEY or not SECRET_KEY:
        print("ERROR: IA_ACCESS_KEY and IA_SECRET_KEY environment variables must be set.")
        sys.exit(1)

    cache = load_cache()
    dank_identifiers = sorted([i for i in cache if i.startswith("dankweight-")])

    if not dank_identifiers:
        print("No dankweight-* identifiers found in cache. Nothing to migrate.")
        return

    print(f"Found {len(dank_identifiers)} dankweight-* identifier(s) to migrate.\n")

    migrated = 0
    failed = []

    for dank_id in dank_identifiers:
        dead_id = dank_id.replace("dankweight-", "deadweight-", 1)
        print(f"{dank_id} → {dead_id}")

        success = migrate_item(dank_id, dead_id)

        if success:
            cache.discard(dank_id)
            cache.add(dead_id)
            save_cache(cache)
            migrated += 1
            print(f"  ✓ Cache updated.")
        else:
            failed.append(dank_id)
            print(f"  ✗ Migration failed, keeping dankweight in cache for now.")

        time.sleep(DELAY_SECONDS)

    print(f"\nDone. Migrated {migrated}/{len(dank_identifiers)} items.")
    if failed:
        print(f"Failed: {failed}")
        print("Re-run this script to retry failed items.")

time.sleep(4500)

if __name__ == "__main__":
    main()