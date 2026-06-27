import streamlit as st  # type: ignore
import pandas as pd  # type: ignore
import random
import subprocess
import time
import streamlit.components.v1 as components  # type: ignore
from zoneinfo import ZoneInfo
today_md = pd.Timestamp.now(tz=ZoneInfo("America/New_York")).strftime("%m/%d")
from shared import ( #type: ignore
    load_data, build_filtered, weighted_pick, find_closers,
    times_played_mult, page_menu, dank_header, build_randomizer_pools, apply_segue_boost, pick_by_kind, generate_setlist,
    dead_weight_artists, dead_weight_year
)

st.markdown("""
<style>
div[data-testid="stHorizontalBlock"] {
    flex-wrap: nowrap !important;
    gap: 8px !important;
}
div[data-testid="stHorizontalBlock"] > div {
    min-width: 60px !important;
    flex: 1 1 0 !important;
}
div[data-testid="stHorizontalBlock"] button {
    font-size: 13px !important;
    padding: 4px 6px !important;
    white-space: normal !important;
    word-break: break-word !important;
}
</style>
""", unsafe_allow_html=True)

df, song_stats, metadata, jam_metadata = load_data()

page_menu()

min_year = int(df["Year"].min())
max_year = int(df["Year"].max())

if "random_setlist" not in st.session_state:
    st.session_state.random_setlist = None

if "active_tab" not in st.session_state:
    st.session_state.active_tab = "Recent Stats"

dank_header(subtitle="Useful Tools for the Dank")

tab_names = ["Recent Tracks", "Bust-outs", "Song Streak", "Rando Sets"]
tab_cols = st.columns(len(tab_names))
for i, name in enumerate(tab_names):
    with tab_cols[i]:
        button_type = "primary" if st.session_state.active_tab == name else "secondary"
        if st.button(name, key=f"tabbtn_{name}", width="stretch", type=button_type):
            st.session_state.active_tab = name
            st.rerun()

st.divider()

active_tab = st.session_state.active_tab

def ranked_table(display_df, sort_col=None, ascending=False, rename=None, columns=None, presorted=False):
    """Sort (unless presorted), rename, add rank, and return a dataframe ready for st.dataframe."""
    out = display_df if presorted else display_df.sort_values(sort_col, ascending=ascending)
    out = out.copy()
    if rename:
        out = out.rename(columns=rename)
    if columns:
        out = out[columns]
    out = out.reset_index(drop=True)
    out.insert(0, "Rank", range(1, len(out) + 1))
    return out

# -------------------------
# TAB: RECENT SETLIST STATS
# -------------------------

if active_tab in ("Recent Tracks", "Bust-outs", "Song Streak"):
    full_df, full_stats = build_filtered(df, metadata, [], (min_year, max_year))
 
if active_tab == "Recent Tracks":
    st.subheader("Most Recent Tracks")

    recent_display = ranked_table(
        full_stats.sort_values("Last_Played", ascending=False).assign(
            Last_Played=lambda x: x["Last_Played"].dt.strftime("%m/%d/%Y")
        ),
        presorted=True,
        rename={"Last_Played": "Last Played", "Times_Played": "Total Plays"},
        columns=["Title", "Last Played", "Total Plays"]
    )
    st.dataframe(recent_display, hide_index=True)
    
elif active_tab == "Bust-outs":
    st.subheader("Most Overdue Songs")
    dead_weight_only = st.checkbox("Dead Weight Only", key="bustout_dead_weight")

    if dead_weight_only:
        bustout_df, bustout_stats = build_filtered(df, metadata, dead_weight_artists, (dead_weight_year, max_year))
    else:
        bustout_df, bustout_stats = full_df, full_stats

    bustouts = bustout_stats.copy()
    bustouts["Days_Since_Played"] = (today_md - bustouts["Last_Played"]).dt.days
    bustouts["Overdue_Score"] = bustouts["Days_Since_Played"] * (bustouts["Times_Played"] ** times_played_mult)
    max_score = bustouts["Overdue_Score"].max()
    bustouts["Overdue_Score_Normalized"] = ((bustouts["Overdue_Score"] / max_score) * 100).round(1)

    st.dataframe(
        bustouts.assign(Last_Played=lambda x: x["Last_Played"].dt.strftime("%m/%d/%Y"))
        .sort_values("Overdue_Score_Normalized", ascending=False)[[
            "Title", "Days_Since_Played", "Times_Played", "Overdue_Score_Normalized"
        ]].rename(columns={
            "Days_Since_Played": "Days Since Played",
            "Times_Played": "Times Played",
            "Overdue_Score_Normalized": "Overdue Score (Normalized)"
        }),
        hide_index=True
    )

elif active_tab == "Song Streak":

    all_dates = sorted(df["Date"].dt.normalize().unique())
    records = []
    for title in full_df["Title"].unique():
        song_dates = set(full_df[full_df["Title"] == title]["Date"].dt.normalize().unique())
        streak = 0
        for date in all_dates:
            streak = streak + 1 if date in song_dates else 0
        if streak > 1:
            records.append({"Title": title, "Active Streak": streak})

    st.subheader("Active Setlist Streaks")
    if records:
        consec_df = ranked_table(pd.DataFrame(records), sort_col="Active Streak")
        st.dataframe(consec_df, width="stretch", hide_index=True)
    else:
        st.write("No Song Streak.")

# -------------------------
#  DEAD WEIGHT Rando Sets
# -------------------------

elif active_tab == "Rando Sets":

    st.markdown("#### Dead Weight Setlist Randomizer v1.0")

    improv_titles = set(metadata[metadata["Type"] == "Improv"]["Title"])
    jam_titles = set(jam_metadata["Title"])

    randomizer_df = df.merge(metadata[["Title", "Artist"]], on="Title", how="left")
    randomizer_df = randomizer_df[
        (randomizer_df["Artist"].isin(dead_weight_artists)) &
        (randomizer_df["Year"] >= dead_weight_year)
    ]
    randomizer_df = randomizer_df[~randomizer_df["Title"].isin(improv_titles)]

    random_messages = [
        "They're all Dark Star, man...",
        "Inspiration, move me brightly...",
        "If I had my way, I would tear this ol' building down...",
        "Ain't nobody messing with you but you...",
        "Look out, Cleveland.",
        "Notes, notes, notes, so many notes!",
        "Why haven't we learned Help/Slip/Franklin's yet?",
        "Playin' in the band, talkin' to my friends...",
        "The grass ain't greener, the wine ain't sweeter...",
        "I picked a good one, it looked like it could run...",
        "The one thing we need is a left handed monkey wrench."
    ]

    col1, col2 = st.columns([1, 1])

    with col1:
        num_songs = st.slider("Number of Songs:", 4, 15, 10)

    with col2:
        st.markdown("&nbsp;", unsafe_allow_html=True)
        if st.button("Create New Setlist", width='stretch'):
            st.session_state.random_setlist = generate_setlist(
                num_songs, randomizer_df, jam_titles, improv_titles, today_md
            )
            st.session_state.setlist_version = st.session_state.get("setlist_version", 0) + 1
            st.session_state.random_message = random.choice(random_messages)

    if st.session_state.get("random_setlist") is not None:

        col1, col2 = st.columns(2)

        with col1:
            if st.button("Re-Roll Those Laughing Bones", width='stretch'):
                current = st.session_state.random_setlist.copy()
                locked_songs = set(current[current["Locked"] == True]["Title"].tolist())
                new = generate_setlist(num_songs, randomizer_df, jam_titles, improv_titles, today_md)

                merged = []
                locked_rows = current[current["Locked"] == True].set_index("#")
                new_unlocked = new[~new["Title"].isin(locked_songs)].reset_index(drop=True)
                new_idx = 0

                for i in range(1, num_songs + 1):
                    if i in locked_rows.index:
                        row = locked_rows.loc[i].to_dict()
                        row["#"] = i
                        merged.append(row)
                    elif new_idx < len(new_unlocked):
                        row = new_unlocked.iloc[new_idx].to_dict()
                        row["#"] = i
                        merged.append(row)
                        new_idx += 1

                st.session_state.random_setlist = pd.DataFrame(merged)
                st.session_state.setlist_version = st.session_state.get("setlist_version", 0) + 1
                st.session_state.random_message = random.choice(random_messages)

        with col2:
            if st.button("Clear Setlist", width='stretch', key="clear_setlists2"):
                st.session_state.random_setlist = None
                st.session_state.setlist_version = 0
                st.rerun()

        if st.session_state.get("random_message"):
            st.write(st.session_state.random_message)

        editor_key = f"setlist_editor_{st.session_state.get('setlist_version', 0)}"

        if editor_key in st.session_state:
            edited_state = st.session_state[editor_key].get("edited_rows", {})
            for row_idx, changes in edited_state.items():
                if "Locked" in changes:
                    st.session_state.random_setlist.at[
                        st.session_state.random_setlist.index[row_idx], "Locked"
                    ] = changes["Locked"]

        st.data_editor(
            st.session_state.random_setlist[["#", "Title", "Locked"]],
            hide_index=True,
            width="stretch",
            column_config={
                "#": st.column_config.NumberColumn(),
                "Title": st.column_config.TextColumn(),
                "Locked": st.column_config.CheckboxColumn("🔒")
            },
            disabled=["#", "Title"],
            key=editor_key
        )

else:
    st.write("Select a tab to view its content.")

# -------------------------
# FOOTER 
# -------------------------
if st.button("⬆ Back to top"):
    components.html("""
        <script>
        var doc = window.parent.document;
        var selectors = [
            'section.main',
            '.main',
            '[data-testid="stAppViewContainer"]',
            '[data-testid="stMain"]',
            '.stApp',
            'div[data-testid="stAppViewBlockContainer"]'
        ];
        selectors.forEach(function(sel) {
            var el = doc.querySelector(sel);
            if (el) { el.scrollTo(0, 0); el.scrollTop = 0; }
        });
        doc.documentElement.scrollTop = 0;
        doc.body.scrollTop = 0;
        window.parent.scrollTo(0, 0);
        </script>
    """, height=0)

st.divider()

st.markdown(
    "<div style='text-align: center; color: grey; font-size: 13px;'>Danktuary Archive Version: 1.5.0 | Believe it if you need it</div>",
    unsafe_allow_html=True
)
st.markdown("")


#LEGACY TOOLS (commented out for now)
# col_f1, col_f2, col_f3 = st.columns(3)

# with col_f1:
#     if st.button("Master List Clearer"):
#         st.session_state.random_setlist = None
#         st.session_state.selected_show = None
#         if "selected_show_widget" in st.session_state:
#             del st.session_state["selected_show_widget"]
#         st.rerun()


# if st.button("Refresh Database"):
#     with st.spinner("Updating archive..."):
#         subprocess.run(["python", "scanner.py"])
#         subprocess.run(["python", "analyze.py"])
#         subprocess.run(["python", "build_metadata.py"])
#         subprocess.run(["python", "generate_onedrive_urls.py"])
#     st.cache_data.clear()
#     success_message = st.empty()
#     success_message.success("Database updated!")
#     time.sleep(2)
#     success_message.empty()
#     st.rerun()