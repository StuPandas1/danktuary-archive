import streamlit as st  # type: ignore
import pandas as pd  # type: ignore
import streamlit.components.v1 as components
import random
from zoneinfo import ZoneInfo
today_md = pd.Timestamp.now(tz=ZoneInfo("America/New_York")).strftime("%m/%d")
from shared import load_data, parse_duration, page_menu, dank_header, force_columns_horizontal, dank_theme, dank_footer, dank_sign, dank_hex, dank_callout, card_html #type: ignore

st.set_page_config(page_title="DankApp | The Dead Weight Hub", page_icon="static/icon.png", layout="wide")

@st.cache_data(show_spinner=False)
def landing_stats(d_all, d):
    """Everything the dashboard cards need. d_all = all takes, d = Take 1 only."""
    counts = d["Title"].value_counts()

    # unique durations only (a segue chain shares one Duration)
    dur_all = d_all["Duration"].ne(d_all["Duration"].shift())
    total_secs = int(d_all.loc[dur_all, "Duration"].apply(parse_duration).sum())
    longest_secs = int(d["Duration"].apply(parse_duration).max())

    return {
        "total_shows": d["Date"].nunique(),
        "gig_count": d[d["Type"] == "live"]["Date"].nunique(),
        "last_show": d["Date"].max(),
        "total_secs": total_secs,
        "songs_played": len(d_all),
        "unique_songs": d["Title"].nunique(),
        "longest_secs": longest_secs,
        "top_song": counts.idxmax(),
        "top_count": int(counts.max()),
    }


@st.cache_data(show_spinner=False)
def landing_fact_data(d):
    """Pools the random fun facts draw from."""
    counts = d["Title"].value_counts()

    # segue chains: same show + same Duration = one jam
    s = d.sort_values(["Date", "Track Number"])
    chain = (s["Date"].ne(s["Date"].shift()) | s["Duration"].ne(s["Duration"].shift())).cumsum()
    jams = (
        s.assign(_g=chain).groupby("_g")
        .agg(Date=("Date", "first"), Songs=("Title", " -> ".join), Duration=("Duration", "first"))
    )
    jams["secs"] = jams["Duration"].apply(parse_duration)
    top_jams = jams.nlargest(10, "secs")

    first_day = d["Date"].min()
    years = d["Year"].value_counts()
    return {
        "top_played": counts.head(10),
        "one_timers": counts[counts == 1].index.tolist(),
        "openers": d[d["Track Number"] == 1]["Title"].value_counts().head(10),
        "top_jams": top_jams,
        "busiest_year": years.idxmax(),
        "busiest_count": int(years.max()),
        "earliest_date": first_day,
        "earliest_title": d[d["Date"] == first_day]["Title"].iloc[0],
    }

dank_theme()

df, song_stats, metadata, jam_metadata = load_data()
df2 = df.copy()
df_durationfiltered = df[df["Duration"] != df["Duration"].shift()].reset_index(drop=True)
df = df[df["Take"] == 1]
force_columns_horizontal(min_col_width="28px", key="login_mod")

force_columns_horizontal(gap="0.75rem", equal_width=True, key="top_row")
with st.container(key="top_row"):
    col1, col2 = st.columns(2, vertical_alignment="center")
    with col1:
        page_menu()
    with col2:
        if st.user.is_logged_in:
            if st.button("Logout", key="landing_logout", width="stretch"):
                st.logout()
        else:
            st.button("Log in with Google", key="landing_login", on_click=st.login, width="stretch")

dank_header(subtitle="The Dankest App In Town")
st.divider()

dank_sign("listen to the latest")

# -------------------------
# MOST RECENT SETLIST
# -------------------------
last_show_row = df[df["Date"] == df["Date"].max()]
last_show_date_str = df["Date"].max().strftime("%m/%d/%Y")
last_show_location = last_show_row["Location"].iloc[0]
last_show_label = f"{last_show_date_str} — {last_show_location}"

with st.container(key="hex_recent"):
    if st.button(f"{last_show_label}", key="most_recent_setlist_btn", width="stretch"):
        st.session_state["listen_mode"] = "Setlists"
        st.session_state["pending_listen_show"] = last_show_label
        st.switch_page("pages/listen.py")

# -------------------------
# ON THIS DAY
# ------------------------
day_name = pd.Timestamp.now(tz=ZoneInfo("America/New_York")).strftime("%A")
on_this_day_df = df[df["Date"].dt.strftime("%m/%d") == today_md].copy()
on_this_day_dates = sorted(on_this_day_df["Date"].unique())

if on_this_day_dates:
    n = len(on_this_day_dates)
    dank_sign(f"Explore {n} {'recording' if n == 1 else 'recordings'} on this day ({today_md})", direction="left")
    with st.container(key="hex_otd"):
        cols = st.columns(len(on_this_day_dates))
        for i, date in enumerate(on_this_day_dates):
            date_str = pd.Timestamp(date).strftime("%m/%d/%Y")
            location = on_this_day_df[on_this_day_df["Date"] == date]["Location"].iloc[0]
            label = f"{date_str} — {location}"

            with cols[i]:
                if st.button(label, key=f"otd_{date_str}", width="stretch"):
                    st.session_state.pending_show_selection = label
                    st.session_state.active_tab = "Setlist Lookup"
                    st.query_params["scroll"] = "1"
                    st.switch_page("pages/stats.py")
else:
    dank_hex(f"No recordings found on this day ({today_md})")

st.write("")

# -------------------------
# FUN FACT
# -------------------------
st.divider()

fd = landing_fact_data(df)
fun_facts = []

i = random.randrange(len(fd["top_played"]))
fun_facts.append(
    f"**\"{fd['top_played'].index[i]}\"** is the **#{i + 1}** most played song in the archive "
    f"(**{fd['top_played'].iloc[i]}** plays)."
)

if fd["one_timers"]:
    pick = random.choice(fd["one_timers"])
    pick_date = df[df["Title"] == pick]["Date"].iloc[0].strftime("%m/%d/%Y")
    fun_facts.append(f"**\"{pick}\"** has only been played once, on **{pick_date}**.")

if not fd["openers"].empty:
    i = random.randrange(len(fd["openers"]))
    fun_facts.append(
        f"**\"{fd['openers'].index[i]}\"** is the **#{i + 1}** most common opener "
        f"(**{fd['openers'].iloc[i]}** times)."
    )

if not fd["top_jams"].empty:
    i = random.randrange(len(fd["top_jams"]))
    j = fd["top_jams"].iloc[i]
    secs = int(j["secs"])
    fun_facts.append(
        f"At **{secs // 60}:{secs % 60:02d}**, **\"{j['Songs']}\"** (**{j['Date']:%m/%d/%Y}**) "
        f"is the **#{i + 1}** longest track in the archive."
    )

fun_facts.append(f"**{fd['busiest_year']}** was the most active year, with **{fd['busiest_count']}** songs played.")
fun_facts.append(
    f"The earliest recording in the archive is **\"{fd['earliest_title']}\"** "
    f"from **{fd['earliest_date']:%m/%d/%Y}**."
)

dank_callout("How 'bout a random fact, man?", random.choice(fun_facts))
 
st.divider()
 
# -------------------------
# STATS DASHBOARD
# -------------------------

dank_sign("Heady Stats Dashboard")
stats = landing_stats(df2, df)
ts = stats["total_secs"]

cards = [
    card_html(stats["total_shows"], "Total Recordings", accent=True),
    card_html(stats["gig_count"], "Gig Recordings"),
    card_html(stats["last_show"].strftime("%m/%d/%y"), "Last Recording"),
    card_html(f"{ts // 86400}d {(ts % 86400) // 3600}h {(ts % 3600) // 60}m", "Total Time Played"),
    card_html(stats["songs_played"], "Songs Played", accent=True),
    card_html(stats["unique_songs"], "Unique Songs"),
    card_html(f"{stats['longest_secs'] // 60}:{stats['longest_secs'] % 60:02d}", "Longest Track", accent=True),
    card_html(f"{stats['top_song']} ({stats['top_count']})", "Most Played Song", accent=True),
]
st.markdown(f'<div class="dank-grid">{"".join(cards)}</div>', unsafe_allow_html=True)

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

dank_footer()