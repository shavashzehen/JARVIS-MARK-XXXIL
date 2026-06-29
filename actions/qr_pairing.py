#qr_pairing.py
"""
QR-based phone pairing for Jarvis.
Generates a QR code for Android Wireless Debugging pairing.
"""
import io
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

_BASE = _base_dir()
_pt_path = _BASE / "platform-tools"
if _pt_path.exists() and str(_pt_path) not in os.environ.get("PATH", ""):
    os.environ["PATH"] = str(_pt_path) + os.pathsep + os.environ.get("PATH", "")

try:
    import qrcode
    _QR_OK = True
except ImportError:
    _QR_OK = False


# ═══════════════════════════════════════════════════════════════
# NETWORK HELPERS
# ═══════════════════════════════════════════════════════════════

def get_local_ip() -> str:
    """Get this PC's local network IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


_adb_path = str(_pt_path / "adb.exe") if (_pt_path / "adb.exe").exists() else "adb"

def _adb(*args, timeout: int = 10) -> subprocess.CompletedProcess:
    """Run an ADB command."""
    cmd = [_adb_path] + list(args)
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


# ═══════════════════════════════════════════════════════════════
# QR CODE GENERATION
# ═══════════════════════════════════════════════════════════════

def generate_pairing_qr(port: int = 5555) -> tuple[bytes, str, str]:
    """
    Generate a QR code for ADB wireless pairing.
    
    The QR content follows the Android Wireless Debugging format:
    WIFI:T:ADB;S:JARVIS-<IP>;P:<pairing_code>;;
    
    Returns: (png_bytes, ip_address, pairing_info_text)
    """
    if not _QR_OK:
        raise RuntimeError("qrcode library not installed. Run: pip install qrcode[pil]")
    
    ip = get_local_ip()
    pairing_info = f"IP: {ip}\nPort: {port}"
    
    # Generate QR content — contains PC connection info
    # The user will use this to pair via Wireless Debugging
    qr_content = f"WIFI:T:ADB;S:adb-{ip}-jarvis;P:{port};;"
    
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(qr_content)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="#00d4ff", back_color="#00060a")
    
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()
    
    return png_bytes, ip, pairing_info


def pair_device(ip: str, port: int, pairing_code: str) -> str:
    """
    Pair with a device using ADB wireless debugging.
    Uses: adb pair <ip>:<port> <pairing_code>
    """
    try:
        target = f"{ip}:{port}"
        r = _adb("pair", target, pairing_code, timeout=15)
        out = r.stdout.decode(errors="replace").strip()
        err = r.stderr.decode(errors="replace").strip()
        
        if "Successfully paired" in out or "successfully" in out.lower():
            print(f"[QR Pairing] Paired with {target}")
            return f"Successfully paired with {target}"
        
        return f"Pairing result: {out or err}"
    except subprocess.TimeoutExpired:
        return "Pairing timed out — make sure the phone is ready."
    except FileNotFoundError:
        return "ADB not found. Please install Android SDK Platform Tools."
    except Exception as e:
        return f"Pairing error: {e}"


def connect_device(ip: str, port: int = 5555) -> str:
    """
    Connect to a paired device wirelessly.
    Uses: adb connect <ip>:<port>
    """
    try:
        target = f"{ip}:{port}"
        r = _adb("connect", target, timeout=10)
        out = r.stdout.decode(errors="replace").strip()
        
        if "connected" in out.lower():
            print(f"[QR Pairing] Connected to {target}")
            return f"Connected to {target}"
        
        return f"Connection result: {out}"
    except subprocess.TimeoutExpired:
        return "Connection timed out."
    except Exception as e:
        return f"Connection error: {e}"


def list_paired_devices() -> list[dict]:
    """List currently connected ADB devices."""
    try:
        r = _adb("devices", "-l", timeout=5)
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
            for p in parts[2:]:
                if p.startswith("model:"):
                    model = p.split(":", 1)[1]
            devices.append({
                "serial": serial,
                "status": status,
                "model": model or "Unknown",
            })
        return devices
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════
# AUTO-DISCOVERY (background thread)
# ═══════════════════════════════════════════════════════════════

_discovery_callback = None
_discovery_running = False
_discovery_thread = None


def start_device_discovery(callback=None, interval: float = 3.0):
    """
    Start a background thread that polls for new ADB devices.
    Calls callback(devices_list) whenever the device list changes.
    """
    global _discovery_callback, _discovery_running, _discovery_thread
    _discovery_callback = callback
    _discovery_running = True
    
    def _poll():
        global _discovery_running
        last_serials = set()
        while _discovery_running:
            try:
                devices = list_paired_devices()
                current = {d["serial"] for d in devices}
                if current != last_serials:
                    last_serials = current
                    if _discovery_callback:
                        _discovery_callback(devices)
            except Exception:
                pass
            time.sleep(interval)
    
    _discovery_thread = threading.Thread(target=_poll, daemon=True)
    _discovery_thread.start()


def stop_device_discovery():
    """Stop the background discovery thread."""
    global _discovery_running
    _discovery_running = False
