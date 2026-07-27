import pandas as pd  # type: ignore
import os

ARCHIVE_PATH = "band_archive.csv"
METADATA_PATH = "song_metadata.csv"

# load archive
df = pd.read_csv(ARCHIVE_PATH)

# unique song titles currently in the archive
songs = sorted(df["Title"].unique())
current_titles = pd.DataFrame({"Title": songs})

if os.path.exists(METADATA_PATH):
    existing = pd.read_csv(METADATA_PATH)

    # keep existing rows for titles still present, add blank rows for new titles
    merged = current_titles.merge(existing, on="Title", how="left")

    for col in ["Type", "Artist"]:
        if col not in merged.columns:
            merged[col] = ""
        merged[col] = merged[col].fillna("")

    metadata = merged[["Title", "Artist"]]

    new_titles = set(songs) - set(existing["Title"])
    if new_titles:
        print(f"Added {len(new_titles)} new song(s) to metadata: {sorted(new_titles)}")
else:
    metadata = pd.DataFrame({
        "Title": songs,
        "Artist": ""
    })
    print("No existing song_metadata.csv found — creating fresh.")

metadata.to_csv(METADATA_PATH, index=False)
print("song_metadata.csv updated!")