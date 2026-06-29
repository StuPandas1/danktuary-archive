import streamlit as st  # type: ignore
import pandas as pd  # type: ignore
from shared import load_data, page_menu, dank_header, dank_playlist_player, suppress_selectbox_keyboard

df, song_stats, metadata, jam_metadata = load_data()

page_menu()

dank_header(subtitle="Listen")

suppress_selectbox_keyboard()

if "IA URL" not in df.columns:
    st.write("No streaming links found yet — run upload_to_archive.py to generate them.")
    st.stop()

performances = df.copy()
performances["Show_Label"] = (
    performances["Date"].dt.strftime("%m/%d/%Y")
    + " — "
    + performances["Location"]
)

# only shows with at least one playable track show up in the picker
playable_shows = performances[performances["IA URL"].notna()]

unique_shows = (
    playable_shows.drop_duplicates(subset="Show_Label")
    .sort_values("Date", ascending=False)["Show_Label"]
    .tolist()
)

if not unique_shows:
    st.write("No shows have been uploaded yet. Run upload_to_archive.py first.")
    st.stop()

selected_show = st.selectbox(
    "Pick a show to listen to",
    unique_shows,
    index=None,
    placeholder="Type to search..."
)

if selected_show:
    show_tracks = performances[
        performances["Show_Label"] == selected_show
    ].sort_values("Track Number").reset_index(drop=True)

    playlist = []
    i = 0
    while i < len(show_tracks):
        current = show_tracks.iloc[i]
        audio_url = current.get("IA URL")

        if pd.isna(audio_url):
            i += 1
            continue

        # group consecutive tracks that share the same duration (segues)
        group_titles = [current["Title"]]
        j = i + 1
        while j < len(show_tracks) and show_tracks.iloc[j]["Duration"] == current["Duration"]:
            group_titles.append(show_tracks.iloc[j]["Title"])
            j += 1

        playlist.append({
            "label": " -> ".join(group_titles),
            "duration": current["Duration"],
            "url": audio_url,
        })
        i = j

    if playlist:
        dank_playlist_player(selected_show, playlist)
    else:
        st.write("No playable tracks found for this show.")