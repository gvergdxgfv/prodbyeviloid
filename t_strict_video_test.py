import os
import requests
from dotenv import load_dotenv

load_dotenv()

IG_USER_ID = os.getenv("IG_USER_ID")
IG_ACCESS_TOKEN = os.getenv("IG_ACCESS_TOKEN")
GRAPH_API_BASE = "https://graph.facebook.com/v18.0"

def test_video_post():
    endpoint = f"{GRAPH_API_BASE}/{IG_USER_ID}/media"
    
    # We will just try a tiny 1-second public MP4 file to rule out local Ngrok issues
    video_url = "https://storage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4"
    
    params = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": "Testing API video upload #test",
        "share_to_feed": "true",
        "access_token": IG_ACCESS_TOKEN
    }
    
    print(f"Testing POST to {endpoint}")
    print(f"Testing with a public video URL: {video_url}")
    
    resp = requests.post(endpoint, data=params)
    data = resp.json()
    
    print(f"Response Status: {resp.status_code}")
    if "id" in data:
        print(f"✅ Success! Container ID: {data['id']}")
    else:
         print(f"❌ Failed: {data}")

test_video_post()
