import streamlit as st  # type: ignore
import pandas as pd  # type: ignore
import altair as alt  # type: ignore
import os
import streamlit.components.v1 as components  # type: ignore
from shared import ( #type: ignore
    load_data, build_filtered, find_closers, parse_duration,
    make_dead_weight_callback, page_menu, local_path_to_onedrive_url, dank_header
)

df, song_stats, metadata, jam_metadata = load_data()

page_menu()

min_year = int(df["Year"].min())
max_year = int(df["Year"].max())

# -------------------------
# SESSION STATE
# -------------------------

if "selected_song" not in st.session_state:
    st.session_state.selected_song = None

if "selected_show" not in st.session_state:
    st.session_state.selected_show = None

if "active_stat" not in st.session_state:
    st.session_state.active_stat = None

if "t1_year" not in st.session_state:
    st.session_state.t1_year = (min_year, max_year)

if "t3_year" not in st.session_state:
    st.session_state.t3_year = (min_year, max_year)

if "active_tab" not in st.session_state:
    st.session_state.active_tab = "Song Search"

dank_header(subtitle="Explore the Archive")

st.markdown("""
<style>
div[data-testid="stHorizontalBlock"] button {
    font-size: 17px !important;
    font-weight: 450 !important;
}
</style>
""", unsafe_allow_html=True)

tab_names = ["Song Search", "Setlist Lookup", "Statistics"]
tab_cols = st.columns(len(tab_names))
for i, name in enumerate(tab_names):
    with tab_cols[i]:
        button_type = "primary" if st.session_state.active_tab == name else "secondary"
        if st.button(name, key=f"tabbtn_{name}", width="stretch", type=button_type):
            st.session_state.active_tab = name
            st.rerun()

st.divider()

# -------------------------
# TAB 1: SONG SEARCH
# -------------------------

if st.session_state.active_tab == "Song Search":
    st.markdown("#### Song Search")

    with st.expander("Filters", expanded=False):
        st.checkbox(
            "Dead Weight Only",
            key="t1_dead_weight",
            on_change=make_dead_weight_callback("t1_artist", "t1_year", "t1_dead_weight", min_year, max_year)
        )

        t1_artist = st.multiselect(
            "By Artist:",
            sorted(song_stats["Artist"].dropna().unique()),
            key="t1_artist"
        )
        t1_year = st.slider(
            "By Year:",
            min_year, max_year,
            key="t1_year"
        )

    t1_df, t1_stats = build_filtered(df, metadata, t1_artist, t1_year)

    search_song = st.selectbox(
        "Get shown the light...",
        sorted(t1_stats["Title"].unique()),
        index=None,
        placeholder="Type to search..."
    )

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("Load Song History"):
            st.session_state.selected_song = search_song

    with col2:
        if st.button("Random Song"):
            import random
            st.session_state.selected_song = random.choice(sorted(t1_stats["Title"].unique()))

    with col3:
        if st.button("Clear Song History"):
            st.session_state.selected_song = None
            st.rerun()

    selected_song = st.session_state.selected_song

    if selected_song:

        matching_stats = t1_stats[t1_stats["Title"] == selected_song]
        performances = df[df["Title"] == selected_song].sort_values("Date", ascending=False)

        if not matching_stats.empty:
            stats = matching_stats.iloc[0]

            st.subheader(selected_song)
            st.write(f"**Between {stats['First_Played'].year} and {stats['Last_Played'].year}:**")
            times = stats['Times_Played']
            st.write(f"\"{selected_song}\" was played **{times}** {'time.' if times == 1 else 'times.'}")
            st.write(f"First played: **{stats['First_Played'].strftime('%m/%d/%Y')}**")
            days_ago = (pd.Timestamp.today() - stats['Last_Played']).days
            st.write(f"Last played: **{stats['Last_Played'].strftime('%m/%d/%Y')}**, or **{days_ago}** {'day ago.' if days_ago == 1 else 'days ago.'}")

            true_debut = df[df["Title"] == selected_song]["Date"].min()
            total_shows_since_debut = df[df["Date"] >= true_debut]["Date"].nunique()
            shows_played = df[(df["Title"] == selected_song) & (df["Date"] >= true_debut)]["Date"].nunique()
            pct = round((shows_played / total_shows_since_debut) * 100, 1)
            st.write(f"Since its debut, **\"{selected_song}\"** has been played in **{pct}%** of setlists.")

        with st.expander("Graph By Year", expanded=False):
            yearly_counts = (
                performances.groupby(performances["Date"].dt.year)
                .size()
                .reset_index(name="Times Played")
            ).rename(columns={"Date": "Year"})

            all_years = pd.DataFrame({"Year": range(min_year, max_year + 1)})

            yearly_counts = (
                all_years
                .merge(yearly_counts, on="Year", how="left")
                .fillna(0)
            )
            yearly_counts["Times Played"] = yearly_counts["Times Played"].astype(int)
            yearly_counts["Year"] = yearly_counts["Year"].astype(str)

            chart = alt.Chart(yearly_counts).mark_bar(
                cornerRadiusTopLeft=4,
                cornerRadiusTopRight=4,
                color="#4a9eff"
            ).encode(
                x=alt.X("Year:O", axis=alt.Axis(labelAngle=0, title=None)),
                y=alt.Y("Times Played:Q", axis=alt.Axis(tickMinStep=1, title="Times Played"), scale=alt.Scale(domain=[0, yearly_counts["Times Played"].max() + 1])),
                tooltip=[
                    alt.Tooltip("Year:O", title="Year"),
                    alt.Tooltip("Times Played:Q", title="Times Played")
                ]
            ).properties(
                height=250,
                title=alt.TitleParams(selected_song, anchor="middle")
            ).configure_axis(
                grid=False,
                labelColor="#888",
                tickColor="#888"
            ).configure_view(
                strokeWidth=0
            )

            st.altair_chart(chart, width='stretch')

        with st.expander("Graph By Length", expanded=False):
            def bucket_duration(secs):
                if secs < 120: return "0–2 min"
                elif secs < 240: return "2–4 min"
                elif secs < 360: return "4–6 min"
                elif secs < 480: return "6–8 min"
                elif secs < 600: return "8–10 min"
                elif secs < 720: return "10–12 min"
                elif secs < 840: return "12–14 min"
                elif secs < 960: return "14–16 min"
                elif secs < 1080: return "16–18 min"
                elif secs < 1200: return "18–20 min"
                else: return "20+ min"

            bucket_order = [
                "0–2 min", "2–4 min", "4–6 min", "6–8 min", "8–10 min",
                "10–12 min", "12–14 min", "14–16 min", "16–18 min", "18–20 min", "20+ min"
            ]

            perf_durations = performances["Duration"].dropna()
            buckets = perf_durations.apply(lambda d: bucket_duration(parse_duration(d)))

            bucket_counts = (
                buckets.value_counts()
                .reindex(bucket_order, fill_value=0)
                .reset_index()
            )
            bucket_counts.columns = ["Length", "Times Played"]
            bucket_counts = bucket_counts[bucket_counts["Times Played"] > 0]

            length_chart = alt.Chart(bucket_counts).mark_bar(
                cornerRadiusTopLeft=4,
                cornerRadiusTopRight=4,
                color="#4a9eff"
            ).encode(
                x=alt.X("Length:O", sort=bucket_order, axis=alt.Axis(labelAngle=0, title=None)),
                y=alt.Y("Times Played:Q", axis=alt.Axis(tickMinStep=1, title="Times Played")),
                tooltip=[
                    alt.Tooltip("Length:O", title="Length"),
                    alt.Tooltip("Times Played:Q", title="Times Played")
                ]
            ).properties(
                height=250,
                title=alt.TitleParams(selected_song, anchor="middle")
            ).configure_axis(
                grid=False,
                labelColor="#888",
                tickColor="#888"
            ).configure_view(
                strokeWidth=0
            )

            st.altair_chart(length_chart, width='stretch')

        with st.expander("Performance History", expanded=False):
            performances["Gap Since Previous"] = (
                performances["Date"].diff().dt.days
            ).fillna(0).astype(int) * -1

            segue_labels = []
            for idx, row in performances.iterrows():
                date = row["Date"]
                track = row["Track Number"]
                duration = row["Duration"]

                session = df[(df["Date"] == date)].sort_values("Track Number")
                tracks = session["Track Number"].tolist()
                durations = session["Duration"].tolist()
                titles = session["Title"].tolist()

                pos = tracks.index(track) if track in tracks else -1
                label = ""

                if pos >= 0:
                    prev_same = pos > 0 and durations[pos - 1] == duration
                    next_same = pos < len(durations) - 1 and durations[pos + 1] == duration

                    if prev_same and next_same:
                        label = f"{titles[pos-1]} -> {titles[pos]} -> {titles[pos+1]}"
                    elif prev_same:
                        label = f"{titles[pos-1]} -> {titles[pos]}"
                    elif next_same:
                        label = f"{titles[pos]} -> {titles[pos+1]}"
                    else:
                        label = titles[pos]

                segue_labels.append(label)

            performances = performances.copy()
            performances["Segue"] = segue_labels

            df_display = performances.assign(
                Show=lambda x: x["Date"].dt.strftime("%m/%d/%Y") + " — " + x["Location"]
            )[["Show", "Segue", "Duration", "Gap Since Previous"]]

            st.dataframe(
                df_display,
                width="stretch",
                hide_index=True,
            )

# -------------------------
# TAB 2: SETLIST LOOKUP
# -------------------------

elif st.session_state.active_tab == "Setlist Lookup":
    st.markdown("#### Setlist Lookup")

    performances = df.copy()
    performances["Show_Label"] = (
        performances["Date"].dt.strftime("%m/%d/%Y")
        + " — "
        + performances["Location"]
    )

    type_order = {"live": 0, "trip": 1, "practice": 2}
    performances["Type_Order"] = performances["Type"].map(type_order).fillna(3)

    col1, col2 = st.columns(2)

    with col1:
        location_filter = st.selectbox(
            "By Location:",
            ["All"] + sorted(performances["Location"].dropna().unique().tolist()),
            index=0
        )

    with col2:
        year_filter = st.selectbox(
            "By Year:",
            ["All"] + sorted(performances["Year"].dropna().unique().tolist(), reverse=True),
            index=0
        )

    filtered_performances = performances.copy()
    if location_filter != "All":
        filtered_performances = filtered_performances[
            filtered_performances["Location"] == location_filter
        ]
    if year_filter != "All":
        filtered_performances = filtered_performances[
            filtered_performances["Year"] == year_filter
        ]

    unique_shows = (
        filtered_performances.drop_duplicates(subset="Show_Label")
        .sort_values(["Type_Order", "Date"], ascending=[True, False])["Show_Label"]
        .tolist()
    )

    # if a show was set externally (e.g. from landing page "on this day")
    # and the widget hasn't picked it up yet, seed the widget's own state
    if (
        st.session_state.selected_show in unique_shows
        and st.session_state.get("selected_show_widget") != st.session_state.selected_show
    ):
        st.session_state.selected_show_widget = st.session_state.selected_show

    selected_show = st.selectbox(
        "Hundreds of shows but one will do",
        unique_shows,
        index=None,
        placeholder="Type to search...",
        key="selected_show_widget"
    )

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("Random Show"):
            import random
            surprise = random.choice(unique_shows)
            st.session_state.selected_show = surprise
            if "selected_show_widget" in st.session_state:
                del st.session_state["selected_show_widget"]
            st.rerun()

    with col2:
        today_md = pd.Timestamp.today().strftime("%m/%d")
        on_this_day = [s for s in unique_shows if s.startswith(today_md)]
        if st.button("Random On This Day"):
            if on_this_day:
                import random
                st.session_state.selected_show = random.choice(on_this_day)
                if "selected_show_widget" in st.session_state:
                    del st.session_state["selected_show_widget"]
                st.rerun()
            else:
                st.toast("No shows found on this date in past years.")

    with col3:
        if st.button("Clear Setlist", key="clear_setlists1"):
            st.session_state.selected_show = None
            if "selected_show_widget" in st.session_state:
                del st.session_state["selected_show_widget"]
            st.rerun()

    if selected_show:
        st.session_state.selected_show = selected_show

    if st.session_state.selected_show:
        selected_label = st.session_state.selected_show

        historical_setlist = performances[
            performances["Show_Label"] == selected_label
        ].sort_values("Track Number")

        selected_date_str = selected_label.split(" — ")[0]
        selected_location = selected_label.split(" — ")[1]

        venue_shows = performances[performances["Location"] == selected_location]["Date"].nunique()
        venue_counts = performances[performances["Location"] == selected_location]["Title"].value_counts()
        most_common_count = venue_counts.max()
        tied_songs = venue_counts[venue_counts == most_common_count]

        st.write(f"**{selected_location} - {selected_date_str}**")
        st.write(f"There {'is' if venue_shows == 1 else 'are'} **{venue_shows}** {'set' if venue_shows == 1 else 'sets'} at {selected_location}.")

        if len(tied_songs) > 1:
            st.write(f"There are **{len(tied_songs)}** songs tied for most commonly played at {selected_location}, each played **{most_common_count}** {'time.' if most_common_count == 1 else 'times.'}")
        else:
            most_common_at_venue = tied_songs.idxmax()
            st.write(f"The most commonly played song at {selected_location} is **\"{most_common_at_venue}\"**, played **{most_common_count}** {'time.' if most_common_count == 1 else 'times.'}")

        deduped = historical_setlist.copy().reset_index(drop=True)
        deduped = deduped[deduped["Duration"] != deduped["Duration"].shift(1)]
        total_secs = deduped["Duration"].apply(parse_duration).sum()
        total_mins = total_secs // 60
        total_secs_remainder = total_secs % 60
        st.write(f"Total setlist duration: **{total_mins}:{total_secs_remainder:02d}**")

        display_setlist = historical_setlist[["Track Number", "Title", "Duration"]].rename(
            columns={"Track Number": "Number"}
        ).copy().reset_index(drop=True)

        segue_indices = set()
        for i in range(len(display_setlist) - 1):
            if display_setlist.at[i, "Duration"] == display_setlist.at[i + 1, "Duration"]:
                display_setlist.at[i, "Title"] = display_setlist.at[i, "Title"] + " ->"
                segue_indices.add(i + 1)

        for i in segue_indices:
            display_setlist.at[i, "Duration"] = "--"

        onedrive_url = (
            historical_setlist["OneDrive URL"].dropna().iloc[0]
            if "OneDrive URL" in historical_setlist.columns and not historical_setlist["OneDrive URL"].dropna().empty
            else None
        )
        sample_filepath = historical_setlist["File Path"].dropna().iloc[0]
        folder_path = "\\".join(sample_filepath.split("\\")[:-1])
        onedrive_url = local_path_to_onedrive_url(folder_path)
        if onedrive_url:
            st.markdown(f"[Listen in OneDrive ↗]({onedrive_url})")
            
        st.dataframe(
            display_setlist,
            hide_index=True,
            width='stretch',
            height=len(display_setlist) * 35 + 38,
        )


# -------------------------
# TAB 3: STATISTICS (general / archive-wide)
# -------------------------

elif st.session_state.active_tab == "Statistics":
    st.markdown("#### Song Statistics")

    with st.expander("Filters", expanded=False):
        st.checkbox(
            "Dead Weight Only",
            key="t3_dead_weight",
            on_change=make_dead_weight_callback("t3_artist", "t3_year", "t3_dead_weight", min_year, max_year)
        )

        t3_artist = st.multiselect(
            "By Artist:",
            sorted(song_stats["Artist"].dropna().unique()),
            key="t3_artist"
        )
        t3_year = st.slider(
            "By Year:",
            min_year, max_year,
            key="t3_year"
        )

    t3_df, t3_stats = build_filtered(df, metadata, t3_artist, t3_year)

    with st.expander("Song Stats", expanded=False):
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("Most Played"):
                st.session_state.active_stat = "most_played"
        with col2:
            if st.button("Longest Historical Gap"):
                st.session_state.active_stat = "longest_gap"
        with col3:
            if st.button("Longest Jams"):
                st.session_state.active_stat = "longest_jams"

    with st.expander("Setlist Stats", expanded=False):
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("Most Common Openers"):
                st.session_state.active_stat = "openers"
            if st.button("Most Common At Gigs"):
                st.session_state.active_stat = "most_common_gig"
        with col2:
            if st.button("Most Common Closers"):
                st.session_state.active_stat = "closers"
            if st.button("Activity Heatmap"):
                st.session_state.active_stat = "heatmap"
        with col3:
            if st.button("Most Common Segues"):
                st.session_state.active_stat = "segues"

    active = st.session_state.get("active_stat")

    if active == "most_played":

        most_played = t3_stats.sort_values("Times_Played", ascending=False)
        most_played_display = (
            most_played.assign(
                First_Played=lambda x: x["First_Played"].dt.strftime("%m/%d/%Y"),
                Last_Played=lambda x: x["Last_Played"].dt.strftime("%m/%d/%Y")
            )[[
                "Title", "Times_Played", "First_Played", "Last_Played"
            ]].rename(columns={
                "Times_Played": "Times Played",
                "First_Played": "First Played",
                "Last_Played": "Last Played"
            })
        )
        most_played_display.insert(0, "Rank", range(1, len(most_played_display) + 1))

        st.subheader("Most Played Songs")
        st.dataframe(
            most_played_display,
            width="stretch",
            hide_index=True,
            column_config={
                "Rank": st.column_config.NumberColumn(width="small")
            }
        )

    elif active == "longest_gap":

        all_dates = sorted(t3_df["Date"].unique())
        date_index = {date: i for i, date in enumerate(all_dates)}

        records = []
        for title in t3_df["Title"].unique():
            song_dates = sorted(t3_df[t3_df["Title"] == title]["Date"].unique())
            if len(song_dates) > 1:
                max_gap = 0
                best_from = None
                best_to = None
                for i in range(1, len(song_dates)):
                    gap = date_index[song_dates[i]] - date_index[song_dates[i - 1]] - 1
                    if gap > max_gap:
                        max_gap = gap
                        best_from = song_dates[i - 1]
                        best_to = song_dates[i]
                if best_from is not None:
                    records.append({
                        "Title": title,
                        "Longest Gap (Sets)": max_gap,
                        "From": pd.Timestamp(best_from).strftime("%m/%d/%Y"),
                        "To": pd.Timestamp(best_to).strftime("%m/%d/%Y")
                    })

        if records:
            gap_df = (
                pd.DataFrame(records)
                .sort_values("Longest Gap (Sets)", ascending=False)
                .reset_index(drop=True)
            )
            gap_df.insert(0, "Rank", range(1, len(gap_df) + 1))

            st.subheader("Longest Historical Gap Between Plays")
            st.dataframe(
                gap_df,
                width="stretch",
                hide_index=True,
            )

    elif active == "openers":

        openers = t3_df[t3_df["Track Number"] == 1]
        opener_counts = (
            openers.groupby("Title")
            .size()
            .reset_index(name="Times Opened")
            .sort_values("Times Opened", ascending=False)
        )
        opener_counts.insert(0, "Rank", range(1, len(opener_counts) + 1))

        st.subheader("Most Common Openers")
        st.dataframe(
            opener_counts,
            width="stretch",
            hide_index=True,
        )

    elif active == "closers":

        year_filtered_df = df[
            (df["Year"] >= t3_year[0]) &
            (df["Year"] <= t3_year[1])
        ]
        allowed_titles = set(t3_df["Title"].unique())
        closers = find_closers(year_filtered_df, allowed_titles)

        closer_counts = (
            pd.Series(closers)
            .value_counts()
            .reset_index()
        )
        closer_counts.columns = ["Title", "Times Closed"]
        closer_counts.insert(0, "Rank", range(1, len(closer_counts) + 1))

        st.subheader("Most Common Closers")
        st.dataframe(
            closer_counts,
            width="stretch",
            hide_index=True,
        )

    elif active == "segues":

        segues = []
        for date in t3_df["Date"].unique():
            session = t3_df[t3_df["Date"] == date].sort_values("Track Number")
            titles = session["Title"].tolist()
            for i in range(len(titles) - 1):
                segues.append(f"{titles[i]}  →  {titles[i + 1]}")

        if segues:
            segue_counts = (
                pd.Series(segues)
                .value_counts()
                .reset_index()
            )
            segue_counts.columns = ["Segue", "Times Played"]
            segue_counts = segue_counts[segue_counts["Times Played"] >= 3]
            segue_counts = segue_counts.reset_index(drop=True)
            segue_counts.insert(0, "Rank", range(1, len(segue_counts) + 1))

            st.subheader("Most Common Segues")
            st.dataframe(
                segue_counts,
                width="stretch",
                hide_index=True,
            )

    elif active == "longest_jams":

        jam_records = []
        for date in t3_df["Date"].unique():
            session = t3_df[t3_df["Date"] == date].sort_values("Track Number").reset_index(drop=True)
            i = 0
            while i < len(session):
                current = session.iloc[i]
                duration = current["Duration"]
                group_titles = [current["Title"]]

                j = i + 1
                while j < len(session) and session.iloc[j]["Duration"] == duration:
                    group_titles.append(session.iloc[j]["Title"])
                    j += 1

                label = " -> ".join(group_titles)
                secs = parse_duration(duration)
                jam_records.append({
                    "Date": pd.Timestamp(date).strftime("%m/%d/%Y"),
                    "Song(s)": label,
                    "Duration": duration,
                    "Duration (secs)": secs
                })
                i = j

        if jam_records:
            jams_df = (
                pd.DataFrame(jam_records)
                .query("`Duration (secs)` >= 1080")
                .sort_values("Duration (secs)", ascending=False)
                .drop(columns=["Duration (secs)"])
                .reset_index(drop=True)
            )
            jams_df.insert(0, "Rank", range(1, len(jams_df) + 1))

            st.subheader("Longest Jams")
            st.dataframe(
                jams_df,
                width="stretch",
                hide_index=True,
            )

    elif active == "most_common_gig":

        gig_df = t3_df[t3_df["Type"] == "live"]

        gig_counts = (
            gig_df.groupby("Title")
            .agg(
                Times_Played=("Title", "count"),
                Last_Played=("Date", "max")
            )
            .reset_index()
            .sort_values("Times_Played", ascending=False)
            .reset_index(drop=True)
        )
        gig_counts["Last_Played"] = pd.to_datetime(gig_counts["Last_Played"]).dt.strftime("%m/%d/%Y")
        gig_counts.insert(0, "Rank", range(1, len(gig_counts) + 1))

        st.subheader("Most Common at Gigs")
        st.dataframe(
            gig_counts.rename(columns={
                "Times_Played": "#",
                "Last_Played": "Last Played"
            }),
            width="stretch",
            hide_index=True,
        )

    elif active == "heatmap":

        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

        heatmap_df = t3_df.drop_duplicates(subset="Date").copy()
        heatmap_df["Month"] = heatmap_df["Date"].dt.month

        counts = (
            heatmap_df.groupby("Month")
            .size()
            .reset_index(name="Shows")
        )
        counts["Month Name"] = counts["Month"].apply(lambda m: month_names[m - 1])

        heatmap_chart = alt.Chart(counts).mark_bar(
            cornerRadiusTopLeft=4,
            cornerRadiusTopRight=4,
            color="#4a9eff"
        ).encode(
            x=alt.X("Month Name:O",
                    sort=month_names,
                    axis=alt.Axis(title=None, labelAngle=0)),
            y=alt.Y("Shows:Q",
                    axis=alt.Axis(tickMinStep=1, title="Shows")),
            tooltip=[
                alt.Tooltip("Month Name:O", title="Month"),
                alt.Tooltip("Shows:Q", title="Shows")
            ]
        ).properties(
            height=250,
            title=alt.TitleParams("Sets by Month", anchor="middle")
        ).configure_axis(
            grid=False,
            labelColor="#888",
            tickColor="#888"
        ).configure_view(
            strokeWidth=0
        )

        st.subheader("Activity Heatmap")
        st.altair_chart(heatmap_chart, width='stretch')
else:
    st.write("Select a tab to view its content.")
# -------------------------
# FOOTER 
# -------------------------
st.divider()
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
