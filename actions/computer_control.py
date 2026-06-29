#computer_control.py
import io
import json
import re
import string
import subprocess
import sys
import time
import random
from pathlib import Path

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE    = 0.05
    _PYAUTOGUI = True
except ImportError:
    _PYAUTOGUI = False

try:
    import pyperclip
    _PYPERCLIP = True
except ImportError:
    _PYPERCLIP = False

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


_BASE         = _base_dir()
_CONFIG_PATH  = _BASE / "config" / "api_keys.json"
_MEMORY_PATH  = _BASE / "memory" / "long_term.json"

def _load_config() -> dict:
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _get_os() -> str:
    return _load_config().get("os_system", "windows").lower()


def _get_api_key() -> str:
    return _load_config().get("gemini_api_key", "")

_SAFE_SCREENSHOT_ROOTS = (
    Path.home(),
)

def _safe_screenshot_path(requested: str | None) -> Path:
    fallback = Path.home() / "Desktop" / "jarvis_screenshot.png"
    if not requested:
        return fallback
    try:
        p = Path(requested).expanduser().resolve()
        for root in _SAFE_SCREENSHOT_ROOTS:
            if p.is_relative_to(root.resolve()):
                p.parent.mkdir(parents=True, exist_ok=True)
                return p
    except Exception:
        pass
    return fallback

def _require_pyautogui():
    if not _PYAUTOGUI:
        raise RuntimeError("PyAutoGUI not installed. Run: pip install pyautogui")

_FIRST_NAMES = [
    "Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Drew", "Quinn",
    "Avery", "Blake", "Cameron", "Dakota", "Emerson", "Finley", "Harper",
]
_LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Wilson", "Moore", "Taylor", "Anderson", "Thomas", "Jackson",
]
_DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "proton.me", "mail.com"]


def _random_data(data_type: str) -> str:
    dt = data_type.lower().strip()

    if dt == "first_name":
        return random.choice(_FIRST_NAMES)

    if dt == "last_name":
        return random.choice(_LAST_NAMES)

    if dt == "name":
        return f"{random.choice(_FIRST_NAMES)} {random.choice(_LAST_NAMES)}"

    if dt == "email":
        first = random.choice(_FIRST_NAMES).lower()
        last  = random.choice(_LAST_NAMES).lower()
        num   = random.randint(10, 999)
        return f"{first}.{last}{num}@{random.choice(_DOMAINS)}"

    if dt == "username":
        return f"{random.choice(_FIRST_NAMES).lower()}{random.randint(100, 9999)}"

    if dt == "password":
        chars = string.ascii_letters + string.digits + "!@#$%"
        raw   = (
            random.choice(string.ascii_uppercase)
            + random.choice(string.digits)
            + random.choice("!@#$%")
            + "".join(random.choices(chars, k=9))
        )
        return "".join(random.sample(raw, len(raw)))

    if dt == "phone":
        return f"+1{random.randint(200,999)}{random.randint(1_000_000, 9_999_999)}"

    if dt == "birthday":
        y = random.randint(1980, 2000)
        m = random.randint(1, 12)
        d = random.randint(1, 28)
        return f"{m:02d}/{d:02d}/{y}"

    if dt == "address":
        num    = random.randint(100, 9999)
        street = random.choice(["Main St", "Oak Ave", "Park Blvd", "Elm St", "Cedar Ln"])
        return f"{num} {street}"

    if dt == "zip_code":
        return str(random.randint(10000, 99999))

    if dt == "city":
        return random.choice(["New York", "Los Angeles", "Chicago", "Houston", "Phoenix"])

    return f"random_{data_type}_{random.randint(1000, 9999)}"

def _user_profile() -> dict:
    """Read identity fields from long-term memory."""
    try:
        if _MEMORY_PATH.exists():
            data     = json.loads(_MEMORY_PATH.read_text(encoding="utf-8"))
            identity = data.get("identity", {})
            return {k: v.get("value", "") for k, v in identity.items()}
    except Exception:
        pass
    return {}

def _type(text: str, interval: float = 0.03) -> str:
    _require_pyautogui()
    time.sleep(0.3)
    pyautogui.typewrite(text, interval=interval)
    return f"Typed: {text[:60]}{'…' if len(text) > 60 else ''}"


def _smart_type(text: str, clear_first: bool = True) -> str:
    _require_pyautogui()
    if clear_first:
        _clear_field()
        time.sleep(0.1)

    if len(text) > 20 and _PYPERCLIP:
        pyperclip.copy(text)
        time.sleep(0.1)
        pyautogui.hotkey("ctrl", "v")
        return f"Smart-typed (clipboard): {text[:60]}{'…' if len(text) > 60 else ''}"

    pyautogui.typewrite(text, interval=0.04)
    return f"Smart-typed: {text[:60]}{'…' if len(text) > 60 else ''}"


def _click(x=None, y=None, button: str = "left", clicks: int = 1) -> str:
    _require_pyautogui()
    if x is not None and y is not None:
        pyautogui.click(x, y, button=button, clicks=clicks)
        return f"{'Double-c' if clicks == 2 else 'C'}licked ({x}, {y}) [{button}]"
    pyautogui.click(button=button, clicks=clicks)
    return f"Clicked at current position [{button}]"


def _hotkey(*keys) -> str:
    _require_pyautogui()
    pyautogui.hotkey(*keys)
    return f"Hotkey: {'+'.join(keys)}"


def _press(key: str) -> str:
    _require_pyautogui()
    pyautogui.press(key)
    return f"Pressed: {key}"


def _scroll(direction: str = "down", amount: int = 3) -> str:
    _require_pyautogui()
    vertical   = direction in ("up", "down")
    clicks     = amount if direction in ("up", "right") else -amount
    pyautogui.scroll(clicks) if vertical else pyautogui.hscroll(clicks)
    return f"Scrolled {direction} ×{amount}"


def _move(x: int, y: int, duration: float = 0.3) -> str:
    _require_pyautogui()
    pyautogui.moveTo(x, y, duration=duration)
    return f"Mouse → ({x}, {y})"


def _drag(x1: int, y1: int, x2: int, y2: int, duration: float = 0.5) -> str:
    _require_pyautogui()
    pyautogui.moveTo(x1, y1, duration=0.2)
    pyautogui.dragTo(x2, y2, duration=duration, button="left")
    return f"Dragged ({x1},{y1}) → ({x2},{y2})"


def _clipboard_get() -> str:
    if _PYPERCLIP:
        return pyperclip.paste()
    _hotkey("ctrl", "c")
    time.sleep(0.2)
    return "(copied — pyperclip unavailable for read)"


def _clipboard_paste(text: str) -> str:
    if _PYPERCLIP:
        pyperclip.copy(text)
        time.sleep(0.1)
        _require_pyautogui()
        pyautogui.hotkey("ctrl", "v")
        return f"Pasted: {text[:60]}{'…' if len(text) > 60 else ''}"
    return "pyperclip not available"


def _screenshot(save_path: str | None = None) -> str:
    _require_pyautogui()
    path = _safe_screenshot_path(save_path)
    img  = pyautogui.screenshot()
    img.save(str(path))
    return f"Screenshot saved: {path}"


def _clear_field() -> str:
    _require_pyautogui()
    pyautogui.hotkey("ctrl", "a")
    time.sleep(0.1)
    pyautogui.press("delete")
    return "Field cleared"

def _screenshot_active(save_path: str | None = None) -> str:
    _require_pyautogui()
    path = _safe_screenshot_path(save_path)
    try:
        import pygetwindow as gw
        active = gw.getActiveWindow()
        if active and active.width > 0 and active.height > 0:
            x, y, w, h = active.left, active.top, active.width, active.height
            img = pyautogui.screenshot(region=(x, y, w, h))
            img.save(str(path))
            return f"Active window '{active.title}' screenshot saved: {path}"
    except Exception as e:
        print(f"[ComputerControl] Active window screenshot failed: {e}")
    # Fallback to full screenshot
    return _screenshot(save_path)

def _empty_recycle_bin() -> str:
    os_name = _get_os()
    if os_name == "windows":
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", "Clear-RecycleBin -Force -ErrorAction SilentlyContinue"],
                capture_output=True, timeout=10
            )
            return "Windows Recycle Bin emptied successfully."
        except Exception as e:
            return f"Failed to empty Windows Recycle Bin: {e}"
    elif os_name == "mac":
        try:
            subprocess.run(
                ["osascript", "-e", 'tell application "Finder" to empty trash'],
                capture_output=True, timeout=10
            )
            return "macOS Trash emptied successfully."
        except Exception as e:
            return f"Failed to empty macOS Trash: {e}"
    elif os_name == "linux":
        try:
            subprocess.run("rm -rf ~/.local/share/Trash/*", shell=True, timeout=10)
            return "Linux Trash emptied successfully."
        except Exception as e:
            return f"Failed to empty Linux Trash: {e}"
    return f"empty_recycle_bin: unsupported OS '{os_name}'"

def _lock_workstation() -> str:
    os_name = _get_os()
    if os_name == "windows":
        try:
            import ctypes
            ctypes.windll.user32.LockWorkStation()
            return "Windows locked successfully."
        except Exception as e:
            subprocess.run("rundll32.exe user32.dll,LockWorkStation", shell=True)
            return "Windows lock command sent."
    elif os_name == "mac":
        subprocess.run(
            ["osascript", "-e", 'tell application "System Events" to keystroke "q" using {control down, command down}'],
            capture_output=True
        )
        return "macOS Lock command sent."
    elif os_name == "linux":
        subprocess.run("xdg-screensaver lock", shell=True)
        return "Linux lock command sent."
    return f"lock_workstation: unsupported OS '{os_name}'"

def _get_selected_text() -> str:
    _require_pyautogui()
    old_clipboard = ""
    if _PYPERCLIP:
        try:
            old_clipboard = pyperclip.paste()
        except Exception:
            pass
            
    pyautogui.hotkey("ctrl", "c")
    time.sleep(0.15)
    
    selected = ""
    if _PYPERCLIP:
        try:
            selected = pyperclip.paste()
            if old_clipboard:
                pyperclip.copy(old_clipboard)
        except Exception:
            pass
            
    return selected.strip() if selected else "(no text selected or clipboard copy failed)"

def _focus_window(title: str) -> str:
    os_name = _get_os()

    if os_name == "windows":
        try:
            script = f'(New-Object -ComObject WScript.Shell).AppActivate("{title}")'
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, timeout=5,
            )
            time.sleep(0.3)
            return f"Focused window: {title}"
        except Exception as e:
            return f"focus_window (Windows) failed: {e}"

    if os_name == "mac":
        script = (
            f'tell application "System Events" to '
            f'set frontmost of (first process whose name contains "{title}") to true'
        )
        try:
            subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, timeout=5,
            )
            time.sleep(0.3)
            return f"Focused window: {title}"
        except Exception as e:
            return f"focus_window (macOS) failed: {e}"

    if os_name == "linux":
        try:
            result = subprocess.run(
                ["wmctrl", "-a", title],
                capture_output=True, timeout=5,
            )
            if result.returncode == 0:
                time.sleep(0.3)
                return f"Focused window: {title}"
        except FileNotFoundError:
            pass
        try:
            result = subprocess.run(
                ["xdotool", "search", "--name", title, "windowactivate"],
                capture_output=True, timeout=5,
            )
            time.sleep(0.3)
            return f"Focused window: {title}"
        except FileNotFoundError:
            return "focus_window (Linux) requires wmctrl or xdotool"
        except Exception as e:
            return f"focus_window (Linux) failed: {e}"

    return f"focus_window: unknown OS '{os_name}'"

def _screen_find(description: str) -> tuple[int, int] | None:
    api_key = _get_api_key()
    if not api_key:
        print("[ComputerControl] ⚠️ No API key for screen_find")
        return None

    try:
        from google import genai
        from google.genai import types as gtypes

        _require_pyautogui()
        w, h  = pyautogui.size()
        img   = pyautogui.screenshot()
        buf   = io.BytesIO()
        img.save(buf, format="PNG")
        image_bytes = buf.getvalue()

        client = genai.Client(api_key=api_key)
        prompt = (
            f"This is a screenshot of a {w}×{h} pixel screen. "
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
            return int(match.group(1)), int(match.group(2))

    except Exception as e:
        print(f"[ComputerControl] ⚠️ screen_find failed: {e}")

    return None

def computer_control(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """
    Dispatch table for all computer control actions.

    parameters keys (all optional unless noted):
      action        : (required) one of the actions listed below
      text          : text to type or paste
      x, y          : screen coordinates
      button        : 'left' | 'right' (default: left)
      keys          : hotkey string, e.g. 'ctrl+c'
      key           : single key name, e.g. 'enter'
      direction     : 'up' | 'down' | 'left' | 'right'
      amount        : scroll amount (default: 3)
      seconds       : wait duration
      title         : window title fragment for focus_window
      description   : natural-language element description for screen_find/click
      type          : data type for random_data
      field         : memory field name for user_data
      clear_first   : bool, clear field before typing (default: true)
      path          : save path for screenshot (must be inside home dir)

    Actions:
      type          — type text at cursor
      smart_type    — clear field + type (clipboard-backed)
      click         — left click
      double_click  — double left click
      right_click   — right click
      move          — move mouse
      drag          — click-drag between two points
      hotkey        — key combination
      press         — single key
      scroll        — scroll the wheel
      copy          — read clipboard
      paste         — write + paste clipboard
      screenshot    — capture screen (safe path only)
      wait          — sleep N seconds
      clear_field   — select-all + delete
      focus_window  — bring window to foreground
      screen_find   — AI element finder (returns x,y)
      screen_click  — AI element finder + click
      random_data   — generate fake form data
      user_data     — pull real data from memory
      window_list   — list all open windows
      window_close  — close a window by title
      window_snap   — snap window (left/right/maximize/minimize)
      clipboard_get — read clipboard content
      clipboard_set — write text to clipboard
      run_command   — execute a shell command
      system_info   — get detailed system information
      process_kill  — kill a process by name
    """
    params = parameters or {}
    action = params.get("action", "").lower().strip()

    if not action:
        return "No action specified for computer_control."

    if player:
        player.write_log(f"[Computer] {action}")

    print(f"[ComputerControl] ▶ {action}  {params}")

    try:

        if action == "type":
            return _type(params.get("text", ""))

        if action == "smart_type":
            return _smart_type(
                params.get("text", ""),
                clear_first=params.get("clear_first", True),
            )

        if action in ("click", "left_click"):
            return _click(params.get("x"), params.get("y"), "left", 1)

        if action == "double_click":
            return _click(params.get("x"), params.get("y"), "left", 2)

        if action == "right_click":
            return _click(params.get("x"), params.get("y"), "right", 1)

        if action == "move":
            return _move(int(params.get("x", 0)), int(params.get("y", 0)))

        if action == "drag":
            return _drag(
                int(params.get("x1", 0)), int(params.get("y1", 0)),
                int(params.get("x2", 0)), int(params.get("y2", 0)),
            )

        if action == "hotkey":
            raw  = params.get("keys", "")
            keys = [k.strip() for k in raw.split("+")] if isinstance(raw, str) else raw
            return _hotkey(*keys)

        if action == "press":
            return _press(params.get("key", "enter"))

        if action == "scroll":
            return _scroll(
                direction=params.get("direction", "down"),
                amount=int(params.get("amount", 3)),
            )

        if action == "copy":
            return _clipboard_get()

        if action == "paste":
            return _clipboard_paste(params.get("text", ""))

        if action == "screenshot":
            return _screenshot(params.get("path"))

        if action == "screen_find":
            coords = _screen_find(params.get("description", ""))
            return f"{coords[0]},{coords[1]}" if coords else "NOT_FOUND"

        if action == "screen_click":
            desc   = params.get("description", "")
            coords = _screen_find(desc)
            if coords:
                time.sleep(0.2)
                _click(x=coords[0], y=coords[1])
                return f"Clicked '{desc}' at {coords}"
            return f"Element not found on screen: '{desc}'"

        if action == "wait":
            secs = float(params.get("seconds", 1.0))
            secs = min(secs, 30.0)
            time.sleep(secs)
            return f"Waited {secs}s"

        if action == "clear_field":
            return _clear_field()

        if action == "focus_window":
            return _focus_window(params.get("title", ""))

        if action == "random_data":
            dt     = params.get("type", "name")
            result = _random_data(dt)
            print(f"[ComputerControl] 🎲 random {dt} → {result}")
            return result

        if action == "user_data":
            field   = params.get("field", "name")
            profile = _user_profile()
            value   = profile.get(field, "")
            if not value:
                value = _random_data(field)
                print(f"[ComputerControl] ⚠️ No '{field}' in memory, using random: {value}")
            return value

        # ── Enhanced Actions ──

        if action == "window_list":
            try:
                import pygetwindow as gw
                windows = gw.getAllWindows()
                visible = [w for w in windows if w.title.strip() and w.visible]
                if not visible:
                    return "No visible windows found."
                lines = [f"  {i+1}. {w.title}" for i, w in enumerate(visible[:20])]
                return f"Open windows ({len(visible)}):\n" + "\n".join(lines)
            except ImportError:
                return "pygetwindow not installed."

        if action == "window_close":
            title = params.get("title", "")
            if not title:
                return "title required for window_close"
            try:
                import pygetwindow as gw
                windows = gw.getWindowsWithTitle(title)
                if not windows:
                    return f"No window found with title containing: '{title}'"
                windows[0].close()
                return f"Closed window: '{windows[0].title}'"
            except Exception as e:
                return f"window_close failed: {e}"

        if action == "window_snap":
            direction = params.get("direction", "maximize").lower()
            title = params.get("title", "")
            try:
                import pygetwindow as gw
                if title:
                    wins = gw.getWindowsWithTitle(title)
                    if not wins:
                        return f"No window: '{title}'"
                    win = wins[0]
                else:
                    win = gw.getActiveWindow()
                    if not win:
                        return "No active window."
                
                if direction == "maximize":
                    win.maximize()
                elif direction == "minimize":
                    win.minimize()
                elif direction == "restore":
                    win.restore()
                elif direction == "left":
                    import ctypes
                    user32 = ctypes.windll.user32
                    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
                    win.restore()
                    win.moveTo(0, 0)
                    win.resizeTo(sw // 2, sh)
                elif direction == "right":
                    import ctypes
                    user32 = ctypes.windll.user32
                    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
                    win.restore()
                    win.moveTo(sw // 2, 0)
                    win.resizeTo(sw // 2, sh)
                else:
                    return f"Unknown snap direction: '{direction}'"
                return f"Window snapped: {direction}"
            except Exception as e:
                return f"window_snap failed: {e}"

        if action == "clipboard_get":
            return _clipboard_get()

        if action == "clipboard_set":
            text = params.get("text", "")
            if not text:
                return "text required for clipboard_set"
            if _PYPERCLIP:
                pyperclip.copy(text)
                return f"Clipboard set ({len(text)} chars)"
            return "pyperclip not installed"

        if action == "run_command":
            cmd = params.get("command", "") or params.get("text", "")
            if not cmd:
                return "command required for run_command"
            try:
                r = subprocess.run(
                    cmd, shell=True, capture_output=True,
                    timeout=30, text=True
                )
                out = r.stdout.strip()
                err = r.stderr.strip()
                result_text = out or err or "(no output)"
                if len(result_text) > 2000:
                    result_text = result_text[:2000] + "...(truncated)"
                return result_text
            except subprocess.TimeoutExpired:
                return "Command timed out (30s limit)"
            except Exception as e:
                return f"run_command failed: {e}"

        if action == "system_info":
            try:
                import psutil
                mem = psutil.virtual_memory()
                disk = psutil.disk_usage("/")
                cpu_freq = psutil.cpu_freq()
                
                lines = [
                    f"CPU: {psutil.cpu_count()} cores, {psutil.cpu_percent()}% usage",
                    f"CPU Freq: {cpu_freq.current:.0f}MHz" if cpu_freq else "CPU Freq: N/A",
                    f"RAM: {mem.used // (1024**3):.1f}GB / {mem.total // (1024**3):.1f}GB ({mem.percent}%)",
                    f"Disk: {disk.used // (1024**3):.0f}GB / {disk.total // (1024**3):.0f}GB ({disk.percent}%)",
                ]
                
                try:
                    battery = psutil.sensors_battery()
                    if battery:
                        lines.append(f"Battery: {battery.percent}%{' (Charging)' if battery.power_plugged else ''}")
                except Exception:
                    pass
                
                import platform as plat
                lines.append(f"OS: {plat.system()} {plat.release()}")
                lines.append(f"Machine: {plat.machine()}")
                
                return "\n".join(lines)
            except Exception as e:
                return f"system_info failed: {e}"

        if action == "process_kill":
            name = params.get("name", "") or params.get("text", "")
            if not name:
                return "name required for process_kill"
            try:
                import psutil
                killed = 0
                for proc in psutil.process_iter(["name", "pid"]):
                    if name.lower() in proc.info["name"].lower():
                        proc.kill()
                        killed += 1
                if killed:
                    return f"Killed {killed} process(es) matching '{name}'"
                return f"No process found matching: '{name}'"
            except Exception as e:
                return f"process_kill failed: {e}"

        if action == "hacking_prank":
            if player:
                player.show_hacker_prank()
                return "Hacker prank overlay console activated."
            return "Failed to show hacker prank — UI player not active."

        if action == "screenshot_active":
            return _screenshot_active(params.get("path"))

        if action == "empty_recycle_bin":
            return _empty_recycle_bin()

        if action == "lock_workstation":
            return _lock_workstation()

        if action == "get_selected_text":
            return _get_selected_text()

        if action == "volume_set":
            val = int(params.get("value", 50))
            from actions.computer_settings import volume_set
            volume_set(val)
            return f"System volume set to {val}%"

        if action == "brightness_set":
            val = int(params.get("value", 50))
            os_name = _get_os()
            if os_name == "windows":
                try:
                    subprocess.run(
                        ["powershell", "-Command",
                         f"(Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1, {val})"],
                        capture_output=True, timeout=5
                    )
                except Exception:
                    pass
            return f"System brightness set to {val}%"

        if action == "mute_toggle":
            from actions.computer_settings import volume_mute
            volume_mute()
            return "Volume mute toggled."

        if action == "open_url":
            url = params.get("url", "")
            if not url:
                return "url required for open_url"
            import webbrowser
            webbrowser.open(url)
            return f"Opened URL in default browser: {url}"

        return f"Unknown action: '{action}'"

    except Exception as e:
        print(f"[ComputerControl] ❌ {action}: {e}")
        return f"computer_control '{action}' failed: {e}"