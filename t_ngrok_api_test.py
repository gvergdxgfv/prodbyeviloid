import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()

IG_USER_ID = os.getenv("IG_USER_ID")
IG_ACCESS_TOKEN = os.getenv("IG_ACCESS_TOKEN")
GRAPH_API_BASE = "https://graph.facebook.com/v21.0"

import socketserver
import http.server
import threading
from pyngrok import ngrok, conf

# Start a local simple server
PORT = 8000
Handler = http.server.SimpleHTTPRequestHandler
httpd = socketserver.TCPServer(("", PORT), Handler)
server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
server_thread.start()

# Start ngrok
try:
    if os.getenv("NGROK_AUTHTOKEN"):
         conf.get_default().auth_token = os.getenv("NGROK_AUTHTOKEN")
    tunnel = ngrok.connect(PORT, bind_tls=True)
    ngrok_url = tunnel.public_url
    print(f"✅ Started ngrok tunnel at: {ngrok_url}")
except Exception as e:
    print(f"❌ Could not start ngrok: {e}")
    exit(1)

video_url = f"{ngrok_url}/test_ig_video.mp4"

def test_video_post():
    endpoint = f"{GRAPH_API_BASE}/{IG_USER_ID}/media"
    
    params = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": "Testing Ngrok video URL #test",
        "share_to_feed": "true",
        "access_token": IG_ACCESS_TOKEN
    }
    
    print(f"Testing POST to {endpoint}")
    print(f"Testing with Ngrok URL: {video_url}")
    
    resp = requests.post(endpoint, data=params)
    data = resp.json()
    
    print(f"Response Status: {resp.status_code}")
    if "id" in data:
        print(f"✅ Success! Container ID: {data['id']}")
    else:
         print(f"❌ Failed: {data}")

test_video_post()
