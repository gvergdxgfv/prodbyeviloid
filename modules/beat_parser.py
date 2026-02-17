"""
Beat Parser Module
==================
Scans the beats folder, extracts metadata from filenames and audio analysis,
and uses AI to infer mood/genre/visual keywords for YouTube searching.
"""

import re
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional

import librosa
import numpy as np

import config

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac"}


@dataclass
class BeatInfo:
    """All metadata about a single beat file."""
    path: Path
    name: str                       # Clean display name
    filename: str                   # Original filename without extension
    duration: float                 # Duration in seconds
    bpm: float                      # Detected BPM
    genre: str = ""                 # Inferred genre
    mood: str = ""                  # Inferred mood
    energy: str = "medium"          # low / medium / high
    visual_keywords: List[str] = field(default_factory=list)
    beat_times: List[float] = field(default_factory=list)  # Beat timestamps in seconds
    drop_times: List[float] = field(default_factory=list)   # Strong beats / onset drops (ideal cut points)
    best_segments: List[tuple] = field(default_factory=list)  # Best (start, end) segments for highlights


def _parse_filename(filename: str) -> dict:
    """
    Extract info from common beat naming conventions.
    Examples:
        dark_trap_140bpm  → genre=trap, mood=dark, bpm_hint=140
        chill_lofi_beat   → genre=lofi, mood=chill
        aggressive_drill  → genre=drill, mood=aggressive
    """
    name_lower = filename.lower().replace("-", "_")

    # Try to extract BPM from filename
    bpm_match = re.search(r"(\d{2,3})\s*bpm", name_lower)
    bpm_hint = int(bpm_match.group(1)) if bpm_match else None

    # Common mood keywords
    moods = [
        "dark", "chill", "aggressive", "sad", "happy", "melancholic",
        "energetic", "dreamy", "hard", "soft", "ambient", "intense",
        "smooth", "gritty", "ethereal", "bouncy", "heavy", "light",
        "midnight", "night", "summer", "winter",
    ]
    # Common genre keywords
    genres = [
        "trap", "drill", "lofi", "lo-fi", "boom bap", "boombap",
        "rnb", "r&b", "pop", "hip hop", "hiphop", "afrobeat",
        "reggaeton", "phonk", "jersey", "uk drill", "type beat",
        "soul", "jazz", "classical", "edm", "house", "techno",
    ]

    detected_mood = ""
    for m in moods:
        if m in name_lower:
            detected_mood = m
            break

    detected_genre = ""
    for g in genres:
        if g.replace(" ", "_") in name_lower or g in name_lower:
            detected_genre = g
            break

    return {
        "bpm_hint": bpm_hint,
        "mood": detected_mood,
        "genre": detected_genre,
    }


def _analyze_audio(filepath: Path) -> dict:
    """
    Use librosa to analyze the audio file.
    Returns tempo, duration, beat times, and energy level.
    """
    logger.info(f"🎵 Analyzing audio: {filepath.name}")

    y, sr = librosa.load(str(filepath), sr=22050, mono=True)
    duration = librosa.get_duration(y=y, sr=sr)

    # Tempo and beat detection
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()

    # Handle tempo as array (newer librosa versions)
    if hasattr(tempo, '__len__'):
        tempo = float(tempo[0]) if len(tempo) > 0 else 120.0
    else:
        tempo = float(tempo)

    # Energy analysis (RMS)
    rms = librosa.feature.rms(y=y)[0]
    avg_rms = float(np.mean(rms))

    if avg_rms > 0.15:
        energy = "high"
    elif avg_rms > 0.06:
        energy = "medium"
    else:
        energy = "low"

    logger.info(f"   ⏱ Duration: {duration:.1f}s | 🥁 BPM: {tempo:.0f} | ⚡ Energy: {energy}")

    # ── Onset / Drop detection ──
    # Find transient onsets (hits, drops, percussive moments)
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    onset_frames = librosa.onset.onset_detect(
        y=y, sr=sr, onset_envelope=onset_env,
        backtrack=False, delta=0.15,
    )
    onset_times = librosa.frames_to_time(onset_frames, sr=sr).tolist()

    # Strong beats = beats that coincide with an onset (within 0.05s)
    # These are the hard-hitting moments ideal for visual cuts
    drop_times = []
    for bt in beat_times:
        for ot in onset_times:
            if abs(bt - ot) < 0.05:
                drop_times.append(bt)
                break

    # Also add very strong onsets even if not on exact beat
    onset_strengths = onset_env[onset_frames] if len(onset_frames) > 0 else []
    if len(onset_strengths) > 0:
        threshold = np.percentile(onset_strengths, 85)  # top 15% of onsets
        for i, of in enumerate(onset_frames):
            if i < len(onset_strengths) and onset_strengths[i] >= threshold:
                ot = onset_times[i]
                # Don't duplicate if already in drop_times
                if not any(abs(ot - dt) < 0.1 for dt in drop_times):
                    drop_times.append(ot)

    drop_times.sort()
    logger.info(f"   💥 Detected {len(drop_times)} drop/cut points ({len(beat_times)} beats, {len(onset_times)} onsets)")

    # ── Best segments detection (sliding window RMS) ──
    highlight_dur = config.HIGHLIGHT_DURATION  # seconds
    max_highlights = config.MAX_HIGHLIGHTS
    best_segments = []

    if duration > highlight_dur + 5:  # Only if beat is long enough
        window_samples = int(highlight_dur * sr)
        step_samples = int(1.0 * sr)  # 1s step
        n_windows = max(1, (len(y) - window_samples) // step_samples)

        window_energies = []
        for wi in range(n_windows):
            start_s = wi * step_samples
            end_s = start_s + window_samples
            chunk = y[start_s:end_s]
            energy_val = float(np.sqrt(np.mean(chunk ** 2)))
            start_time = start_s / sr
            end_time = min(end_s / sr, duration)
            window_energies.append((energy_val, start_time, end_time))

        # Sort by energy descending
        window_energies.sort(key=lambda x: x[0], reverse=True)

        # Pick top non-overlapping segments
        selected = []
        for e_val, ws, we in window_energies:
            if len(selected) >= max_highlights:
                break
            # Check overlap with already selected
            overlaps = False
            for _, ss, se in selected:
                if ws < se and we > ss:
                    overlaps = True
                    break
            if not overlaps:
                selected.append((e_val, ws, we))

        # Sort by position in track
        selected.sort(key=lambda x: x[1])
        best_segments = [(s, e) for _, s, e in selected]

        logger.info(f"   🔥 Found {len(best_segments)} best {highlight_dur}s segments")
        for i, (s, e) in enumerate(best_segments):
            logger.info(f"      Highlight {i+1}: {s:.1f}s – {e:.1f}s")

    return {
        "duration": duration,
        "bpm": round(tempo),
        "beat_times": beat_times,
        "drop_times": drop_times,
        "energy": energy,
        "best_segments": best_segments,
    }


def _generate_visual_keywords(beat_info: BeatInfo) -> BeatInfo:
    """
    Use Google Gemini to infer genre, mood, and visual search keywords
    from the beat name and audio characteristics.
    """
    beat_name = beat_info.filename
    bpm = beat_info.bpm
    energy = beat_info.energy
    duration = beat_info.duration

    prompt = f"""You are a music video director. Given a beat's metadata, generate:
1. Genre (if not already known)
2. Mood (1-2 words)
3. 6 visual keywords for finding YouTube footage (lifestyle, vibes, no lyrics)

Beat Info:
- Name: "{beat_name}"
- BPM: {bpm}
- Energy: {energy}
- Duration: {duration}s

Respond in JSON format:
{{
  "genre": "...",
  "mood": "...",
  "keywords": ["...", "...", ...]
}}
"""

    try:
        from modules import ai_helper
        text = ai_helper.generate_text(prompt)
        logger.info(f"   🤖 AI response: {text[:100]}...")

        import json
        # Strip markdown if present
        clean_text = text.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_text)

        if "genre" in data and data["genre"]:
            beat_info.genre = beat_info.genre or data["genre"]
        if "mood" in data and data["mood"]:
            beat_info.mood = beat_info.mood or data["mood"]
        if "keywords" in data and isinstance(data["keywords"], list):
            beat_info.visual_keywords = [k for k in data["keywords"] if isinstance(k, str)]

    except Exception as e:
        logger.warning(f"   ⚠️ Gemini keyword generation failed: {e}")
        # Fallback keywords based on available info
        beat_info.visual_keywords = _fallback_keywords(beat_info)

    return beat_info


def _fallback_keywords(beat_info: BeatInfo) -> List[str]:
    """Generate fallback visual keywords without AI."""
    keywords = []
    if beat_info.mood:
        keywords.append(f"{beat_info.mood} aesthetic cinematic footage")
    if beat_info.genre:
        keywords.append(f"{beat_info.genre} music video aesthetic")
    if beat_info.energy == "high":
        keywords.append("fast paced urban night footage 4k")
        keywords.append("dynamic action cinematic shots")
    elif beat_info.energy == "low":
        keywords.append("calm nature landscape cinematic")
        keywords.append("slow motion ambient footage")
    else:
        keywords.append("cinematic urban footage 4k")
        keywords.append("aesthetic drone footage city")
    keywords.append("abstract visual effects dark background")
    return keywords[:5]


def parse_beat(beat_path: Path) -> BeatInfo:
    """
    Parse a single beat file: analyze audio + generate visual keywords.
    """
    filename = beat_path.stem
    parsed = _parse_filename(filename)
    audio = _analyze_audio(beat_path)

    # Clean up display name
    clean_name = filename.replace("_", " ").replace("-", " ").title()

    beat_info = BeatInfo(
        path=beat_path,
        name=clean_name,
        filename=filename,
        duration=audio["duration"],
        bpm=parsed.get("bpm_hint") or audio["bpm"],
        genre=parsed.get("genre", ""),
        mood=parsed.get("mood", ""),
        energy=audio["energy"],
        beat_times=audio["beat_times"],
        drop_times=audio["drop_times"],
        best_segments=audio["best_segments"],
    )

    # Use AI to fill in missing metadata and generate visual keywords
    beat_info = _generate_visual_keywords(beat_info)

    logger.info(f"   ✅ Parsed: {beat_info.name} | {beat_info.bpm}bpm | {beat_info.genre} | {beat_info.mood}")
    logger.info(f"   🔍 Keywords: {', '.join(beat_info.visual_keywords)}")

    return beat_info


def scan_beats_folder() -> List[BeatInfo]:
    """
    Scan the beats directory and parse all beat files.
    """
    beats = []
    beats_dir = config.BEATS_DIR

    if not beats_dir.exists():
        logger.warning(f"⚠️ Beats directory not found: {beats_dir}")
        return beats

    for f in sorted(beats_dir.iterdir()):
        if f.suffix.lower() in SUPPORTED_EXTENSIONS:
            try:
                beat = parse_beat(f)
                beats.append(beat)
            except Exception as e:
                logger.error(f"❌ Failed to parse {f.name}: {e}")

    logger.info(f"📂 Found {len(beats)} beat(s) in {beats_dir}")
    return beats
