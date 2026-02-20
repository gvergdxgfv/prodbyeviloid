"""
Configuration loader for the Beat-to-Instagram automation pipeline.
Reads from .env file and provides typed access to all settings.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
PROJECT_ROOT = Path(__file__).parent
load_dotenv(PROJECT_ROOT / ".env")


def _require(key: str) -> str:
    """Get a required env var or exit with a helpful message."""
    val = os.getenv(key)
    if not val or val.startswith("your-") or val.startswith("sk-your"):
        print(f"❌ Missing required config: {key}")
        print(f"   Please set it in your .env file (see .env.example)")
        sys.exit(1)
    return val.strip()


def _optional(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def _int(key: str, default: int) -> int:
    return int(os.getenv(key, str(default)))


# ── API Keys ──────────────────────────────────────────────
GEMINI_API_KEY: str = ""  # Loaded lazily when needed
IG_USER_ID: str = ""
IG_ACCESS_TOKEN: str = ""
OPENROUTER_API_KEY: str = ""

# ── Video Settings ────────────────────────────────────────
MAX_CLIPS_PER_BEAT: int = _int("MAX_CLIPS_PER_BEAT", 10)
CLIP_SEGMENT_DURATION: int = _int("CLIP_SEGMENT_DURATION", 10)
VIDEO_DURATION_MAX: int = _int("VIDEO_DURATION_MAX", 900)
VIDEO_WIDTH: int = _int("VIDEO_WIDTH", 1080)
VIDEO_HEIGHT: int = _int("VIDEO_HEIGHT", 1920)
HIGHLIGHT_DURATION: int = _int("HIGHLIGHT_DURATION", 30)
MAX_HIGHLIGHTS: int = _int("MAX_HIGHLIGHTS", 3)
PRODUCER_TAG: str = _optional("PRODUCER_TAG", "prodbyeviloid")

# ── Paths ─────────────────────────────────────────────────
BEATS_DIR: Path = PROJECT_ROOT / _optional("BEATS_DIR", "beats")
CLIPS_DIR: Path = PROJECT_ROOT / _optional("CLIPS_DIR", "clips")
OUTPUT_DIR: Path = PROJECT_ROOT / _optional("OUTPUT_DIR", "output")

# ── Public Hosting ────────────────────────────────────────
PUBLIC_VIDEO_HOST: str = _optional("PUBLIC_VIDEO_HOST", "auto")
NGROK_AUTHTOKEN: str = _optional("NGROK_AUTHTOKEN", "")


# ── Stable Diffusion Settings ─────────────────────────────
SD_WEBUI_URL: str = _optional("SD_WEBUI_URL", "http://127.0.0.1:7860")
SD_API_ENABLED: bool = os.getenv("SD_API_ENABLED", "False").lower() == "true"

# ── YouTube API ───────────────────────────────────────────
YT_CLIENT_SECRETS_FILE: str = _optional("YT_CLIENT_SECRETS_FILE", "client_secrets.json")
YT_TOKEN_FILE: str = _optional("YT_TOKEN_FILE", "yt_token.json")


def ensure_dirs():
    """Create required directories if they don't exist."""
    BEATS_DIR.mkdir(parents=True, exist_ok=True)
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def load_api_keys():
    """Load API keys (called when actually needed, not at import time)."""
    global GEMINI_API_KEY, IG_USER_ID, IG_ACCESS_TOKEN, OPENROUTER_API_KEY, PEXELS_API_KEY
    GEMINI_API_KEY = _require("GEMINI_API_KEY").strip()
    IG_USER_ID = _require("IG_USER_ID").strip()
    IG_ACCESS_TOKEN = _require("IG_ACCESS_TOKEN").strip()
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
    PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "").strip()


def load_openai_key_only():
    """Load just the Gemini key (for --no-upload mode)."""
    global GEMINI_API_KEY, OPENROUTER_API_KEY
    GEMINI_API_KEY = _require("GEMINI_API_KEY").strip()
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()


def validate():
    """Run all config validation checks."""
    ensure_dirs()
    if VIDEO_WIDTH <= 0 or VIDEO_HEIGHT <= 0:
        print("❌ VIDEO_WIDTH and VIDEO_HEIGHT must be positive integers")
        sys.exit(1)
    if VIDEO_DURATION_MAX <= 0 or VIDEO_DURATION_MAX > 900:
        print("❌ VIDEO_DURATION_MAX must be between 1 and 900 seconds")
        sys.exit(1)
    print(f"✅ Config loaded — beats: {BEATS_DIR}, output: {OUTPUT_DIR}")
