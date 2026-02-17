"""
Video Assembler Module
======================
Combines downloaded YouTube clips with a beat audio file into
9:16 vertical videos suitable for Instagram Reels / YouTube Shorts.

Produces:
  - Full beat video (entire beat duration)
  - N highlight clips (best 30s segments detected by energy analysis)
"""

import logging
import random
from pathlib import Path
from typing import List, Optional, Tuple

from moviepy import (
    VideoFileClip,
    AudioFileClip,
    ColorClip,
    TextClip,
    CompositeVideoClip,
    concatenate_videoclips,
    vfx,
)
import numpy as np

import config
from modules.beat_parser import BeatInfo
from modules.youtube_sourcer import ClipInfo

logger = logging.getLogger(__name__)

TARGET_W = config.VIDEO_WIDTH   # 1080
TARGET_H = config.VIDEO_HEIGHT  # 1920
TARGET_FPS = 30


def _resize_clip_to_vertical(clip: VideoFileClip) -> VideoFileClip:
    """
    Resize and crop a clip to fill 9:16 vertical frame.
    Strategy: scale to fill, then center-crop.
    """
    cw, ch = clip.size
    target_ratio = TARGET_W / TARGET_H  # 0.5625

    clip_ratio = cw / ch

    if clip_ratio > target_ratio:
        new_h = TARGET_H
        new_w = int(cw * (TARGET_H / ch))
    else:
        new_w = TARGET_W
        new_h = int(ch * (TARGET_W / cw))

    clip = clip.resized((new_w, new_h))

    x_center = new_w / 2
    y_center = new_h / 2
    x1 = int(x_center - TARGET_W / 2)
    y1 = int(y_center - TARGET_H / 2)

    clip = clip.cropped(x1=x1, y1=y1, width=TARGET_W, height=TARGET_H)
    return clip


def _apply_ken_burns(clip: VideoFileClip, zoom_range: float = 0.08) -> VideoFileClip:
    """
    Apply a subtle slow zoom (Ken Burns effect) to a clip.
    Randomly zooms in or out.
    """
    zoom_in = random.choice([True, False])

    def zoom_filter(get_frame, t):
        frame = get_frame(t)
        progress = t / max(clip.duration, 0.1)

        if zoom_in:
            scale = 1.0 + (zoom_range * progress)
        else:
            scale = 1.0 + zoom_range - (zoom_range * progress)

        h, w = frame.shape[:2]
        new_h, new_w = int(h * scale), int(w * scale)

        if new_h > h and new_w > w:
            crop_y = int((new_h - h) / 2 * (1 / scale))
            crop_x = int((new_w - w) / 2 * (1 / scale))
            crop_y = min(crop_y, h // 4)
            crop_x = min(crop_x, w // 4)

            if crop_y > 0 and crop_x > 0:
                frame = frame[crop_y:-crop_y, crop_x:-crop_x]
                from PIL import Image
                img = Image.fromarray(frame)
                img = img.resize((w, h), Image.LANCZOS)
                frame = np.array(img)

        return frame

    return clip.transform(zoom_filter)


def _apply_transition(clip, transition_type: str = "crossfade"):
    """
    Apply a transition effect to the beginning of a clip.
    Supports: crossfade, zoom
    """
    try:
        duration = min(0.3, clip.duration / 3)  # Transition = 0.3s or 1/3 of clip
        
        if transition_type == "crossfade":
            clip = clip.with_effects([vfx.CrossFadeIn(duration)])
        elif transition_type == "zoom":
            # Quick zoom-in effect at the start
            def zoom_in(get_frame, t):
                frame = get_frame(t)
                if t < duration:
                    progress = t / duration
                    scale = 1.3 - (0.3 * progress)  # 1.3x -> 1.0x
                    h, w = frame.shape[:2]
                    new_h, new_w = int(h * scale), int(w * scale)
                    y_off = (new_h - h) // 2
                    x_off = (new_w - w) // 2
                    from PIL import Image
                    img = Image.fromarray(frame)
                    img = img.resize((new_w, new_h), Image.LANCZOS)
                    frame = np.array(img)[y_off:y_off+h, x_off:x_off+w]
                return frame
            clip = clip.transform(zoom_in)
        
        return clip
    except Exception as e:
        logger.warning(f"⚠️ Transition '{transition_type}' failed: {e}")
        return clip


def _create_beat_flash(beat_times: List[float], duration: float) -> Optional[List]:
    """
    Create subtle flash overlays that pulse on beat drops.
    Limited to every 4th beat (max 30 flashes) to prevent memory issues.
    """
    if not beat_times:
        return None

    # Only flash every 4th beat to save memory
    sparse_beats = [bt for i, bt in enumerate(beat_times) if i % 4 == 0 and bt < duration]
    sparse_beats = sparse_beats[:30]  # Hard cap

    flash_clips = []
    for bt in sparse_beats:
        flash = (
            ColorClip(size=(TARGET_W, TARGET_H), color=(255, 255, 255))
            .with_duration(0.05)
            .with_start(bt)
            .with_effects([vfx.CrossFadeIn(0.02), vfx.CrossFadeOut(0.03)])
            .with_opacity(0.08)
        )
        flash_clips.append(flash)

    return flash_clips


def _create_producer_watermark(duration: float, producer_tag: str = None) -> Optional[TextClip]:
    """
    Create the 'prodbyeviloid' watermark at the bottom of the video.
    """
    if producer_tag is None:
        producer_tag = config.PRODUCER_TAG

    try:
        txt = TextClip(
            text=producer_tag,
            font_size=32,
            color="white",
            font="C:/Windows/Fonts/arial.ttf",
            stroke_color="black",
            stroke_width=1,
        )
        txt = (
            txt
            .with_duration(duration)
            .with_position(("center", TARGET_H - 100))
            .with_opacity(0.7)
        )
        return txt
    except Exception as e:
        logger.warning(f"⚠️ Could not create producer watermark: {e}")
        return None



def _apply_cinematic_effects(clip, beat_info: BeatInfo, audio_start: float = 0.0) -> VideoFileClip:
    """
    Apply cinematic effects and baked-in beat flashes directly to the clip.
    This saves RAM by avoiding composite layers.
    """
    # 1. Color Grading (Slight Contrast + Saturation)
    # Note: MoviePy v2 effects might differ, using standard valid ones or numpy
    try:
        # Simple color grading: increase saturation slightly
        clip = clip.with_effects([vfx.Colorx(1.1)]) 
    except Exception:
        pass

    # 2. Baked-in Flashes (Frame Processor)
    # We create a filter that brightens frames at beat times
    
    # Pre-calculate flash times relative to clip start
    flash_times = []
    if beat_info.drop_times:
        flash_times = [t - audio_start for t in beat_info.drop_times]
    elif beat_info.beat_times:
        # If no drops, flash on every 4th beat
        flash_times = [t - audio_start for i, t in enumerate(beat_info.beat_times) if i % 4 == 0]
    
    # Filter valid flash times for this clip
    valid_flashes = [t for t in flash_times if 0 <= t <= clip.duration]
    
    if not valid_flashes:
        return clip

    def flash_filter(get_frame, t):
        frame = get_frame(t)
        
        # Check if we are close to a flash time
        brightness = 1.0
        for ft in valid_flashes:
            dist = t - ft
            if 0 <= dist < 0.15: # Flash duration 0.15s
                # Decay intensity
                intensity = 1.0 - (dist / 0.15)
                brightness += 0.3 * intensity # Max +30% brightness
        
        if brightness > 1.0:
            # Apply brightness
            frame = np.clip(frame * brightness, 0, 255).astype(np.uint8)
            
        return frame

    return clip.transform(flash_filter)


def _stitch_clips_to_beat(
    clips: List[ClipInfo],
    beat_info: BeatInfo,
    target_duration: float,
    audio_start: float = 0.0,
) -> VideoFileClip:
    """
    Stitch clips together with beat-synced cuts.
    Now returns just the video clip (effects are baked in).
    """
    if not clips:
        raise ValueError("No clips to stitch!")

    # Load and prepare all clips
    prepared = []
    for clip_info in clips:
        try:
            vc = VideoFileClip(str(clip_info.path))
            vc = _resize_clip_to_vertical(vc)
            vc = _apply_ken_burns(vc)
            prepared.append(vc)
        except Exception as e:
            logger.warning(f"⚠️ Failed to load clip {clip_info.path.name}: {e}")
            continue

    if not prepared:
        raise ValueError("No clips could be loaded!")

    # ── Build cut points from drop_times ──────────────────
    drop_times = beat_info.drop_times or beat_info.beat_times or []
    MIN_SEGMENT = 1.5   # Minimum segment duration (seconds)
    MAX_SEGMENT = 6.0   # Force a cut if no drop for this long

    cut_points = [0.0]
    
    last_cut = 0.0
    for dt in drop_times:
        adjusted = dt - audio_start
        if adjusted <= 0:
            continue
        if adjusted >= target_duration:
            break

        gap = adjusted - last_cut
        if gap >= MIN_SEGMENT:
            cut_points.append(adjusted)
            last_cut = adjusted

    # Fill gaps > MAX_SEGMENT with intermediate cuts from beat_times
    beat_times = beat_info.beat_times or []
    filled_cuts = [cut_points[0]]
    
    for i in range(1, len(cut_points)):
        gap = cut_points[i] - filled_cuts[-1]
        if gap > MAX_SEGMENT:
            # Insert intermediate beat-based cuts
            for bt in beat_times:
                adj_bt = bt - audio_start
                if filled_cuts[-1] + MIN_SEGMENT < adj_bt < cut_points[i] - MIN_SEGMENT:
                    if adj_bt - filled_cuts[-1] >= MIN_SEGMENT:
                        filled_cuts.append(adj_bt)
                    if cut_points[i] - filled_cuts[-1] <= MAX_SEGMENT:
                        break
        filled_cuts.append(cut_points[i])

    # Ensure we reach target_duration
    if filled_cuts[-1] < target_duration - 0.5:
        filled_cuts.append(target_duration)
    
    cut_points = filled_cuts
    logger.info(f"   ✂️ {len(cut_points) - 1} beat-synced cuts planned")

    # ── Create segments with transitions ─────────────────
    segments = []
    clip_idx = 0
    transition_types = ["crossfade", "zoom", "crossfade"]  # Weighted pool

    for i in range(len(cut_points) - 1):
        seg_start = cut_points[i]
        seg_end = cut_points[i + 1]
        seg_duration = seg_end - seg_start

        if seg_duration <= 0.1:
            continue

        source_clip = prepared[clip_idx % len(prepared)]
        clip_idx += 1

        clip_dur = source_clip.duration
        if clip_dur <= 0:
            continue

        max_start = max(0, clip_dur - seg_duration)
        offset = random.uniform(0, max_start) if max_start > 0 else 0

        try:
            sub = source_clip.subclipped(offset, min(offset + seg_duration, clip_dur))

            if sub.duration < seg_duration:
                sub = sub.with_effects([vfx.TimeMirror()])
                sub = sub.subclipped(0, min(sub.duration, seg_duration))

            # Apply transition (skip first segment)
            if i > 0:
                t_type = random.choice(transition_types)
                sub = _apply_transition(sub, t_type)

            segments.append(sub)
        except Exception as e:
            logger.warning(f"⚠️ Subclip failed, using full clip: {e}")
            segments.append(source_clip.subclipped(0, min(seg_duration, clip_dur)))

    if not segments:
        logger.warning("⚠️ No segments created, looping first clip")
        clip = prepared[0]
        loops_needed = int(target_duration / clip.duration) + 1
        segments = [clip] * loops_needed

    final = concatenate_videoclips(segments, method="compose")

    if final.duration > target_duration:
        final = final.subclipped(0, target_duration)

    # Clean up sources
    for vc in prepared:
        try:
            vc.close()
        except Exception:
            pass
            
    # Apply baked-in cinematic effects and flashes
    final = _apply_cinematic_effects(final, beat_info, audio_start)

    return final


def _render_video(
    beat_info: BeatInfo,
    clips: List[ClipInfo],
    output_path: Path,
    target_duration: float,
    visualizer: bool = False,
    viz_theme: str = "neon",
    producer_tag: str = None,
    audio_start: float = 0.0,
    audio_end: float = None,
    gpu_enabled: bool = False,
) -> Path:
    """
    Core render function used by both full-beat and highlight video assembly.
    """
    if producer_tag is None:
        producer_tag = config.PRODUCER_TAG

    logger.info(f"🎬 Rendering: {output_path.name} ({target_duration:.0f}s)")

    # 1. Stitch clips together (returns single clip with effects baked in)
    video = _stitch_clips_to_beat(clips, beat_info, target_duration, audio_start=audio_start)
    logger.info("   📐 Clips stitched (effects baked in)")

    # 2. Load beat audio (trimmed to segment)
    audio = AudioFileClip(str(beat_info.path))
    if audio_end and audio_end > 0:
        audio = audio.subclipped(audio_start, min(audio_end, audio.duration))
    elif audio_start > 0:
        audio = audio.subclipped(audio_start, min(audio_start + target_duration, audio.duration))
    else:
        if audio.duration > target_duration:
            audio = audio.subclipped(0, target_duration)

    # 3. Replace video audio with beat
    video = video.with_audio(audio)
    logger.info("   🔊 Audio overlay applied")

    # 4. Add visual layers (Overlay stack)
    # Since flashes are now baked into 'video', we only need watermark/visualizer here
    layers = [video]

    # Visualizer overlay (waveform only)
    if visualizer:
        try:
            from modules.visualizer import generate_visualizer_overlay
            viz_overlay = generate_visualizer_overlay(
                beat_info, target_duration,
                theme_name=viz_theme,
                producer_tag=producer_tag,
                start_time=audio_start,
                end_time=audio_end,
            )
            layers.append(viz_overlay)
            logger.info(f"   🎨 Waveform visualizer overlay added ({viz_theme} theme)")
        except Exception as e:
            logger.error(f"   ❌ Visualizer failed: {e}", exc_info=True)
            # Fall back to watermark
            watermark = _create_producer_watermark(target_duration, producer_tag)
            if watermark:
                layers.append(watermark)
    else:
        # Always add producer watermark when visualizer is off
        watermark = _create_producer_watermark(target_duration, producer_tag)
        if watermark:
            layers.append(watermark)
            logger.info("   🏷️ Producer watermark added")

    # 5. Composite all layers
    final = CompositeVideoClip(layers, size=(TARGET_W, TARGET_H))
    final = final.with_duration(target_duration)

    # 6. Render
    logger.info(f"   🔄 Rendering to {output_path.name} ...")
    
    # Configure encoding settings
    codec = "libx264"
    preset = "ultrafast"
    ffmpeg_params = []
    
    if gpu_enabled:
        logger.info("   🚀 Using GPU Encoding (h264_nvenc)")
        codec = "h264_nvenc"
        preset = "p4"  # Use p4 (medium) preset
        # p4 = medium/fast, p1 = fastest, p7 = slowest/best
        ffmpeg_params = ["-rc", "vbr", "-cq", "24", "-b:v", "6M"]
    else:
        preset = "ultrafast"
        ffmpeg_params = ["-tune", "fastdecode"]

    final.write_videofile(
        str(output_path),
        fps=TARGET_FPS,
        codec=codec,
        audio_codec="aac",
        preset=preset, 
        bitrate=None if gpu_enabled else "6000k", # Let NVENC manage bitrate via params
        audio_bitrate="192k",
        threads=4,
        ffmpeg_params=ffmpeg_params,
        logger=None,
    )

    # Cleanup
    try:
        final.close()
        audio.close()
    except Exception:
        pass

    logger.info(f"   ✅ Video rendered: {output_path} ({output_path.stat().st_size / 1024 / 1024:.1f} MB)")
    return output_path


def assemble_video(
    beat_info: BeatInfo,
    clips: List[ClipInfo],
    visualizer: bool = False,
    viz_theme: str = "neon",
    producer_tag: str = None,
    gpu_enabled: bool = False,
) -> Path:
    """
    Assemble the full-beat video.

    Args:
        beat_info: Parsed beat metadata
        clips: List of downloaded YouTube clips
        visualizer: If True, overlay waveform visualizer
        viz_theme: Visualizer color theme
        producer_tag: Producer name tag (defaults to config.PRODUCER_TAG)

    Returns:
        Path to the rendered full-beat video
    """
    output_path = config.OUTPUT_DIR / f"{beat_info.filename}_full.mp4"
    target_duration = min(beat_info.duration, config.VIDEO_DURATION_MAX)

    return _render_video(
        beat_info, clips, output_path, target_duration,
        visualizer=visualizer, viz_theme=viz_theme,
        producer_tag=producer_tag,
        gpu_enabled=gpu_enabled,
    )


def assemble_highlight_videos(
    beat_info: BeatInfo,
    clips: List[ClipInfo],
    visualizer: bool = False,
    viz_theme: str = "neon",
    producer_tag: str = None,
    gpu_enabled: bool = False,
) -> List[Path]:
    """
    Assemble highlight clips from the best segments of a beat.

    Each highlight is a 30s (HIGHLIGHT_DURATION) clip from the most
    energetic section of the beat, with waveform visualizer and
    producer tag.

    Args:
        beat_info: Parsed beat metadata (must have best_segments populated)
        clips: List of downloaded YouTube clips
        visualizer: If True, overlay waveform visualizer
        viz_theme: Visualizer color theme
        producer_tag: Producer name tag

    Returns:
        List of paths to rendered highlight videos
    """
    if not beat_info.best_segments:
        logger.info("   ℹ️ No highlight segments detected (beat may be too short)")
        return []

    highlight_paths = []

    for i, (seg_start, seg_end) in enumerate(beat_info.best_segments, 1):
        seg_duration = seg_end - seg_start
        output_path = config.OUTPUT_DIR / f"{beat_info.filename}_highlight_{i}.mp4"

        logger.info(f"\n🎯 Highlight {i}/{len(beat_info.best_segments)}: {seg_start:.1f}s – {seg_end:.1f}s")

        try:
            path = _render_video(
                beat_info, clips, output_path, seg_duration,
                visualizer=visualizer, viz_theme=viz_theme,
                producer_tag=producer_tag,
                audio_start=seg_start, audio_end=seg_end,
                gpu_enabled=gpu_enabled,
            )
            highlight_paths.append(path)
        except Exception as e:
            logger.error(f"   ❌ Highlight {i} failed: {e}", exc_info=True)

    return highlight_paths
