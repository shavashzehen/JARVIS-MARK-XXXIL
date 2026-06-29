#phone_control.py
"""
Multi-device Android phone control via ADB.
Supports 10-25 simultaneous devices.
"""
import io
import json
import re
import subprocess
import sys
import time
import threading
from pathlib import Path
from urllib.parse import quote_plus

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

import os
_BASE        = _base_dir()
_CONFIG_PATH = _BASE / "config" / "api_keys.json"
_MEMORY_PATH = _BASE / "memory" / "long_term.json"

# Add platform-tools to PATH
_pt_path = _BASE / "platform-tools"
if _pt_path.exists() and str(_pt_path) not in os.environ.get("PATH", ""):
    os.environ["PATH"] = str(_pt_path) + os.pathsep + os.environ.get("PATH", "")

def _load_config() -> dict:
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _get_api_key() -> str:
    return _load_config().get("gemini_api_key", "")

# ─── App Package Map ─────────────────────────────────────────
_APP_PACKAGES = {
    "whatsapp":     "com.whatsapp",
    "instagram":    "com.instagram.android",
    "youtube":      "com.google.android.youtube",
    "chrome":       "com.android.chrome",
    "telegram":     "org.telegram.messenger",
    "spotify":      "com.spotify.music",
    "twitter":      "com.twitter.android",
    "x":            "com.twitter.android",
    "tiktok":       "com.zhiliaoapp.musically",
    "snapchat":     "com.snapchat.android",
    "facebook":     "com.facebook.katana",
    "messenger":    "com.facebook.orca",
    "camera":       "com.android.camera",
    "gallery":      "com.google.android.apps.photos",
    "photos":       "com.google.android.apps.photos",
    "settings":     "com.android.settings",
    "calculator":   "com.google.android.calculator",
    "clock":        "com.google.android.deskclock",
    "maps":         "com.google.android.apps.maps",
    "gmail":        "com.google.android.gm",
    "phone":        "com.google.android.dialer",
    "dialer":       "com.google.android.dialer",
    "messages":     "com.google.android.apps.messaging",
    "sms":          "com.google.android.apps.messaging",
    "files":        "com.google.android.apps.nbu.files",
    "play store":   "com.android.vending",
    "netflix":      "com.netflix.mediaclient",
    "amazon":       "com.amazon.mShop.android.shopping",
    "uber":         "com.ubercab",
    "discord":      "com.discord",
    "reddit":       "com.reddit.frontpage",
    "pinterest":    "com.pinterest",
    "linkedin":     "com.linkedin.android",
    "zoom":         "us.zoom.videomeetings",
    "teams":        "com.microsoft.teams",
    "outlook":      "com.microsoft.office.outlook",
    "notes":        "com.google.android.keep",
    "keep":         "com.google.android.keep",
    "whatsapp business": "com.whatsapp.w4b",
    "pubg":         "com.tencent.ig",
    "free fire":    "com.dts.freefireth",
    "candy crush":  "com.king.candycrushsaga",
    "clash royale":  "com.supercell.clashroyale",
    "clash of clans": "com.supercell.clashofclans",
}

# ─── Key Code Map ─────────────────────────────────────────────
_KEY_CODES = {
    "home": 3, "back": 4, "call": 5, "end_call": 6,
    "power": 26, "camera": 27, "volume_up": 24, "volume_down": 25,
    "mute": 164, "enter": 66, "delete": 67, "tab": 61,
    "space": 62, "menu": 82, "recents": 187,
    "play_pause": 85, "stop": 86, "next": 87, "previous": 88,
    "brightness_up": 221, "brightness_down": 220,
}

# ─── Recording State ─────────────────────────────────────────
_recording_processes: dict[str, subprocess.Popen] = {}
_recording_lock = threading.Lock()

# ─── Device Resolution Cache ─────────────────────────────────
_resolution_cache: dict[str, tuple[int, int]] = {}


# ═══════════════════════════════════════════════════════════════
# ADB CORE
# ═══════════════════════════════════════════════════════════════

_adb_path = str(_pt_path / "adb.exe") if _pt_path.exists() else "adb"

def _adb(serial: str | None, *args, timeout: int = 10) -> subprocess.CompletedProcess:
    """Run an ADB command, optionally targeting a specific device."""
    cmd = [_adb_path]
    if serial:
        cmd += ["-s", serial]
    cmd += list(args)
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def _adb_shell(serial: str | None, *args, timeout: int = 10) -> str:
    """Run ADB shell command and return stdout."""
    r = _adb(serial, "shell", *args, timeout=timeout)
    return r.stdout.decode(errors="replace").strip()


def _get_device_serial(params: dict, player=None) -> str | None:
    """Get device serial from params, UI active device, or first connected device."""
    serial = params.get("device") or params.get("serial")
    if serial:
        return serial
    if player and hasattr(player, "active_device") and player.active_device:
        return player.active_device
    try:
        devices = _list_devices()
        if devices:
            return devices[0]["serial"]
    except Exception:
        pass
    return None


# ═══════════════════════════════════════════════════════════════
# DEVICE MANAGEMENT
# ═══════════════════════════════════════════════════════════════

def _list_devices() -> list[dict]:
    """List all connected ADB devices with model info."""
    try:
        r = _adb(None, "devices", "-l", timeout=10)
        lines = r.stdout.decode(errors="replace").strip().split("\n")[1:]
        devices = []
        for line in lines:
            line = line.strip()
            if not line or "offline" in line:
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            serial = parts[0]
            status = parts[1]
            model = ""
            device_name = ""
            for p in parts[2:]:
                if p.startswith("model:"):
                    model = p.split(":", 1)[1]
                elif p.startswith("device:"):
                    device_name = p.split(":", 1)[1]
            devices.append({
                "serial": serial,
                "status": status,
                "model": model or device_name or "Unknown",
            })
        return devices
    except Exception as e:
        print(f"[PhoneControl] [!] list_devices failed: {e}")
        return []


def _check_device(serial: str | None) -> str:
    """Check if a specific device (or any device) is connected."""
    devices = _list_devices()
    if not devices:
        return "ERROR: No Android devices connected. Connect via USB and enable USB Debugging."
    if serial:
        for d in devices:
            if d["serial"] == serial:
                return f"Device connected: {d['model']} ({serial})"
        return f"ERROR: Device '{serial}' not found. Connected: {[d['serial'] for d in devices]}"
    return f"Device connected: {devices[0]['model']} ({devices[0]['serial']})"


def _get_resolution(serial: str | None) -> tuple[int, int]:
    """Get phone screen resolution, cached per device."""
    key = serial or "_default"
    if key in _resolution_cache:
        return _resolution_cache[key]
    try:
        out = _adb_shell(serial, "wm", "size")
        match = re.search(r"(\d+)x(\d+)", out)
        if match:
            w, h = int(match.group(1)), int(match.group(2))
            _resolution_cache[key] = (w, h)
            return w, h
    except Exception:
        pass
    return 1080, 1920


# ═══════════════════════════════════════════════════════════════
# BASIC CONTROLS
# ═══════════════════════════════════════════════════════════════

def _tap(serial: str | None, x: int, y: int) -> str:
    _adb_shell(serial, "input", "tap", str(x), str(y))
    return f"Tapped ({x}, {y})"


def _swipe(serial: str | None, x1: int, y1: int, x2: int, y2: int,
           duration: int = 300) -> str:
    _adb_shell(serial, "input", "swipe",
               str(x1), str(y1), str(x2), str(y2), str(duration))
    return f"Swiped ({x1},{y1}) → ({x2},{y2}) in {duration}ms"


def _long_press(serial: str | None, x: int, y: int,
                duration: int = 1500) -> str:
    _adb_shell(serial, "input", "swipe",
               str(x), str(y), str(x), str(y), str(duration))
    return f"Long-pressed ({x}, {y}) for {duration}ms"


def _type_text(serial: str | None, text: str) -> str:
    safe = text.replace(" ", "%s").replace("'", "\\'").replace('"', '\\"')
    safe = re.sub(r'[&|;`$]', '', safe)
    _adb_shell(serial, "input", "text", safe)
    return f"Typed: {text[:60]}{'…' if len(text) > 60 else ''}"


def _key_event(serial: str | None, keycode: str) -> str:
    code = keycode.upper()
    if not code.startswith("KEYCODE_"):
        num = _KEY_CODES.get(code.lower())
        if num:
            code = str(num)
        else:
            code = f"KEYCODE_{code}"
    _adb_shell(serial, "input", "keyevent", code)
    return f"Key: {keycode}"


def _scroll(serial: str | None, direction: str = "down",
            amount: int = 3) -> str:
    w, h = _get_resolution(serial)
    cx, cy = w // 2, h // 2
    dist = h // 4 * amount
    swipes = {
        "down":  (cx, cy + dist // 2, cx, cy - dist // 2),
        "up":    (cx, cy - dist // 2, cx, cy + dist // 2),
        "left":  (cx + dist // 2, cy, cx - dist // 2, cy),
        "right": (cx - dist // 2, cy, cx + dist // 2, cy),
    }
    coords = swipes.get(direction.lower(), swipes["down"])
    _adb_shell(serial, "input", "swipe",
               str(coords[0]), str(coords[1]),
               str(coords[2]), str(coords[3]), "300")
    return f"Scrolled {direction}"


# ═══════════════════════════════════════════════════════════════
# NAVIGATION KEYS
# ═══════════════════════════════════════════════════════════════

def _go_home(serial: str | None) -> str:
    _adb_shell(serial, "input", "keyevent", "3")
    return "Pressed HOME"

def _go_back(serial: str | None) -> str:
    _adb_shell(serial, "input", "keyevent", "4")
    return "Pressed BACK"

def _recents(serial: str | None) -> str:
    _adb_shell(serial, "input", "keyevent", "187")
    return "Opened recent apps"

def _notifications(serial: str | None) -> str:
    _adb_shell(serial, "cmd", "statusbar", "expand-notifications")
    return "Opened notifications"


# ═══════════════════════════════════════════════════════════════
# MEDIA / HARDWARE KEYS
# ═══════════════════════════════════════════════════════════════

def _volume_up(serial: str | None) -> str:
    _adb_shell(serial, "input", "keyevent", "24")
    return "Volume up"

def _volume_down(serial: str | None) -> str:
    _adb_shell(serial, "input", "keyevent", "25")
    return "Volume down"

def _mute_toggle(serial: str | None) -> str:
    _adb_shell(serial, "input", "keyevent", "164")
    return "Mute toggled"

def _power_btn(serial: str | None) -> str:
    _adb_shell(serial, "input", "keyevent", "26")
    return "Power button pressed"

def _lock_screen(serial: str | None) -> str:
    _adb_shell(serial, "input", "keyevent", "26")
    return "Screen locked"

def _unlock(serial: str | None) -> str:
    _adb_shell(serial, "input", "keyevent", "82")
    return "Unlock attempted (swipe/PIN may be needed)"


# ═══════════════════════════════════════════════════════════════
# SETTINGS
# ═══════════════════════════════════════════════════════════════

def _set_brightness(serial: str | None, value: int) -> str:
    value = max(0, min(255, value))
    _adb_shell(serial, "settings", "put", "system", "screen_brightness", str(value))
    return f"Brightness set to {value}/255"

def _wifi_toggle(serial: str | None, enable: bool = True) -> str:
    state = "enable" if enable else "disable"
    _adb_shell(serial, "svc", "wifi", state)
    return f"WiFi {'enabled' if enable else 'disabled'}"

def _airplane_mode(serial: str | None, enable: bool = True) -> str:
    val = "1" if enable else "0"
    _adb_shell(serial, "settings", "put", "global", "airplane_mode_on", val)
    _adb_shell(serial, "am", "broadcast", "-a",
               "android.intent.action.AIRPLANE_MODE", "--ez", "state", str(enable).lower())
    return f"Airplane mode {'ON' if enable else 'OFF'}"


# ═══════════════════════════════════════════════════════════════
# APP MANAGEMENT
# ═══════════════════════════════════════════════════════════════

def _resolve_package(app_name: str, serial: str | None = None) -> str:
    """Resolve app name to package. Try map first, then search installed."""
    key = app_name.lower().strip()
    if key in _APP_PACKAGES:
        return _APP_PACKAGES[key]
    try:
        out = _adb_shell(serial, "pm", "list", "packages", "-f")
        for line in out.split("\n"):
            if key.replace(" ", "") in line.lower():
                match = re.search(r"package:(.+?)=(.+)", line)
                if match:
                    return match.group(2)
    except Exception:
        pass
    return key


def _open_app(serial: str | None, app_name: str) -> str:
    pkg = _resolve_package(app_name, serial)
    r = _adb_shell(serial, "monkey", "-p", pkg, "-c",
                    "android.intent.category.LAUNCHER", "1")
    if "No activities found" in r:
        return f"App '{app_name}' ({pkg}) not found on device"
    return f"Opened {app_name}"


def _close_app(serial: str | None, app_name: str) -> str:
    pkg = _resolve_package(app_name, serial)
    _adb_shell(serial, "am", "force-stop", pkg)
    return f"Closed {app_name}"


def _current_app(serial: str | None) -> str:
    out = _adb_shell(serial, "dumpsys", "activity", "recents",
                     "|", "grep", "'Recent #0'", timeout=5)
    if not out:
        out = _adb_shell(serial, "dumpsys", "window", "windows",
                         "|", "grep", "-E", "'mCurrentFocus'", timeout=5)
    return f"Current app: {out}" if out else "Could not determine current app"


def _list_apps(serial: str | None) -> str:
    out = _adb_shell(serial, "pm", "list", "packages", "-3", timeout=15)
    packages = [line.replace("package:", "") for line in out.split("\n") if line.strip()]
    if not packages:
        return "No third-party apps found"
    return f"Installed apps ({len(packages)}):\n" + "\n".join(sorted(packages)[:50])


def _install_apk(serial: str | None, apk_path: str) -> str:
    p = Path(apk_path)
    if not p.exists():
        return f"APK not found: {apk_path}"
    r = _adb(serial, "install", "-r", str(p), timeout=120)
    out = r.stdout.decode(errors="replace")
    if "Success" in out:
        return f"APK installed: {p.name}"
    return f"Install failed: {out}"


def _open_url(serial: str | None, url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    _adb_shell(serial, "am", "start", "-a", "android.intent.action.VIEW",
               "-d", url)
    return f"Opened URL: {url}"


# ═══════════════════════════════════════════════════════════════
# PHONE INFO
# ═══════════════════════════════════════════════════════════════

def _phone_info(serial: str | None) -> str:
    info = {}
    try:
        info["model"] = _adb_shell(serial, "getprop", "ro.product.model")
        info["brand"] = _adb_shell(serial, "getprop", "ro.product.brand")
        info["android"] = _adb_shell(serial, "getprop", "ro.build.version.release")
        info["sdk"] = _adb_shell(serial, "getprop", "ro.build.version.sdk")

        battery_out = _adb_shell(serial, "dumpsys", "battery", timeout=5)
        for line in battery_out.split("\n"):
            line = line.strip()
            if line.startswith("level:"):
                info["battery"] = line.split(":")[1].strip() + "%"
            elif line.startswith("status:"):
                status_map = {"2": "Charging", "3": "Discharging",
                              "4": "Not charging", "5": "Full"}
                info["charging"] = status_map.get(line.split(":")[1].strip(), "Unknown")

        storage = _adb_shell(serial, "df", "/data", "|", "tail", "-1", timeout=5)
        if storage:
            parts = storage.split()
            if len(parts) >= 4:
                info["storage_used"] = parts[2]
                info["storage_free"] = parts[3]

    except Exception as e:
        info["error"] = str(e)

    lines = [f"  {k}: {v}" for k, v in info.items()]
    return "Phone Info:\n" + "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# SCREENSHOT
# ═══════════════════════════════════════════════════════════════

def _screenshot(serial: str | None, save_path: str | None = None) -> str:
    r = _adb(serial, "exec-out", "screencap", "-p", timeout=10)
    if r.returncode != 0 or not r.stdout:
        return "Screenshot failed — is the device connected?"
    local = Path(save_path) if save_path else Path.home() / "Desktop" / "phone_screenshot.png"
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(r.stdout)
    return f"Phone screenshot saved: {local}"


# ═══════════════════════════════════════════════════════════════
# AI SCREEN FIND (Gemini Vision)
# ═══════════════════════════════════════════════════════════════

def _screen_find(serial: str | None, description: str) -> tuple[int, int] | None:
    api_key = _get_api_key()
    if not api_key:
        print("[PhoneControl] [!] No API key for screen_find")
        return None

    try:
        from google import genai
        from google.genai import types as gtypes

        r = _adb(serial, "exec-out", "screencap", "-p", timeout=10)
        if r.returncode != 0 or not r.stdout:
            return None

        image_bytes = r.stdout
        w, h = _get_resolution(serial)

        client = genai.Client(api_key=api_key)
        prompt = (
            f"This is a screenshot of an Android phone screen ({w}×{h} pixels). "
            f"Locate the UI element described as: '{description}'. "
            f"Reply with ONLY the center coordinates as: x,y "
            f"If the element is not visible, reply: NOT_FOUND"
        )

        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=[
                gtypes.Part.from_bytes(data=image_bytes, mime_type="image/png"),
                prompt,
            ],
        )

        text = (response.text or "").strip()
        if "NOT_FOUND" in text.upper():
            return None

        match = re.search(r"(\d+)\s*,\s*(\d+)", text)
        if match:
            fx, fy = int(match.group(1)), int(match.group(2))
            if 0 <= fx <= w and 0 <= fy <= h:
                return fx, fy

    except Exception as e:
        print(f"[PhoneControl] [!] screen_find failed: {e}")

    return None


def _screen_tap(serial: str | None, description: str) -> str:
    coords = _screen_find(serial, description)
    if coords:
        time.sleep(0.2)
        _tap(serial, coords[0], coords[1])
        return f"Found and tapped '{description}' at {coords}"
    return f"Element not found on phone screen: '{description}'"


# ═══════════════════════════════════════════════════════════════
# PHONE CALLS
# ═══════════════════════════════════════════════════════════════

def _call(serial: str | None, number: str) -> str:
    clean = re.sub(r'[^\d+*#]', '', number)
    if not clean:
        return "Invalid phone number"
    _adb_shell(serial, "am", "start", "-a", "android.intent.action.CALL",
               "-d", f"tel:{clean}")
    return f"Calling {clean}..."


def _end_call(serial: str | None) -> str:
    _adb_shell(serial, "input", "keyevent", "6")
    return "Call ended"


# ═══════════════════════════════════════════════════════════════
# MESSAGING
# ═══════════════════════════════════════════════════════════════

def _send_whatsapp(serial: str | None, contact: str, message: str) -> str:
    """Send WhatsApp message — by number (direct) or by contact name (UI search)."""
    clean = re.sub(r'[^\d+]', '', contact)
    if clean and len(clean) >= 10:
        encoded = quote_plus(message)
        _adb_shell(serial, "am", "start", "-a", "android.intent.action.VIEW",
                   "-d", f"https://wa.me/{clean}?text={encoded}")
        time.sleep(4)
        coords = _screen_find(serial, "send button or green arrow send icon")
        if coords:
            _tap(serial, coords[0], coords[1])
            return f"WhatsApp message sent to {contact}"
        return f"WhatsApp opened for {contact} — could not find send button"
    else:
        _open_app(serial, "whatsapp")
        time.sleep(3)
        find = _screen_find(serial, "search icon or magnifying glass at top")
        if find:
            _tap(serial, find[0], find[1])
            time.sleep(1)
        _type_text(serial, contact)
        time.sleep(2)
        chat = _screen_find(serial, f"contact or chat named {contact}")
        if chat:
            _tap(serial, chat[0], chat[1])
            time.sleep(1.5)
        msg_box = _screen_find(serial, "message input field or Type a message box")
        if msg_box:
            _tap(serial, msg_box[0], msg_box[1])
            time.sleep(0.5)
        _type_text(serial, message)
        time.sleep(0.5)
        send = _screen_find(serial, "send button or green arrow")
        if send:
            _tap(serial, send[0], send[1])
            return f"WhatsApp message sent to {contact}"
        return f"Message typed but send button not found — check phone screen"


def _send_sms(serial: str | None, number: str, message: str) -> str:
    """Send SMS using Android intent."""
    clean = re.sub(r'[^\d+]', '', number)
    if not clean:
        return "Invalid phone number for SMS"
    _adb_shell(serial, "am", "start", "-a", "android.intent.action.SENDTO",
               "-d", f"sms:{clean}", "--es", "sms_body", message)
    time.sleep(3)
    send = _screen_find(serial, "send button or SMS send icon")
    if send:
        _tap(serial, send[0], send[1])
        return f"SMS sent to {clean}"
    _adb_shell(serial, "input", "keyevent", "66")
    return f"SMS composed to {clean} — pressed Enter to send"


def _whatsapp_call(serial: str | None, contact: str, call_type: str = "audio") -> str:
    """Start WhatsApp voice or video call."""
    clean = re.sub(r'[^\d+]', '', contact)
    if not clean or len(clean) < 10:
        return "Invalid phone number for WhatsApp call. Provide full country code (e.g. +91xxxxxxxxxx)."
    
    # Open direct WhatsApp chat view
    _adb_shell(serial, "am", "start", "-a", "android.intent.action.VIEW",
               "-d", f"https://api.whatsapp.com/send?phone={clean}")
    time.sleep(4)
    
    if call_type == "video":
        target = "video call button or camera icon at top right"
    else:
        target = "voice call button or phone call icon at top right"
        
    coords = _screen_find(serial, target)
    if coords:
        _tap(serial, coords[0], coords[1])
        time.sleep(1.5)
        # Check if confirmation popup shows up ("Start voice/video call?")
        confirm = _screen_find(serial, "call or start call or dial button on confirmation prompt")
        if confirm:
            _tap(serial, confirm[0], confirm[1])
        return f"Initiated WhatsApp {call_type} call to {clean}"
        
    return f"Opened WhatsApp chat for {clean} — call button not found on screen"


# ═══════════════════════════════════════════════════════════════
# SCREEN RECORDING
# ═══════════════════════════════════════════════════════════════

def _record_screen(serial: str | None, duration: int = 30) -> str:
    """Start screen recording on phone. Max 180 seconds."""
    global _recording_processes
    duration = max(5, min(180, duration))
    phone_path = "/sdcard/jarvis_recording.mp4"
    key = serial or "_default"

    with _recording_lock:
        if key in _recording_processes:
            return "Already recording on this device. Say 'stop recording' first."

    cmd = ["adb"]
    if serial:
        cmd += ["-s", serial]
    cmd += ["shell", "screenrecord", "--time-limit", str(duration), phone_path]

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    with _recording_lock:
        _recording_processes[key] = proc

    def _auto_cleanup():
        proc.wait()
        with _recording_lock:
            _recording_processes.pop(key, None)

    threading.Thread(target=_auto_cleanup, daemon=True).start()
    return f"Recording started ({duration}s max). Say 'stop recording' to stop and save."


def _stop_recording(serial: str | None, save_path: str | None = None) -> str:
    """Stop recording and pull file to PC."""
    global _recording_processes
    key = serial or "_default"
    phone_path = "/sdcard/jarvis_recording.mp4"

    with _recording_lock:
        proc = _recording_processes.pop(key, None)

    if proc:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

    time.sleep(2)

    local = Path(save_path) if save_path else Path.home() / "Desktop" / "phone_recording.mp4"
    local.parent.mkdir(parents=True, exist_ok=True)

    r = _adb(serial, "pull", phone_path, str(local), timeout=60)
    if r.returncode != 0:
        return f"Recording stopped but pull failed: {r.stderr.decode(errors='replace')}"

    _adb_shell(serial, "rm", phone_path, timeout=5)
    size = local.stat().st_size if local.exists() else 0
    size_str = f"{size / 1024 / 1024:.1f}MB" if size > 0 else "unknown size"
    return f"Recording saved: {local} ({size_str})"


# ═══════════════════════════════════════════════════════════════
# FILE TRANSFER
# ═══════════════════════════════════════════════════════════════

def _pull_file(serial: str | None, phone_path: str,
               save_path: str | None = None) -> str:
    local = Path(save_path) if save_path else Path.home() / "Desktop" / Path(phone_path).name
    local.parent.mkdir(parents=True, exist_ok=True)
    r = _adb(serial, "pull", phone_path, str(local), timeout=120)
    if r.returncode == 0:
        return f"Pulled: {phone_path} → {local}"
    return f"Pull failed: {r.stderr.decode(errors='replace')}"


def _push_file(serial: str | None, local_path: str,
               phone_path: str = "/sdcard/") -> str:
    p = Path(local_path)
    if not p.exists():
        return f"Local file not found: {local_path}"
    r = _adb(serial, "push", str(p), phone_path, timeout=120)
    if r.returncode == 0:
        return f"Pushed: {p.name} → {phone_path}"
    return f"Push failed: {r.stderr.decode(errors='replace')}"


# ═══════════════════════════════════════════════════════════════
# CONTACTS
# ═══════════════════════════════════════════════════════════════

def _search_contacts(serial: str | None, name: str) -> str:
    try:
        out = _adb_shell(
            serial, "content", "query", "--uri",
            f"content://contacts/phones/filter/{name}",
            "--projection", "display_name:number",
            timeout=10
        )
        if out and "Row:" in out:
            return f"Contacts matching '{name}':\n{out}"
        return f"No contacts found matching '{name}'"
    except Exception as e:
        return f"Contact search failed: {e}"

def _diagnose_and_fix_phone(serial: str | None, ui_glitch: bool = False) -> str:
    logs = []
    fixed = []
    
    logs.append("🔍 Starting Android System Diagnosis...")
    
    def get_setting(namespace, key):
        try:
            return _adb_shell(serial, f"settings get {namespace} {key}", timeout=5).strip()
        except Exception:
            return "unknown"
            
    def put_setting(namespace, key, value):
        try:
            _adb_shell(serial, f"settings put {namespace} {key} {value}", timeout=5)
            return True
        except Exception:
            return False

    # 1. Airplane Mode
    airplane = get_setting("global", "airplane_mode_on")
    if airplane == "1":
        logs.append("⚠️ Alert: Airplane Mode is enabled (Network disabled).")
        if put_setting("global", "airplane_mode_on", "0"):
            try:
                _adb_shell(serial, "am broadcast -a android.intent.action.AIRPLANE_MODE --ez state false", timeout=5)
            except Exception:
                pass
            fixed.append("Disabled Airplane Mode and re-enabled network radios.")
            
    # 1b. DND (Zen Mode) Check
    zen = get_setting("global", "zen_mode")
    if zen != "0" and zen.isdigit():
        logs.append(f"⚠️ Alert: Do Not Disturb (DND) is active (Zen Mode: {zen}).")
        if put_setting("global", "zen_mode", "0"):
            fixed.append("Disabled Do Not Disturb (DND) mode to ensure notifications and calls are active.")

    # 2. Stay Awake while Charging
    stay_awake = get_setting("global", "stay_on_while_plugged_in")
    if stay_awake != "3" and stay_awake != "7":
        logs.append("ℹ️ stay_on_while_plugged_in is disabled (screen turns off while connected).")
        if put_setting("global", "stay_on_while_plugged_in", "3"):
            fixed.append("Configured phone screen to 'Stay Awake' when plugged into laptop.")

    # 3. Screen Timeout
    timeout = get_setting("system", "screen_off_timeout")
    if timeout.isdigit():
        timeout_ms = int(timeout)
        if timeout_ms < 30000:
            logs.append(f"⚠️ Alert: Screen Timeout is very short ({timeout_ms // 1000}s). Screen turns off too fast.")
            if put_setting("system", "screen_off_timeout", "120000"):
                fixed.append("Increased screen timeout to 2 minutes.")
        elif timeout_ms > 1800000:
            logs.append("⚠️ Alert: Screen Timeout is set to never turn off (high battery drain).")
            if put_setting("system", "screen_off_timeout", "600000"):
                fixed.append("Reduced screen timeout to 10 minutes to save battery.")
    else:
        put_setting("system", "screen_off_timeout", "120000")

    # 4. Animation Scales (Speed booster)
    win_anim = get_setting("global", "window_animation_scale")
    trans_anim = get_setting("global", "transition_animation_scale")
    dur_anim = get_setting("global", "animator_duration_scale")
    
    for name, key, val in [("Window", "window_animation_scale", win_anim),
                           ("Transition", "transition_animation_scale", trans_anim),
                           ("Animator", "animator_duration_scale", dur_anim)]:
        try:
            val_f = float(val)
            if val_f > 1.5:
                logs.append(f"⚠️ Alert: {name} Animation Scale is set to {val_f}x (makes phone feel very slow).")
                if put_setting("global", key, "1.0"):
                    fixed.append(f"Reset {name} Animation Scale to 1.0x (normal speed).")
            elif val_f == 0.0:
                logs.append(f"ℹ️ {name} Animation is disabled (jerky UI transitions).")
        except ValueError:
            pass

    # 5. Volume Muted / Zero Check
    try:
        music_vol = _adb_shell(serial, "settings get system volume_music", timeout=5).strip()
        if music_vol == "0" or not music_vol:
            logs.append("⚠️ Alert: Media Volume is completely muted (no sound in videos/games).")
            _adb_shell(serial, "cmd audio set-stream-volume 3 8", timeout=5)
            fixed.append("Restored Media Volume to 50% (unmuted).")
            
        ring_vol = _adb_shell(serial, "settings get system volume_ring", timeout=5).strip()
        if ring_vol == "0" or not ring_vol:
            logs.append("⚠️ Alert: Ringer Volume is set to 0 (missed calls).")
            _adb_shell(serial, "cmd audio set-stream-volume 2 5", timeout=5)
            fixed.append("Restored Phone Ringer Volume to 35%.")
    except Exception:
        pass

    # 6. Display font scale
    font_scale = get_setting("system", "font_scale")
    try:
        fs = float(font_scale)
        if fs > 1.3 or fs < 0.85:
            logs.append(f"⚠️ Alert: Font size scale is set to {fs}x (unusual size, could distort layouts).")
            if put_setting("system", "font_scale", "1.0"):
                fixed.append("Reset display font size scale to standard (1.0x).")
    except ValueError:
        pass

    # 7. Crashing App Auto-Fix & Auto-Permission Healing
    try:
        crash_logs = _adb_shell(serial, "logcat -d -b crash -t 30", timeout=5)
        if crash_logs and len(crash_logs.strip()) > 10:
            matches = re.findall(r"Process:\s+([a-zA-Z0-9\._]+)", crash_logs)
            if matches:
                crashed_pkgs = list(set(matches))
                logs.append(f"⚠️ Alert: Crashed apps detected in logcat: {crashed_pkgs}")
                for pkg in crashed_pkgs:
                    if pkg != "system" and pkg != "android" and "google" not in pkg:
                        _adb_shell(serial, f"am force-stop {pkg}", timeout=5)
                        fixed.append(f"Force stopped crashing application: '{pkg}' to restore stability.")
                        # Auto-grant basic permissions to prevent permission-related crashes
                        perms = [
                            "android.permission.READ_EXTERNAL_STORAGE",
                            "android.permission.WRITE_EXTERNAL_STORAGE",
                            "android.permission.CAMERA",
                            "android.permission.ACCESS_FINE_LOCATION",
                            "android.permission.RECORD_AUDIO",
                            "android.permission.READ_CONTACTS"
                        ]
                        healed = []
                        for perm in perms:
                            try:
                                _adb_shell(serial, f"pm grant {pkg} {perm}", timeout=3)
                                healed.append(perm.split(".")[-1])
                            except Exception:
                                pass
                        if healed:
                            fixed.append(f"Auto-healed permissions for '{pkg}': {', '.join(healed)}")
    except Exception:
        pass

    # 8. Network Connection Reset (WiFi, Bluetooth, Mobile Data)
    try:
        # Toggle Wi-Fi
        _adb_shell(serial, "svc wifi disable", timeout=5)
        time.sleep(0.5)
        _adb_shell(serial, "svc wifi enable", timeout=5)
        # Toggle Bluetooth
        _adb_shell(serial, "cmd bluetooth disable", timeout=5)
        time.sleep(0.5)
        _adb_shell(serial, "cmd bluetooth enable", timeout=5)
        # Toggle Mobile Data
        _adb_shell(serial, "svc data disable", timeout=5)
        time.sleep(0.5)
        _adb_shell(serial, "svc data enable", timeout=5)
        fixed.append("Reset phone Wi-Fi, Bluetooth, and Mobile Data radios to solve wireless glitches.")
    except Exception:
        pass

    # 9. UI Freeze Fix (Restart SystemUI if requested)
    if ui_glitch:
        try:
            _adb_shell(serial, "pkill -f com.android.systemui", timeout=5)
            fixed.append("Restarted Android System UI to resolve status bar or screen freeze.")
        except Exception:
            pass

    # 10. CPU load diagnostics
    try:
        cpu_info = _adb_shell(serial, "dumpsys cpuinfo | head -n 5", timeout=5)
        if cpu_info:
            logs.append(f"\n📱 CPU Load by Process:\n{cpu_info.strip()}")
    except Exception:
        pass

    # 11. Storage space cleanup & Cache trimming
    try:
        df_out = _adb_shell(serial, "df -h /data", timeout=5)
        if df_out:
            logs.append(f"\nDisk Info:\n{df_out.strip()}")
        
        _adb_shell(serial, "rm -rf /sdcard/DCIM/.thumbnails/*", timeout=5)
        _adb_shell(serial, "rm -rf /sdcard/Download/*.tmp /sdcard/Download/*.log", timeout=5)
        _adb_shell(serial, "pm trim-caches 999G", timeout=10)
        fixed.append("Purged temporary cache files and thumbnail cache to free storage space.")
    except Exception:
        pass

    # 12. Screen Brightness Stuck Check
    brightness_mode = get_setting("system", "screen_brightness_mode")
    brightness_val = get_setting("system", "screen_brightness")
    if brightness_mode == "0" and brightness_val.isdigit() and int(brightness_val) == 255:
        logs.append("⚠️ Alert: Screen Brightness is stuck at MAX (255) with Auto-Brightness OFF.")
        if put_setting("system", "screen_brightness_mode", "1"):
            fixed.append("Enabled adaptive auto-brightness to save battery and prevent screen burn-in.")
        elif put_setting("system", "screen_brightness", "140"):
            fixed.append("Dimmed screen brightness to standard (140/255).")

    # 13. Screen Rotation Lock Check
    rotation = get_setting("system", "accelerometer_rotation")
    if rotation == "0":
        logs.append("ℹ️ Screen Rotation is locked to portrait mode.")
        if put_setting("system", "accelerometer_rotation", "1"):
            fixed.append("Enabled screen auto-rotation.")

    # 14. Master Sync Check
    try:
        sync_out = _adb_shell(serial, "content query --uri content://settings/global --where \"name='sync_on'\"", timeout=3)
        if "value=0" in sync_out:
            logs.append("⚠️ Alert: Global background sync is disabled.")
            _adb_shell(serial, "content insert --uri content://settings/global --bind name:s:sync_on --bind value:s:1", timeout=3)
            fixed.append("Enabled global background data synchronization (Master Sync).")
    except Exception:
        pass

    # 15. Show Touches / Visual feedback developer options cleanup
    touches = get_setting("system", "show_touches")
    if touches == "1":
        logs.append("ℹ️ Developer option 'Show Touches / Taps' is enabled.")
        if put_setting("system", "show_touches", "0"):
            fixed.append("Disabled visual screen taps feedback.")

    # 16. Thermal temperature check
    try:
        battery_out = _adb_shell(serial, "dumpsys battery", timeout=5)
        temp_val = None
        for line in battery_out.split("\n"):
            if "temperature:" in line.lower():
                val_str = line.split(":", 1)[1].strip()
                if val_str.isdigit():
                    temp_val = float(val_str) / 10.0
                    break
        if temp_val and temp_val > 42.0:
            logs.append(f"🔥 Alert: Phone temperature is high ({temp_val}°C).")
            put_setting("system", "screen_brightness", "80")
            fixed.append(f"Throttled phone brightness to reduce battery heat ({temp_val}°C).")
    except Exception:
        pass

    # Summary
    if not fixed:
        return "\n".join(logs) + "\n\n✅ Diagnosis complete: All tested settings are in healthy configurations!"
        
    res = "\n".join(logs) + "\n\n🔧 Troubleshooter completed the following fixes:\n"
    for i, item in enumerate(fixed):
        res += f"  {i+1}. {item}\n"
    res += "\n✅ Phone software is repaired, optimized, and stabilized, sir!"
    return res

def _battery_status(serial: str | None) -> str:
    try:
        out = _adb_shell(serial, "dumpsys battery", timeout=5)
        lines = out.strip().split("\n")
        info = {}
        for line in lines:
            if ":" in line:
                k, v = line.split(":", 1)
                info[k.strip().lower()] = v.strip()
        
        level = info.get("level", "Unknown")
        temp = info.get("temperature", "Unknown")
        health = info.get("health", "Unknown")
        status = info.get("status", "Unknown")
        
        if temp != "Unknown" and temp.isdigit():
            temp_c = float(temp) / 10.0
            temp_str = f"{temp_c}°C"
        else:
            temp_str = "Unknown"
            
        health_map = {
            "1": "Unknown", "2": "Good", "3": "Overheat", "4": "Dead",
            "5": "Over Voltage", "6": "Unspecified Failure", "7": "Cold"
        }
        health_str = health_map.get(health, f"Unknown ({health})")
        
        status_map = {
            "1": "Unknown", "2": "Charging", "3": "Discharging",
            "4": "Not Charging", "5": "Full"
        }
        status_str = status_map.get(status, f"Unknown ({status})")
        
        return (
            f"🔋 Battery Status:\n"
            f"  • Level: {level}%\n"
            f"  • Status: {status_str}\n"
            f"  • Health: {health_str}\n"
            f"  • Temperature: {temp_str}"
        )
    except Exception as e:
        return f"Failed to get battery status: {e}"

def _ringer_mode(serial: str | None, mode: str) -> str:
    mode = mode.lower().strip()
    if mode == "silent":
        val = "0"
    elif mode == "vibrate":
        val = "1"
    elif mode == "normal":
        val = "2"
    else:
        return "Invalid ringer mode. Choose from: silent, vibrate, normal"
    try:
        _adb_shell(serial, "cmd audio set-ringer-mode", val, timeout=5)
        return f"Phone ringer mode set to: {mode.upper()}"
    except Exception as e:
        try:
            _adb_shell(serial, "settings put global mode_ringer", val, timeout=5)
            return f"Phone ringer mode updated via settings: {mode.upper()}"
        except Exception as e2:
            return f"Failed to set ringer mode: {e2}"

def _camera_photo(serial: str | None, save_path: str | None = None) -> str:
    try:
        _adb_shell(serial, "input keyevent 224", timeout=5)
        time.sleep(0.5)
        _adb_shell(serial, "am start -a android.media.action.IMAGE_CAPTURE", timeout=10)
        time.sleep(3.0)
        _adb_shell(serial, "input keyevent 27", timeout=5)
        time.sleep(2.0)
        
        find_cmd = "ls -t /sdcard/DCIM/Camera/ | head -n 1"
        latest_file = _adb_shell(serial, find_cmd, timeout=5).strip()
        phone_dir = "/sdcard/DCIM/Camera/"
        
        if not latest_file or latest_file.startswith("ls:") or "No such file" in latest_file:
            find_cmd = "ls -t /sdcard/Pictures/ | head -n 1"
            latest_file = _adb_shell(serial, find_cmd, timeout=5).strip()
            phone_dir = "/sdcard/Pictures/"
            
        if not latest_file or latest_file.startswith("ls:") or "No such file" in latest_file:
            return "Camera shutter was triggered, but failed to locate the photo file on phone."
            
        phone_file_path = f"{phone_dir}{latest_file}"
        local_path = Path(save_path) if save_path else Path.home() / "Desktop" / f"phone_photo_{latest_file}"
        local_path.parent.mkdir(parents=True, exist_ok=True)
        
        r = _adb(serial, "pull", phone_file_path, str(local_path), timeout=15)
        if r.returncode != 0:
            return f"Failed to pull photo from phone: {r.stderr.decode(errors='replace')}"
            
        _adb_shell(serial, "input keyevent 3", timeout=5)
        return f"Phone photo captured and saved to PC: {local_path}"
    except Exception as e:
        return f"Failed to take phone camera photo: {e}"

def _youtube_play(serial: str | None, query: str) -> str:
    query_str = query.strip()
    try:
        if "youtube.com" in query_str or "youtu.be" in query_str:
            _adb_shell(serial, "am start -a android.intent.action.VIEW", "-d", f"'{query_str}'", timeout=10)
            return f"Opening YouTube URL: {query_str}"
        else:
            _adb_shell(serial, f"am start -a android.intent.action.SEARCH -n com.google.android.youtube/com.google.android.apps.youtube.app.search.SearchActivity -e query '{query_str}'", timeout=10)
            return f"Searching YouTube on phone for: '{query_str}'"
    except Exception as e:
        return f"Failed to play/search YouTube: {e}"

def _screen_state(serial: str | None, state: str) -> str:
    state = state.lower().strip()
    try:
        out = _adb_shell(serial, "dumpsys power | grep 'Display Power: state='", timeout=5)
        is_on = "ON" in out.upper()
        if state == "on" and not is_on:
            _adb_shell(serial, "input keyevent 224", timeout=5)
            return "Screen turned ON"
        elif state == "off" and is_on:
            _adb_shell(serial, "input keyevent 223", timeout=5)
            return "Screen turned OFF"
        elif state == "toggle":
            _adb_shell(serial, "input keyevent 26", timeout=5)
            return "Screen state toggled"
        else:
            return f"Screen is already {'ON' if is_on else 'OFF'}"
    except Exception as e:
        return f"Failed to modify screen state: {e}"


# ═══════════════════════════════════════════════════════════════
# WIFI ADB
# ═══════════════════════════════════════════════════════════════

def _wifi_connect(ip: str) -> str:
    """Connect to phone over WiFi ADB."""
    if ":" not in ip:
        ip = f"{ip}:5555"
    try:
        _adb(None, "tcpip", "5555", timeout=5)
        time.sleep(1)
    except Exception:
        pass
    r = _adb(None, "connect", ip, timeout=10)
    out = r.stdout.decode(errors="replace").strip()
    if "connected" in out.lower():
        return f"Connected to {ip} via WiFi"
    return f"WiFi connection result: {out}"


def _share_clipboard(serial: str | None, text: str) -> str:
    """Send text clipboard content from PC to the active input field on the phone."""
    if not text:
        return "No text provided to share."
    
    # Replace spaces with %s for adb shell input text
    sanitized = text.replace(" ", "%s")
    # Escape quotes and other shell special characters
    sanitized = re.sub(r'([\'"\\&|<>*?$;])', r'\\\1', sanitized)
    
    try:
        _adb_shell(serial, "input", "text", sanitized, timeout=10)
        return f"Clipboard text shared to phone successfully: '{text[:30]}...'"
    except Exception as e:
        return f"Failed to share clipboard text to phone: {e}"


def _backup_phone(
    serial: str | None,
    backup_type: str = "all",
    local_dest_dir: str = None,
    log_callback=None,
    progress_callback=None
) -> str:
    """Backup contacts, DCIM photos, documents, and downloads to local PC folder."""
    import csv
    if not local_dest_dir:
        local_dest_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backups")
    
    os.makedirs(local_dest_dir, exist_ok=True)
    
    def log(msg):
        print(f"[Backup] {msg}")
        if log_callback:
            try:
                log_callback(msg)
            except Exception:
                pass
            
    def prog(val):
        if progress_callback:
            try:
                progress_callback(val)
            except Exception:
                pass

    log(f"Initializing backup directory: {local_dest_dir}")
    prog(5)

    types = []
    if backup_type == "all":
        types = ["contacts", "photos", "documents", "downloads"]
    else:
        types = [backup_type]

    total = len(types)
    step = 90 // total if total > 0 else 90
    curr_progress = 5

    try:
        from actions.phone_control import _list_devices
        devs = _list_devices()
        if not devs:
            return "No connected device found for backup."
        if not serial:
            serial = devs[0]["serial"]

        log(f"Backing up device: {serial}")
        prog(10)
        curr_progress = 10

        for t in types:
            log(f"Starting {t} backup...")
            if t == "contacts":
                log("Querying contacts from phone provider...")
                out = _adb_shell(
                    serial, "content", "query", "--uri",
                    "content://contacts/phones",
                    "--projection", "display_name:number",
                    timeout=15
                )
                if out and "Row:" in out:
                    contacts_file = os.path.join(local_dest_dir, f"contacts_{serial}.csv")
                    lines = out.strip().split("\n")
                    count = 0
                    with open(contacts_file, "w", newline="", encoding="utf-8") as f:
                        writer = csv.writer(f)
                        writer.writerow(["Name", "Number"])
                        for line in lines:
                            m = re.search(r'display_name=([^,]*),\s*number=(.*)', line)
                            if m:
                                writer.writerow([m.group(1).strip(), m.group(2).strip()])
                                count += 1
                    log(f"Successfully backed up {count} contacts to {contacts_file}")
                else:
                    log("No contacts found or permission denied on phone.")

            elif t == "photos":
                log("Pulling photos from /sdcard/DCIM/Camera...")
                dest = os.path.join(local_dest_dir, "photos")
                os.makedirs(dest, exist_ok=True)
                
                check = _adb_shell(serial, "ls", "-d", "/sdcard/DCIM/Camera", timeout=5)
                src = "/sdcard/DCIM/Camera/"
                if "no such file" in check.lower():
                    src = "/sdcard/DCIM/"
                    log("Camera folder not found, pulling entire DCIM folder...")

                cmd = ["adb"]
                if serial:
                    cmd += ["-s", serial]
                cmd += ["pull", src, dest]
                res = subprocess.run(cmd, capture_output=True, timeout=120)
                if res.returncode == 0:
                    log(f"Successfully backed up DCIM images to {dest}")
                else:
                    log(f"Failed to backup DCIM images: {res.stderr.decode(errors='replace')}")

            elif t == "documents":
                log("Pulling /sdcard/Documents...")
                dest = os.path.join(local_dest_dir, "documents")
                os.makedirs(dest, exist_ok=True)
                cmd = ["adb"]
                if serial:
                    cmd += ["-s", serial]
                cmd += ["pull", "/sdcard/Documents/", dest]
                res = subprocess.run(cmd, capture_output=True, timeout=120)
                if res.returncode == 0:
                    log(f"Successfully backed up Documents to {dest}")
                else:
                    log(f"Failed to backup Documents: {res.stderr.decode(errors='replace')}")

            elif t == "downloads":
                log("Pulling /sdcard/Download...")
                dest = os.path.join(local_dest_dir, "downloads")
                os.makedirs(dest, exist_ok=True)
                cmd = ["adb"]
                if serial:
                    cmd += ["-s", serial]
                cmd += ["pull", "/sdcard/Download/", dest]
                res = subprocess.run(cmd, capture_output=True, timeout=120)
                if res.returncode == 0:
                    log(f"Successfully backed up Downloads to {dest}")
                else:
                    log(f"Failed to backup Downloads: {res.stderr.decode(errors='replace')}")

            curr_progress += step
            prog(min(curr_progress, 99))

        prog(100)
        log("Backup utility process COMPLETED.")
        return f"Successfully backed up {types} to {local_dest_dir}"

    except Exception as e:
        log(f"Backup failed with error: {e}")
        prog(100)
        return f"Backup failed: {e}"


# ═══════════════════════════════════════════════════════════════
# MAIN DISPATCH
# ═══════════════════════════════════════════════════════════════

def phone_control(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """
    Dispatch table for all phone control actions.
    Supports multi-device via 'device' parameter (serial number).
    """
    params = parameters or {}
    action = params.get("action", "").lower().strip()
    serial = _get_device_serial(params, player)

    if not action:
        return "No action specified for phone_control."

    if player:
        device_tag = f" [{serial[:8]}]" if serial else ""
        player.write_log(f"[Phone{device_tag}] {action}")

    print(f"[PhoneControl] ▶ {action}  serial={serial}  {params}")

    try:
        # ── Device Management ──
        if action == "device_check":
            return _check_device(serial)

        if action == "list_devices":
            devices = _list_devices()
            if not devices:
                return "No Android devices connected."
            lines = [f"  {i+1}. {d['model']} — {d['serial']} ({d['status']})"
                     for i, d in enumerate(devices)]
            return f"Connected devices ({len(devices)}):\n" + "\n".join(lines)

        if action == "wifi_connect":
            ip = params.get("ip_address", "")
            if not ip:
                return "ip_address required for wifi_connect"
            return _wifi_connect(ip)

        # ── Basic Controls ──
        if action == "tap":
            return _tap(serial, int(params.get("x", 0)), int(params.get("y", 0)))

        if action == "swipe":
            return _swipe(serial,
                          int(params.get("x1", 0)), int(params.get("y1", 0)),
                          int(params.get("x2", 0)), int(params.get("y2", 0)),
                          int(params.get("duration", 300)))

        if action == "long_press":
            return _long_press(serial,
                               int(params.get("x", 0)), int(params.get("y", 0)),
                               int(params.get("duration", 1500)))

        if action == "type":
            return _type_text(serial, params.get("text", ""))

        if action == "key":
            return _key_event(serial, params.get("keycode", "ENTER"))

        if action == "scroll":
            return _scroll(serial,
                           params.get("direction", "down"),
                           int(params.get("amount", 3)))

        # ── Navigation ──
        if action == "home":
            return _go_home(serial)

        if action == "back":
            return _go_back(serial)

        if action == "recents":
            return _recents(serial)

        if action == "notifications":
            return _notifications(serial)

        # ── Media / Hardware ──
        if action == "volume_up":
            return _volume_up(serial)

        if action == "volume_down":
            return _volume_down(serial)

        if action == "mute":
            return _mute_toggle(serial)

        if action == "power":
            return _power_btn(serial)

        if action == "lock_screen":
            return _lock_screen(serial)

        if action == "unlock":
            return _unlock(serial)

        # ── Settings ──
        if action == "brightness":
            return _set_brightness(serial, int(params.get("value", 128)))

        if action == "wifi_toggle":
            enable = str(params.get("value", "1")).lower() not in ("0", "false", "off", "disable")
            return _wifi_toggle(serial, enable)

        if action == "airplane_mode":
            enable = str(params.get("value", "1")).lower() not in ("0", "false", "off", "disable")
            return _airplane_mode(serial, enable)

        # ── App Management ──
        if action == "open_app":
            name = params.get("app_name", "")
            if not name:
                return "app_name required"
            return _open_app(serial, name)

        if action == "close_app":
            name = params.get("app_name", "")
            if not name:
                return "app_name required"
            return _close_app(serial, name)

        if action == "current_app":
            return _current_app(serial)

        if action == "list_apps":
            return _list_apps(serial)

        if action == "install_apk":
            path = params.get("apk_path", "")
            if not path:
                return "apk_path required"
            return _install_apk(serial, path)

        if action == "open_url":
            url = params.get("url", "")
            if not url:
                return "url required"
            return _open_url(serial, url)

        # ── Screenshot / Vision ──
        if action == "screenshot":
            return _screenshot(serial, params.get("save_path"))

        if action == "screen_find":
            desc = params.get("description", "")
            if not desc:
                return "description required for screen_find"
            coords = _screen_find(serial, desc)
            return f"{coords[0]},{coords[1]}" if coords else "NOT_FOUND"

        if action == "screen_tap":
            desc = params.get("description", "")
            if not desc:
                return "description required for screen_tap"
            return _screen_tap(serial, desc)

        # ── Phone Info ──
        if action == "phone_info":
            return _phone_info(serial)

        # ── Calls ──
        if action == "call":
            number = params.get("phone_number", "") or params.get("contact_name", "")
            if not number:
                return "phone_number or contact_name required"
            if not re.search(r'\d', number):
                contacts = _search_contacts(serial, number)
                return f"Please provide a phone number. {contacts}"
            return _call(serial, number)

        if action == "end_call":
            return _end_call(serial)

        # ── Messaging ──
        if action == "send_whatsapp":
            contact = params.get("contact_name", "") or params.get("phone_number", "")
            message = params.get("message", "") or params.get("text", "")
            if not contact or not message:
                return "contact_name/phone_number and message required"
            return _send_whatsapp(serial, contact, message)

        if action == "send_sms":
            number = params.get("phone_number", "")
            message = params.get("message", "") or params.get("text", "")
            if not number or not message:
                return "phone_number and message required"
            return _send_sms(serial, number, message)

        if action == "whatsapp_call":
            number = params.get("phone_number", "") or params.get("contact_name", "") or params.get("text", "")
            call_type = params.get("call_type", "audio")
            if not number:
                return "phone_number or contact_name is required for whatsapp_call"
            return _whatsapp_call(serial, number, call_type)

        # ── Screen Recording ──
        if action == "record_screen":
            dur = int(params.get("duration", 30))
            return _record_screen(serial, dur)

        if action == "stop_recording":
            return _stop_recording(serial, params.get("save_path"))

        # ── File Transfer ──
        if action == "pull_file":
            pp = params.get("phone_path", "")
            if not pp:
                return "phone_path required"
            return _pull_file(serial, pp, params.get("save_path"))

        if action == "push_file":
            lp = params.get("local_path", "")
            if not lp:
                return "local_path required"
            return _push_file(serial, lp, params.get("phone_path", "/sdcard/"))

        # ── Backup & Clipboard Share ──
        if action == "backup":
            bt = params.get("backup_type", "all")
            dest = params.get("local_path", "")
            return _backup_phone(serial, bt, dest)

        if action == "share_clipboard":
            text = params.get("text", "")
            if not text:
                return "text is required for share_clipboard"
            return _share_clipboard(serial, text)

        if action == "diagnose_and_fix":
            ui_glitch = str(params.get("ui_glitch", "0")).lower() not in ("0", "false", "off", "no")
            return _diagnose_and_fix_phone(serial, ui_glitch=ui_glitch)

        if action == "reboot":
            try:
                _adb(serial, "reboot", timeout=5)
                return "Phone reboot command sent successfully. The device is restarting."
            except Exception as e:
                return f"Reboot failed: {e}"

        if action == "reset_app":
            app_name = params.get("app_name", "")
            if not app_name:
                return "app_name required for reset_app"
            pkg = _resolve_package(app_name, serial)
            if not pkg:
                return f"Could not find app package for: '{app_name}'"
            try:
                _adb_shell(serial, f"pm clear {pkg}", timeout=10)
                return f"App '{app_name}' ({pkg}) has been fully reset (data & cache cleared)."
            except Exception as e:
                return f"Failed to reset app: {e}"

        if action == "grant_permissions":
            app_name = params.get("app_name", "")
            if not app_name:
                return "app_name required for grant_permissions"
            pkg = _resolve_package(app_name, serial)
            if not pkg:
                return f"Could not find app package for: '{app_name}'"
            perms = [
                "android.permission.READ_EXTERNAL_STORAGE",
                "android.permission.WRITE_EXTERNAL_STORAGE",
                "android.permission.CAMERA",
                "android.permission.ACCESS_FINE_LOCATION",
                "android.permission.RECORD_AUDIO",
                "android.permission.READ_CONTACTS"
            ]
            granted = []
            for perm in perms:
                try:
                    _adb_shell(serial, f"pm grant {pkg} {perm}", timeout=5)
                    granted.append(perm.split(".")[-1])
                except Exception:
                    pass
            return f"Permissions granted to '{app_name}' ({pkg}): {', '.join(granted) if granted else 'None (already granted or not supported)'}"

        if action == "battery_status":
            return _battery_status(serial)

        if action == "ringer_mode":
            mode = params.get("mode", "") or params.get("text", "")
            if not mode:
                return "mode (silent|vibrate|normal) is required for ringer_mode"
            return _ringer_mode(serial, mode)

        if action == "camera_photo":
            return _camera_photo(serial, params.get("save_path"))

        if action == "youtube_play":
            query = params.get("query", "") or params.get("text", "")
            if not query:
                return "query/text is required for youtube_play"
            return _youtube_play(serial, query)

        if action == "screen_state":
            state = params.get("state", "toggle") or params.get("text", "toggle")
            return _screen_state(serial, state)

        return f"Unknown phone action: '{action}'"

    except subprocess.TimeoutExpired:
        return f"phone_control '{action}' timed out — is the device responding?"
    except FileNotFoundError:
        return "ADB not found. Install Android SDK Platform Tools and add to PATH."
    except Exception as e:
        print(f"[PhoneControl] [ERROR] {action}: {e}")
        return f"phone_control '{action}' failed: {e}"
