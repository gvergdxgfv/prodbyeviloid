import logging
import json
import math
from pathlib import Path
from typing import Dict, List, Optional
import google.generativeai as genai

import config
from modules.beat_parser import BeatInfo

logger = logging.getLogger(__name__)

class DeforumSettingsGenerator:
    """
    Generates Deforum (Stable Diffusion) settings tailored to a beat.
    Creates a JSON/text file with prompts and math schedules synced to the beat.
    """
    
    def __init__(self):
        genai.configure(api_key=config.GEMINI_API_KEY)
        # Use flash model for speed and cost
        self.model = genai.GenerativeModel("gemini-1.5-flash")

    def generate_settings(self, beat_info: BeatInfo, fps: int = 30) -> str:
        """
        Generate the full Deforum settings string (prompts + motion).
        """
        logger.info(f"🎨 Generating Deforum settings for '{beat_info.name}' ({beat_info.bpm} BPM)")
        
        # 1. Generate Visual Prompts via Gemini
        prompts = self._generate_prompts(beat_info)
        
        # 2. Build Schedule (Intro, Drop, Outro)
        # We need to map prompts to specific frames
        prompt_schedule = self._build_prompt_schedule(prompts, beat_info, fps)
        
        # 3. Generate Math Schedules (Motion)
        motion_settings = self._generate_motion_settings(beat_info, fps)
        
        # 4. Assemble Output
        output = []
        output.append("=== DEFORUM SETTINGS FOR: " + beat_info.name + " ===")
        output.append(f"BPM: {beat_info.bpm} | FPS: {fps}")
        output.append("-" * 30)
        output.append("\n[PROMPTS (JSON format)]")
        output.append(json.dumps(prompt_schedule, indent=4))
        output.append("-" * 30)
        output.append("\n[MOTION SETTINGS (Math Strings)]")
        for key, val in motion_settings.items():
            output.append(f"{key}: {val}")
        output.append("-" * 30)
        output.append("\n[INSTRUCTIONS]")
        output.append("1. Copy the PROMPTS JSON into the 'Prompts' tab in Deforum.")
        output.append("2. Copy the MOTION SETTINGS into the 'Keyframes' > 'Motion' tab.")
        output.append("3. Ensure output FPS matches the FPS above.")
        
        return "\n".join(output)

    def _generate_prompts(self, beat_info: BeatInfo) -> Dict[str, str]:
        """
        Use Gemini to create visual prompts for Intro, Build-up, Drop, and Outro.
        """
        prompt = f"""You are a VJ creating visual prompts for an AI video generation (Stable Diffusion Deforum).
The video must sync with a music beat.

Beat Info:
- Genre: {beat_info.genre or "Unknown"}
- Mood: {beat_info.mood or "Unknown"}
- Energy: {beat_info.energy}
- Visual Keywords: {', '.join(beat_info.visual_keywords[:5])}

Generate 4 distinct visual prompts for these sections:
1. INTRO: Sets the scene, atmospheric (0s - drop)
2. BUILD: Increasing tension, faster movement (pre-drop)
3. DROP: Explosive, high energy, abstract or chaotic, intense colors (at the drop)
4. OUTRO: Fading out, calmer (end)

Format requirements:
- Stable Diffusion prompt style (comma separated keywords)
- Include "masterpiece, best quality, 8k, trending on artstation"
- NO negative prompts
- Output JSON format: {{"intro": "...", "build": "...", "drop": "...", "outro": "..."}}
"""
        try:
            from modules import ai_helper
            text = ai_helper.generate_text(prompt)
            clean_text = text.replace("```json", "").replace("```", "").strip()
            return json.loads(clean_text)
        except Exception as e:
            logger.error(f"⚠️ Failed to generate prompt with AI: {e}")
            # Fallback prompts
            base = f"abstract {beat_info.genre} visuals, {beat_info.mood}, 4k, trending on artstation"
            return {
                "intro": f"cinematic establishing shot, {base}, slow motion",
                "build": f"accelerating tunnel, {base}, neon lights",
                "drop": f"explosive psychedelic geometric patterns, {base}, intricate details, vibrant",
                "outro": f"fading smoke, {base}, calm"
            }

    def _build_prompt_schedule(self, prompts: Dict[str, str], beat_info: BeatInfo, fps: int) -> Dict[str, str]:
        """
        Map prompts to frame numbers based on beat structure.
        """
        schedule = {}
        
        # Frame 0: Intro
        schedule["0"] = prompts.get("intro", "")
        
        # Find drop time (if any)
        drop_time = 0.0
        if beat_info.drop_times:
            drop_time = beat_info.drop_times[0]
        elif beat_info.beat_times:
            # Fallback: drop at ~15s or 16th beat
            drop_time = beat_info.beat_times[min(16, len(beat_info.beat_times)-1)]
            
        drop_frame = int(drop_time * fps)
        
        # Build-up (4 beats before drop)
        if drop_frame > 60:
            build_frame = max(0, drop_frame - (4 * 60)) # Approx 4 sec before
            schedule[str(build_frame)] = prompts.get("build", "")
            
        # Drop
        schedule[str(drop_frame)] = prompts.get("drop", "")
        
        # Outro (at 80% duration or known end)
        duration = beat_info.duration or 60.0 # Default 60s if unknown
        outro_frame = int(duration * 0.85 * fps)
        schedule[str(outro_frame)] = prompts.get("outro", "")
        
        return schedule

    def _generate_motion_settings(self, beat_info: BeatInfo, fps: int) -> Dict[str, str]:
        """
        Generate audio-reactive math formulas for Deforum motion.
        """
        bpm = beat_info.bpm or 120
        fps = float(fps)
        
        # Basic math helper strings
        # beat_freq = bpm / 60
        # Deforum uses 't' for time or 'f' for frame? 
        # Usually Deforum allows math expressions. 
        # Common reactive pattern: "1.0 + (bass_level * 0.05)"
        
        # Since we don't have the audio-reactivity baked INTO Deforum (unless using the extension's audio mode),
        # we can provide "pseudo-audio-reactive" formulas using sine waves synced to BPM.
        
        beat_period_frames = (60 / bpm) * fps
        
        # Zoom: Pulse on every beat
        # sin(frame / period * 2pi) -> peaks every beat
        zoom_formula = f"1.0 + (0.05 * max(0, sin(frame / {beat_period_frames:.2f} * 6.28)))"
        
        # Translation Z: Move forward constantly, boost on beat
        trans_z = f"10 + (2 * max(0, sin(frame / {beat_period_frames:.2f} * 6.28)))"
        
        # Rotation: Slight sway
        rot_z = f"0.5 * sin(frame / {beat_period_frames*4:.2f} * 6.28)" # Sway every 4 beats
        
        return {
            "zoom": zoom_formula,
            "translation_x": "0",
            "translation_y": "0",
            "translation_z": trans_z,
            "rotation_3d_x": "0",
            "rotation_3d_y": "0",
            "rotation_3d_z": rot_z,
        }

def generate_deforum_file(beat_info: BeatInfo, output_dir: Path) -> Path:
    """Wrapper to write settings to file"""
    generator = DeforumSettingsGenerator()
    content = generator.generate_settings(beat_info)
    
    filename = output_dir / f"{beat_info.name}_deforum.txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)
    
    return filename
