import re
import os
import csv
import string
import pandas as pd  # type: ignore
from mutagen import File as MutagenFile
from shared import manual_fixes, junk_terms, segue_fixes, local_path_to_onedrive_url

print("Let's a-gooooo!")


archive_paths = [
    r"C:\Users\Administrator\OneDrive\LoveDeep\Audio Recordings\Gig Recordings",
    r"C:\Users\Administrator\OneDrive\LoveDeep\Audio Recordings\Jam Session Recordings 2015-2020",
    r"C:\Users\Administrator\OneDrive\LoveDeep\Audio Recordings\Jam Session Recordings 2021-",
    r"C:\Users\Administrator\OneDrive\LoveDeep\Audio Recordings\Trips"
]

CSV_PATH = "band_archive.csv"

FIELDNAMES = [
    "Track Number", "File Track", "Title", "Date", "Location",
    "Type", "Duration", "Raw Title", "File Path", "Take", "IA URL", "OneDrive URL", "Status"
]


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


# -------------------------
# LOAD EXISTING CSV (rows to preserve + per-folder state to resume from)
# -------------------------

existing_rows = []          # every row from the old CSV, kept verbatim
processed_files = set()     # file paths already catalogued -> skip on rescan
folder_state = {}           # folder -> {"next_track": int, "seen_songs": {title: take}}
known_folders = set()       # folders that already had at least one catalogued file

if os.path.exists(CSV_PATH):
    try:
        existing_df = pd.read_csv(CSV_PATH, dtype=str)
        for _, row in existing_df.iterrows():
            row_dict = row.to_dict()
            existing_rows.append(row_dict)

            fp = row.get("File Path")
            if pd.isna(fp):
                continue

            processed_files.add(fp)
            folder = os.path.dirname(fp)
            known_folders.add(folder)
            state = folder_state.setdefault(folder, {"next_track": 1, "seen_songs": {}})

            # resume track numbering after the highest one already used in this folder
            try:
                track_num = int(row.get("Track Number"))
                state["next_track"] = max(state["next_track"], track_num + 1)
            except (TypeError, ValueError):
                pass

            # resume "take" counting per base title in this folder
            title = row.get("Title")
            take = row.get("Take")
            if pd.notna(title) and pd.notna(take):
                base_title = re.sub(r"\s\(\d+\)$", "", title)
                try:
                    take_num = int(take)
                    state["seen_songs"][base_title] = max(
                        state["seen_songs"].get(base_title, 0), take_num
                    )
                except ValueError:
                    pass

        print(f"Loaded {len(existing_rows)} existing row(s); "
              f"{len(processed_files)} file(s) already catalogued and will be skipped.")
    except Exception as e:
        print(f"Warning: could not read existing {CSV_PATH} ({e}). Starting fresh.")


# -------------------------
# DETECT DELETED FILES / FOLDERS (present in CSV, missing on disk)
# -------------------------

deleted_folders = set()
for folder in sorted(known_folders):
    if not os.path.isdir(folder):
        deleted_folders.add(folder)
        print(f"Folder removed: '{folder}' no longer exists on disk.")

removed_file_count = 0
missing_flagged_count = 0
kept_rows = []
for row in existing_rows:
    fp = row.get("File Path")
    if fp and not os.path.exists(fp):
        answer = ""
        while answer not in ("yes", "no"):
            answer = input(
                f"File '{fp}' no longer exists on disk.\n"
                f"  Type 'yes' to remove it from the CSV, or 'no' to keep it "
                f"labeled as Status: missing: "
            ).strip().lower()

        if answer == "yes":
            print(f"File removed: '{fp}' dropped from CSV.")
            removed_file_count += 1
            continue
        else:
            row["Status"] = "missing"
            missing_flagged_count += 1
            print(f"File kept in CSV, labeled Status: missing -> '{fp}'")

    kept_rows.append(row)
existing_rows = kept_rows

if removed_file_count:
    print(f"Removed {removed_file_count} row(s) for file(s) no longer found on disk.")
if missing_flagged_count:
    print(f"Flagged {missing_flagged_count} row(s) as Status: missing.")


# -------------------------
# SCAN FOR NEW FILES ONLY
# -------------------------

new_rows = []

for archive_path in archive_paths:

    for root, dirs, files in os.walk(archive_path):
        has_audio = any(
            f.lower().endswith((".mp3", ".m4a", ".wav", ".wma", ".aac", ".bmp")) for f in files
        )
        if has_audio and root not in known_folders:
            print(f"New folder detected: '{root}'")

        state = folder_state.setdefault(root, {"next_track": 1, "seen_songs": {}})

        for file in sorted(files):
            if not file.lower().endswith((".mp3", ".m4a", ".wav", ".wma", ".aac", ".bmp")):
                continue

            filepath = os.path.join(root, file)

            if filepath in processed_files:
                continue  # already in the CSV from a previous run

            print(f"New file detected: '{filepath}'")

            # track name and num
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

            songs = [song.strip() for song in raw_title.split("_")]

            for raw_song in songs:

                cleaned_title = raw_song.strip()
                cleaned_title = cleaned_title.lower()
                cleaned_title = cleaned_title.replace("  ", " ")
                cleaned_title = re.sub(r"\s+jam$", "", cleaned_title)

                if cleaned_title in manual_fixes:
                    cleaned_title = manual_fixes[cleaned_title]

                title = string.capwords(cleaned_title)

                folder_name = os.path.basename(root)
                date = folder_name[:10]

                lower_root = root.lower()
                if "gig" in lower_root:
                    recording_type = "live"
                    gig_place = folder_name.split(" _ ", 1)[1]
                elif "trips" in lower_root:
                    recording_type = "trip"
                    gig_place = folder_name.split(" _ ", 1)[1]
                else:
                    recording_type = "practice"
                    if date >= "2024-06-26":
                        gig_place = "Danktuary Studios"
                    elif date >= "2020-03-10":
                        gig_place = "Studio Chill"
                    else:
                        gig_place = "The Music Building"

                duration = get_duration(filepath)
                onedrive_url = local_path_to_onedrive_url(filepath) or ""

                if title not in state["seen_songs"]:
                    take = 1
                    display_title = title
                else:
                    take = state["seen_songs"][title] + 1
                    display_title = f"{title} ({take})"

                new_rows.append({
                    "Track Number": state["next_track"],
                    "File Track": track_number,
                    "Title": display_title,
                    "Date": date,
                    "Location": gig_place,
                    "Type": recording_type,
                    "Duration": duration,
                    "Raw Title": raw_name,
                    "File Path": filepath,
                    "Take": take,
                    "IA URL": "",
                    "OneDrive URL": onedrive_url,
                    "Status": "",
                })

                state["seen_songs"][title] = take
                state["next_track"] += 1

            # a file we just processed counts as catalogued now, in case the same
            # path shows up again later in this same run for any reason
            processed_files.add(filepath)


# -------------------------
# WRITE COMBINED CSV: old rows preserved, new rows appended
# -------------------------

with open(CSV_PATH, "w", newline="", encoding="utf-8") as csvfile:
    writer = csv.DictWriter(csvfile, fieldnames=FIELDNAMES)
    writer.writeheader()
    for row in existing_rows:
        writer.writerow(row)
    for row in new_rows:
        writer.writerow(row)

print(
    f"Added {len(new_rows)} new row(s), removed {removed_file_count} row(s), "
    f"flagged {missing_flagged_count} row(s) as missing. "
    f"CSV now has {len(existing_rows) + len(new_rows)} total row(s)."
)