import logging
import sys
from pathlib import Path
from modules.ffmpeg_video_assembler import _render_ffmpeg_video
from modules.beat_parser import parse_beat
from modules.youtube_sourcer import ClipInfo
import os
import shutil

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_ffmpeg_assembler():
    beats_dir = Path("beats")
    if not beats_dir.exists():
        logger.error("No beats dir")
        return
        
    beat_path = Path("beats/AYUSHCOLLAB.mp3")
    if not beat_path.exists():
        logger.error("Beats dir doesn't have AYUSHCOLLAB.mp3")
        return
        
    beat_info = parse_beat(beat_path)
    
    # Let's mock some clips using any mp4s in clips/
    clips = []
    clips_dir = Path(f"clips/{beat_info.filename}")
    if clips_dir.exists():
        for f in clips_dir.glob("*.mp4"):
            # Mock get duration
            clips.append(ClipInfo(path=f, duration=10.0, source_url="", title=f.name))
            
    if len(clips) < 2:
        logger.error("Need at least 2 clips in clips directory.")
        return
        
    output_path = Path("output/test_ffmpeg_assembly.mp4")
    
    logger.info("Starting encode...")
    try:
        _render_ffmpeg_video(
            beat_info=beat_info,
            clips=clips,
            output_path=output_path,
            target_duration=15.0,
            visualizer=True,
            viz_theme="neon",
            producer_tag="Eviloid",
            audio_start=0.0,
            gpu_enabled=True,
        )
        logger.info("Success! Check output/test_ffmpeg_assembly.mp4")
    except Exception as e:
        logger.exception("Failed to assemble:")

if __name__ == "__main__":
    test_ffmpeg_assembler()
