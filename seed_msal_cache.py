# seed_msal_cache.py
import getpass
from supabase import create_client

url = input("Supabase URL: ").strip()
key = getpass.getpass("Service role key: ").strip()
sb = create_client(url, key)

cache = open(".msal_token_cache.bin").read()
sb.table("msal_cache").upsert({"id": 1, "cache": cache}).execute()
print("Seeded.")