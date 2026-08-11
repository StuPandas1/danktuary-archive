import pandas as pd  # type: ignore
import os

ARCHIVE_PATH = "band_archive.csv"
METADATA_PATH = "song_metadata.csv"

# load archive
df = pd.read_csv(ARCHIVE_PATH)

# Strip the take suffix scanner.py adds for repeated songs within a session
# (e.g. "Song (2)", "Song (3)") so metadata is keyed on the actual song, not
# on every individual take of it.
base_titles = df["Title"].str.replace(r"\s\(\d+\)$", "", regex=True)

# unique song titles currently in the archive
songs = sorted(base_titles.unique())
current_titles = pd.DataFrame({"Title": songs})

if os.path.exists(METADATA_PATH):
    existing = pd.read_csv(METADATA_PATH)

    # Collapse any duplicate titles left over from before take-suffixes were
    # stripped (e.g. old rows for "Song", "Song (2)", "Song (3)" now all
    # resolve to "Song"). Keep the first occurrence's Artist for each title.
    duplicate_count = existing["Title"].duplicated().sum()
    if duplicate_count:
        print(f"Collapsing {duplicate_count} duplicate title row(s) in "
              f"{METADATA_PATH}, keeping the first instance of each.")
        existing = existing.drop_duplicates(subset="Title", keep="first")

    # keep existing Artist values for titles still present, add blank rows
    # for new titles
    merged = current_titles.merge(existing, on="Title", how="left")

    if "Artist" not in merged.columns:
        merged["Artist"] = ""
    merged["Artist"] = merged["Artist"].fillna("")

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