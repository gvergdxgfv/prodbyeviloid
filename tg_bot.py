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
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
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


SUPPORTED_AUDIO = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac"}
MAX_FILE_SIZE_MB = 50  # Telegram file size limit


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



# In-memory user settings (reset on restart)
# Maps user_id -> "VIDEO" or "DEFORUM"
USER_MODES = {}

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

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming audio/document files."""
    message = update.message
    user_id = update.effective_user.id
    
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

        # Step 3: Assemble full video
        output_path = assemble_video(
            beat_info, clips,
            visualizer=True,
            viz_theme="neon",
        )
        logger.info(f"✅ Full video: {output_path}")

        # Step 4: Assemble highlights
        highlight_paths = []
        if beat_info.best_segments:
            await status_msg.edit_text(f"⏳ Processing...\n\n{beat_summary}\n\n✂️ Rendering {len(beat_info.best_segments)} highlight clips...")
            highlight_paths = assemble_highlight_videos(
                beat_info, clips,
                visualizer=True,
                viz_theme="neon",
            )

        # Step 5: Generate metadata
        await status_msg.edit_text(f"⏳ Processing...\n\n{beat_summary}\n\n🤖 Generating captions & hashtags...")
        metadata = generate_metadata(beat_info)

        # Done!
        await status_msg.edit_text(f"✅ Done!\n\n{beat_summary}\n\n📤 Sending videos...")

        # Send full video
        with open(output_path, "rb") as f:
            await message.reply_video(
                video=f,
                caption=f"🎬 Full Video — {beat_info.name}",
                supports_streaming=True,
                read_timeout=120,
                write_timeout=120,
            )

        # Send highlights
        for i, hp in enumerate(highlight_paths):
            with open(hp, "rb") as f:
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

        # Update status
        n_videos = 1 + len(highlight_paths)
        await status_msg.edit_text(
            f"✅ Complete! Sent {n_videos} video(s) + captions\n\n{beat_summary}"
        )

    except Exception as e:
        logger.error(f"❌ Pipeline failed: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Processing failed:\n`{str(e)[:200]}`")



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

    # Build application
    app = Application.builder().token(token).build()

    # Register handlers
    # Register handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("mode_video", mode_video_command))
    app.add_handler(CommandHandler("mode_deforum", mode_deforum_command))

    # Handle audio files, documents, and voice messages
    app.add_handler(MessageHandler(
        filters.AUDIO | filters.Document.ALL | filters.VOICE,
        handle_audio,
    ))

    # Start polling
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
