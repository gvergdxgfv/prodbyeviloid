import logging
import requests
from google import genai
import config

logger = logging.getLogger(__name__)

GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-pro",
]

def generate_text(prompt: str, model_name: str = None) -> str:
    """
    Generate text using Gemini models in rotation (via google-genai SDK), 
    then fallback to Grok.
    """
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    
    # Try preferred model first if specified, otherwise rotate
    models_to_try = [model_name] if model_name else GEMINI_MODELS
    
    # If starting rotation, ensure all models are tried
    if not model_name:
        models_to_try = GEMINI_MODELS
    else:
        # Try requested one, then others if it fails
        others = [m for m in GEMINI_MODELS if m != model_name]
        models_to_try.extend(others)

    for model_id in models_to_try:
        try:
            logger.info(f"   🤖 Trying Gemini Model: {model_id}...")
            response = client.models.generate_content(
                model=model_id,
                contents=prompt
            )
            return response.text.strip()
        except Exception as e:
            err_str = str(e).lower()
            is_quota_error = "429" in err_str or "quota" in err_str or "limit" in err_str or "resource exhausted" in err_str or "not found" in err_str
            
            if is_quota_error:
                logger.warning(f"⚠️ Quota/Error for {model_id} ({e}). Trying next...")
                continue
            else:
                logger.error(f"❌ Error with {model_id}: {e}")
                continue
    
    # If all Gemini models fail, try OpenRouter
    logger.warning("⚠️ All Gemini models exhausted! Switching to OpenRouter fallback...")
    return _generate_with_openrouter(prompt)

def _generate_with_openrouter(prompt: str) -> str:
    """Generate text using OpenRouter API."""
    if not config.OPENROUTER_API_KEY:
        logger.error("❌ OpenRouter API Key not set! Cannot fallback.")
        return ""

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "HTTP-Referer": "https://github.com/Start-Automating/Antigravity",
        "X-Title": "Antigravity Bot",
    }
    payload = {
        "messages": [
            {"role": "system", "content": "You are a helpful assistant found in a music video production pipeline. Answer concisely."},
            {"role": "user", "content": prompt}
        ],
        "model": "z-ai/glm-4.5-air", 
        "stream": False,
        "temperature": 0.7,
        "max_tokens": 1024,
    }
    
    try:
        logger.info("   🤖 Calling OpenRouter API (GLM-4.5 Air)...")
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"].strip()
        logger.info("   ✅ OpenRouter responded successfully")
        return content
    except Exception as e:
        logger.error(f"❌ OpenRouter API Error: {e}")
        try:
             if 'resp' in locals(): logger.error(f"   Response: {resp.text}")
        except: pass
        return ""
