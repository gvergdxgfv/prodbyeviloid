"""
Instagram Uploader Module
==========================
Uploads rendered videos to Instagram as Reels using the Graph API.
Uses multiple CDN fallback services to stage the video publicly so
the Meta API crawler can access it.
"""

import logging
import time
import threading
import socket
import http.server
import urllib.request
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import requests

import config
from modules.metadata_gen import ReelMetadata

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"


def _transcode_for_instagram(video_path: Path) -> Path:
    """
    Re-encode the video to exact Instagram Reels specifications using CPU (libx264).
    This fixes Meta error 2207076 which is caused by NVENC-encoded files
    that don't meet Instagram's strict codec/container requirements.

    Instagram Reels requirements:
    - Container: MP4 with moov atom at start (+faststart)
    - Video: H264, yuv420p, baseline/main profile, closed GOP, no B-frames
    - Audio: AAC, 128kbps, 44.1kHz, stereo
    - Pixel format: yuv420p (no 4:2:2 or 4:4:4)
    """
    suffix = "_ig.mp4"
    out_path = video_path.with_name(video_path.stem + suffix)

    if out_path.exists():
        logger.info(f"   ♻️ Already transcoded: {out_path.name}")
        return out_path

    logger.info(f"   🔄 Transcoding to Instagram specs: {out_path.name}...")

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        # Video: H264 baseline, closed GOP, no B-frames, yuv420p
        "-c:v", "libx264",
        "-profile:v", "baseline",
        "-level", "3.1",
        "-pix_fmt", "yuv420p",
        "-g", "30",           # keyframe every 30 frames (closed GOP)
        "-keyint_min", "30",
        "-bf", "0",           # no B-frames
        "-crf", "23",
        "-preset", "fast",
        # Audio: AAC 128kbps stereo 44.1kHz
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar", "44100",
        "-ac", "2",
        # Put moov atom at start for streaming
        "-movflags", "+faststart",
        str(out_path),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            logger.error(f"   ❌ Transcode failed: {result.stderr[-500:]}")
            return video_path  # Return original if transcode fails
        size_mb = out_path.stat().st_size / (1024 * 1024)
        logger.info(f"   ✅ Transcoded: {out_path.name} ({size_mb:.1f} MB)")
        return out_path
    except Exception as e:
        logger.error(f"   ❌ Transcode error: {e}")
        return video_path


# ── CDN Staging ──────────────────────────────────────────────────────────────

def _try_tmpfiles(video_path: Path) -> Optional[str]:
    """Upload to tmpfiles.org (free, reliable for small files)."""
    try:
        logger.info("   🌐 Trying tmpfiles.org...")
        file_size_mb = video_path.stat().st_size / (1024 * 1024)
        timeout = min(500, max(180, int(file_size_mb * 30)))  # 30s/MB, min 3min, max 500s
        with open(video_path, "rb") as f:
            resp = requests.post(
                "https://tmpfiles.org/api/v1/upload",
                files={"file": f},
                timeout=timeout,
            )
        data = resp.json()
        if "data" in data and "url" in data["data"]:
            view_url = data["data"]["url"]
            dl_url = view_url.replace("tmpfiles.org/", "tmpfiles.org/dl/")
            logger.info(f"   ✅ tmpfiles.org: {dl_url}")
            return dl_url
        logger.warning(f"   ⚠️ tmpfiles.org unexpected response: {data}")
        return None
    except Exception as e:
        logger.warning(f"   ⚠️ tmpfiles.org failed: {e}")
        return None


def _try_0x0(video_path: Path) -> Optional[str]:
    """Upload to 0x0.st (no-nonsense file host, 512MB limit, 1yr retention)."""
    try:
        logger.info("   🌐 Trying 0x0.st...")
        file_size_mb = video_path.stat().st_size / (1024 * 1024)
        timeout = min(500, max(180, int(file_size_mb * 30)))
        with open(video_path, "rb") as f:
            resp = requests.post(
                "https://0x0.st",
                files={"file": f},
                timeout=timeout,
            )
        if resp.status_code == 200:
            url = resp.text.strip()
            if url.startswith("http"):
                logger.info(f"   ✅ 0x0.st: {url}")
                return url
        logger.warning(f"   ⚠️ 0x0.st returned {resp.status_code}: {resp.text[:200]}")
        return None
    except Exception as e:
        logger.warning(f"   ⚠️ 0x0.st failed: {e}")
        return None


def _try_fileio(video_path: Path) -> Optional[str]:
    """Upload to file.io (one-time download link, 2GB limit)."""
    try:
        logger.info("   🌐 Trying file.io...")
        file_size_mb = video_path.stat().st_size / (1024 * 1024)
        timeout = min(500, max(180, int(file_size_mb * 30)))
        with open(video_path, "rb") as f:
            resp = requests.post(
                "https://file.io",
                files={"file": f},
                data={"expires": "1h"},
                timeout=timeout,
            )
        data = resp.json()
        if data.get("success") and data.get("link"):
            url = data["link"]
            logger.info(f"   ✅ file.io: {url}")
            return url
        logger.warning(f"   ⚠️ file.io failed: {data}")
        return None
    except Exception as e:
        logger.warning(f"   ⚠️ file.io failed: {e}")
        return None


def _try_local_server(video_path: Path) -> Optional[str]:
    """
    Spin up a local HTTP server and expose it via a public tunnel (ngrok or similar).
    Falls back to the machine's LAN IP (useful if the server has a public IP).
    """
    try:
        logger.info("   🌐 Trying local HTTP server...")

        # Find a free port
        with socket.socket() as s:
            s.bind(("", 0))
            port = s.getsockname()[1]

        serve_dir = video_path.parent
        filename = video_path.name

        class _Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(serve_dir), **kwargs)
            def log_message(self, format, *args):
                pass  # suppress access logs

        server = http.server.HTTPServer(("0.0.0.0", port), _Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        # Try to get the public IP
        try:
            public_ip = urllib.request.urlopen("https://api.ipify.org", timeout=5).read().decode()
        except Exception:
            public_ip = socket.gethostbyname(socket.gethostname())

        url = f"http://{public_ip}:{port}/{filename}"
        logger.info(f"   ✅ Local server: {url}")
        logger.info(f"   ⚠️ Note: Only works if port {port} is publicly accessible")

        # Keep a reference so it's not garbage collected
        _try_local_server._servers = getattr(_try_local_server, "_servers", [])
        _try_local_server._servers.append(server)

        return url
    except Exception as e:
        logger.warning(f"   ⚠️ Local server failed: {e}")
        return None


def _stage_video_to_cloud(video_path: Path) -> Optional[str]:
    """
    Try multiple CDN services in order until one succeeds.
    Falls back to local HTTP server as last resort.
    """
    file_size_mb = video_path.stat().st_size / (1024 * 1024)
    logger.info(f"☁️ Staging {video_path.name} ({file_size_mb:.1f} MB) to cloud CDN for Meta...")

    # Try CDN services in order of reliability for large files
    for attempt in [_try_0x0, _try_fileio, _try_tmpfiles, _try_local_server]:
        url = attempt(video_path)
        if url:
            return url
        logger.info("   ↪️ Trying next CDN...")

    logger.error("   ❌ All CDN staging options failed.")
    return None


# ── Meta API ─────────────────────────────────────────────────────────────────

def _create_media_container(
    video_url: str,
    caption: str,
) -> Optional[str]:
    """
    Step 1: Create a media container for the Reel.
    Returns the container/creation ID.
    """
    endpoint = f"{GRAPH_API_BASE}/{config.IG_USER_ID}/media"

    params = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "share_to_feed": "true",
        "access_token": config.IG_ACCESS_TOKEN,
    }

    logger.info(f"📤 Creating media container w/ URL: {video_url}")
    try:
        resp = requests.post(endpoint, data=params, timeout=30)
        data = resp.json()

        if "id" in data:
            container_id = data["id"]
            logger.info(f"   ✅ Container created: {container_id}")
            return container_id
        else:
            logger.error(f"   ❌ Container creation failed. API Response: {data}")
            return None

    except Exception as e:
        logger.error(f"   ❌ API request failed: {e}")
        return None


def _check_container_status(container_id: str) -> tuple[str, str]:
    """
    Check the status of a media container.
    Returns: ('FINISHED', ''), ('ERROR', 'msg'), or ('IN_PROGRESS', '').
    """
    endpoint = f"{GRAPH_API_BASE}/{container_id}"
    params = {
        "fields": "status_code,status",
        "access_token": config.IG_ACCESS_TOKEN,
    }

    try:
        resp = requests.get(endpoint, params=params, timeout=15)
        data = resp.json()
        status_code = data.get("status_code", "UNKNOWN")
        error_msg = ""

        if status_code == "ERROR":
            status_info = data.get("status", {})
            logger.error(f"   ❌ Meta API Processing Error: {status_info}")
            if isinstance(status_info, dict):
                err_dict = status_info.get("errors", {})
                if isinstance(err_dict, dict) and "message" in err_dict:
                    error_msg = err_dict["message"]
                else:
                    error_msg = str(status_info)
            else:
                error_msg = str(status_info)

        return status_code, error_msg
    except Exception as e:
        logger.warning(f"   ⚠️ Status check failed: {e}")
        return "UNKNOWN", ""


def _publish_container(container_id: str) -> Optional[str]:
    """
    Step 2: Publish the media container as a Reel.
    Returns the published media ID.
    """
    endpoint = f"{GRAPH_API_BASE}/{config.IG_USER_ID}/media_publish"
    params = {
        "creation_id": container_id,
        "access_token": config.IG_ACCESS_TOKEN,
    }

    logger.info("📢 Publishing Reel...")

    try:
        resp = requests.post(endpoint, data=params, timeout=30)
        data = resp.json()

        if "id" in data:
            media_id = data["id"]
            logger.info(f"   ✅ Reel published! Media ID: {media_id}")
            return media_id
        else:
            error = data.get("error", {})
            logger.error(f"   ❌ Publish failed: {error.get('message', data)}")
            return None

    except Exception as e:
        logger.error(f"   ❌ Publish request failed: {e}")
        return None


# ── Public API ────────────────────────────────────────────────────────────────

def upload_to_instagram(
    video_path: Path,
    metadata: ReelMetadata,
    max_wait: int = 300,
) -> bool:
    """
    Upload a video to Instagram as a Reel.

    1. Stages video to a cloud CDN (tries 0x0.st, file.io, tmpfiles.org, local server)
    2. Creates a media container via Graph API
    3. Waits for Meta to process it
    4. Publishes the Reel

    Args:
        video_path: Path to the rendered .mp4 file
        metadata: Generated caption, hashtags, etc.
        max_wait: Max seconds to wait for IG processing

    Returns:
        True if upload succeeded, False otherwise
    """
    if not video_path.exists():
        logger.error(f"❌ Video file not found: {video_path}")
        return False

    if not config.IG_USER_ID or not config.IG_ACCESS_TOKEN:
        config.load_api_keys()

    # Transcode to exact Instagram Reels specs (fixes error 2207076)
    video_path = _transcode_for_instagram(video_path)

    # Stage to cloud
    video_url = _stage_video_to_cloud(video_path)
    if not video_url:
        return False


    try:
        container_id = _create_media_container(
            video_url=video_url,
            caption=metadata.full_caption,
        )

        if not container_id:
            return False

        # Wait for Meta to process
        logger.info("⏳ Waiting for Instagram to process the video...")
        start_time = time.time()

        while time.time() - start_time < max_wait:
            status, error_msg = _check_container_status(container_id)

            if status == "FINISHED":
                logger.info("   ✅ Processing complete!")
                break
            elif status == "ERROR":
                logger.error(f"   ❌ Instagram returned an error: {error_msg}")
                return False
            elif status == "EXPIRED":
                logger.error("   ❌ Media container expired")
                return False
            else:
                elapsed = int(time.time() - start_time)
                logger.info(f"   ⏳ Status: {status} ({elapsed}s elapsed)")
                time.sleep(10)
        else:
            logger.error(f"   ❌ Timed out after {max_wait}s waiting for processing")
            return False

        media_id = _publish_container(container_id)

        if media_id:
            logger.info(f"🎉 Reel published successfully! Media ID: {media_id}")
            return True
        else:
            return False

    except Exception as e:
        logger.error(f"   ❌ Network error during Instagram upload: {e}")
        return False
