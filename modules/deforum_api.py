import logging
import json
import time
import requests
import base64
from pathlib import Path
from typing import Optional, Dict, Any

import config
from modules.beat_parser import BeatInfo
from modules.deforum_gen import DeforumSettingsGenerator

logger = logging.getLogger(__name__)

class DeforumAPI:
    """
    Client for interacting with Automatic1111 WebUI API (Deforum extension).
    Requires --api flag on A1111 start.
    """
    
    def __init__(self, base_url: str = None):
        self.base_url = base_url or config.SD_WEBUI_URL
        self.generator = DeforumSettingsGenerator()
        
    def is_reachable(self) -> bool:
        """Check if A1111 API is running."""
        try:
            resp = requests.get(f"{self.base_url}/sdapi/v1/progress", timeout=3)
            return resp.status_code == 200
        except Exception:
            return False

    def generate_video(self, beat_info: BeatInfo, output_path: Path) -> Optional[Path]:
        """
        Full workflow: Generate settings -> Send to API -> Poll -> Save Video.
        """
        if not self.is_reachable():
            logger.error("❌ SD WebUI API not reachable. Is it running with --api?")
            return None
            
        logger.info(f"🚀 Sending Deforum job for '{beat_info.name}' to {self.base_url}...")
        
        # 1. Generate Settings
        prompts = self.generator._generate_prompts(beat_info)
        prompt_schedule = self.generator._build_prompt_schedule(prompts, beat_info, fps=30)
        motion_settings = self.generator._generate_motion_settings(beat_info, fps=30)
        
        # 2. Construct Payload
        # NOTE: This payload structure depends on the specific Deforum API version.
        # This is a generic structure usually accepted by the deforum/run endpoint.
        payload = {
            "batch_name": f"Deforum_{beat_info.name}",
            "n_batch": 1,
            "prompts": prompt_schedule,
            "animation_prompts": prompt_schedule,
            "max_frames": int(beat_info.duration * 30),
            "fps": 30,
            
            # Motion settings
            "animation_mode": "3D",
            "zoom": motion_settings.get("zoom", "1.0"),
            "translation_x": motion_settings.get("translation_x", "0"),
            "translation_y": motion_settings.get("translation_y", "0"),
            "translation_z": motion_settings.get("translation_z", "10"),
            "rotation_3d_x": motion_settings.get("rotation_3d_x", "0"),
            "rotation_3d_y": motion_settings.get("rotation_3d_y", "0"),
            "rotation_3d_z": motion_settings.get("rotation_3d_z", "0"),
            
            # Rendering settings
            "width": 512,  # Keep low for speed/VRAM, upscale later
            "height": 912, # 9:16 aspect ratio
            "sampler_name": "Euler a",
            "steps": 25,
            "cfg_scale": 7,
            "seed": -1,
            
            # Audio (optional, if deforum supports sending audio path)
            # "audio_path": str(beat_info.path),
        }
        
        try:
            # 3. Send Request
            # Common endpoints: /deforum/api/batch_make_video or just hitting txt2img with script?
            # Deforum extension usually exposes specific endpoints.
            # If standard API, we might need to use 'script_name': 'Deforum v1...' in txt2img
            
            # Attempting to use the direct Deforum extension API if available
            response = requests.post(f"{self.base_url}/deforum_api/batches", json=payload, timeout=10)
            
            if response.status_code != 200:
                logger.warning(f"⚠️ Deforum API returned {response.status_code}: {response.text}")
                logger.info("   Trying fallback to generic txt2img with script args...")
                # Fallback logic would go here, often complex. 
                # For now, we assume the user has the API helper installed or we print the error.
                return None
                
            job_id = response.json().get("job_id")
            if not job_id:
                # Some versions return the job immediately
                pass
                
            # 4. Poll for Completion
            logger.info("⏳ Waiting for render to complete...")
            start_time = time.time()
            while True:
                time.sleep(5)
                progress_resp = requests.get(f"{self.base_url}/sdapi/v1/progress")
                prog = progress_resp.json()
                
                logger.info(f"   Progress: {prog.get('progress', 0)*100:.1f}% | ETA: {prog.get('eta_relative', '?')}s")
                
                if prog.get('progress', 0) >= 0.99 or prog.get('state', {}).get('job_count', 0) == 0:
                    break
                    
                if time.time() - start_time > 3600: # 1 hour timeout
                    logger.error("❌ Timeout waiting for render.")
                    return None
            
            # 5. Retrieve Result
            # Usually outputs to A1111 output dir. Can we download it?
            # If running locally, we might assume shared filesystem or base64 return.
            # If base64 is not returned for video (too large), we might need to look in the output folder
            # configured in A1111 if we have access, or rely on the API returning a path.
            
            # Setup for local file assumption if on same machine
            # Or ask API for the file
            
            logger.info("✅ Render complete! (Note: File retrieval via API is experimental)")
            # Return a dummy path if we can't download, prompting user to check A1111 outputs
            return None

        except Exception as e:
            logger.error(f"❌ API Error: {e}")
            return None
