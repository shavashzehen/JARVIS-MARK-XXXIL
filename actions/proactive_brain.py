# proactive_brain.py
"""
Jarvis Proactive Brain / Cognitive Thought Engine.
Periodically checks computer metrics and active mobile phone status,
reasons about any issues, and outputs suggestions via UI Thought Log and vocal alerts.
"""
import os
import sys
import time
import json
import threading
import datetime
from pathlib import Path

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

_BASE = _base_dir()
_CONFIG_PATH = _BASE / "config" / "api_keys.json"

def _load_api_key() -> str:
    try:
        if _CONFIG_PATH.exists():
            return json.loads(_CONFIG_PATH.read_text(encoding="utf-8")).get("gemini_api_key", "")
    except Exception:
        pass
    return ""

_brain_running = False
_brain_thread = None

class ProactiveBrain:
    def __init__(self, jarvis_live):
        self.jarvis = jarvis_live
        self.ui = jarvis_live.ui
        self.api_key = _load_api_key()
        self.check_interval = 60  # seconds
        self.high_cpu_count = 0
        self.last_greeting_date = None
        self.last_spoken_alert = None
        self.last_spoken_time = 0

    def start(self):
        global _brain_running, _brain_thread
        if _brain_running:
            return
        _brain_running = True
        _brain_thread = threading.Thread(target=self._loop, daemon=True)
        _brain_thread.start()
        self.ui.write_log("SYS: Proactive Thought Engine ACTIVE")

    def stop(self):
        global _brain_running
        _brain_running = False

    def _loop(self):
        # Allow UI/Connection to stabilize first
        time.sleep(5)
        while _brain_running:
            try:
                # 1. Gather all PC metrics
                import psutil
                cpu = psutil.cpu_percent()
                mem = psutil.virtual_memory().percent
                
                # Check laptop temp
                from ui import _metrics
                snap = _metrics.snapshot()
                temp = snap.get("tmp", -1)
                
                # 2. Gather Phone metrics (if connected)
                phone_serial = self.ui.active_device
                phone_connected = phone_serial is not None
                phone_battery = "N/A"
                phone_charging = "N/A"
                phone_crashes = []
                phone_model = "N/A"
                phone_dnd = "N/A"
                phone_brightness = "N/A"

                if phone_connected:
                    try:
                        from actions.phone_control import _adb_shell, _list_devices
                        devices = _list_devices()
                        for d in devices:
                            if d["serial"] == phone_serial:
                                phone_model = d["model"]
                                break
                                
                        # Battery
                        battery_out = _adb_shell(phone_serial, "dumpsys battery", timeout=3)
                        for line in battery_out.split("\n"):
                            line = line.strip()
                            if line.startswith("level:"):
                                phone_battery = line.split(":")[1].strip() + "%"
                            elif line.startswith("status:"):
                                status_val = line.split(":")[1].strip()
                                phone_charging = "Yes" if status_val in ("2", "5") else "No"
                        
                        # Zen/DND
                        zen = _adb_shell(phone_serial, "settings get global zen_mode", timeout=3).strip()
                        phone_dnd = "ON" if zen != "0" and zen.isdigit() else "OFF"
                        
                        # Brightness
                        bright = _adb_shell(phone_serial, "settings get system screen_brightness", timeout=3).strip()
                        phone_brightness = bright if bright.isdigit() else "unknown"

                        # Check recent crashes in logcat
                        crash_logs = _adb_shell(phone_serial, "logcat -d -b crash -t 15", timeout=3)
                        if crash_logs and len(crash_logs.strip()) > 10:
                            import re
                            matches = re.findall(r"Process:\s+([a-zA-Z0-9\._]+)", crash_logs)
                            if matches:
                                phone_crashes = list(set(matches))
                    except Exception as e:
                        print(f"[ProactiveBrain] Phone check error: {e}")

                # 3. Detect any warning anomalies immediately
                anomalies = []
                
                if cpu > 80:
                    self.high_cpu_count += 1
                    if self.high_cpu_count >= 2:
                        anomalies.append(f"Laptop CPU usage is critically high ({cpu}%)")
                else:
                    self.high_cpu_count = 0

                if mem > 88:
                    anomalies.append(f"Laptop RAM memory usage is very high ({mem}%)")

                if temp > 78:
                    anomalies.append(f"Laptop core temperature is high ({temp}°C)")

                if phone_connected:
                    if phone_battery != "N/A":
                        bat_pct = int(phone_battery.replace("%", ""))
                        if bat_pct < 15 and phone_charging == "No":
                            anomalies.append(f"Connected Android phone battery is low ({phone_battery}) and not charging")
                    if phone_crashes:
                        anomalies.append(f"Android phone apps recently crashed: {phone_crashes}")
                    if phone_dnd == "ON":
                        anomalies.append("Android phone is in Do Not Disturb (DND) mode, which might block important incoming alerts")
                    if phone_brightness.isdigit() and int(phone_brightness) == 255:
                        anomalies.append("Android phone screen brightness is set to max (255), causing high battery consumption")

                # Time-based checks
                now = datetime.datetime.now()
                hour = now.hour
                current_date = now.date()

                # Morning greeting (proactive check-in once a day between 6 AM and 11 AM)
                is_morning = 6 <= hour <= 11
                if is_morning and self.last_greeting_date != current_date:
                    self.last_greeting_date = current_date
                    anomalies.append("First morning system boot up. Time for a morning briefing.")

                # Late night check
                if hour >= 22 or hour <= 4:
                    anomalies.append("It is late night (past 10 PM)")

                # If no anomalies or greetings, we still log a "Thinking status" in the thought log, but do not speak
                if anomalies:
                    suggestion = self._ask_gemini_to_think(cpu, mem, temp, phone_model, phone_battery, phone_charging, phone_crashes, anomalies)
                    if suggestion and not suggestion.startswith("SAFE"):
                        # Log it to thought log
                        self._log_thought(f"🧠 {suggestion}")
                        
                        # Rate limit vocal speech alerts (min 5 minutes between speaks to prevent irritation)
                        cur_t = time.time()
                        if (suggestion != self.last_spoken_alert) or (cur_t - self.last_spoken_time > 300):
                            self.last_spoken_alert = suggestion
                            self.last_spoken_time = cur_t
                            self.jarvis.speak(suggestion)
                    else:
                        self._log_thought("All systems operational. Background conditions checked.")
                else:
                    self._log_thought("All systems operating at peak efficiency, sir.")

            except Exception as e:
                print(f"[ProactiveBrain] Loop error: {e}")
            
            # Sleep in intervals
            for _ in range(self.check_interval):
                if not _brain_running:
                    break
                time.sleep(1)

    def _log_thought(self, text: str):
        try:
            # Append log to UI thought log
            if hasattr(self.ui, "_win") and hasattr(self.ui._win, "_thought_log"):
                self.ui._win._thought_log.append_log(text)
            else:
                self.ui.write_log(f"🧠 [Thought] {text}")
        except Exception:
            pass

    def _ask_gemini_to_think(self, cpu, mem, temp, phone_model, phone_battery, phone_charging, phone_crashes, anomalies) -> str:
        try:
            from google import genai
            if not self.api_key:
                return "SAFE: API key missing."
                
            client = genai.Client(api_key=self.api_key)
            prompt = (
                f"You are the proactive thinking core of JARVIS, Tony Stark's AI assistant.\n"
                f"Here are the current system metrics and observations:\n"
                f"- Laptop CPU: {cpu}%\n"
                f"- Laptop RAM: {mem}%\n"
                f"- Laptop Temp: {temp}°C\n"
                f"- Phone Connected: {phone_model} (Battery: {phone_battery}, Charging: {phone_charging})\n"
                f"- Phone Crashed Apps: {phone_crashes}\n"
                f"- Anomalies/Observations detected: {anomalies}\n\n"
                f"Your task is to think about these inputs. If there are warnings, suggestions, or briefings, "
                f"formulate a natural, polite, and brief voice message (1-2 sentences) addressing the user as 'sir'.\n"
                f"If the observation is just normal operation or you have no recommendation, reply with exactly 'SAFE'."
            )
            
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )
            return response.text.strip()
        except Exception as e:
            print(f"[ProactiveBrain] Gemini call failed: {e}")
            return "SAFE"
