"""
Instagram Uploader Module
==========================
Uploads rendered videos to Instagram as Reels using the Graph API.
Includes a temporary HTTP server to serve the video publicly.
"""

import logging
import time
import threading
import http.server
import socketserver
import socket
from pathlib import Path
from typing import Optional

import requests
from pyngrok import ngrok, conf

import config
from modules.metadata_gen import ReelMetadata

logger = logging.getLogger(__name__)

# Instagram Content Publishing requires the Facebook Graph API base
GRAPH_API_BASE = "https://graph.facebook.com/v21.0"


class _VideoServer:
    """
    Temporary HTTP server to serve a single video file publicly.
    Instagram's Graph API requires a public URL to cURL the video from.
    """

    def __init__(self, video_path: Path, host: str = "0.0.0.0", port: int = 0):
        self.video_path = video_path
        self.host = host
        self.port = port
        self._server: Optional[socketserver.TCPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._tunnel_url: Optional[str] = None

    def start(self) -> str:
        """Start the server and return the URL to the video."""
        video_dir = str(self.video_path.parent)
        video_name = self.video_path.name

        handler = http.server.SimpleHTTPRequestHandler

        class QuietHandler(handler):
            def __init__(self, *args, directory=video_dir, **kwargs):
                super().__init__(*args, directory=directory, **kwargs)

            def log_message(self, format, *args):
                pass  # Suppress access logs

            def end_headers(self):
                self.send_header("Content-Type", "video/mp4")
                super().end_headers()

        self._server = socketserver.TCPServer((self.host, self.port), QuietHandler)
        self.port = self._server.server_address[1]

        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

        # Determine public URL
        public_host = config.PUBLIC_VIDEO_HOST
        
        # Configure ngrok auth if provided
        if config.NGROK_AUTHTOKEN:
            conf.get_default().auth_token = config.NGROK_AUTHTOKEN

        if public_host == "auto":
            # If we have an ngrok token, prefer ngrok for reliability
            if config.NGROK_AUTHTOKEN:
                try:
                    logger.info("   🚀 Starting ngrok tunnel...")
                    # bind_tls=True ensures we get an https URL
                    self._tunnel_url = ngrok.connect(self.port, bind_tls=True).public_url
                    public_host = self._tunnel_url
                    logger.info(f"   ✅ Ngrok tunnel established: {public_host}")
                except Exception as e:
                    logger.error(f"   ❌ Ngrok connection failed: {e}")
                    # Fallback to local IP logic below
                    pass

            # Fallback or if no token: Try to get the machine's IP
            if not self._tunnel_url:
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.connect(("8.8.8.8", 80))
                    ip = s.getsockname()[0]
                    s.close()
                except Exception:
                    ip = "127.0.0.1"
                public_host = f"http://{ip}:{self.port}"
                
        elif not public_host.startswith("http"):
            public_host = f"http://{public_host}:{self.port}"

        import urllib.parse
        encoded_name = urllib.parse.quote(video_name)
        url = f"{public_host}/{encoded_name}"
        logger.info(f"📡 Video server started at {url}. Waiting 3 seconds for tunnel to stabilize...")
        time.sleep(3) # Give ngrok and the local server a moment to start
        return url

    def stop(self):
        """Shut down the server."""
        if self._tunnel_url:
            try:
                ngrok.disconnect(self._tunnel_url)
                # optionally kill the ngrok process if you want to be clean
                # ngrok.kill() 
                logger.info("   🔌 Ngrok tunnel closed")
            except Exception as e:
                logger.error(f"   ⚠️ Error closing tunnel: {e}")
            self._tunnel_url = None

        if self._server:
            self._server.shutdown()
            logger.info("📡 Video server stopped")


def _create_media_container(
    video_url: str,
    caption: str,
    cover_url: Optional[str] = None,
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

    if cover_url and cover_url.startswith("http"):
        params["cover_url"] = cover_url

    logger.info(f"📤 Final Exact Params to Facebook: {params}")
    
    # Internal check: is the video server actually accessible right now?
    try:
        logger.info(f"🔍 Testing internal accessibility of {video_url}...")
        test_resp = requests.head(video_url, timeout=5)
        logger.info(f"🔍 Internal test status: {test_resp.status_code}")
    except Exception as e:
        logger.warning(f"⚠️ Internal test failed: {e}")

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


def _check_container_status(container_id: str) -> str:
    """
    Check the status of a media container.
    Returns: 'FINISHED', 'IN_PROGRESS', 'ERROR', or 'EXPIRED'.
    """
    endpoint = f"{GRAPH_API_BASE}/{container_id}"
    params = {
        "fields": "status_code,status",
        "access_token": config.IG_ACCESS_TOKEN,
    }

    try:
        resp = requests.get(endpoint, params=params, timeout=15)
        data = resp.json()
        status = data.get("status_code", "UNKNOWN")
        return status
    except Exception as e:
        logger.warning(f"   ⚠️ Status check failed: {e}")
        return "UNKNOWN"


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


def upload_to_instagram(
    video_path: Path,
    metadata: ReelMetadata,
    max_wait: int = 300,
) -> bool:
    """
    Upload a video to Instagram as a Reel.

    1. Starts a temporary HTTP server to serve the video
    2. Creates a media container via Graph API
    3. Waits for processing to finish
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

    # Ensure API keys are loaded
    if not config.IG_USER_ID or not config.IG_ACCESS_TOKEN:
        config.load_api_keys()

    # Start temporary video server
    server = _VideoServer(video_path)
    video_url = server.start()

    try:
        # Give server a moment to start
        time.sleep(1)

        # Step 1: Create container
        container_id = _create_media_container(
            video_url=video_url,
            caption=metadata.full_caption,
        )

        if not container_id:
            return False

        # Step 2: Wait for processing
        logger.info("⏳ Waiting for Instagram to process the video...")
        start_time = time.time()

        while time.time() - start_time < max_wait:
            status = _check_container_status(container_id)

            if status == "FINISHED":
                logger.info("   ✅ Processing complete!")
                break
            elif status == "ERROR":
                logger.error("   ❌ Instagram returned an error during processing")
                return False
            elif status == "EXPIRED":
                logger.error("   ❌ Media container expired")
                return False
            else:
                elapsed = int(time.time() - start_time)
                logger.info(f"   ⏳ Status: {status} ({elapsed}s elapsed)")
                time.sleep(10)  # Check every 10 seconds
        else:
            logger.error(f"   ❌ Timed out after {max_wait}s waiting for processing")
            return False

        # Step 3: Publish
        media_id = _publish_container(container_id)

        if media_id:
            logger.info(f"🎉 Reel published successfully! Media ID: {media_id}")
            return True
        else:
            return False

    finally:
        # Always stop the server
        server.stop()
