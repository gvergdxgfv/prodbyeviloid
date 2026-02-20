"""
Pexels Clip Sourcer Module
==========================
Sources high-quality, royalty-free vertical video from Pexels API.
Perfect for 'vibe' footage (cities, nature, abstract) without watermarks.
"""

import logging
import requests
import random
from pathlib import Path
from typing import List, Optional

import config
from modules.beat_parser import BeatInfo
from modules.youtube_sourcer import ClipInfo

logger = logging.getLogger(__name__)

PEXELS_API_URL = "https://api.pexels.com/videos/search"
MAX_RESULTS_PER_QUERY = 5

def search_pexels(query: str, orientation: str = "portrait", size: str = "medium") -> List[dict]:
    """
    Search Pexels API for videos.
    """
    if not config.PEXELS_API_KEY:
        logger.warning("⚠️ Pexels API Key not set. Skipping Pexels search.")
        return []

    headers = {"Authorization": config.PEXELS_API_KEY}
    params = {
        "query": query,
        "orientation": orientation,
        "size": size,
        "per_page": MAX_RESULTS_PER_QUERY,
        "min_duration": 5, 
        "max_duration": 60,
    }

    try:
        resp = requests.get(PEXELS_API_URL, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data.get("videos", [])
    except Exception as e:
        logger.error(f"❌ Pexels API error for '{query}': {e}")
        return []

def download_video(video_url: str, title: str) -> Optional[Path]:
    """
    Download a video file from a URL.
    """
    try:
        # Sanitize filename
        safe_title = "".join(c for c in title if c.isalnum() or c in (" ", "-", "_")).strip()
        filename = f"pexels_{safe_title[:50]}.mp4"
        output_path = config.CLIPS_DIR / filename
        
        if output_path.exists() and output_path.stat().st_size > 0:
            return output_path

        logger.info(f"   ⬇️ Downloading Pexels: {filename}...")
        
        with requests.get(video_url, stream=True, timeout=30) as r:
            r.raise_for_status()
            with open(output_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        
        return output_path
    except Exception as e:
        logger.warning(f"   ⚠️ Failed to download Pexels video: {e}")
        return None

def get_best_video_file(video_data: dict) -> Optional[str]:
    """
    Extract the best video file URL (HD quality, link).
    """
    video_files = video_data.get("video_files", [])
    if not video_files:
        return None

    # Prefer HD (1080p or 720p)
    best_file = None
    max_width = 0

    for vf in video_files:
        # We want link compatible with direct download
        if vf.get("quality") == "hd" and vf.get("width", 0) <= 1920:
             if vf.get("width", 0) > max_width:
                 max_width = vf["width"]
                 best_file = vf["link"]
    
    if not best_file and video_files:
        best_file = video_files[0]["link"]

    return best_file

def source_clips(beat_info: BeatInfo, max_clips: int = 3) -> List[ClipInfo]:
    """
    Source clips from Pexels based on beat beat_info.
    """
    if not config.PEXELS_API_KEY:
        return []

    logger.info("🎨 Sourcing detailed clips from Pexels...")

    # Generate Pexels-friendly queries
    # Pexels works best with simple 1-2 word visual terms
    queries = []
    
    # Use visual keywords from Gemini
    if beat_info.visual_keywords:
        queries.extend(beat_info.visual_keywords[:3])
    
    # Add genre-based vibe queries
    # We can reuse _guess_genre from youtube_sourcer if we move it to a shared util, 
    # but for now let's just use simple mappings based on keywords/mood
    mood = (beat_info.mood or "").lower()
    if "dark" in mood:
        queries.extend(["dark city", "neon night", "shadows"])
    elif "chill" in mood:
        queries.extend(["sunset", "ocean", "clouds", "nature"])
    elif "hype" in mood or "trap" in (beat_info.genre or ""):
        queries.extend(["money", "luxury car", "city lights", "party"])
    else:
        queries.extend(["abstract", "geometry", "ink", "smoke"])

    # Shuffle and limit
    random.shuffle(queries)
    selected_queries = queries[:3]

    sourced_clips = []
    seen_urls = set()

    for q in selected_queries:
        logger.info(f"   🔍 Pexels Search: '{q}'")
        videos = search_pexels(q)
        
        for v in videos:
            if len(sourced_clips) >= max_clips:
                break
                
            vid_id = v.get("id")
            if vid_id in seen_urls:
                continue
            seen_urls.add(vid_id)

            duration = v.get("duration", 0)
            url = get_best_video_file(v)
            if not url:
                continue

            path = download_video(url, f"{q}_{vid_id}")
            if path:
                clip_info = ClipInfo(
                    path=path,
                    duration=duration,
                    source_url=v.get("url", ""),
                    title=f"Pexels: {q}"
                )
                sourced_clips.append(clip_info)

    logger.info(f"   ✅ Sourced {len(sourced_clips)} Pexels clips")
    return sourced_clips
