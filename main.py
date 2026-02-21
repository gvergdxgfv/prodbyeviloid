"""
Beat-to-Instagram Reel Automation
==================================
Main CLI entrypoint that orchestrates the full pipeline:
Beat → Parse → YouTube Search → Download → Assemble Video → Generate Metadata → Upload to IG/YT

Usage:
    python main.py                        # Process all beats in beats/ folder
    python main.py --beat my_beat.wav     # Process a specific beat
    python main.py --no-upload            # Render video only, skip IG upload
    python main.py --dry-run              # Preview what would happen
    python main.py --visualizer           # Add audio-reactive visualizer overlay
    python main.py --youtube              # Also upload to YouTube Shorts
    python main.py --viz-theme fire       # Use fire color theme for visualizer
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import config
from modules.beat_parser import parse_beat, scan_beats_folder, BeatInfo
import modules.youtube_sourcer as youtube_sourcer
import modules.pexels_sourcer as pexels_sourcer
from modules.video_assembler import assemble_video, assemble_highlight_videos
from modules.metadata_gen import generate_metadata
from modules.ig_uploader import upload_to_instagram
from modules.ui import print_intro, get_help_header

# ── Logging ───────────────────────────────────────────────
LOG_FORMAT = "%(asctime)s │ %(message)s"
DATE_FORMAT = "%H:%M:%S"


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        datefmt=DATE_FORMAT,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(config.PROJECT_ROOT / "automation.log", encoding="utf-8"),
        ],
    )


# ── Pipeline ──────────────────────────────────────────────

def process_beat(
    beat_path: Path,
    no_upload: bool = False,
    dry_run: bool = False,
    visualizer: bool = False,
    viz_theme: str = "neon",
    youtube: bool = False,
    highlights: bool = True,
    gpu: bool = True,
    ig_highlight_only: bool = False,
) -> bool:
    """
    Run the full pipeline for a single beat file.

    Returns True if successful, False otherwise.
    """
    logger = logging.getLogger(__name__)

    # ── Step 1: Parse beat ────────────────────────────────
    logger.info("=" * 60)
    logger.info(f"🎵 PROCESSING: {beat_path.name}")
    logger.info("=" * 60)

    beat_info = parse_beat(beat_path)

    if dry_run:
        logger.info(f"\n📋 Beat Info:")
        logger.info(f"   Name:     {beat_info.name}")
        logger.info(f"   BPM:      {beat_info.bpm}")
        logger.info(f"   Genre:    {beat_info.genre}")
        logger.info(f"   Mood:     {beat_info.mood}")
        logger.info(f"   Energy:   {beat_info.energy}")
        logger.info(f"   Duration: {beat_info.duration:.1f}s")
        logger.info(f"   Keywords: {', '.join(beat_info.visual_keywords)}")
        if gpu:
             logger.info(f"   🚀 GPU Encoding: Enabled")

    # ── Step 2: Source Clips ──────────────────────────────
    logger.info("")
    logger.info("📹 Step 2: Sourcing clips (YouTube + Pexels)...")
    
    # YouTube
    yt_clips = []
    if not dry_run:  # In dry run we skip actual sourcing usually, but here we simulate
         try:
             yt_clips = youtube_sourcer.source_clips(beat_info, max_clips=config.MAX_CLIPS_PER_BEAT)
         except Exception as e:
             logger.error(f"❌ YouTube sourcing failed: {e}")

    # Pexels
    pexels_clips = []
    if not dry_run and getattr(config, "PEXELS_API_KEY", None):
         try:
             pexels_clips = pexels_sourcer.source_clips(beat_info, max_clips=config.MAX_CLIPS_PER_BEAT)
         except Exception as e:
             logger.error(f"❌ Pexels sourcing failed: {e}")
             
    clips = yt_clips + pexels_clips
    import random
    random.shuffle(clips)

    if dry_run:
        logger.info("")
        if visualizer:
            logger.info(f"🎨 Visualizer: enabled ({viz_theme} theme)")
        if highlights and beat_info.best_segments:
            logger.info(f"🎯 Highlights: {len(beat_info.best_segments)} segment(s) detected")
            for i, (s, e) in enumerate(beat_info.best_segments, 1):
                logger.info(f"   Highlight {i}: {s:.1f}s – {e:.1f}s")
        if youtube:
            logger.info("📺 YouTube Shorts: would upload after render")
        logger.info("\n🏃 DRY RUN complete — no files were downloaded or created.")
        return True

    if not clips:
        logger.error("❌ No clips could be sourced. Aborting.")
        return False

    # ── Step 3: Assemble video ────────────────────────────
    logger.info("")
    logger.info("🎬 Step 3: Assembling video...")
    try:
        output_path = assemble_video(
            beat_info, clips,
            visualizer=visualizer,
            viz_theme=viz_theme,
            gpu_enabled=gpu,
        )
    except Exception as e:
        logger.error(f"❌ Video assembly failed: {e}")
        return False

    # ── Step 3b: Assemble highlight clips ─────────────────
    highlight_paths = []
    if highlights and beat_info.best_segments:
        logger.info("")
        logger.info(f"🎯 Step 3b: Assembling {len(beat_info.best_segments)} highlight clip(s)...")
        try:
            highlight_paths = assemble_highlight_videos(
                beat_info, clips,
                visualizer=visualizer,
                viz_theme=viz_theme,
                gpu_enabled=gpu,
            )
        except Exception as e:
            logger.error(f"❌ Highlight assembly failed: {e}")

    # ── Step 4: Generate metadata ─────────────────────────
    logger.info("")
    logger.info("📝 Step 4: Generating Instagram metadata...")
    metadata = generate_metadata(beat_info)

    logger.info(f"\n📋 Reel Metadata:")
    logger.info(f"   Caption: {metadata.caption[:100]}...")
    logger.info(f"   Hashtags: {len(metadata.hashtags)} tags")

    # ── Step 5: Upload to Instagram ───────────────────────
    if no_upload:
        logger.info("")
        logger.info(f"⏭️ Upload skipped (--no-upload). Videos saved:")
        logger.info(f"   Full:  {output_path}")
        for hp in highlight_paths:
            logger.info(f"   Clip:  {hp}")
        logger.info(f"\n📋 Full caption for manual upload:\n{metadata.full_caption}")
        return True

    logger.info("")
    logger.info("📤 Step 5: Uploading to Instagram...")
    
    # IG always uploads the best 30s highlight (small file, fast upload)
    # Full video goes to YouTube only
    if highlight_paths:
        upload_path = highlight_paths[0]
        logger.info(f"   📎 Using highlight clip for IG (smaller upload): {upload_path.name}")
    else:
        upload_path = output_path
        logger.info(f"   📎 No highlights — using full video for IG: {upload_path.name}")

    ig_success = upload_to_instagram(upload_path, metadata)


    if ig_success:
        logger.info("")
        logger.info("🎉 " + "=" * 56)
        logger.info(f"🎉 DONE! '{beat_info.name}' is now live on Instagram!")
        logger.info("🎉 " + "=" * 56)
    else:
        logger.error(f"❌ Instagram upload failed for {beat_info.name}")

    # ── Step 6: Upload to YouTube Shorts ──────────────────
    yt_success = False
    if youtube:
        logger.info("")
        logger.info("📺 Step 6: Uploading to YouTube Shorts...")
        try:
            from modules.yt_uploader import upload_to_youtube

            # Upload full video
            yt_success = upload_to_youtube(
                output_path, metadata,
                beat_name=beat_info.name,
                genre=beat_info.genre,
                bpm=beat_info.bpm,
            )
            if yt_success:
                logger.info("🎉 YouTube Short (full beat) published!")
            else:
                logger.error("❌ YouTube upload failed (full beat)")

            # Upload highlights
            for i, hp in enumerate(highlight_paths, 1):
                logger.info(f"   📺 Uploading highlight {i}...")
                try:
                    ht_success = upload_to_youtube(
                        hp, metadata,
                        beat_name=f"{beat_info.name} (Highlight {i})",
                        genre=beat_info.genre,
                        bpm=beat_info.bpm,
                    )
                    if ht_success:
                        logger.info(f"   🎉 Highlight {i} published!")
                except Exception as e:
                    logger.error(f"   ❌ Highlight {i} upload error: {e}")

        except ImportError:
            logger.error(
                "❌ YouTube upload requires: pip install google-api-python-client google-auth-oauthlib"
            )
        except Exception as e:
            logger.error(f"❌ YouTube upload error: {e}")

    return ig_success or (no_upload and True)


# ── CLI ───────────────────────────────────────────────────

def process_beat_deforum(beat_path: Path) -> bool:
    """
    Process a beat using the Deforum AI pipeline.
    """
    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info(f"🎨 DEFORUM PROCESSING: {beat_path.name}")
    logger.info("=" * 60)
    
    try:
        beat_info = parse_beat(beat_path)
        
        output_dir = config.OUTPUT_DIR
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Try API first if enabled
        if config.SD_API_ENABLED:
            from modules.deforum_api import DeforumAPI
            api = DeforumAPI()
            if api.is_reachable():
                logger.info(f"🚀 Sending to Deforum API ({config.SD_WEBUI_URL})...")
                logger.info("   This may take a while. Check your A1111 console.")
                vid = api.generate_video(beat_info, output_dir / f"{beat_info.name}_deforum.mp4")
                if vid and vid.exists():
                    logger.info(f"✅ Deforum Video Saved: {vid}")
                    return True
                else:
                    logger.warning("ℹ️ Deforum API did not return video. Creating settings file instead...")
            else:
                logger.warning("ℹ️ Deforum API not reachable. Creating settings file instead...")
        
        # Fallback to settings file
        from modules.deforum_gen import generate_deforum_file
        f = generate_deforum_file(beat_info, output_dir)
        logger.info(f"✅ Deforum Settings Saved: {f}")
        return True
    except Exception as e:
        logger.error(f"❌ Deforum processing failed: {e}", exc_info=True)
        return False


def main():
    parser = argparse.ArgumentParser(
        description=get_help_header() + "\n\n🎵 Beat-to-Instagram Reel Automation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                              Process all beats in beats/ folder
  python main.py --watch --deforum            Auto-process new beats with Deforum AI
  python main.py --beat my_beat.wav           Process a specific beat file
  python main.py --deforum                    Process all beats with Deforum AI
  python main.py --no-upload                  Render videos only (no IG upload)
  python main.py --visualizer                 Add audio-reactive visualizer overlay
        """,
    )

    parser.add_argument("--beat", "-b", type=str, help="Process a specific beat file")
    parser.add_argument("--no-upload", action="store_true", help="Render video but skip Instagram upload")
    parser.add_argument("--dry-run", action="store_true", help="Preview without downloading or rendering")
    parser.add_argument("--visualizer", action="store_true", help="Enable audio-reactive visualizer overlay")
    parser.add_argument("--viz-theme", type=str, default="neon", choices=["neon", "fire", "ice", "purple"], help="Visualizer theme")
    parser.add_argument("--youtube", "-yt", action="store_true", help="Also upload to YouTube Shorts")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose/debug logging")
    parser.add_argument("--no-highlights", action="store_true", help="Skip generating highlight clips")
    parser.add_argument("--ig-highlight-only", action="store_true", help="Upload only the first highlight clip to Instagram")
    parser.add_argument("--deforum", action="store_true", help="Use Stable Diffusion Deforum pipeline instead of video clips")
    parser.add_argument("--watch", "-w", action="store_true", help="Watch beats/ folder and auto-process new files")
    parser.add_argument("--no-gpu", dest="gpu", action="store_false", default=True, help="Disable GPU acceleration (NVENC) for faster rendering")
    parser.add_argument("--ig-only", type=str, metavar="BEAT_STEM",
                        help="Skip full pipeline — upload existing highlight_1.mp4 to IG directly. "
                             "Provide the beat filename stem (without extension), e.g. \"hoodtrap khedoo;\"")

    args = parser.parse_args()

    # Setup
    setup_logging(args.verbose)
    # Show intro unless it's a specific sub-command that shouldn't have it (optional)
    # We print intro here so it shows on -h as well
    if len(sys.argv) > 1 and sys.argv[1] in ["-h", "--help"]:
        from modules.ui import print_banner
        print_banner()
    else:
        print_intro()

    logger = logging.getLogger(__name__)

    logger.info("🚀 Pipeline Startup")
    logger.info("=" * 60)

    # Validate config
    config.validate()

    if args.no_upload or args.dry_run:
        config.load_openai_key_only()
    else:
        config.load_api_keys()

    # ── WATCH MODE ──────────────────────────────────────────
    if args.watch:
        logger.info(f"👀 WATCHING {config.BEATS_DIR} for new beats...")
        logger.info(f"   Mode: {'DEFORUM 🎨' if args.deforum else 'VIDEO 📹'}")
        
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
        except ImportError:
            logger.error("❌ 'watchdog' library not found. Install it with: pip install watchdog")
            sys.exit(1)

        class BeatHandler(FileSystemEventHandler):
            def on_created(self, event):
                if event.is_directory: return
                path = Path(event.src_path)
                if path.suffix.lower() not in {".wav", ".mp3", ".flac", ".ogg", ".m4a"}: return
                
                logger.info(f"🆕 New beat detected: {path.name}")
                time.sleep(2) # Wait for file write to complete
                
                try:
                    if args.deforum:
                        process_beat_deforum(path)
                    else:
                        process_beat(
                            path, 
                            no_upload=args.no_upload,
                            dry_run=args.dry_run,
                            visualizer=args.visualizer,
                            viz_theme=args.viz_theme,
                            youtube=args.youtube,
                            highlights=not args.no_highlights,
                            gpu=args.gpu,
                            ig_highlight_only=args.ig_highlight_only,
                        )
                    logger.info("✅ Auto-processing complete. Watching for next beat...")
                except Exception as e:
                    logger.error(f"❌ Auto-processing failed: {e}")

        observer = Observer()
        observer.schedule(BeatHandler(), str(config.BEATS_DIR), recursive=False)
        observer.start()
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt:
            observer.stop()
        observer.join()
        sys.exit(0)

    # ── IG-ONLY MODE (upload existing highlight_1 directly) ──
    if args.ig_only:
        from modules.beat_parser import parse_beat
        from modules.metadata_gen import generate_metadata
        from modules.ig_uploader import upload_to_instagram

        stem = args.ig_only
        # Find the highlight_1 file in output dir
        highlight_path = config.OUTPUT_DIR / f"{stem}_highlight_1.mp4"
        if not highlight_path.exists():
            # Try case-insensitive glob fallback
            matches = list(config.OUTPUT_DIR.glob(f"*highlight_1*.mp4"))
            matches = [m for m in matches if stem.lower() in m.name.lower()]
            if matches:
                highlight_path = matches[0]
            else:
                logger.error(f"❌ highlight_1 not found for '{stem}' in {config.OUTPUT_DIR}")
                logger.info(f"   Available highlight files:")
                for f in sorted(config.OUTPUT_DIR.glob('*highlight_1*.mp4')):
                    logger.info(f"   - {f.name}")
                sys.exit(1)

        logger.info(f"🎵 Found highlight: {highlight_path.name} ({highlight_path.stat().st_size / 1024 / 1024:.1f} MB)")

        # Find the original beat file to generate metadata
        beat_path = None
        for ext in [".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac"]:
            candidate = config.BEATS_DIR / f"{stem}{ext}"
            if candidate.exists():
                beat_path = candidate
                break
        if not beat_path:
            # Try glob
            matches = list(config.BEATS_DIR.glob(f"{stem}.*"))
            if matches:
                beat_path = matches[0]

        if beat_path:
            logger.info(f"🎵 Generating metadata from: {beat_path.name}")
            from modules.beat_parser import parse_beat
            beat_info = parse_beat(beat_path)
        else:
            logger.warning(f"⚠️ Beat file not found for '{stem}', using minimal metadata")
            from modules.beat_parser import BeatInfo
            from pathlib import Path as _Path
            beat_info = BeatInfo(
                name=stem.replace(";", "").strip().title(),
                filename=stem,
                path=_Path(stem),
                bpm=120, duration=30, energy="high",
                genre="hip hop", mood="vibes",
                brightness="neutral", rhythm="bouncy",
                visual_keywords=["trap", "aesthetic"],
                best_segments=[],
            )

        metadata = generate_metadata(beat_info)
        logger.info(f"📝 Metadata ready | Caption: {metadata.caption[:60]}...")
        logger.info(f"   Hashtags: {len(metadata.hashtags)} | YT Title: {metadata.yt_title}")

        logger.info("📤 Uploading to Instagram...")
        success = upload_to_instagram(highlight_path, metadata)
        if success:
            logger.info("🎉 IG upload complete!")
        else:
            logger.error("❌ IG upload failed")
        sys.exit(0 if success else 1)

    # ── BATCH MODE ──────────────────────────────────────────
    # Determine which beats to process
    if args.beat:
        beat_path = Path(args.beat)
        if not beat_path.exists():
            beat_path = config.BEATS_DIR / args.beat
        if not beat_path.exists():
            logger.error(f"❌ Beat file not found: {args.beat}")
            logger.info(f"   Place your beats in: {config.BEATS_DIR}")
            sys.exit(1)
        beats_to_process = [beat_path]
    else:
        beats_to_process = [
            f for f in sorted(config.BEATS_DIR.iterdir())
            if f.suffix.lower() in {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac"}
        ]

    if not beats_to_process:
        logger.warning(f"⚠️ No beat files found in {config.BEATS_DIR}")
        logger.info(f"   Drop your .wav/.mp3 files into: {config.BEATS_DIR}")
        sys.exit(0)

    logger.info(f"📂 Found {len(beats_to_process)} beat(s) to process\n")

    # Process each beat
    results = []
    for i, beat_path in enumerate(beats_to_process, 1):
        logger.info(f"\n[{i}/{len(beats_to_process)}] Processing {beat_path.name}")

        start_time = time.time()
        success = False

        try:
            if args.deforum:
                success = process_beat_deforum(beat_path)
            else:
                success = process_beat(
                    beat_path,
                    no_upload=args.no_upload,
                    dry_run=args.dry_run,
                    visualizer=args.visualizer,
                    viz_theme=args.viz_theme,
                    youtube=args.youtube,
                    highlights=not args.no_highlights,
                    gpu=args.gpu,
                    ig_highlight_only=args.ig_highlight_only,
                )
        except Exception as e:
            logger.error(f"❌ Unexpected error processing {beat_path.name}: {e}", exc_info=True)

        elapsed = time.time() - start_time
        results.append((beat_path.name, success, elapsed))
        logger.info(f"⏱️ Took {elapsed:.1f}s\n")

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("📊 SUMMARY")
    logger.info("=" * 60)

    for name, success, elapsed in results:
        status = "✅" if success else "❌"
        logger.info(f"  {status} {name} ({elapsed:.1f}s)")

    total_success = sum(1 for _, s, _ in results if s)
    logger.info(f"\n  {total_success}/{len(results)} beat(s) processed successfully")


if __name__ == "__main__":
    main()
