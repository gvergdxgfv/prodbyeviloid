import sys
from pathlib import Path

import logging
logging.basicConfig(level=logging.INFO)

print("--------------------------------------------------")
print("🎬 Testing YouTube Data API v3 OAuth2 Flow")
print("--------------------------------------------------")

try:
    from modules.yt_uploader import _get_authenticated_service
    import config
    
    # Ensure config loads the paths correctly
    config.validate()
    
    # This will trigger the browser popup if the token doesn't exist or is expired
    print("\nLooking for client_secrets.json...")
    youtube_service = _get_authenticated_service()
    
    if youtube_service:
        print("\n✅ SUCCESS! YouTube API Authentication complete.")
        print(f"The token was saved to {config.PROJECT_ROOT / config.YT_TOKEN_FILE}")
        print("You can now safely upload to YouTube from the Telegram Bot!")
    else:
        print("\n❌ FAILED. Could not authenticate with YouTube.")
        
except Exception as e:
    print(f"\n❌ Error during authentication test: {e}")
