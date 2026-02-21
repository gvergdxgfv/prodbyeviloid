"""
YouTube Shorts Uploader Module
===============================
Uploads rendered videos to YouTube as Shorts using the YouTube Data API v3.
Handles OAuth2 authentication with token persistence.
"""

import logging
import os
from pathlib import Path
from typing import Optional

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

import config
from modules.metadata_gen import ReelMetadata

logger = logging.getLogger(__name__)

# YouTube API scopes
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

# Maximum retry attempts
MAX_RETRIES = 3


def _get_authenticated_service():
    """
    Authenticate with YouTube Data API v3.

    First run triggers a browser-based OAuth2 flow.
    Subsequent runs use the saved refresh token.

    Returns:
        Authenticated YouTube API service object.
    """
    credentials = None
    token_file = config.PROJECT_ROOT / config.YT_TOKEN_FILE

    # Load saved credentials
    if token_file.exists():
        try:
            credentials = Credentials.from_authorized_user_file(
                str(token_file), SCOPES
            )
        except Exception as e:
            logger.warning(f"⚠️ Failed to load saved credentials: {e}")

    # Refresh or create new credentials
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            logger.info("🔄 Refreshing YouTube credentials...")
            try:
                credentials.refresh(Request())
            except Exception as e:
                logger.warning(f"⚠️ Token refresh failed: {e}")
                credentials = None

        if not credentials:
            secrets_file = config.PROJECT_ROOT / config.YT_CLIENT_SECRETS_FILE
            if not secrets_file.exists():
                logger.error(
                    f"❌ YouTube client secrets file not found: {secrets_file}\n"
                    f"   Download it from Google Cloud Console:\n"
                    f"   1. Go to https://console.cloud.google.com/apis/credentials\n"
                    f"   2. Create OAuth 2.0 Client ID (Desktop App)\n"
                    f"   3. Download the JSON and save as {secrets_file}"
                )
                return None

            logger.info("🔐 Starting YouTube OAuth2 flow (browser will open)...")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(secrets_file), SCOPES
            )
            credentials = flow.run_local_server(port=8080)

        # Save credentials for next time
        with open(str(token_file), "w") as f:
            f.write(credentials.to_json())
        logger.info(f"💾 YouTube credentials saved to {token_file}")

    return build("youtube", "v3", credentials=credentials)


def _build_shorts_metadata(
    metadata: ReelMetadata,
    beat_name: str,
    genre: str = "",
    bpm: float = 0,
) -> dict:
    """
    Build YouTube Shorts metadata from the existing ReelMetadata.

    Returns dict with 'snippet' and 'status' for the API call.
    """
    # Build title (max 100 chars)
    # Using the AI generated title, optimally appending #Shorts if not present and there is space
    title = metadata.yt_title
    if "#Shorts" not in title and len(title) + 8 <= 100:
        title += " #Shorts"
    title = title[:100]

    # Build description
    description = metadata.yt_description[:5000]  # YT max is 5000

    # Tags (max 500 chars total)
    tags = metadata.yt_tags[:20] if metadata.yt_tags else []
    if "Shorts" not in [t.lower() for t in tags]:
        tags.append("Shorts")

    return {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "10",  # Music category
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }


def upload_to_youtube(
    video_path: Path,
    metadata: ReelMetadata,
    beat_name: str = "",
    genre: str = "",
    bpm: float = 0,
) -> bool:
    """
    Upload a video to YouTube as a Short.

    Args:
        video_path: Path to the rendered .mp4 file
        metadata: Generated caption, hashtags, etc.
        beat_name: Display name of the beat
        genre: Beat genre
        bpm: Beats per minute

    Returns:
        True if upload succeeded, False otherwise
    """
    if not video_path.exists():
        logger.error(f"❌ Video file not found: {video_path}")
        return False

    # Authenticate
    youtube = _get_authenticated_service()
    if not youtube:
        return False

    # Build metadata
    yt_metadata = _build_shorts_metadata(metadata, beat_name, genre, bpm)

    logger.info(f"📤 Uploading to YouTube Shorts: {yt_metadata['snippet']['title']}")

    # Create media upload
    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=1024 * 1024 * 5,  # 5MB chunks
    )

    try:
        request = youtube.videos().insert(
            part="snippet,status",
            body=yt_metadata,
            media_body=media,
        )

        # Execute resumable upload
        response = None
        retry = 0

        while response is None:
            try:
                status, response = request.next_chunk()
                if status:
                    progress = int(status.progress() * 100)
                    logger.info(f"   📤 Upload progress: {progress}%")
            except Exception as e:
                retry += 1
                if retry > MAX_RETRIES:
                    logger.error(f"❌ Upload failed after {MAX_RETRIES} retries: {e}")
                    return False
                logger.warning(f"   ⚠️ Upload error, retrying ({retry}/{MAX_RETRIES}): {e}")
                continue

        if response:
            video_id = response.get("id", "unknown")
            logger.info(f"🎉 YouTube Short published! Video ID: {video_id}")
            logger.info(f"   🔗 https://youtube.com/shorts/{video_id}")
            return True
        else:
            logger.error("❌ Upload completed but no response received")
            return False

    except Exception as e:
        logger.error(f"❌ YouTube upload failed: {e}", exc_info=True)
        return False
