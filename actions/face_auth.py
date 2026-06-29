# face_auth.py
"""
Face ID Verification and registration using the webcam and Gemini Vision.
Greets Fatih on verification, and locks PC on intruder detection.
"""
import io
import json
import os
import sys
import subprocess
from pathlib import Path

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

_BASE = _base_dir()
_CONFIG_DIR = _BASE / "config"
_FACE_REF_PATH = _CONFIG_DIR / "face_reference.jpg"
_KEYS_PATH = _CONFIG_DIR / "api_keys.json"

def _get_api_key() -> str:
    try:
        cfg = json.loads(_KEYS_PATH.read_text(encoding="utf-8"))
        return cfg.get("gemini_api_key", "")
    except Exception:
        return ""

def _log_player(player, msg: str):
    if not player:
        return
    try:
        if hasattr(player, "write_log"):
            player.write_log(msg)
        elif hasattr(player, "_log") and hasattr(player._log, "append_log"):
            player._log.append_log(msg)
    except Exception:
        pass

def register_face_id(player=None) -> str:
    """Capture webcam frame and save as face reference image."""
    try:
        from actions.screen_processor import _capture_camera
        _CONFIG_DIR.mkdir(exist_ok=True) if hasattr(_CONFIG_DIR, "mkdir") else os.makedirs(_CONFIG_DIR, exist_ok=True)
        
        _log_player(player, "SYS: Opening camera to register Face ID...")
            
        img_bytes, _ = _capture_camera()
        _FACE_REF_PATH.write_bytes(img_bytes)
        
        msg = "Face ID successfully registered for Fatih. Reference photo saved."
        _log_player(player, f"SYS: {msg}")
        return msg
    except Exception as e:
        err = f"Face ID registration failed: {e}"
        _log_player(player, f"SYS: [ERROR] {err}")
        return err

def verify_face_id(player=None, speak=None) -> str:
    """Capture camera, compare to reference photo using Gemini, lock if intruder."""
    if not _FACE_REF_PATH.exists():
        return "Face ID not registered. Please register Face ID first."

    api_key = _get_api_key()
    if not api_key:
        return "API key not configured."

    try:
        import google.generativeai as genai
        from actions.screen_processor import _capture_camera

        _log_player(player, "[Security] Analyzing webcam face...")

        # 1. Capture current camera
        ref_bytes = _FACE_REF_PATH.read_bytes()
        curr_bytes, _ = _capture_camera()

        # 2. Configure Gemini
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")

        prompt = """Compare these two webcam images. 
The first image is the reference photo of the authorized owner, Fatih.
The second image is the current user sitting in front of the laptop.
Analyze if the person in the second image is Fatih.
- If it IS Fatih: Reply with exactly "VERIFIED"
- If it is someone else (or no face is visible): Reply with exactly "INTRUDER"
Keep your response to exactly one word: VERIFIED or INTRUDER."""

        contents = [
            prompt,
            {"mime_type": "image/jpeg", "data": ref_bytes},
            {"mime_type": "image/jpeg", "data": curr_bytes}
        ]

        response = model.generate_content(contents)
        result = response.text.strip().upper()

        if "VERIFIED" in result:
            msg = "Face ID Verified. Welcome back, Fatih."
            _log_player(player, f"SEC: {msg}")
            if speak:
                speak("Welcome back, Fatih. System cleared.")
            return "VERIFIED"
        else:
            msg = "INTRUDER DETECTED! Locking workstation."
            _log_player(player, f"ALERT: {msg}")
            if speak:
                speak("Security breach! Unauthorized user detected. Locking computer.")
            
            # Execute lock screen command on Windows
            subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"])
            return "INTRUDER"

    except Exception as e:
        print(f"[FaceAuth] Verification failed: {e}")
        return f"Face ID verification failed: {e}"
