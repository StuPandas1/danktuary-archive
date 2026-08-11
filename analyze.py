import re
import pandas as pd  # type: ignore

df = pd.read_csv("band_archive.csv")

# convert dates
df["Date"] = pd.to_datetime(df["Date"])

# Strip the take suffix scanner.py adds for repeated songs within a session
# (e.g. "Song (2)", "Song (3)") so takes of the same song collapse back to
# one base title. Multiple takes are separate files/rows for playback and
# setlist purposes, but should count as ONE play for stats.
df["Base Title"] = df["Title"].str.replace(r"\s\(\d+\)$", "", regex=True)

# Collapse to one row per actual performance: same song, same date, same
# location -- regardless of how many takes were recorded for it that day.
plays = df.drop_duplicates(subset=["Base Title", "Date", "Location"])

# build stats table
song_stats = plays.groupby("Base Title").agg(
    Times_Played=("Base Title", "count"),
    First_Played=("Date", "min"),
    Last_Played=("Date", "max")
)

# sort by most played
song_stats = song_stats.sort_values(
    by="Times_Played",
    ascending=False
)

song_stats = song_stats.reset_index()
song_stats = song_stats.rename(columns={"Base Title": "Title"})

song_stats.to_csv(
    "song_stats.csv",
    index=False
)

print("song_stats.csv created!")