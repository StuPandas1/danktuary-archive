import os
import pandas as pd
import msal
import requests
from streamlit import secrets
import tomllib

with open(".streamlit/secrets.toml", "rb") as f:
    secrets = tomllib.load(f)

CLIENT_ID = secrets["microsoft"]["client_id"]
CLIENT_SECRET = secrets["microsoft"]["client_secret"]
TENANT_ID = secrets["microsoft"]["tenant_id"]
SCOPES = ["https://graph.microsoft.com/Files.ReadWrite"]

CSV_PATH = "band_archive.csv"
SHARE_URL_COLUMN = "OneDrive Share URL"
ONEDRIVE_MARKER = "OneDrive\\LoveDeep"

# -------------------------
# AUTH
# -------------------------

def get_access_token():
    app = msal.PublicClientApplication(
        CLIENT_ID,
        authority=f"https://login.microsoftonline.com/common"
    )

    # try device flow so you can log in via browser
    flow = app.initiate_device_flow(scopes=SCOPES)
    print(flow)
    print(flow["message"])  # prints the URL and code to enter
    result = app.acquire_token_by_device_flow(flow)

    if "access_token" in result:
        return result["access_token"]
    else:
        raise Exception(f"Auth failed: {result.get('error_description')}")

# -------------------------
# ONEDRIVE HELPERS
# -------------------------

def get_folder_item_id(token, folder_path):
    """Gets the OneDrive item ID for a folder given its path relative to Documents."""
    headers = {"Authorization": f"Bearer {token}"}
    encoded = requests.utils.quote(folder_path, safe="/")
    url = f"https://graph.microsoft.com/v1.0/me/drive/root:/{encoded}"
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json().get("id")
    return None

def create_share_link(token, item_id):
    """Creates an anonymous view-only share link for a OneDrive item."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    url = f"https://graph.microsoft.com/v1.0/me/drive/items/{item_id}/createLink"
    body = {"type": "view", "scope": "anonymous"}
    response = requests.post(url, headers=headers, json=body)
    if response.status_code in (200, 201):
        return response.json()["link"]["webUrl"]
    return None

def local_path_to_documents_relative(local_path):
    """Extracts the path relative to Documents from a full local path."""
    marker = "OneDrive\\LoveDeep"
    idx = local_path.find(marker)
    if idx == -1:
        return None
    relative = local_path[idx + len("OneDrive\\"):]
    return relative.replace("\\", "/")

# -------------------------
# MAIN
# -------------------------

df = pd.read_csv(CSV_PATH)

if SHARE_URL_COLUMN not in df.columns:
    df[SHARE_URL_COLUMN] = None

# find rows that need a share link
needs_link = df[
    df["File Path"].notna() &
    (df[SHARE_URL_COLUMN].isna() | (df[SHARE_URL_COLUMN] == ""))
]

# get unique folders only
folder_paths = {}
for _, row in needs_link.iterrows():
    file_path = str(row["File Path"])
    folder = "\\".join(file_path.split("\\")[:-1])
    rel = local_path_to_documents_relative(folder)
    if rel:
        folder_paths[folder] = rel

if not folder_paths:
    print("No new folders to process.")
else:
    print(f"Found {len(folder_paths)} folders to generate share links for.")
    token = get_access_token()

    folder_to_url = {}
    for local_folder, rel_path in folder_paths.items():
        print(f"  Processing: {rel_path}")
        item_id = get_folder_item_id(token, rel_path)
        if item_id:
            url = create_share_link(token, item_id)
            if url:
                folder_to_url[local_folder] = url
                print(f"    ✓ {url}")
            else:
                print(f"    ✗ Couldn't create share link")
        else:
            print(f"    ✗ Folder not found in OneDrive")

    # write URLs back to CSV
    for idx, row in df.iterrows():
        if pd.isna(row["File Path"]):
            continue
        folder = "\\".join(str(row["File Path"]).split("\\")[:-1])
        if folder in folder_to_url:
            df.at[idx, SHARE_URL_COLUMN] = folder_to_url[folder]

    df.to_csv(CSV_PATH, index=False)
    print(f"\nDone. {len(folder_to_url)} share links written to {CSV_PATH}.")
