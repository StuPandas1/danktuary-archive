import pandas as pd # type: ignore

df = pd.read_csv("band_archive.csv")

# convert dates
df["Date"] = pd.to_datetime(df["Date"])

# build stats table
song_stats = df.groupby("Title").agg(
    Times_Played=("Title", "count"),
    First_Played=("Date", "min"),
    Last_Played=("Date", "max")
)

# sort by most played
song_stats = song_stats.sort_values(
    by="Times_Played",
    ascending=False
)

song_stats = song_stats.reset_index()

song_stats.to_csv(
    "song_stats.csv",
    index=False
)

print("analyzerino!.csv created!")