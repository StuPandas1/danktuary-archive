import pandas as pd # type: ignore

song_stats = pd.read_csv("song_stats.csv")

while True:
    query = input("\nSearch for a song: ").lower()

    if query == "exit":
        break

    results = song_stats[
        song_stats["Title"].str.lower().str.contains(query)
    ]

    if results.empty:
        print("No matches found.")
    else:
        print(results)

