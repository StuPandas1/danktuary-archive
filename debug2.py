import streamlit as st  # type: ignore
import pandas as pd  # type: ignore
import json
import os
import streamlit_authenticator as stauth
from shared import (
    load_data, page_menu, dank_header, dank_playlist_player, suppress_selectbox_keyboard,
    load_users_from_supabase, create_user_in_supabase,
    group_tracks, save_playlist_to_supabase, load_playlists_from_supabase, delete_playlist_from_supabase,
    update_playlist_in_supabase, add_tracks_to_playlist,
    get_show_list, get_playlist_for_show,
    style_playlist_draft_rows,
    load_all_recordings, _data_file_mtimes
)


try:
    stauth.authenticator.login(location="unrendered")
except Exception as e:
    st.write("DEBUG cookie login error:", e)