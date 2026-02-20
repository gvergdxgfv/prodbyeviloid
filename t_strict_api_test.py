import os
import requests
from dotenv import load_dotenv

load_dotenv()

IG_USER_ID = os.getenv("IG_USER_ID")
IG_ACCESS_TOKEN = os.getenv("IG_ACCESS_TOKEN")
GRAPH_API_BASE = "https://graph.facebook.com/v21.0"

def test_media_post():
    endpoint = f"{GRAPH_API_BASE}/{IG_USER_ID}/media"
    
    # We will just try an image first to rule out Video processing issues / Ngrok issues
    image_url = "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e0/SNice.svg/1200px-SNice.svg.png"
    
    params = {
        "image_url": image_url,
        "caption": "Testing API #test",
         "access_token": IG_ACCESS_TOKEN
    }
    
    print(f"Testing POST to {endpoint}")
    print("Testing with a public image URL first...")
    
    resp = requests.post(endpoint, data=params)
    data = resp.json()
    
    print(f"Response Status: {resp.status_code}")
    if "id" in data:
        print(f"✅ Success! Container ID: {data['id']}")
    else:
         print(f"❌ Failed: {data}")
         
    # Let's also check permissions
    perm_url = f"{GRAPH_API_BASE}/me/permissions"
    perm_resp = requests.get(perm_url, params={"access_token": IG_ACCESS_TOKEN})
    print("\n--- Token Permissions ---")
    if "data" in perm_resp.json():
         for p in perm_resp.json()["data"]:
              if p.get("status") == "granted":
                   print(f"✅ {p.get('permission')}")
              else:
                   print(f"❌ {p.get('permission')} (DECLINED)")
    else:
         print(f"Could not load permissions: {perm_resp.json()}")

test_media_post()
