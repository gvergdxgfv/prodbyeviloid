"""
AI Metadata Generator Module (Gemini)
======================================
Uses Google Gemini to generate Instagram & YouTube Shorts optimized
captions, hashtags, and cover frame suggestions for each video.
"""

import logging
from dataclasses import dataclass, field
from typing import List

from google import genai

import config
from modules.beat_parser import BeatInfo

logger = logging.getLogger(__name__)


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
    Generate platform-optimized metadata using Google Gemini.

    Produces engaging captions and hashtags for both
    Instagram Reels and YouTube Shorts.
    """
    client = genai.Client(api_key=config.GEMINI_API_KEY)

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

3. YT_TITLE: A catchy YouTube Shorts title (under 70 chars). Include the genre and "Type Beat".
   Example: "[FREE] Dark Trap Type Beat 2026 - 'Midnight' | prodbyeviloid"

4. YT_DESCRIPTION: A YouTube description (3-5 lines) with:
   - Beat name and producer tag
   - BPM and key info
   - Contact/business info placeholder
   - A few relevant hashtags inline

5. YT_TAGS: 15 comma-separated YouTube tags for discoverability (no # symbol).
   Include: genre, "type beat", "free beat", producer name, mood keywords, etc.

6. COVER_SECOND: A number (in seconds) between 1 and {min(beat_info.duration, 10):.0f}
   representing the most impactful moment for the video thumbnail.

Respond in this EXACT format:
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

        return _parse_response(text, beat_info)

    except Exception as e:
        logger.warning(f"⚠️ Gemini metadata generation failed: {e}")
        return _fallback_metadata(beat_info)


def _parse_response(text: str, beat_info: BeatInfo) -> ReelMetadata:
    """Parse the structured Gemini response into ReelMetadata."""
    caption = ""
    hashtags = []
    yt_title = ""
    yt_description = ""
    yt_tags = []
    cover_second = 3.0

    current_section = None
    caption_lines = []
    yt_desc_lines = []

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
                cover_second = float(rest)
            except ValueError:
                cover_second = 3.0
        elif current_section == "ig_caption" and stripped:
            caption_lines.append(stripped)
        elif current_section == "yt_description" and stripped:
            yt_desc_lines.append(stripped)

    caption = "\n".join(caption_lines).strip()
    yt_description = "\n".join(yt_desc_lines).strip()

    # Default YT title if not parsed
    if not yt_title:
        genre = beat_info.genre or "Hip Hop"
        yt_title = f"[FREE] {genre.title()} Type Beat 2026 - '{beat_info.name}' | prodbyeviloid"

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


def _fallback_metadata(beat_info: BeatInfo) -> ReelMetadata:
    """Generate basic metadata without AI as a fallback."""
    genre = beat_info.genre or "hip hop"
    mood = beat_info.mood or "vibes"

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
        "reels", "instagramreels", "prodbyeviloid", "freetype beat",
        "beatstars",
    ]

    yt_title = f"[FREE] {genre.title()} Type Beat 2026 - '{beat_info.name}' | prodbyeviloid"
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
        "prodbyeviloid", "beats", mood, "instrumental",
        f"{beat_info.bpm} bpm", "2026", "new beat", "rap beat",
        "hip hop beat", "free instrumental", "beat for sale",
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
