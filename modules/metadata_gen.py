"""
AI Metadata Generator Module (Gemini)
======================================
Uses Google Gemini to generate Instagram & YouTube Shorts optimized
captions, hashtags, and cover frame suggestions for each video.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import List

import config
from modules.beat_parser import BeatInfo

logger = logging.getLogger(__name__)

# Genre → artist mapping for "[FREE] Artist Type Beat" titles
GENRE_ARTIST_MAP = {
    "trap": "Travis Scott",
    "dark trap": "Travis Scott",
    "drill": "Central Cee",
    "uk drill": "Central Cee",
    "hip hop": "Drake",
    "hiphop": "Drake",
    "boom bap": "J. Cole",
    "boombap": "J. Cole",
    "lofi": "Jorja Smith",
    "lo-fi": "Jorja Smith",
    "rnb": "The Weeknd",
    "r&b": "The Weeknd",
    "pop": "The Weeknd",
    "phonk": "Night Lovell",
    "afrobeat": "Burna Boy",
    "reggaeton": "Bad Bunny",
    "jersey": "Young Thug",
    "soul": "SZA",
    "ambient": "Frank Ocean",
    "edm": "Skrillex",
    "house": "Drake",
    "techno": "Travis Scott",
}


def _get_artist_for_genre(genre: str) -> str:
    """Return a well-known artist name matching the genre."""
    if not genre:
        return "Drake"
    genre_lower = genre.lower().strip()
    for key, artist in GENRE_ARTIST_MAP.items():
        if key in genre_lower:
            return artist
    return "Drake"


@dataclass
class ReelMetadata:
    """Generated metadata for Instagram Reel / YouTube Short."""
    caption: str
    hashtags: List[str]
    full_caption: str        # caption + hashtags combined (for IG)
    yt_title: str            # YouTube Shorts title
    yt_description: str      # YouTube Shorts description
    yt_tags: List[str]       # YouTube tags
    cover_timestamp: float   # Suggested timestamp for cover frame


def generate_metadata(beat_info: BeatInfo) -> ReelMetadata:
    """
    Generate platform-optimized metadata using AI (Gemini / OpenRouter fallback).

    Produces engaging captions and hashtags for both
    Instagram Reels and YouTube Shorts.
    """
    artist = _get_artist_for_genre(beat_info.genre)

    prompt = f"""You are a social media expert for a music producer called "prodbyeviloid".
Generate metadata for posting a beat video on Instagram Reels AND YouTube Shorts.

Beat info:
- Name: "{beat_info.name}"
- Genre: {beat_info.genre or "hip hop"}
- Mood: {beat_info.mood or "vibes"}
- BPM: {beat_info.bpm}
- Energy: {beat_info.energy}
- Duration: {beat_info.duration:.0f}s

Generate ALL of the following:

1. IG_CAPTION: An engaging, short Instagram caption (2-3 lines max) with emoji and a call-to-action.
   Make it feel authentic, not overly promotional. Include the beat name naturally.
   End with a CTA like "DM for exclusive beats 🔥" or "Link in bio for leases 💰".

2. IG_HASHTAGS: Exactly 25 relevant hashtags (no # symbol, comma-separated). Mix of:
   - Genre-specific (trap, drill, lofi, etc.)
   - Mood-specific (darktrap, chillvibes, etc.)
   - Music production (beatmaker, producer, typebeat, etc.)
   - Discovery (newmusic, unsigned, explorepage, viral, etc.)
   - Platform (reels, instagramreels, etc.)

3. YT_TITLE: A catchy YouTube Shorts title (under 70 chars). Include "{artist} Type Beat".
   Example: "[FREE] {artist} Type Beat 2026 - '{beat_info.name}' | prodbyeviloid"

4. YT_DESCRIPTION: A YouTube description (3-5 lines) with:
   - Beat name and producer tag
   - BPM and key info
   - Contact/business info placeholder
   - A few relevant hashtags inline

5. YT_TAGS: 15 comma-separated YouTube tags for discoverability (no # symbol).
   Include: genre, "type beat", "free beat", producer name, mood keywords, etc.

6. COVER_SECOND: A number (in seconds) between 1 and {min(beat_info.duration, 10):.0f}
   representing the most impactful moment for the video thumbnail.

Respond in this EXACT format (plain text, no JSON, no markdown):
IG_CAPTION:
<your caption here>

IG_HASHTAGS: tag1, tag2, tag3, ...

YT_TITLE: <title here>

YT_DESCRIPTION:
<description here>

YT_TAGS: tag1, tag2, tag3, ...

COVER_SECOND: <number>"""

    try:
        from modules import ai_helper
        text = ai_helper.generate_text(prompt)
        logger.info(f"🤖 AI generated metadata for '{beat_info.name}'")

        result = _parse_response(text, beat_info)

        # If parsing returned empty critical fields, log a warning
        if not result.hashtags or not result.yt_tags:
            logger.warning(f"⚠️ Metadata parsing returned empty fields — applying defaults")
            result = _fill_defaults(result, beat_info)

        return result

    except Exception as e:
        logger.warning(f"⚠️ AI metadata generation failed: {e}")
        return _fallback_metadata(beat_info)


def _parse_response(text: str, beat_info: BeatInfo) -> "ReelMetadata":
    """Parse AI response into ReelMetadata. Handles JSON and plain-text formats."""
    caption = ""
    hashtags = []
    yt_title = ""
    yt_description = ""
    yt_tags = []
    cover_second = 3.0

    # Strip markdown code fences if present
    text = text.strip()
    for fence in ["```json", "```"]:
        if text.startswith(fence):
            text = text[len(fence):]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    # ── Try JSON parsing ──────────────────────────────────
    try:
        data = json.loads(text)

        caption = str(data.get("IG_CAPTION", data.get("ig_caption", ""))).strip()

        raw_hashtags = data.get("IG_HASHTAGS", data.get("ig_hashtags", []))
        if isinstance(raw_hashtags, str):
            hashtags = [t.strip().lstrip("#") for t in raw_hashtags.split(",") if t.strip()]
        elif isinstance(raw_hashtags, list):
            hashtags = [str(t).strip().lstrip("#") for t in raw_hashtags if str(t).strip()]

        yt_title = str(data.get("YT_TITLE", data.get("yt_title", ""))).strip()

        raw_desc = data.get("YT_DESCRIPTION", data.get("yt_description", ""))
        if isinstance(raw_desc, list):
            yt_description = "\n".join(str(l) for l in raw_desc).strip()
        else:
            yt_description = str(raw_desc).strip()

        raw_tags = data.get("YT_TAGS", data.get("yt_tags", []))
        if isinstance(raw_tags, str):
            yt_tags = [t.strip().lstrip("#") for t in raw_tags.split(",") if t.strip()]
        elif isinstance(raw_tags, list):
            yt_tags = [str(t).strip().lstrip("#") for t in raw_tags if str(t).strip()]

        try:
            cover_second = float(data.get("COVER_SECOND", data.get("cover_second", 3.0)))
        except (TypeError, ValueError):
            cover_second = 3.0

    except json.JSONDecodeError:
        # ── Plain-text format parsing ─────────────────────
        current_section = None
        caption_lines: List[str] = []
        yt_desc_lines: List[str] = []

        for line in text.split("\n"):
            stripped = line.strip()

            if stripped.startswith("IG_CAPTION:"):
                current_section = "ig_caption"
                rest = stripped[len("IG_CAPTION:"):].strip()
                if rest:
                    caption_lines.append(rest)
            elif stripped.startswith("IG_HASHTAGS:"):
                current_section = "ig_hashtags"
                rest = stripped[len("IG_HASHTAGS:"):].strip()
                if rest:
                    hashtags = [t.strip().lstrip("#") for t in rest.split(",") if t.strip()]
            elif stripped.startswith("YT_TITLE:"):
                current_section = "yt_title"
                rest = stripped[len("YT_TITLE:"):].strip()
                if rest:
                    yt_title = rest
            elif stripped.startswith("YT_DESCRIPTION:"):
                current_section = "yt_description"
                rest = stripped[len("YT_DESCRIPTION:"):].strip()
                if rest:
                    yt_desc_lines.append(rest)
            elif stripped.startswith("YT_TAGS:"):
                current_section = "yt_tags"
                rest = stripped[len("YT_TAGS:"):].strip()
                if rest:
                    yt_tags = [t.strip().lstrip("#") for t in rest.split(",") if t.strip()]
            elif stripped.startswith("COVER_SECOND:"):
                current_section = "cover"
                rest = stripped[len("COVER_SECOND:"):].strip()
                try:
                    cover_second = float(rest.split()[0])
                except (ValueError, IndexError):
                    cover_second = 3.0
            elif current_section == "ig_caption" and stripped:
                caption_lines.append(stripped)
            elif current_section == "yt_description" and stripped:
                yt_desc_lines.append(stripped)

        caption = "\n".join(caption_lines).strip()
        yt_description = "\n".join(yt_desc_lines).strip()

    # ── Apply defaults for missing fields ────────────────
    if not yt_title:
        artist = _get_artist_for_genre(beat_info.genre)
        yt_title = f"[FREE] {artist} Type Beat 2026 - '{beat_info.name}' | prodbyeviloid"

    # Format hashtags for IG
    hashtag_str = " ".join(f"#{tag}" for tag in hashtags[:30])
    full_caption = f"{caption}\n\n.\n.\n.\n{hashtag_str}" if hashtags else caption

    metadata = ReelMetadata(
        caption=caption,
        hashtags=hashtags,
        full_caption=full_caption,
        yt_title=yt_title,
        yt_description=yt_description,
        yt_tags=yt_tags,
        cover_timestamp=cover_second,
    )

    logger.info(f"   📝 IG Caption: {caption[:80]}...")
    logger.info(f"   #️⃣  {len(hashtags)} IG hashtags generated")
    logger.info(f"   📺 YT Title: {yt_title}")
    logger.info(f"   🏷️  {len(yt_tags)} YT tags generated")
    logger.info(f"   🖼️ Cover at {cover_second}s")

    return metadata


def _fill_defaults(metadata: "ReelMetadata", beat_info: BeatInfo) -> "ReelMetadata":
    """Fill in any empty fields with sensible defaults derived from beat_info."""
    fallback = _fallback_metadata(beat_info)

    if not metadata.caption:
        metadata.caption = fallback.caption
    if not metadata.hashtags:
        metadata.hashtags = fallback.hashtags
    if not metadata.yt_tags:
        metadata.yt_tags = fallback.yt_tags
    if not metadata.yt_description:
        metadata.yt_description = fallback.yt_description
    if not metadata.yt_title:
        metadata.yt_title = fallback.yt_title

    # Rebuild full_caption with final hashtags
    hashtag_str = " ".join(f"#{tag}" for tag in metadata.hashtags[:30])
    metadata.full_caption = (
        f"{metadata.caption}\n\n.\n.\n.\n{hashtag_str}"
        if metadata.hashtags
        else metadata.caption
    )
    return metadata


def _fallback_metadata(beat_info: BeatInfo) -> ReelMetadata:
    """Generate complete metadata without AI as a last-resort fallback."""
    genre = beat_info.genre or "hip hop"
    mood = beat_info.mood or "vibes"
    artist = _get_artist_for_genre(genre)

    caption = (
        f"🔥 {beat_info.name} 🔥\n"
        f"{genre.title()} | {beat_info.bpm} BPM | {mood.title()}\n"
        f"DM for exclusive beats 💰"
    )

    hashtags = [
        "beats", "producer", "beatmaker", genre.replace(" ", ""),
        "typebeat", "newmusic", "instrumentals", "studiolife",
        mood.replace(" ", ""), "hiphop", "rap", "trapbeats",
        "musicproducer", "beatsforsale", "exclusive", "fire",
        "unsigned", "rapper", "explorepage", "viral",
        "reels", "instagramreels", "prodbyeviloid", "freebeat",
        "beatstars",
    ]

    yt_title = f"[FREE] {artist} Type Beat 2026 - '{beat_info.name}' | prodbyeviloid"
    yt_description = (
        f"🔥 {beat_info.name} - {genre.title()} Type Beat\n"
        f"Produced by prodbyeviloid\n"
        f"BPM: {beat_info.bpm} | Mood: {mood.title()}\n"
        f"\n"
        f"📩 Business: DM on Instagram\n"
        f"#typebeat #freebeat #{genre.replace(' ', '')} #prodbyeviloid"
    )
    yt_tags = [
        "type beat", "free beat", genre, f"{genre} type beat",
        artist.lower(), "prodbyeviloid", "beats", mood, "instrumental",
        f"{beat_info.bpm} bpm", "2026", "new beat", "rap beat",
        "hip hop beat", "free instrumental",
    ]

    full_caption = f"{caption}\n\n.\n.\n.\n{' '.join(f'#{t}' for t in hashtags)}"

    return ReelMetadata(
        caption=caption,
        hashtags=hashtags,
        full_caption=full_caption,
        yt_title=yt_title,
        yt_description=yt_description,
        yt_tags=yt_tags,
        cover_timestamp=3.0,
    )
