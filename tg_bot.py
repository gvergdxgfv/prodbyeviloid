"""
Telegram Bot for Beat-to-Video Pipeline
=========================================
Drop a beat file (.wav / .mp3) in Telegram, and the bot
processes it through the full pipeline and sends back
the rendered videos + captions/hashtags.

Usage:
    python tg_bot.py

Requires TG_BOT_TOKEN in .env
"""

import os
import sys
import logging
import asyncio
import time
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler,
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-7s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Load config
import config

# Import pipeline modules
from modules.beat_parser import parse_beat
from modules.youtube_sourcer import source_clips
from modules.video_assembler import assemble_video, assemble_highlight_videos
from modules.metadata_gen import generate_metadata
from modules.ai_helper import generate_beat_name


SUPPORTED_AUDIO = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac"}
MAX_FILE_SIZE_MB = 50  # Telegram file size limit

import subprocess

def _compress_for_telegram(video_path: Path) -> Path:
    """
    Compress a video to fit under Telegram's 50MB bot API limit.
    Returns the path to the compressed video, or the original if it fails/is small enough.
    """
    # 48MB safety limit
    MAX_BYTES = 48 * 1024 * 1024 
    
    if video_path.stat().st_size <= MAX_BYTES:
        return video_path
        
    logger.info(f"⚠️ Video {video_path.name} is {video_path.stat().st_size / 1e6:.1f}MB (over 50MB limit). Compressing for Telegram preview...")
    
    compressed_path = video_path.with_name(f"{video_path.stem}_tg_compressed.mp4")
    
    if compressed_path.exists():
        return compressed_path
        
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", "scale=-2:720", # Downscale to 720p for the chat preview
        "-c:v", "libx264",
        "-profile:v", "high",
        "-pix_fmt", "yuv420p",
        "-crf", "28",          # High compression
        "-preset", "faster",
        "-movflags", "+faststart",
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar", "48000",
        str(compressed_path)
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        if compressed_path.exists() and compressed_path.stat().st_size <= MAX_BYTES:
            logger.info("✅ Compression successful.")
            return compressed_path
        else:
            logger.warning("⚠️ Compression failed to shrink below 50MB limit. Using original (might fail).")
            return compressed_path
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Compression failed: {e}")
        return video_path


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    await update.message.reply_text(
        "🎵 *Beat-to-Video Bot* by prodbyeviloid\n\n"
        "Drop me an audio file (.wav, .mp3) and I'll:\n"
        "1️⃣ Analyze the beat (BPM, energy, mood)\n"
        "2️⃣ Source matching visuals from YouTube\n"
        "3️⃣ Render a full video with waveform visualizer\n"
        "4️⃣ Generate 30s highlight clips of the best parts\n"
        "5️⃣ Create IG + YT Shorts optimized captions & hashtags\n\n"
        "Just send me an audio file to get started! 🚀",
        parse_mode="Markdown",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    await update.message.reply_text(
        "📖 *How to use:*\n\n"
        "• Send any audio file (.wav, .mp3, .flac, .ogg)\n"
        "• Wait for processing (this takes a few minutes)\n"
        "• Receive your video(s) + captions + hashtags\n\n"
        "⚙️ *Settings:*\n"
        f"• Max file size: {MAX_FILE_SIZE_MB}MB\n"
        f"• Highlight duration: {config.HIGHLIGHT_DURATION}s\n"
        f"• Max highlights: {config.MAX_HIGHLIGHTS}\n"
        f"• Producer tag: {config.PRODUCER_TAG}\n\n"
        "📍 *Commands:*\n"
        "/start — Welcome message\n"
        "/help — This help text",
        parse_mode="Markdown",
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages like greetings or questions."""
    text = update.message.text.lower() if update.message.text else ""
    if any(word in text for word in ["hi", "hello", "hey", "guide", "help", "yo", "wassup"]):
        await help_command(update, context)
    else:
        await update.message.reply_text(
            "Send me an audio file (.mp3, .wav) to generate a beat video! 🎵\n\n"
            "Type /help to see the full guide."
        )



# In-memory user settings (reset on restart)
# Maps user_id -> "VIDEO" or "DEFORUM"
USER_MODES = {}
USER_SETTINGS = {}

def get_settings(user_id):
    if user_id not in USER_SETTINGS:
        USER_SETTINGS[user_id] = {
            "theme": "neon",
            "visualizer": True,
        }
    return USER_SETTINGS[user_id]

async def mode_video_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Switch to Video Generation mode."""
    user_id = update.effective_user.id
    USER_MODES[user_id] = "VIDEO"
    await update.message.reply_text("📹 **Mode set to: VIDEO GENERATION**\nSend an audio file to get a beat video.")

async def mode_deforum_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Switch to Deforum Settings mode."""
    user_id = update.effective_user.id
    USER_MODES[user_id] = "DEFORUM"
    await update.message.reply_text(
        "🎨 **Mode set to: DEFORUM SETTINGS**\n"
        "Send an audio file, and I'll generate a settings file for Stable Diffusion Deforum.\n"
        "(Prompts + Audio-reactive motion schedules)"
    )

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show interactive settings menu."""
    user_id = update.effective_user.id
    settings = get_settings(user_id)
    
    keyboard = [
        [
            InlineKeyboardButton(f"{'✅ ' if settings['theme'] == 'neon' else ''}Neon", callback_data="set_theme_neon"),
            InlineKeyboardButton(f"{'✅ ' if settings['theme'] == 'fire' else ''}Fire", callback_data="set_theme_fire"),
        ],
        [
            InlineKeyboardButton(f"{'✅ ' if settings['theme'] == 'ice' else ''}Ice", callback_data="set_theme_ice"),
            InlineKeyboardButton(f"{'✅ ' if settings['theme'] == 'purple' else ''}Purple", callback_data="set_theme_purple"),
        ],
        [
            InlineKeyboardButton(f"{'✅ ' if settings['visualizer'] else '❌ '}Visualizer Enabled", callback_data="toggle_viz"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("⚙️ *Video Generation Settings:*\nClick to toggle.", reply_markup=reply_markup, parse_mode="Markdown")

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming audio/document files."""
    message = update.message
    user_id = update.effective_user.id
    settings = get_settings(user_id)
    
    # Default to VIDEO mode if not set
    current_mode = USER_MODES.get(user_id, "VIDEO")

    # Get the file object (audio or document)
    if message.audio:
        file_obj = message.audio
        file_name = file_obj.file_name or f"beat_{file_obj.file_unique_id}.mp3"
    elif message.document:
        file_obj = message.document
        file_name = file_obj.file_name or f"beat_{file_obj.file_unique_id}"
    elif message.voice:
        file_obj = message.voice
        file_name = f"voice_{file_obj.file_unique_id}.ogg"
    else:
        return

    # Check file extension
    ext = Path(file_name).suffix.lower()
    if ext not in SUPPORTED_AUDIO:
        await message.reply_text(
            f"❌ Unsupported format: `{ext}`\n"
            f"Supported: {', '.join(SUPPORTED_AUDIO)}",
            parse_mode="Markdown",
        )
        return

    # Check file size
    if file_obj.file_size and file_obj.file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
        await message.reply_text(f"❌ File too large! Max size is {MAX_FILE_SIZE_MB}MB.")
        return

    # Send processing message
    mode_text = "Video Generation" if current_mode == "VIDEO" else "Deforum Settings"
    status_msg = await message.reply_text(f"⏳ Processing ({mode_text})...\n\n🎵 Downloading file...")

    try:
        # Download file
        beat_dir = config.BEATS_DIR
        beat_dir.mkdir(parents=True, exist_ok=True)
        beat_path = beat_dir / file_name

        tg_file = await file_obj.get_file()
        await tg_file.download_to_drive(str(beat_path))
        logger.info(f"📥 Downloaded: {beat_path}")

        # Step 1: Parse beat
        await status_msg.edit_text("⏳ Processing...\n\n🎵 Analyzing beat structure...")
        beat_info = parse_beat(beat_path)
        
        # Step 1.5: Invent a better name using Gemini unconditionally
        await status_msg.edit_text("⏳ Processing...\n\n🤖 Naming your track...")
        
        # Run LLM prediction in a thread to avoid blocking asyncio
        new_name = await asyncio.to_thread(
            generate_beat_name, 
            genre=beat_info.genre or "Hip-Hop", 
            mood=beat_info.mood or "Dark", 
            bpm=beat_info.bpm, 
            energy=beat_info.energy,
            original_name=beat_info.name
        )
        
        if new_name and new_name != beat_info.name:
            logger.info(f"✨ AI renamed track: '{beat_info.name}' -> '{new_name}'")
            beat_info.name = new_name

        beat_summary = (
            f"🎵 *{beat_info.name}*\n"
            f"🥁 BPM: {beat_info.bpm} | ⚡ Energy: {beat_info.energy}\n"
            f"🎸 Genre: {beat_info.genre or 'detecting...'} | 🌙 Mood: {beat_info.mood or 'detecting...'}\n"
            f"⏱ Duration: {beat_info.duration:.0f}s | 💥 Drops: {len(beat_info.drop_times)}"
        )
        
        # ── DEFORUM MODE ─────────────────────────────────────────────────────────
        if current_mode == "DEFORUM":
            await status_msg.edit_text(f"⏳ Generating Deforum Settings...\n\n{beat_summary}\n\n🤖 AI generating prompts & motion schedules...")
            
            output_dir = config.OUTPUT_DIR
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Check if API is enabled and reachable
            if config.SD_API_ENABLED:
                from modules.deforum_api import DeforumAPI
                api = DeforumAPI()
                
                if api.is_reachable():
                    await status_msg.edit_text(f"⏳ Sending to Deforum API ({config.SD_WEBUI_URL})...\n\nThis may take a while to render on your GPU.")
                    video_path = api.generate_video(beat_info, output_dir / f"{beat_info.name}_deforum.mp4")
                    
                    if video_path and video_path.exists():
                        await status_msg.edit_text(f"✅ Deforum Render Complete!\n\n{beat_summary}\n\n📤 Sending video...")
                        with open(video_path, "rb") as f:
                            await message.reply_video(
                                video=f,
                                caption=f"🎨 Deforum AI Video — {beat_info.name}",
                                supports_streaming=True
                            )
                        return
                    else:
                        await status_msg.edit_text("⚠️ Deforum API finished but no video found. Falling back to settings file.")
                else:
                    await status_msg.edit_text("⚠️ SD WebUI API enabled but unreachable. Falling back to settings file.")

            # Fallback: Generate settings file
            from modules.deforum_gen import generate_deforum_file
            settings_path = generate_deforum_file(beat_info, output_dir)
            
            await status_msg.edit_text(f"✅ Deforum Settings Ready!\n\n{beat_summary}\n\n📤 Sending file...")
            
            with open(settings_path, "rb") as f:
                await message.reply_document(
                    document=f,
                    filename=settings_path.name,
                    caption=f"🎨 Deforum Settings for {beat_info.name}\n\nCopy prompts to 'Prompts' tab and motion strings to 'Keyframes' tab in automatic1111."
                )
            return
        
        # ── VIDEO MODE (Standard Pipeline) ───────────────────────────────────────
        await status_msg.edit_text(f"⏳ Processing...\n\n{beat_summary}\n\n🔍 Sourcing matching video clips...")

        # Step 2: Source clips
        clips = source_clips(beat_info)
        if not clips:
            await status_msg.edit_text("❌ Couldn't find suitable video clips. Please try a different beat.")
            return

        await status_msg.edit_text(f"⏳ Processing...\n\n{beat_summary}\n\n📹 Found {len(clips)} clips. Rendering video...")

        loop = asyncio.get_running_loop()
        last_update_time = 0.0

        def _sync_progress(percent: float):
            nonlocal last_update_time
            now = time.time()
            if now - last_update_time > 2.0 or percent >= 1.0:
                last_update_time = now
                p_bar = int(percent * 10)
                bar_str = "█" * p_bar + "░" * (10 - p_bar)
                text = f"⏳ Processing...\n\n{beat_summary}\n\n🎬 Rendering Full Video...\n[{bar_str}] {int(percent*100)}%"
                asyncio.run_coroutine_threadsafe(status_msg.edit_text(text), loop)

        # Step 3: Assemble full video in a background thread
        output_path = await asyncio.to_thread(
            assemble_video,
            beat_info, clips,
            visualizer=settings["visualizer"],
            viz_theme=settings["theme"],
            gpu_enabled=True,
            progress_callback=_sync_progress
        )
        logger.info(f"✅ Full video: {output_path}")

        # Step 4: Assemble highlights
        highlight_paths = []
        if beat_info.best_segments:
            await status_msg.edit_text(f"⏳ Processing...\n\n{beat_summary}\n\n✂️ Rendering {len(beat_info.best_segments)} highlight clips...")
            last_update_time = 0.0

            def _sync_hl_progress(idx: int, percent: float):
                nonlocal last_update_time
                now = time.time()
                if now - last_update_time > 2.0 or percent >= 1.0:
                    last_update_time = now
                    p_bar = int(percent * 10)
                    bar_str = "█" * p_bar + "░" * (10 - p_bar)
                    text = f"⏳ Processing...\n\n{beat_summary}\n\n✂️ Rendering Highlight {idx}/{len(beat_info.best_segments)}...\n[{bar_str}] {int(percent*100)}%"
                    asyncio.run_coroutine_threadsafe(status_msg.edit_text(text), loop)

            highlight_paths = await asyncio.to_thread(
                assemble_highlight_videos,
                beat_info, clips,
                visualizer=settings["visualizer"],
                viz_theme=settings["theme"],
                gpu_enabled=True,
                progress_callback=_sync_hl_progress
            )

        # Step 5: Generate metadata
        await status_msg.edit_text(f"⏳ Processing...\n\n{beat_summary}\n\n🤖 Generating captions & hashtags...")
        metadata = generate_metadata(beat_info)

        # Done!
        await status_msg.edit_text(f"✅ Done!\n\n{beat_summary}\n\n📤 Sending videos...")

        # Send full video
        tg_full_video_path = _compress_for_telegram(output_path)
        with open(tg_full_video_path, "rb") as f:
            await message.reply_video(
                video=f,
                caption=f"🎬 Full Video — {beat_info.name}",
                supports_streaming=True,
                read_timeout=120,
                write_timeout=120,
            )

        # Send highlights
        for i, hp in enumerate(highlight_paths):
            tg_hp = _compress_for_telegram(hp)
            with open(tg_hp, "rb") as f:
                await message.reply_video(
                    video=f,
                    caption=f"✂️ Highlight {i+1} — {beat_info.name}",
                    supports_streaming=True,
                    read_timeout=120,
                    write_timeout=120,
                )

        # Send metadata
        ig_text = (
            "📱 *Instagram Caption:*\n\n"
            f"{metadata.full_caption}\n\n"
            "─────────────────────"
        )
        yt_text = (
            "📺 *YouTube Shorts:*\n\n"
            f"*Title:* {metadata.yt_title}\n\n"
            f"*Description:*\n{metadata.yt_description}\n\n"
            f"*Tags:* {', '.join(metadata.yt_tags)}"
        )

        await message.reply_text(ig_text, parse_mode="Markdown")
        await message.reply_text(yt_text, parse_mode="Markdown")

        # Update status and attach interactive buttons
        n_videos = 1 + len(highlight_paths)
        import uuid
        job_id = str(uuid.uuid4())[:8]
        
        # Highlight videos are prioritized for Shorts/Reels because of the algorithm length caps
        upload_target = highlight_paths[0] if highlight_paths else output_path
        
        context.user_data[job_id] = {
            "video_path": upload_target,
            "metadata": metadata,
            "beat_name": beat_info.name,
            "genre": beat_info.genre,
            "bpm": beat_info.bpm
        }

        keyboard = [
            [
                InlineKeyboardButton("💬 Upload to Instagram", callback_data=f"ig_{job_id}"),
            ],
            [
                InlineKeyboardButton("📺 Upload to YouTube", callback_data=f"yt_{job_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await status_msg.edit_text(
            f"✅ Complete! Sent {n_videos} video(s)\n\n{beat_summary}\n\nReady to publish?",
            reply_markup=reply_markup
        )

    except Exception as e:
        logger.error(f"❌ Pipeline failed: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Processing failed:\n`{str(e)[:200]}`")


async def handle_upload_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the interactive upload buttons."""
    query = update.callback_query
    await query.answer()

    data = query.data
    action, job_id = data.split("_", 1)
    
    orig_text = query.message.text
    
    if job_id not in context.user_data:
        await query.edit_message_text(text=f"{orig_text}\n\n❌ Upload data expired. Please process the beat again.")
        return

    job_data = context.user_data[job_id]
    video_path = job_data["video_path"]
    metadata = job_data["metadata"]
    
    if action == "ig":
        await query.edit_message_text(text=f"{orig_text}\n\n⏳ Uploading to Instagram...")
        try:
            from modules.ig_uploader import upload_to_instagram
            success = upload_to_instagram(video_path, metadata)
            if success:
                await query.edit_message_text(text=f"{orig_text}\n\n✅ Successfully uploaded to Instagram!")
            else:
                await query.edit_message_text(text=f"{orig_text}\n\n❌ Failed to upload to Instagram. Check logs.")
        except Exception as e:
            logger.error(f"IG Upload Error: {e}", exc_info=True)
            await query.edit_message_text(text=f"{orig_text}\n\n❌ IG Upload Error:\n`{e}`", parse_mode="Markdown")
            
    elif action == "yt":
        await query.edit_message_text(text=f"{orig_text}\n\n⏳ Uploading to YouTube Shorts...")
        try:
            from modules.yt_uploader import upload_to_youtube
            success = upload_to_youtube(
                video_path, metadata,
                beat_name=job_data['beat_name'],
                genre=job_data['genre'],
                bpm=job_data['bpm']
            )
            if success:
                await query.edit_message_text(text=f"{orig_text}\n\n✅ Successfully uploaded to YouTube Shorts!")
            else:
                await query.edit_message_text(text=f"{orig_text}\n\n❌ Failed to upload to YouTube.")
        except ImportError:
            await query.edit_message_text(text=f"{orig_text}\n\n❌ YouTube uploader not installed.")
        except Exception as e:
            logger.error(f"YT Upload Error: {e}", exc_info=True)
            await query.edit_message_text(text=f"{orig_text}\n\n❌ YT Upload Error:\n`{e}`", parse_mode="Markdown")

async def handle_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle settings menu inline buttons."""
    query = update.callback_query
    data = query.data
    user_id = update.effective_user.id
    settings = get_settings(user_id)

    if data.startswith("set_theme_"):
        theme = data.replace("set_theme_", "")
        settings["theme"] = theme
    elif data == "toggle_viz":
        settings["visualizer"] = not settings["visualizer"]
    else:
        return
        
    await query.answer("Settings updated!")
    
    keyboard = [
        [
            InlineKeyboardButton(f"{'✅ ' if settings['theme'] == 'neon' else ''}Neon", callback_data="set_theme_neon"),
            InlineKeyboardButton(f"{'✅ ' if settings['theme'] == 'fire' else ''}Fire", callback_data="set_theme_fire"),
        ],
        [
            InlineKeyboardButton(f"{'✅ ' if settings['theme'] == 'ice' else ''}Ice", callback_data="set_theme_ice"),
            InlineKeyboardButton(f"{'✅ ' if settings['theme'] == 'purple' else ''}Purple", callback_data="set_theme_purple"),
        ],
        [
            InlineKeyboardButton(f"{'✅ ' if settings['visualizer'] else '❌ '}Visualizer Enabled", callback_data="toggle_viz"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Only edit if we successfully generated a new markup to avoid "Message is not modified" Exception
    try:
        await query.edit_message_reply_markup(reply_markup=reply_markup)
    except Exception:
        pass


def main():
    """Start the Telegram bot."""
    # Load config
    config.load_openai_key_only()  # Loads GEMINI_API_KEY

    token = os.getenv("TG_BOT_TOKEN", "").strip()
    if not token:
        print("❌ TG_BOT_TOKEN not set in .env!")
        print("   Get one from @BotFather on Telegram")
        sys.exit(1)

    print("🤖 Starting Beat-to-Video Telegram Bot...")
    print("   Press Ctrl+C to stop\n")

    # Build application with increased timeouts
    app = Application.builder().token(token).read_timeout(30).write_timeout(30).build()

    # Register handlers
    # Register handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("settings", settings_command))
    app.add_handler(CommandHandler("mode_video", mode_video_command))
    app.add_handler(CommandHandler("mode_deforum", mode_deforum_command))

    # Handle audio files, documents, and voice messages
    app.add_handler(MessageHandler(
        filters.AUDIO | filters.Document.ALL | filters.VOICE,
        handle_audio,
    ))
    
    # Handle text messages
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_text,
    ))
    
    app.add_handler(CallbackQueryHandler(handle_upload_callback, pattern="^(ig_|yt_)"))
    app.add_handler(CallbackQueryHandler(handle_settings_callback, pattern="^(set_theme_|toggle_)"))

    # Start polling
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
