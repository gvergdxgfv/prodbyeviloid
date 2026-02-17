"""
YouTube Clip Sourcer Module (AI-Powered)
=========================================
Uses Google Gemini to generate intelligent search queries matching
the beat's vibe, then searches YouTube with yt-dlp, ranks results
by relevance, and downloads the best clips.
"""

import logging
import subprocess
import json
import hashlib
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional

# AI generation handled by modules.ai_helper

import config
from modules.beat_parser import BeatInfo

logger = logging.getLogger(__name__)


@dataclass
class ClipInfo:
    """Info about a downloaded YouTube clip."""
    path: Path
    duration: float
    source_url: str
    title: str


def _generate_search_queries(beat_info: BeatInfo) -> List[str]:
    """
    Use Gemini to generate smart YouTube search queries
    tailored to the beat's genre, mood, and energy.
    """
    # Determine likely genre from BPM + energy for better prompting
    bpm = beat_info.bpm or 120
    energy = (beat_info.energy or "medium").lower()
    genre_hint = beat_info.genre or _guess_genre(bpm, energy)

    prompt = f"""You are a music video director sourcing clips for a beat video.
Given the beat info below, generate 8 YouTube search queries to find MUSIC VIDEO clips
of artists that match this beat's genre and vibe. We want clips of artists vibing,
performing, lifestyle shots — NOT stock footage or cinematography reels.

Beat info:
- Name: "{beat_info.name}"
- Genre: {genre_hint}
- Mood: {beat_info.mood or "vibes"}
- BPM: {bpm}
- Energy: {energy}
- Visual keywords already detected: {', '.join(beat_info.visual_keywords[:5]) if beat_info.visual_keywords else "none"}

Rules for search queries:
- 5-6 queries MUST be for actual MUSIC VIDEOS of artists matching this genre:
  * Trap / dark trap → Travis Scott, Playboi Carti, Future, Metro Boomin, Young Thug
  * Hood trap → Don Toliver, 21 Savage, Gunna, Lil Baby, Rod Wave
  * Drill → Pop Smoke, Central Cee, Fivio Foreign, Kay Flock
  * RnB / chill → The Weeknd, Daniel Caesar, SZA, Brent Faiyaz, Bryson Tiller
  * Lofi / chill → Joji, Mac Miller, Frank Ocean
  * Rage / hyperpop → Yeat, Ken Carson, Destroy Lonely, Lancey Foux
  * Boom bap → Kendrick Lamar, J. Cole, Joey Bada$$, JID
  * Electro / pop → Dua Lipa, The Weeknd, Daft Punk, Tame Impala
  Use queries like: "travis scott music video", "don toliver official video",
  "the weeknd mv", "playboi carti vibes", "21 savage music video"
- 2-3 queries for LIFESTYLE/VIBE footage matching the mood:
  * Dark → "dark night city driving vibes", "late night vibes aesthetic"
  * Chill → "summer vibes aesthetic", "golden hour vibes"
  * Hype → "lit concert crowd", "luxury lifestyle aesthetic"
- DO NOT search for "stock footage", "no copyright", "royalty free"
- Keep queries SHORT (3-7 words max)

Respond with EXACTLY 8 lines, one search query per line, nothing else:"""

    try:
        from modules import ai_helper
        text = ai_helper.generate_text(prompt)
        queries = [q.strip().strip('"').strip("'").strip("-").strip() for q in text.split("\n") if q.strip()]
        queries = [q for q in queries if len(q) > 5][:8]

        logger.info(f"   🤖 AI generated {len(queries)} search queries:")
        for q in queries:
            logger.info(f"      🔍 {q}")

        return queries

    except Exception as e:
        logger.warning(f"   ⚠️ AI query generation failed: {e}")
        # Fall back to visual keywords
        return _fallback_queries(beat_info)


def _guess_genre(bpm: int, energy: str) -> str:
    """Guess genre from BPM and energy level."""
    if bpm >= 140 and energy == "high":
        return "trap"
    elif bpm >= 140 and energy == "medium":
        return "drill"
    elif 120 <= bpm < 140 and energy == "high":
        return "hip hop"
    elif 100 <= bpm < 120 and energy == "high":
        return "rage"
    elif 90 <= bpm < 110 and energy in ("low", "medium"):
        return "rnb"
    elif bpm < 90:
        return "lofi"
    elif bpm >= 120 and energy == "medium":
        return "pop"
    return "hip hop"


# Genre -> artist/vibe mapping for fallback queries
_GENRE_QUERIES = {
    "trap":     ["travis scott music video", "playboi carti vibes", "future music video", "metro boomin type beat visual", "young thug official video", "dark trap aesthetic night city", "luxury car night vibes", "concert crowd lit"],
    "drill":    ["pop smoke music video", "central cee official video", "fivio foreign music video", "uk drill music video", "kay flock official video", "dark urban night shots", "city nightlife aesthetic", "drill rap vibes"],
    "hip hop":  ["kendrick lamar music video", "j cole official video", "jid music video", "joey badass vibes", "21 savage official video", "hip hop lifestyle aesthetic", "studio session rap vibes", "urban street culture"],
    "rnb":      ["the weeknd music video", "sza official video", "brent faiyaz vibes", "daniel caesar music video", "bryson tiller official video", "golden hour aesthetic", "moody night vibes", "romantic city lights"],
    "lofi":     ["joji music video", "mac miller vibes", "frank ocean aesthetic", "lofi girl animation", "chill vibes aesthetic sunset", "rainy window cozy night", "anime aesthetic vibes", "vintage film grain aesthetic"],
    "rage":     ["yeat music video", "ken carson official video", "destroy lonely vibes", "lancey foux music video", "hyperpop aesthetic glitch", "rave party lights", "cyberpunk city neon", "fast car racing aesthetic"],
    "pop":      ["dua lipa music video", "the weeknd starboy mv", "daft punk official video", "tame impala vibes", "post malone music video", "neon lights party aesthetic", "summer vibes beach", "colorful aesthetic dance"],
}


def _fallback_queries(beat_info: BeatInfo) -> List[str]:
    """Generate smart search queries without AI, based on audio analysis."""
    bpm = beat_info.bpm or 120
    energy = (beat_info.energy or "medium").lower()
    genre = beat_info.genre or _guess_genre(bpm, energy)

    # Get genre-specific queries
    queries = list(_GENRE_QUERIES.get(genre, _GENRE_QUERIES["hip hop"]))

    # Add visual keyword queries if available
    if beat_info.visual_keywords:
        for kw in beat_info.visual_keywords[:2]:
            queries.insert(0, f"{kw} music video aesthetic")

    logger.info(f"   🎯 Fallback queries (genre={genre}, bpm={bpm}, energy={energy})")
    return queries[:8]


def _rank_results_with_ai(videos: List[dict], beat_info: BeatInfo, max_clips: int) -> List[dict]:
    """
    Use Gemini to rank/filter search results by relevance to the beat.
    Picks the best clips from all search results.
    """
    if len(videos) <= max_clips:
        return videos

    # AI ranking via ai_helper

    # Build a list of video titles for Gemini to rank
    video_list = "\n".join(
        f"{i+1}. \"{v['title']}\" (duration: {v.get('duration', '?')}s)"
        for i, v in enumerate(videos[:20])  # Cap at 20 for prompt size
    )

    prompt = f"""You are selecting video clips for a music beat video.

Beat info:
- Genre: {beat_info.genre or "hip hop"}
- Mood: {beat_info.mood or "vibes"}
- Energy: {beat_info.energy}
- BPM: {beat_info.bpm}

Here are the available YouTube clips:
{video_list}

Select the {max_clips} BEST clips for this beat. Consider:
- PREFER: Music videos with artists vibing, performing, lifestyle shots
- PREFER: Clips that match the genre's visual aesthetic
- GOOD: Concert footage, music video scenes, artist lifestyle content
- OK: Cinematic/atmospheric footage that matches the mood
- AVOID: tutorials, podcasts, reaction videos, lyric videos, audio-only uploads

Respond with ONLY the numbers of the {max_clips} best clips, comma-separated. Example: 1, 4, 7, 2, 5"""

    try:
        from modules import ai_helper
        text = ai_helper.generate_text(prompt)

        # Parse the numbers
        selected_indices = []
        for part in text.replace(",", " ").split():
            part = part.strip().rstrip(".")
            try:
                idx = int(part) - 1  # Convert 1-indexed to 0-indexed
                if 0 <= idx < len(videos):
                    selected_indices.append(idx)
            except ValueError:
                continue

        if selected_indices:
            ranked = [videos[i] for i in selected_indices[:max_clips]]
            logger.info(f"   🤖 Gemini ranked and selected {len(ranked)} best clips")
            return ranked

    except Exception as e:
        logger.warning(f"   ⚠️ Gemini ranking failed, using default order: {e}")

    return videos[:max_clips]


def _search_youtube(query: str, max_results: int = 5) -> List[dict]:
    """
    Search YouTube using yt-dlp and return video metadata.
    """
    logger.info(f"🔍 Searching YouTube: '{query}'")

    cmd = [
        "yt-dlp",
        f"ytsearch{max_results}:{query}",
        "--dump-json",
        "--no-download",
        "--no-warnings",
        "--flat-playlist",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            encoding="utf-8",
            errors="replace",
        )

        videos = []
        for line in result.stdout.strip().split("\n"):
            if line.strip():
                try:
                    data = json.loads(line)
                    videos.append({
                        "url": data.get("url") or data.get("webpage_url") or f"https://www.youtube.com/watch?v={data.get('id', '')}",
                        "title": data.get("title", "Unknown"),
                        "duration": data.get("duration", 0),
                        "id": data.get("id", ""),
                    })
                except json.JSONDecodeError:
                    continue

        logger.info(f"   Found {len(videos)} result(s)")
        return videos

    except subprocess.TimeoutExpired:
        logger.warning(f"   ⚠️ YouTube search timed out for: {query}")
        return []
    except Exception as e:
        logger.error(f"   ❌ YouTube search failed: {e}")
        return []


def _download_clip(
    video_url: str,
    output_dir: Path,
    clip_name: str,
    segment_duration: int = 10,
) -> Optional[Path]:
    """
    Download a segment of a YouTube video using yt-dlp.
    Downloads only the first `segment_duration` seconds.
    """
    url_hash = hashlib.md5(video_url.encode()).hexdigest()[:8]
    output_path = output_dir / f"{clip_name}_{url_hash}.mp4"

    if output_path.exists():
        logger.info(f"   ⏭️ Already cached: {output_path.name}")
        return output_path

    logger.info(f"   ⬇️ Downloading clip: {video_url}")

    cmd = [
        "yt-dlp",
        video_url,
        "-o", str(output_path),
        "--download-sections", f"*0:00-0:{segment_duration:02d}",
        "-f", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best",
        "--merge-output-format", "mp4",
        "--no-playlist",
        "--no-write-thumbnail",
        "--no-write-description",
        "--no-write-info-json",
        "--no-write-comments",
        "--no-warnings",
        "--quiet",
        "--progress",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            encoding="utf-8",
            errors="replace",
        )

        if output_path.exists():
            logger.info(f"   ✅ Downloaded: {output_path.name}")
            return output_path
        else:
            for ext in [".mp4", ".mkv", ".webm"]:
                alt = output_path.with_suffix(ext)
                if alt.exists():
                    return alt

            logger.warning(f"   ⚠️ Download produced no output file")
            if result.stderr:
                logger.debug(f"   stderr: {result.stderr[:200]}")
            return None

    except subprocess.TimeoutExpired:
        logger.warning(f"   ⚠️ Download timed out: {video_url}")
        return None
    except Exception as e:
        logger.error(f"   ❌ Download failed: {e}")
        return None


def _get_video_duration(filepath: Path) -> float:
    """Get the duration of a downloaded video file using ffprobe."""
    try:
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            str(filepath),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        data = json.loads(result.stdout)
        return float(data.get("format", {}).get("duration", 0))
    except Exception:
        return 0.0


def source_clips(beat_info: BeatInfo, dry_run: bool = False) -> List[ClipInfo]:
    """
    AI-powered clip sourcing: uses Gemini to generate smart search queries,
    searches YouTube, ranks results by relevance, and downloads the best clips.

    Args:
        beat_info: Parsed beat metadata with visual keywords
        dry_run: If True, only search but don't download

    Returns:
        List of ClipInfo for downloaded clips
    """
    clips: List[ClipInfo] = []
    clip_dir = config.CLIPS_DIR / beat_info.filename
    clip_dir.mkdir(parents=True, exist_ok=True)

    max_clips = config.MAX_CLIPS_PER_BEAT
    segment_dur = config.CLIP_SEGMENT_DURATION

    # ── Step 1: Generate smart search queries via Gemini ──
    logger.info("🤖 Generating AI-powered search queries...")
    search_queries = _generate_search_queries(beat_info)

    # ── Step 2: Search YouTube for each query ────────────
    all_videos = []
    seen_ids = set()

    for query in search_queries:
        results = _search_youtube(query, max_results=3)

        for video in results:
            vid_id = video.get("id", "")
            if vid_id and vid_id not in seen_ids:
                seen_ids.add(vid_id)
                all_videos.append(video)

        if len(all_videos) >= max_clips * 3:
            break

    # Filter to reasonable duration videos
    all_videos = [v for v in all_videos if v.get("duration", 0) >= segment_dur or v.get("duration", 0) == 0]

    if dry_run:
        logger.info(f"🏃 DRY RUN — Found {len(all_videos)} candidate clips:")
        for v in all_videos[:max_clips]:
            logger.info(f"   📹 {v['title']} — {v['url']}")
        return []

    # ── Step 3: Rank results with AI ─────────────────────
    if len(all_videos) > max_clips:
        logger.info(f"🤖 Ranking {len(all_videos)} clips by relevance...")
        best_videos = _rank_results_with_ai(all_videos, beat_info, max_clips)
    else:
        best_videos = all_videos[:max_clips]

    # ── Step 4: Download selected clips ──────────────────
    # ── Step 4: Download selected clips (Parallel) ──────
    import concurrent.futures

    def _download_task(video_data):
        """Helper to download a single clip and return ClipInfo."""
        path = _download_clip(
            video_data["url"],
            clip_dir,
            beat_info.filename,
            segment_dur,
        )
        if path and path.exists():
            duration = _get_video_duration(path)
            # Return ClipInfo directly
            return ClipInfo(
                path=path,
                duration=duration,
                source_url=video_data["url"],
                title=video_data["title"]
            )
        return None

    logger.info(f"🚀 Downloading {len(best_videos)} clips in parallel (workers=4)...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_download_task, v) for v in best_videos]
        for future in concurrent.futures.as_completed(futures):
            try:
                result = future.result()
                if result:
                    clips.append(result)
            except Exception as e:
                logger.error(f"   ❌ Parallel download task failed: {e}")

    logger.info(f"📦 Sourced {len(clips)} clip(s) for '{beat_info.name}'")
    return clips
