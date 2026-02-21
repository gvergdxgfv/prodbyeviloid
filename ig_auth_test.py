import requests
import config

print("--------------------------------------------------")
print("🔍 Diagnosing Instagram '2207076' / Account Linkage")
print("--------------------------------------------------")

config.load_api_keys()

if not config.IG_ACCESS_TOKEN:
    print("❌ Error: IG_ACCESS_TOKEN is missing")
    exit(1)

token = config.IG_ACCESS_TOKEN
base_url = "https://graph.facebook.com/v21.0"

try:
    print("\n[Step 1] Fetching your Facebook Pages...")
    pages_url = f"{base_url}/me/accounts"
    resp = requests.get(pages_url, params={"access_token": token})
    data = resp.json()
    
    if "data" not in data or len(data["data"]) == 0:
        print("❌ No Facebook Pages found! You MUST link your IG to a FB Page.")
        print(data)
        exit(1)
        
    for page in data["data"]:
        page_id = page["id"]
        page_name = page["name"]
        print(f"\n   Found Page: '{page_name}' (ID: {page_id})")
        
        print(f"   [Step 2] Checking for linked Instagram Professional Account...")
        ig_url = f"{base_url}/{page_id}?fields=instagram_business_account"
        ig_resp = requests.get(ig_url, params={"access_token": token})
        ig_data = ig_resp.json()
        
        if "instagram_business_account" in ig_data:
            real_ig_id = ig_data["instagram_business_account"]["id"]
            print(f"   ✅ SUCCESS! Linked Instagram ID string is: {real_ig_id}")
            
            if real_ig_id != config.IG_USER_ID:
                print(f"\n🚨🚨 CRITICAL MISMATCH! 🚨🚨")
                print(f"Your .env file has IG_USER_ID={config.IG_USER_ID}")
                print(f"The actual Graph API requires IG_USER_ID={real_ig_id}")
                print("\nTo fix the upload error, please UPDATE your .env file to use the new ID above.")
            else:
                print("   (This matches your .env perfectly.)")
                print("   If uploads still fail, it's NOT an Auth error. Ngrok's free tier HTML warning page is blocking Meta.")
        else:
            print("   ❌ No Instagram Professional Account linked to this page.")
            
except Exception as e:
    print(f"Oops: {e}")
