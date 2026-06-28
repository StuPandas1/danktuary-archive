# import streamlit as st  # type: ignore
# import pandas as pd  # type: ignore

# from shared import (
#     load_data,
#     page_menu,
#     dank_header,
#     dank_audio_player,
#     authenticate_user,
#     get_streamable_url_from_path,
# )  # type: ignore

# # --- Auth ---
# token = authenticate_user()

# # --- Layout ---
# page_menu()
# dank_header(subtitle="Listen")

# df, song_stats, metadata, jam_metadata = load_data()

# performances = df.copy()
# performances["Show_Label"] = (
#     performances["Date"].dt.strftime("%m/%d/%Y")
#     + " — "
#     + performances["Location"]
# )

# unique_shows = (
#     performances.drop_duplicates(subset="Show_Label")
#     .sort_values("Date", ascending=False)["Show_Label"]
#     .tolist()
# )

# selected_show = st.selectbox(
#     "Pick a show to listen to",
#     unique_shows,
#     index=None,
#     placeholder="Type to search...",
# )

# if selected_show:
#     show_tracks = performances[
#         performances["Show_Label"] == selected_show
#     ].sort_values("Track Number")

#     st.write(f"**{selected_show}**")
#     st.divider()

#     if "File Path" not in show_tracks.columns:
#         st.write(
#             "No file paths found for this show — run the scanner with the File Path column enabled."
#         )
#     else:
#         for _, row in show_tracks.iterrows():
#             filepath = row.get("File Path")
#             if pd.isna(filepath):
#                 continue

#             # IMPORTANT: filepath must be the OneDrive-relative path,
#             # e.g. 'LoveDeep/Shows/2024-06-01/track01.flac'
#             audio_url = get_streamable_url_from_path(filepath, token)
#             if not audio_url:
#                 continue

#             track_label = f"{int(row['Track Number'])}. {row['Title']}"
#             subtitle = f"{row['Duration']} — {selected_show}"

#             dank_audio_player(track_label, subtitle, audio_url)

