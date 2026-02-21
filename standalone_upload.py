import time
import requests
import json
import config
from pathlib import Path

config.load_api_keys()

def upload_to_tmpfiles(filepath: Path) -> str:
    print(f"Uploading {filepath.name} to tmpfiles.org cloud staging...")
    with open(filepath, 'rb') as f:
        resp = requests.post("https://tmpfiles.org/api/v1/upload", files={'file': f})
    data = resp.json()
    if "data" in data and "url" in data["data"]:
        # tmpfiles returns a viewing URL: https://tmpfiles.org/12345/vid.mp4
        # Meta needs the direct download URL: https://tmpfiles.org/dl/12345/vid.mp4
        view_url = data["data"]["url"]
        dl_url = view_url.replace("tmpfiles.org/", "tmpfiles.org/dl/")
        print(f"✅ Cloud Staging URL: {dl_url}")
        return dl_url
    raise Exception(f"Cloud upload failed: {data}")

def test_upload():
    video_path = Path("output/mov_bbb.mp4")
    if not video_path.exists():
        print(f"❌ File not found: {video_path}")
        return

    test_video_url = upload_to_tmpfiles(video_path)
    print(f"Sending to Meta: {test_video_url}")
    
    endpoint = f"https://graph.facebook.com/v21.0/{config.IG_USER_ID}/media"
    params = {
        "media_type": "REELS",
        "video_url": test_video_url,
        "caption": "Test from API",
        "access_token": config.IG_ACCESS_TOKEN,
    }

    print("\nStep 1: Creating Media Container...")
    try:
        resp = requests.post(endpoint, data=params)
        data = resp.json()
        print(f"Response: {data}")
        
        if "id" in data:
            container_id = data["id"]
            print(f"✅ Container created: {container_id}")
            
            for _ in range(15):
                time.sleep(5)
                status_url = f"https://graph.facebook.com/v21.0/{container_id}?fields=status_code,status&access_token={config.IG_ACCESS_TOKEN}"
                s_resp = requests.get(status_url).json()
                print(f"Status: {s_resp}")
                
                if s_resp.get("status_code") == "FINISHED":
                    print("✅ Processing Complete! cloud staging fixes the error!")
                    break
                elif s_resp.get("status_code") == "ERROR":
                    print("❌ Meta rejected the video during processing!")
                    break
        else:
            print("❌ Container creation failed!")
            
    except Exception as e:
        print(f"❌ Exception: {e}")

if __name__ == "__main__":
    test_upload()
