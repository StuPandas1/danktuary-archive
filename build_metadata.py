import pandas as pd # type: ignore

# load archive
df = pd.read_csv("band_archive.csv")

# unique song titles
songs = sorted(df["Title"].unique())

# build metadata table
metadata = pd.DataFrame({
    "Title": songs,
    "Type": "",
    "Artist": ""
})

# save
metadata.to_csv(
    "song_metadata.csv",
    index=False
)

print("song_metadata.csv created!")