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
    tailored to the beat's genre, mood, and dynamically extracted energy.
    """
    import random
    
    bpm = beat_info.bpm or 120
    energy = (beat_info.energy or "medium").lower()
    brightness = beat_info.brightness or "neutral"
    rhythm = beat_info.rhythm or "straight"
    genre_hint = beat_info.genre or _guess_genre(bpm, energy)

    # Seed the AI to ensure varied results every single execution
    random_seed = random.randint(1000, 9999)

    prompt = f"""You are a music video director sourcing clips for a beat video.
Given the audio analysis below, generate 7 UNIQUE YouTube search queries to find clips that match this beat's vibe.

Beat info:
- Genre: {genre_hint}
- Mood: {beat_info.mood or "vibes"}
- BPM: {bpm}
- Timbre: {brightness.upper()} (Dark = bass heavy/gritty | Bright = synths/melodic)
- Rhythm: {rhythm.upper()} (Bouncy = syncopated/trap | Straight = 4-on-the-floor)
- Energy: {energy.upper()}
- Visual keywords: {', '.join(beat_info.visual_keywords[:5]) if getattr(beat_info, 'visual_keywords', None) else "none"}

CRITICAL RULES [Seed: {random_seed}]:
1. ARTIST MUSIC VIDEO QUERIES (4 queries): Pick 4 DIFFERENT artists that fit this genre/timbre. Search specifically for their MUSIC VIDEOS — NOT concerts, NOT podcasts, NOT interviews.
   - GOOD: "[Artist] music partyingist] music clip", "[Artist] visual"
   - BAD: "[Artist] concert", "[Artist] interview", "[Artist] podcast", "[Artist] reaction"
   - Vary the artists every run — don't always use the same names.
2. CINEMATIC B-ROLL (3 queries): Pure visual/aesthetic clips that strictly match the Timbre and Energy:
   - DARK+BOUNCY: "gritty neon city timelapse", "rain slick streets cinematic"
   - DARK+STRAIGHT: "dark fog forest 4k", "industrial urban night aesthetic"
   - BRIGHT+BOUNCY: "vibrant street graffiti slow motion", "colorful city rooftop"
   - BRIGHT+STRAIGHT: "ocean waves drone 4k", "mountain sunrise timelapse"
3. DO NOT search for: stock footage, royalty free, no copyright, podcast, reaction, compilation.
4. Keep queries SHORT (3-6 words max).

Respond with EXACTLY 7 lines, one search query per line, nothing else:"""



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
    "trap":     ["travis scott concert lit", "future music video", "playboi carti partying", "metro boomin studio session", "fast car night racing aesthetic", "luxury lifestyle vibe"],
    "drill":    ["pop smoke music video", "central cee concert", "chief keef vibes", "night city driving POV", "dirt bike riding aesthetic"],
    "hip hop":  ["j cole studio session", "kendrick lamar performing", "asap rocky music video", "old school hip hop aesthetic", "skateboarding city vibes"],
    "rnb":      ["don toliver partying", "the weeknd music video", "brent faiyaz studio", "late night city driving aesthetic", "moody club lights aesthetic"],
    "lofi":     ["joji music video", "mac miller studio session", "post malone sad visual", "chill anime aesthetic loop", "rainy night drive aesthetic"],
    "rage":     ["yeat concert moshpit", "ken carson performing", "playboi carti lit", "fast car racing neon", "underground rave aesthetic"],
    "pop":      ["the weeknd starboy mv", "post malone partying", "dua lipa concert", "party crowd lit aesthetic", "sunset beach driving"],
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


# Keywords that indicate a clip is NOT useful for a music video
_BAD_CLIP_KEYWORDS = [
    "podcast", "interview", "reaction", "react", "review", "explained",
    "full album", "album", "lyrics", "lyric video", "documentary", 
    "behind the scenes", "making of", "vlog", "compilation", "news",
    "commentary", "essay", "discussion", "analysis", "breakdown",
    "watch party", "piano tutorial", "guitar lesson", "tutorial",
    "highlights reel", "best moments", "top 10", "ranking",
]

def _is_good_clip(video: dict) -> bool:
    """Return True if the video is suitable for a music video (not a podcast/interview/reaction)."""
    title = (video.get("title") or "").lower()
    return not any(kw in title for kw in _BAD_CLIP_KEYWORDS)




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
    except KeyboardInterrupt:
        # Python 3.14 on Windows raises KeyboardInterrupt on subprocess timeout
        logger.warning(f"   ⚠️ YouTube search interrupted (timeout) for: {query}")
        return []
    except Exception as e:
        logger.error(f"   ❌ YouTube search failed: {e}")
        return []


def _download_clip(
    video_url: str,
    output_dir: Path,
    clip_name: str,
    segment_duration: int = 10,
    video_duration: float = 0.0,
) -> Optional[Path]:
    """
    Download a random middle segment of a YouTube video using yt-dlp.
    Avoids intros and outros by calculating a safe start range.
    """
    import random
    url_hash = hashlib.md5(video_url.encode()).hexdigest()[:8]
    
    # Calculate safe random start time to skip boring intros
    start_sec = 0
    if video_duration > segment_duration * 3:
        min_start = int(video_duration * 0.15)
        max_start = int(video_duration * 0.85) - segment_duration
        if max_start > min_start:
            start_sec = random.randint(min_start, max_start)

    end_sec = start_sec + segment_duration
    output_path = output_dir / f"{clip_name}_{url_hash}_{start_sec}s.mp4"

    if output_path.exists():
        logger.info(f"   ⏭️ Already cached: {output_path.name}")
        return output_path

    logger.info(f"   ⬇️ Downloading clip: {video_url} (segment {start_sec}s - {end_sec}s)")

    cmd = [
        "yt-dlp",
        video_url,
        "-o", str(output_path),
        "--download-sections", f"*{start_sec}-{end_sec}",
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


def source_clips(beat_info: BeatInfo, dry_run: bool = False, max_clips: int = 5) -> List[ClipInfo]:
    """
    AI-powered clip sourcing: uses Gemini to generate smart search queries,
    searches YouTube, ranks results by relevance, and downloads the best clips.

    Args:
        beat_info: Parsed beat metadata with visual keywords
        dry_run: If True, only search but don't download
        max_clips: Maximum number of clips to source (default 5)

    Returns:
        List of ClipInfo for downloaded clips
    """
    clips: List[ClipInfo] = []
    clip_dir = config.CLIPS_DIR / beat_info.filename
    clip_dir.mkdir(parents=True, exist_ok=True)

    if not max_clips or max_clips == config.MAX_CLIPS_PER_BEAT:
        # User requested dynamic scaling: e.g., 10 clips per 60 seconds of audio
        # We ensure a minimum floor of 5 clips just in case the audio track is very short.
        calculated_clips = int((beat_info.duration / 60.0) * 10)
        max_clips = max(5, calculated_clips)
        logger.info(f"⏱️ Track duration is {beat_info.duration:.1f}s. Dynamically scaling to source {max_clips} YouTube clips.")

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
    all_videos = [v for v in all_videos if (v.get("duration") or 0) >= segment_dur or (v.get("duration") or 0) == 0]

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
            video_url=video_data["url"],
            output_dir=clip_dir,
            clip_name=beat_info.filename,
            segment_duration=segment_dur,
            video_duration=video_data.get("duration", 0.0)
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
