import re
import os
import csv
import string
import pandas as pd  # type: ignore
from mutagen import File as MutagenFile
from shared import manual_fixes, junk_terms, segue_fixes

print("Let's a-gooooo!")


archive_paths = [
    r"C:\Users\Administrator\OneDrive\LoveDeep\Audio Recordings\Gig Recordings",
    r"C:\Users\Administrator\OneDrive\LoveDeep\Audio Recordings\Jam Session Recordings 2015-2020",
    r"C:\Users\Administrator\OneDrive\LoveDeep\Audio Recordings\Jam Session Recordings 2021-",
    r"C:\Users\Administrator\OneDrive\LoveDeep\Audio Recordings\Trips"
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
# LOAD EXISTING IA URLS TO PRESERVE ACROSS REWRITES
# -------------------------

existing_ia_urls = {}
if os.path.exists("band_archive.csv"):
    try:
        existing_df = pd.read_csv("band_archive.csv", dtype=str)
        if "File Path" in existing_df.columns and "IA URL" in existing_df.columns:
            for _, row in existing_df.iterrows():
                fp = row.get("File Path")
                ia_url = row.get("IA URL")
                if pd.notna(fp) and pd.notna(ia_url) and ia_url.strip():
                    existing_ia_urls[fp] = ia_url
        print(f"Loaded {len(existing_ia_urls)} existing IA URL(s) to preserve.")
    except Exception as e:
        print(f"Warning: could not read existing band_archive.csv ({e}). Starting fresh.")


with open("band_archive.csv", "w", newline="", encoding="utf-8") as csvfile:
    writer = csv.writer(csvfile)
    writer.writerow([
        "Track Number", "File Track", "Title", "Date", "Location",
        "Type", "Duration", "Raw Title", "File Path", "Take", "IA URL"
    ])

    for archive_path in archive_paths:

        for root, dirs, files in os.walk(archive_path):
            logical_track_number = 1
            seen_songs = {}
            for file in sorted(files):
                if file.lower().endswith((".mp3", ".m4a", ".wav", ".wma", ".aac", ".bmp")):

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

                        filepath = os.path.join(root, file)
                        duration = get_duration(filepath)
                        ia_url = existing_ia_urls.get(filepath, "")

                        if title not in seen_songs:
                            take = 1
                            display_title = title
                        else:
                            take = seen_songs[title] + 1
                            display_title = f"{title} ({take})"

                        writer.writerow([
                            logical_track_number,
                            track_number,
                            display_title,
                            date,
                            gig_place,
                            recording_type,
                            duration,
                            raw_name,
                            filepath,
                            take,
                            ia_url
                        ])
                        seen_songs[title] = take
                        logical_track_number += 1

print("CSV created successfully!")