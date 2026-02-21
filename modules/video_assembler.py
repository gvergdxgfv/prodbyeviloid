"""
Video Assembler Module (FFmpeg Native)
======================================
Combines downloaded YouTube clips with a beat audio file into
9:16 vertical videos suitable for Instagram Reels / YouTube Shorts.

Fully hardware-accelerated via FFmpeg.
"""

import logging
import subprocess
from pathlib import Path
from typing import List
import os

from modules.beat_parser import BeatInfo
from modules.youtube_sourcer import ClipInfo
import config

logger = logging.getLogger(__name__)

TARGET_W = config.VIDEO_WIDTH   # 1080
TARGET_H = config.VIDEO_HEIGHT  # 1920
TARGET_FPS = 30


def _build_visualizer_filtergraph(
    audio_idx: int,
    video_link_out: str,
    beat_info: BeatInfo,
    theme_name: str,
    producer_tag: str
) -> tuple[str, str]:
    """Returns the filtergraph string and the new video output pad name."""
    
    font_path = "/Windows/Fonts/ariblk.ttf"
    if not os.path.exists("C:/Windows/Fonts/ariblk.ttf"):
        font_path = "/Windows/Fonts/arial.ttf"
        
    theme_colors = {
        "neon": "0x00FFCC",
        "fire": "0xFF8C00",
        "ice": "0x82C8FF",
        "purple": "0xC850FF",
    }
    theme_color = theme_colors.get(theme_name, "0x00FFCC")
    beat_name = beat_info.name
    if not producer_tag:
        producer_tag = config.PRODUCER_TAG
        
    lines = []
    # 1. Generate showwaves from audio
    lines.append(f"[{audio_idx}:a]showwaves=s=960x400:mode=cline:colors={theme_color}:scale=sqrt[wave]")
    # 2. Overlay waveform onto current video
    lines.append(f"[{video_link_out}][wave]overlay=(W-w)/2:(H-h)/2+100[v_viz]")
    # 3. Add text (beat name)
    lines.append(f"[v_viz]drawtext=fontfile='{font_path}':text='{beat_name}':fontcolor=white:fontsize=50:x=(w-text_w)/2:y=(h-text_h)/2-150[v_txt1]")
    # 4. Add text (producer tag)
    lines.append(f"[v_txt1]drawtext=fontfile='{font_path}':text='{producer_tag}':fontcolor=white:fontsize=40:x=(w-text_w)/2:y=h-150[v_txt2]")
    
    return ";".join(lines), "v_txt2"


def _render_ffmpeg_video(
    beat_info: BeatInfo,
    clips: List[ClipInfo],
    output_path: Path,
    target_duration: float,
    visualizer: bool = False,
    viz_theme: str = "neon",
    producer_tag: str = None,
    audio_start: float = 0.0,
    audio_end: float = None,
    gpu_enabled: bool = True,
) -> Path:
    logger.info(f"🎞️ Building FFmpeg assembly for {output_path.name}")
    
    fade_duration = 0.4
    selected_clips = []
    current_time = 0.0
    
    for clip in clips:
        clip_dur = clip.duration
        if clip_dur < fade_duration * 3:
            continue 
            
        selected_clips.append(clip)
        if len(selected_clips) == 1:
            current_time += clip_dur
        else:
            current_time += (clip_dur - fade_duration)
            
        if current_time >= target_duration:
            break

    if not selected_clips:
        raise ValueError("No valid clips found to assemble video")

    # Repeat clips if we didn't have enough to fill duration
    idx = 0
    while current_time < target_duration:
        clip = selected_clips[idx % len(selected_clips)]
        selected_clips.append(clip)
        current_time += (clip.duration - fade_duration)
        idx += 1

    cmd = ["ffmpeg", "-y"]
    
    # 1. Input audio
    cmd.extend(["-ss", str(audio_start)])
    if audio_end:
        cmd.extend(["-to", str(audio_end)])
    cmd.extend(["-i", str(beat_info.path)])
    
    # 2. Input video clips
    for clip in selected_clips:
        cmd.extend(["-i", str(clip.path)])

    filter_lines = []
    
    # 3. Scale and normalize all input videos
    for i in range(len(selected_clips)):
        v_idx = i + 1
        scale_filter = (
            f"[{v_idx}:v]scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
            f"crop={TARGET_W}:{TARGET_H},setsar=1,fps={TARGET_FPS},format=yuv420p[v_s{i}]"
        )
        filter_lines.append(scale_filter)

    # 4. Crossfade all clips sequentially
    current_v_out = "v_s0"
    if len(selected_clips) > 1:
        current_offset = selected_clips[0].duration - fade_duration
        
        for i in range(1, len(selected_clips)):
            next_v_in = f"v_s{i}"
            next_v_out = f"v_c{i}"
            
            xfade = f"[{current_v_out}][{next_v_in}]xfade=transition=fade:duration={fade_duration}:offset={current_offset:.2f}[{next_v_out}]"
            filter_lines.append(xfade)
            
            current_v_out = next_v_out
            current_offset += (selected_clips[i].duration - fade_duration)

    # 4.5 Apply Cinematic Color Grading & Beat-Reactive Zoom
    cinematic_filter = "eq=contrast=1.1:saturation=1.2:gamma=0.95,vignette=PI/4,noise=alls=4:allf=t+u"
    
    z_exprs = []
    drops = beat_info.drop_times or beat_info.beat_times or []
    
    clip_audio_end = audio_end if audio_end is not None else (audio_start + target_duration)
    
    # Keep the absolute drop times directly from the audio file parser!
    valid_drops = [t for t in drops if audio_start <= t <= clip_audio_end]
    valid_drops = valid_drops[:25] # Cap to prevent cmd line length limits
    
    for dt in valid_drops:
        # zoom to 105% instantly on drop, ease out back to 100% over 0.25 seconds
        # Note: We must compare `in_time + audio_start` against the absolute `dt`
        # Using `in_time` is required because `xfade` changes FFmpeg `t` timescale.
        expr = f"if(between(in_time+{audio_start},{dt},{dt+0.25}), 1.05-(in_time+{audio_start}-{dt})*0.2, 1)"
        z_exprs.append(expr)
        
    z_full = "1"
    if z_exprs:
        for expr in reversed(z_exprs):
            z_full = expr.replace(", 1)", f", {z_full})")
            
    zoompan_filter = f"zoompan=z='{z_full}':d=1:x='iw/2-(iw/zoom)/2':y='ih/2-(ih/zoom)/2':s={TARGET_W}x{TARGET_H}:fps={TARGET_FPS}"
    
    v_fx_out = "v_fx"
    if valid_drops:
        filter_lines.append(f"[{current_v_out}]{zoompan_filter},{cinematic_filter}[{v_fx_out}]")
    else:
        filter_lines.append(f"[{current_v_out}]{cinematic_filter}[{v_fx_out}]")
        
    current_v_out = v_fx_out

    # 5. Apply Visualizer if requested
    if visualizer:
        viz_lines, current_v_out = _build_visualizer_filtergraph(
            audio_idx=0,
            video_link_out=current_v_out,
            beat_info=beat_info,
            theme_name=viz_theme,
            producer_tag=producer_tag
        )
        filter_lines.append(viz_lines)
    else:
        # If no visualizer, still draw producer watermark
        watermark_lines, current_v_out = _build_producer_watermark_filtergraph(
            video_link_out=current_v_out,
            producer_tag=producer_tag
        )
        filter_lines.append(watermark_lines)
        
    filtergraph = ";".join(filter_lines)
    
    cmd.extend(["-filter_complex", filtergraph])
    cmd.extend(["-map", f"[{current_v_out}]"])
    cmd.extend(["-map", "0:a"]) # Output the original audio

    # Encoding parameters
    if gpu_enabled:
        logger.info("   🚀 Using GPU Encoding (h264_nvenc)")
        cmd.extend([
            "-c:v", "h264_nvenc",
            "-preset", "p1",
            "-rc", "vbr", "-cq", "28", "-b:v", "5M", "-spatial_aq", "1"
        ])
    else:
        logger.info("   🐢 Using CPU Encoding (libx264 ultrafast)")
        cmd.extend([
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "23"
        ])

    cmd.extend([
        "-c:a", "aac",
        "-b:a", "192k",
        "-t", str(target_duration), # Hard stop!
        str(output_path)
    ])

    logger.debug(f"Render CMD: {' '.join(cmd)}")
    
    try:
        subprocess.run(cmd, check=True)
        return output_path
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ FFmpeg assembled render failed: {e}")
        raise

def _build_producer_watermark_filtergraph(
    video_link_out: str,
    producer_tag: str
) -> tuple[str, str]:
    if not producer_tag:
        producer_tag = config.PRODUCER_TAG
    font_path = "/Windows/Fonts/ariblk.ttf"
    if not os.path.exists("C:/Windows/Fonts/ariblk.ttf"):
        font_path = "/Windows/Fonts/arial.ttf"
        
    line = f"[{video_link_out}]drawtext=fontfile='{font_path}':text='{producer_tag}':fontcolor=white:fontsize=32:x=(w-text_w)/2:y=h-100:bordercolor=black:borderw=1[v_mark]"
    return line, "v_mark"


def assemble_video(
    beat_info: BeatInfo,
    clips: List[ClipInfo],
    visualizer: bool = False,
    viz_theme: str = "neon",
    producer_tag: str = None,
    gpu_enabled: bool = True,
) -> Path:
    output_path = config.OUTPUT_DIR / f"{beat_info.filename}_full.mp4"
    target_duration = min(beat_info.duration, config.VIDEO_DURATION_MAX)

    return _render_ffmpeg_video(
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
    gpu_enabled: bool = True,
) -> List[Path]:
    if not beat_info.best_segments:
        logger.info("   ℹ️ No highlight segments detected")
        return []

    highlight_paths = []

    for i, (seg_start, seg_end) in enumerate(beat_info.best_segments, 1):
        seg_duration = seg_end - seg_start
        output_path = config.OUTPUT_DIR / f"{beat_info.filename}_highlight_{i}.mp4"

        logger.info(f"\n🎯 Highlight {i}/{len(beat_info.best_segments)}: {seg_start:.1f}s – {seg_end:.1f}s")

        try:
            path = _render_ffmpeg_video(
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
