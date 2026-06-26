import pandas as pd
from urllib.parse import quote
 
def local_path_to_onedrive_url(local_path):
    if not isinstance(local_path, str):
        return None
    marker = "OneDrive\\LoveDeep"
    idx = local_path.find(marker)
    if idx == -1:
        return None
    relative = local_path[idx + len("OneDrive\\"):]
    relative = relative.replace("\\", "/")
    onedrive_path = f"/personal/436f797b4dd480a3/Documents/{relative}".rstrip("/")
    encoded_path = quote(onedrive_path, safe="")
    viewid = "5df66b5e-e8a6-4d4e-a4a3-babd050c831a"
    return f"https://onedrive.live.com/?id={encoded_path}&viewid={viewid}&view=0"
 
df = pd.read_csv("band_archive.csv")
 
# generate folder-level URL per show (one URL per unique date+location)
df["OneDrive URL"] = df["File Path"].apply(
    lambda p: local_path_to_onedrive_url(str(p)) if pd.notna(p) else None
)
 
df.to_csv("band_archive.csv", index=False)
print(f"Done. {df['OneDrive URL'].notna().sum()} URLs written.")
