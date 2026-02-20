
import os
import sys
import socket
import requests
from dotenv import load_dotenv
from pyngrok import ngrok, conf

# Load .env
load_dotenv()

IG_ACCESS_TOKEN = os.getenv("IG_ACCESS_TOKEN")
PUBLIC_VIDEO_HOST = os.getenv("PUBLIC_VIDEO_HOST", "auto")
NGROK_AUTHTOKEN = os.getenv("NGROK_AUTHTOKEN")

def check_ngrok():
    print("Checking Ngrok Configuration...")
    if not NGROK_AUTHTOKEN:
        print("❌ NGROK_AUTHTOKEN is missing in .env")
        print("   Please sign up at ngrok.com, get a token, and add it to .env")
        return False
    
    print(f"✅ Ngrok token found (starts with {NGROK_AUTHTOKEN[:4]}...)")
    
    try:
        conf.get_default().auth_token = NGROK_AUTHTOKEN
        print("   🚀 Attempting to start a test tunnel...")
        url = ngrok.connect(8000, bind_tls=True).public_url
        print(f"   ✅ Tunnel successfully established! Public URL: {url}")
        print("   🔌 Closing test tunnel...")
        ngrok.disconnect(url)
        return True
    except Exception as e:
        print(f"   ❌ Failed to start ngrok tunnel: {e}")
        return False

def check_ip():
    # ... (rest of the function is same, but we can simplify since we rely on ngrok now)
    print(f"Configured PUBLIC_VIDEO_HOST: {PUBLIC_VIDEO_HOST}")
    
    if PUBLIC_VIDEO_HOST == "auto":
        print("ℹ️ Mode is 'auto'. Checking if we need ngrok...")
        # Check local IP just for info
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            print(f"   Local IP: {ip}")
            if ip.startswith("192.168.") or ip.startswith("10."):
                print("   👉 Local IP detected. Ngrok usage is HIGHLY RECOMMENDED.")
        except:
             pass
    else:
        print(f"ℹ️ Custom host configured: {PUBLIC_VIDEO_HOST}")


def check_token():
    if not IG_ACCESS_TOKEN:
        print("❌ IG_ACCESS_TOKEN is missing in .env")
        return

    print(f"Checking IG Token (length: {len(IG_ACCESS_TOKEN)})...")
    
    url = "https://graph.facebook.com/v21.0/me/accounts"
    params = {
        "fields": "name,instagram_business_account{id,username}",
        "access_token": IG_ACCESS_TOKEN.strip()
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if "error" in data:
            print(f"❌ Token Validation Failed: {data['error']['message']}")
            print(f"   Error Details: {data}")
        elif "data" in data:
            print(f"✅ Token Verified! Found Facebook Pages/Accounts:")
            found_ig = False
            for page in data["data"]:
                print(f"   - Facebook Page: {page.get('name')} (ID: {page.get('id')})")
                ig_info = page.get('instagram_business_account')
                if ig_info:
                    print(f"     ✅ Linked Instagram: @{ig_info.get('username')} (ID: {ig_info.get('id')})")
                    if str(ig_info.get('id')) == os.getenv("IG_USER_ID"):
                        print("        🎯 Matches IG_USER_ID in .env!")
                    else:
                        print(f"        ⚠️ Warning: IG_USER_ID in .env is {os.getenv('IG_USER_ID')}, but found {ig_info.get('id')}")
                    found_ig = True
                else:
                    print("     ❌ No Instagram Business/Creator account linked to this page.")
            if not found_ig:
                print("⚠️ No linked Instagram account found. Make sure your Instagram is a Professional Account and linked to a Facebook Page.")
        else:
            print(f"❓ Unexpected response: {data}")
    except Exception as e:
        print(f"❌ Request failed: {e}")

if __name__ == "__main__":
    print("--- DIAGNOSTIC START ---")
    check_ip()
    print("-" * 20)
    ngrok_ok = check_ngrok()
    print("-" * 20)
    check_token()
    print("--- DIAGNOSTIC END ---")
