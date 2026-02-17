"""
Beat Visualizer Module — Waveform Only
=======================================
Generates an audio-reactive waveform overlay with glow effects,
beat-reactive amplitude, and a mirror reflection.

Composited on top of YouTube clips as a transparent-background VideoClip.
"""

import logging
from pathlib import Path
from typing import List, Optional, Tuple

import librosa
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from moviepy import VideoClip, TextClip, CompositeVideoClip

import config
from modules.beat_parser import BeatInfo

logger = logging.getLogger(__name__)

TARGET_W = config.VIDEO_WIDTH   # 1080
TARGET_H = config.VIDEO_HEIGHT  # 1920
TARGET_FPS = 30

# ── Color Themes ──────────────────────────────────────────

THEMES = {
    "neon": {
        "waveform_color": (0, 255, 200),
        "waveform_glow": (0, 255, 255, 80),
        "mirror_color": (0, 200, 180, 50),
        "text_color": (255, 255, 255),
        "text_glow": (0, 255, 255, 100),
        "flash_color": (0, 255, 255, 18),
        "center_line": (0, 255, 200, 30),
    },
    "fire": {
        "waveform_color": (255, 140, 0),
        "waveform_glow": (255, 80, 0, 80),
        "mirror_color": (255, 100, 0, 50),
        "text_color": (255, 255, 255),
        "text_glow": (255, 100, 0, 100),
        "flash_color": (255, 120, 0, 18),
        "center_line": (255, 140, 0, 30),
    },
    "ice": {
        "waveform_color": (130, 200, 255),
        "waveform_glow": (100, 180, 255, 80),
        "mirror_color": (120, 170, 255, 50),
        "text_color": (255, 255, 255),
        "text_glow": (100, 180, 255, 100),
        "flash_color": (150, 200, 255, 18),
        "center_line": (130, 200, 255, 30),
    },
    "purple": {
        "waveform_color": (200, 80, 255),
        "waveform_glow": (180, 0, 255, 80),
        "mirror_color": (160, 50, 255, 50),
        "text_color": (255, 255, 255),
        "text_glow": (180, 0, 255, 100),
        "flash_color": (200, 80, 255, 18),
        "center_line": (200, 80, 255, 30),
    },
}

# ── Font Discovery ────────────────────────────────────────

def _find_font(size: int = 36) -> ImageFont.FreeTypeFont:
    """Find a usable font, trying multiple options."""
    font_candidates = [
        "C:/Windows/Fonts/seguisb.ttf",   # Segoe UI Semibold (Windows)
        "C:/Windows/Fonts/segoeui.ttf",    # Segoe UI (Windows)
        "C:/Windows/Fonts/arial.ttf",      # Arial (Windows)
        "C:/Windows/Fonts/calibri.ttf",    # Calibri (Windows)
        "C:/Windows/Fonts/consola.ttf",    # Consolas (Windows)
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Linux
        "/System/Library/Fonts/Helvetica.ttc",  # macOS
    ]
    for font_path in font_candidates:
        try:
            return ImageFont.truetype(font_path, size)
        except (IOError, OSError):
            continue
    logger.warning("⚠️ No TrueType fonts found, using default bitmap font")
    return ImageFont.load_default()


# ── Audio Analysis ────────────────────────────────────────

def _analyze_for_visualizer(
    audio_path: Path,
    fps: int = TARGET_FPS,
    start_time: float = 0.0,
    end_time: float = None,
) -> dict:
    """
    Analyze audio to extract per-frame waveform data for visualization.

    Args:
        audio_path: Path to the audio file
        fps: Frames per second
        start_time: Start time in seconds (for highlight clips)
        end_time: End time in seconds (for highlight clips)

    Returns:
        dict with 'rms_frames', 'y', 'sr', 'duration', etc.
    """
    logger.info("🎨 Analyzing audio for waveform visualizer...")

    y, sr = librosa.load(str(audio_path), sr=22050, mono=True)

    # Trim to segment if specified
    if start_time > 0 or end_time is not None:
        start_sample = int(start_time * sr)
        end_sample = int(end_time * sr) if end_time else len(y)
        end_sample = min(end_sample, len(y))
        y = y[start_sample:end_sample]

    duration = librosa.get_duration(y=y, sr=sr)

    hop_length = int(sr / fps)

    # RMS energy per frame (for beat-reactive amplitude)
    rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
    rms_norm = rms / (rms.max() + 1e-8)

    # Waveform samples per frame
    samples_per_frame = len(y) // max(int(duration * fps), 1)
    n_frames = int(duration * fps)

    logger.info(f"   📊 {n_frames} frames | {duration:.1f}s | waveform-only mode")

    return {
        "rms_frames": rms_norm,
        "y": y,
        "sr": sr,
        "duration": duration,
        "hop_length": hop_length,
        "n_frames": n_frames,
        "samples_per_frame": samples_per_frame,
    }


# ── Frame Rendering ──────────────────────────────────────

def _render_frame(
    frame_idx: int,
    audio_data: dict,
    theme: dict,
    beat_name: str,
    producer_tag: str,
    font_large: ImageFont.FreeTypeFont,
    font_small: ImageFont.FreeTypeFont,
    font_tag: ImageFont.FreeTypeFont,
    beat_times: List[float],
    audio_offset: float = 0.0,
) -> np.ndarray:
    """
    Render a single waveform visualizer frame as RGBA numpy array.
    Large, centered waveform with glow, mirror, and beat-reactive effects.
    """
    rms = audio_data["rms_frames"]
    rms_idx = min(frame_idx, len(rms) - 1)
    energy = rms[rms_idx]

    # Create RGBA image (transparent background)
    img = Image.new("RGBA", (TARGET_W, TARGET_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    wf_color = theme["waveform_color"]
    wf_glow = theme["waveform_glow"]
    mirror_color = theme["mirror_color"]
    center_line_color = theme["center_line"]

    # ── Waveform position ────────────────────────────────
    # Centered in the lower-middle of the screen
    wf_y_center = int(TARGET_H * 0.55)
    wf_x_start = int(TARGET_W * 0.06)
    wf_width = int(TARGET_W * 0.88)
    max_amplitude = 120  # max pixel height of waveform from center

    # ── Get waveform chunk for this frame ────────────────
    y_data = audio_data["y"]
    spf = audio_data["samples_per_frame"]
    start_sample = frame_idx * spf
    end_sample = min(start_sample + spf, len(y_data))

    # Check for beat flash
    current_time = frame_idx / TARGET_FPS + audio_offset
    is_beat = False
    for bt in beat_times:
        if abs(current_time - bt) < 0.06:
            is_beat = True
            break

    # Beat-reactive scaling
    amplitude_scale = 0.6 + energy * 0.7
    if is_beat:
        amplitude_scale *= 1.5

    if end_sample > start_sample:
        waveform_chunk = y_data[start_sample:end_sample]

        # Downsample to ~300 points for smooth drawing
        n_points = 300
        if len(waveform_chunk) > n_points:
            indices = np.linspace(0, len(waveform_chunk) - 1, n_points, dtype=int)
            waveform_chunk = waveform_chunk[indices]

        # ── Draw center line (subtle) ────────────────────
        draw.line(
            [(wf_x_start, wf_y_center), (wf_x_start + wf_width, wf_y_center)],
            fill=center_line_color,
            width=1,
        )

        # ── Build waveform points ────────────────────────
        points_upper = []
        points_lower = []

        for j, sample in enumerate(waveform_chunk):
            x = wf_x_start + int(j / len(waveform_chunk) * wf_width)
            displacement = sample * max_amplitude * amplitude_scale
            y_up = int(wf_y_center - displacement)
            y_down = int(wf_y_center + displacement)
            points_upper.append((x, y_up))
            points_lower.append((x, y_down))

        # ── Glow layer (thick, blurred) ──────────────────
        glow_layer = Image.new("RGBA", (TARGET_W, TARGET_H), (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow_layer)

        if len(points_upper) > 2:
            # Draw thick glow lines
            glow_draw.line(points_upper, fill=wf_glow, width=6)
            glow_draw.line(points_lower, fill=wf_glow, width=6)

        # Blur the glow
        glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=10))
        img = Image.alpha_composite(img, glow_layer)
        draw = ImageDraw.Draw(img)

        # ── Main waveform lines (crisp) ──────────────────
        if len(points_upper) > 2:
            # Upper waveform
            draw.line(points_upper, fill=(*wf_color, 230), width=3)
            # Lower waveform
            draw.line(points_lower, fill=(*wf_color, 230), width=3)

        # ── Fill between upper and lower for solid waveform feel ──
        if len(points_upper) > 2:
            fill_layer = Image.new("RGBA", (TARGET_W, TARGET_H), (0, 0, 0, 0))
            fill_draw = ImageDraw.Draw(fill_layer)

            # Create filled polygon between upper and lower curves
            polygon_points = points_upper + list(reversed(points_lower))
            fill_draw.polygon(polygon_points, fill=(*wf_color, 35))
            img = Image.alpha_composite(img, fill_layer)
            draw = ImageDraw.Draw(img)

        # ── Mirror reflection (below, faded) ─────────────
        mirror_y_center = wf_y_center + max_amplitude + 30
        mirror_amplitude = max_amplitude * 0.25

        mirror_points = []
        for j, sample in enumerate(waveform_chunk):
            x = wf_x_start + int(j / len(waveform_chunk) * wf_width)
            displacement = sample * mirror_amplitude * amplitude_scale
            y_m = int(mirror_y_center + abs(displacement))
            mirror_points.append((x, y_m))

        if len(mirror_points) > 2:
            mirror_layer = Image.new("RGBA", (TARGET_W, TARGET_H), (0, 0, 0, 0))
            mirror_draw = ImageDraw.Draw(mirror_layer)
            mirror_draw.line(mirror_points, fill=mirror_color, width=2)
            mirror_layer = mirror_layer.filter(ImageFilter.GaussianBlur(radius=4))
            img = Image.alpha_composite(img, mirror_layer)
            draw = ImageDraw.Draw(img)

    # ── Beat name (above waveform) ────────────────────────
    text_color = theme["text_color"]
    try:
        name_bbox = draw.textbbox((0, 0), beat_name, font=font_large)
        name_w = name_bbox[2] - name_bbox[0]
        name_x = (TARGET_W - name_w) // 2
        name_y = wf_y_center - max_amplitude - 100

        # Glow behind text
        text_glow_layer = Image.new("RGBA", (TARGET_W, TARGET_H), (0, 0, 0, 0))
        tg_draw = ImageDraw.Draw(text_glow_layer)
        tg_draw.text(
            (name_x, name_y), beat_name, font=font_large,
            fill=theme["text_glow"],
        )
        text_glow_layer = text_glow_layer.filter(ImageFilter.GaussianBlur(radius=6))
        img = Image.alpha_composite(img, text_glow_layer)
        draw = ImageDraw.Draw(img)

        draw.text(
            (name_x, name_y), beat_name, font=font_large,
            fill=(*text_color, 220),
        )
    except Exception:
        pass

    # ── Producer tag at BOTTOM ────────────────────────────
    try:
        tag_bbox = draw.textbbox((0, 0), producer_tag, font=font_tag)
        tag_w = tag_bbox[2] - tag_bbox[0]
        tag_h = tag_bbox[3] - tag_bbox[1]
        tag_x = (TARGET_W - tag_w) // 2
        tag_y = TARGET_H - tag_h - 60  # 60px from bottom edge

        # Glow behind producer tag
        pg_layer = Image.new("RGBA", (TARGET_W, TARGET_H), (0, 0, 0, 0))
        pg_draw = ImageDraw.Draw(pg_layer)
        pg_draw.text(
            (tag_x, tag_y), producer_tag, font=font_tag,
            fill=theme["text_glow"],
        )
        pg_layer = pg_layer.filter(ImageFilter.GaussianBlur(radius=8))
        img = Image.alpha_composite(img, pg_layer)
        draw = ImageDraw.Draw(img)

        # Shadow
        draw.text(
            (tag_x + 2, tag_y + 2), producer_tag, font=font_tag,
            fill=(0, 0, 0, 120),
        )
        # Main tag text
        draw.text(
            (tag_x, tag_y), producer_tag, font=font_tag,
            fill=(*text_color, 240),
        )
    except Exception:
        pass

    # ── Beat flash overlay ────────────────────────────────
    if is_beat:
        flash_color = theme["flash_color"]
        flash = Image.new("RGBA", (TARGET_W, TARGET_H), flash_color)
        img = Image.alpha_composite(img, flash)

    return np.array(img)


# ── Main Entry Point ──────────────────────────────────────

def generate_visualizer_overlay(
    beat_info: BeatInfo,
    duration: float,
    theme_name: str = "neon",
    producer_tag: str = None,
    start_time: float = 0.0,
    end_time: float = None,
) -> VideoClip:
    """
    Generate an waveform-only audio-reactive visualizer overlay as a VideoClip.

    The overlay has a transparent background and is meant to be composited
    on top of the YouTube clip background.

    Args:
        beat_info: Parsed beat metadata (includes path, beat_times, etc.)
        duration: Target duration in seconds
        theme_name: Color theme — 'neon', 'fire', 'ice', 'purple'
        producer_tag: Producer name to display (defaults to config.PRODUCER_TAG)
        start_time: Start time in audio for highlight clips
        end_time: End time in audio for highlight clips

    Returns:
        A moviepy VideoClip (RGBA) with the waveform visualizer overlay
    """
    if producer_tag is None:
        producer_tag = config.PRODUCER_TAG

    theme = THEMES.get(theme_name, THEMES["neon"])

    # Analyze audio for per-frame data (trimmed to segment if highlight)
    audio_data = _analyze_for_visualizer(
        beat_info.path, fps=TARGET_FPS,
        start_time=start_time, end_time=end_time,
    )

    # Load fonts
    font_large = _find_font(44)
    font_small = _find_font(28)
    font_tag = _find_font(36)

    beat_name = beat_info.name
    beat_times = beat_info.beat_times or []

    # Pre-render
    logger.info(f"🎨 Rendering waveform visualizer ({theme_name} theme)...")
    n_frames = min(int(duration * TARGET_FPS), audio_data["n_frames"])

    frame_cache = {}

    def make_frame(t):
        """Generate frame at time t."""
        idx = int(t * TARGET_FPS)
        idx = min(idx, max(n_frames - 1, 0))

        if idx not in frame_cache:
            rgba_frame = _render_frame(
                idx, audio_data, theme, beat_name, producer_tag,
                font_large, font_small, font_tag, beat_times,
                audio_offset=start_time,
            )
            frame_cache[idx] = rgba_frame

        return frame_cache[idx]

    clip = VideoClip(make_frame, duration=duration)
    clip = clip.with_fps(TARGET_FPS)

    logger.info(f"   ✅ Waveform visualizer ready ({n_frames} frames, {duration:.1f}s)")
    return clip
