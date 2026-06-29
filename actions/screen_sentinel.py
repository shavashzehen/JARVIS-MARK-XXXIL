#screen_sentinel.py
"""
Always-on screen security monitoring for Jarvis.
Periodically captures the screen and uses Gemini Vision
to detect security threats like phishing, scams, malware, etc.
"""
import io
import json
import sys
import threading
import time
import hashlib
from pathlib import Path

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

_BASE        = _base_dir()
_CONFIG_PATH = _BASE / "config" / "api_keys.json"

def _load_config() -> dict:
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _get_api_key() -> str:
    return _load_config().get("gemini_api_key", "")


# ═══════════════════════════════════════════════════════════════
# SCREEN CAPTURE (reuse from screen_processor)
# ═══════════════════════════════════════════════════════════════

def _capture_screen() -> bytes:
    """Capture the primary screen and return PNG bytes."""
    try:
        import mss
        import mss.tools
    except ImportError:
        raise RuntimeError("mss not installed")
    
    with mss.mss() as sct:
        monitors = sct.monitors
        target = monitors[1] if len(monitors) > 1 else monitors[0]
        shot = sct.grab(target)
        return mss.tools.to_png(shot.rgb, shot.size)


def _compress(raw_png: bytes, max_size: int = 300_000) -> bytes:
    """Compress image if too large."""
    if len(raw_png) <= max_size:
        return raw_png
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(raw_png))
        # Scale down
        ratio = (max_size / len(raw_png)) ** 0.5
        new_w = max(int(img.width * ratio), 200)
        new_h = max(int(img.height * ratio), 200)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=60)
        return buf.getvalue()
    except Exception:
        return raw_png


# ═══════════════════════════════════════════════════════════════
# THREAT ANALYSIS
# ═══════════════════════════════════════════════════════════════

_SECURITY_PROMPT = """You are a cybersecurity AI analyst. You are analyzing up to two screenshots: the first is the Laptop Screen, and the second (if present) is the Android Phone Screen. Your critical task is to monitor BOTH screens to see who is using them and identify any unauthorized usage.

CHECK FOR:
1. Phishing websites (fake login pages, suspicious URLs)
2. Scam popups or fake virus warnings
3. Suspicious download prompts
4. Malware/ransomware indicators
5. Fake tech support messages
6. Data exposure (passwords, credit cards visible)
7. Suspicious browser extensions or toolbars
8. Social engineering attempts
9. Unsafe website certificates
10. Unauthorized user access. The authorized owner of both the laptop and phone is Fatih. Look closely at both screens to see who is using them. If the screen content, profiles, open accounts, chats, emails, or settings show that someone else (an unauthorized user or intruder) is using either device or accessing private data, flag it immediately. If you can infer who the user is from the screen, mention it.
11. Any other security concern

RESPONSE FORMAT:
- If SAFE: Reply with exactly "SAFE"
- If THREAT or unauthorized usage detected: Reply with "THREAT: <brief description of the danger or unauthorized access, specifying which device (laptop/phone) and who is using it or what is being accessed>" (max 2 sentences)

Be conservative — only flag genuine threats or clear signs of unauthorized usage, not normal usage by Fatih."""


def _analyze_for_threats(laptop_image: bytes, phone_image: bytes | None = None) -> str | None:
    """
    Send screenshot(s) to Gemini for security and unauthorized access analysis.
    """
    try:
        import google.generativeai as genai
        
        api_key = _get_api_key()
        if not api_key:
            return None
        
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")
        
        contents = [_SECURITY_PROMPT]
        
        mime_lap = "image/png" if laptop_image[:4] == b'\x89PNG' else "image/jpeg"
        contents.append({"mime_type": mime_lap, "data": laptop_image})
        
        if phone_image:
            mime_ph = "image/png" if phone_image[:4] == b'\x89PNG' else "image/jpeg"
            contents.append({"mime_type": mime_ph, "data": phone_image})
            
        response = model.generate_content(contents)
        result = response.text.strip()
        
        if result.upper().startswith("SAFE"):
            return None
        
        if result.upper().startswith("THREAT"):
            return result
        
        threat_keywords = ["phishing", "scam", "malware", "suspicious", "danger", "warning", "fake", "unauthorized"]
        if any(kw in result.lower() for kw in threat_keywords):
            return f"THREAT: {result}"
        
        return None
        
    except Exception as e:
        print(f"[Sentinel] Analysis error: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
# SENTINEL ENGINE
# ═══════════════════════════════════════════════════════════════

_sentinel_running = False
_sentinel_thread = None
_sentinel_interval = 60  # seconds
_last_threat_hash = None
_player_ref = None
_speak_ref = None


def _screen_hash(image_bytes: bytes) -> str:
    """Generate a hash of the image to avoid duplicate alerts."""
    return hashlib.md5(image_bytes[:10000]).hexdigest()


def _sentinel_loop():
    """Main sentinel monitoring loop."""
    global _sentinel_running, _last_threat_hash
    
    print(f"[Sentinel] Started — checking every {_sentinel_interval}s")
    if _player_ref:
        _player_ref.write_log("SYS: Screen Sentinel ACTIVE")
    
    while _sentinel_running:
        try:
            # 1. Capture Laptop Screen
            raw_png = _capture_screen()
            compressed = _compress(raw_png)
            
            # 2. Try to capture Phone Screen if active
            phone_compressed = None
            try:
                from actions.phone_control import _list_devices
                from actions.screen_processor import _capture_phone
                devices = _list_devices()
                if devices:
                    serial = None
                    if _player_ref and hasattr(_player_ref, "active_device") and _player_ref.active_device:
                        serial = _player_ref.active_device
                    else:
                        serial = devices[0]["serial"]
                    
                    phone_png, _ = _capture_phone(serial)
                    phone_compressed = _compress(phone_png)
            except Exception:
                pass
            
            # Combined hash for change tracking
            current_hash = _screen_hash(compressed)
            if phone_compressed:
                current_hash += "_" + _screen_hash(phone_compressed)
            
            # 3. Webcam Face ID Verification Check
            try:
                from actions.face_auth import verify_face_id, _FACE_REF_PATH
                if _FACE_REF_PATH.exists():
                    face_res = verify_face_id(player=_player_ref, speak=_speak_ref)
                    if face_res == "INTRUDER":
                        time.sleep(10)
                        continue
            except Exception as e:
                print(f"[Sentinel] Face ID check error: {e}")

            # 4. Analyze for Threats/Unauthorized Users
            threat = _analyze_for_threats(compressed, phone_compressed)
            
            if threat and current_hash != _last_threat_hash:
                _last_threat_hash = current_hash
                print(f"[Sentinel] {threat}")
                
                if _player_ref:
                    _player_ref.write_log(f"ALERT: {threat}")
                
                if _speak_ref:
                    desc = threat.replace("THREAT:", "").strip()
                    _speak_ref(f"Security alert, sir. {desc}")
            
        except Exception as e:
            print(f"[Sentinel] Loop error: {e}")
        
        # Sleep in small increments
        for _ in range(int(_sentinel_interval)):
            if not _sentinel_running:
                break
            time.sleep(1)
    
    print("[Sentinel] Stopped")
    if _player_ref:
        _player_ref.write_log("SYS: Screen Sentinel STOPPED")


def start_sentinel(player=None, speak=None, interval: int = 60) -> str:
    """Start the screen sentinel background monitor."""
    global _sentinel_running, _sentinel_thread, _sentinel_interval
    global _player_ref, _speak_ref, _last_threat_hash
    
    if _sentinel_running:
        return "Screen Sentinel is already running."
    
    _player_ref = player
    _speak_ref = speak
    _sentinel_interval = max(15, interval)
    _last_threat_hash = None
    _sentinel_running = True
    
    _sentinel_thread = threading.Thread(target=_sentinel_loop, daemon=True)
    _sentinel_thread.start()
    
    return f"Screen Sentinel activated — monitoring every {_sentinel_interval} seconds."


def stop_sentinel() -> str:
    """Stop the screen sentinel."""
    global _sentinel_running
    
    if not _sentinel_running:
        return "Screen Sentinel is not running."
    
    _sentinel_running = False
    return "Screen Sentinel deactivated."


def sentinel_status() -> str:
    """Get current sentinel status."""
    if _sentinel_running:
        return f"Screen Sentinel is ACTIVE — checking every {_sentinel_interval}s"
    return "Screen Sentinel is INACTIVE"


# ═══════════════════════════════════════════════════════════════
# MAIN DISPATCH
# ═══════════════════════════════════════════════════════════════

def screen_sentinel(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
    speak=None,
) -> str:
    """Dispatch for screen sentinel actions."""
    params = parameters or {}
    action = params.get("action", "status").lower().strip()
    
    if player:
        player.write_log(f"[Sentinel] {action}")
    
    if action == "start":
        interval = int(params.get("interval", 60))
        return start_sentinel(player=player, speak=speak, interval=interval)
    
    elif action == "stop":
        return stop_sentinel()
    
    elif action == "status":
        return sentinel_status()
    
    elif action == "check":
        # One-time immediate check
        try:
            raw_png = _capture_screen()
            compressed = _compress(raw_png)
            threat = _analyze_for_threats(compressed)
            if threat:
                if player:
                    player.write_log(f"ALERT: {threat}")
                return threat
            return "Screen is SAFE — no threats detected."
        except Exception as e:
            return f"Check failed: {e}"
    
    else:
        return f"Unknown sentinel action: '{action}'. Use: start, stop, status, check"
