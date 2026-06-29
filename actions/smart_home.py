# smart_home.py
"""
Smart Home IoT Actions.
Controls and manages the state of simulated home devices (Lights, Fan, AC, Locks).
"""
import os
import sys
import json
from pathlib import Path

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

_BASE = _base_dir()
_STATE_PATH = _BASE / "config" / "smart_home_state.json"

_DEFAULT_STATE = {
    "light": "OFF",
    "fan": "OFF",
    "ac_temp": 24,
    "ac_status": "OFF",
    "door_lock": "LOCKED"
}

def _load_state() -> dict:
    try:
        if _STATE_PATH.exists():
            return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return _DEFAULT_STATE.copy()

def _save_state(state: dict):
    try:
        os.makedirs(_STATE_PATH.parent, exist_ok=True)
        _STATE_PATH.write_text(json.dumps(state, indent=4), encoding="utf-8")
    except Exception as e:
        print(f"[SmartHome] [ERROR] Save state failed: {e}")

def smart_home(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
    speak=None
) -> str:
    """Simulate Smart Home IoT device controls and update dashboard UI."""
    params = parameters or {}
    action = params.get("action", "").lower().strip()
    device = params.get("device", "").lower().strip()
    value = params.get("value", "")

    state = _load_state()
    result = "Device state unchanged."

    if action == "turn_on":
        if "light" in device:
            state["light"] = "ON"
            result = "Living Room Light is now ON."
        elif "fan" in device:
            state["fan"] = "3"
            result = "Fan is now ON at speed 3."
        elif "ac" in device:
            state["ac_status"] = "ON"
            result = f"AC is now ON set to {state['ac_temp']}°C."
        elif "lock" in device:
            state["door_lock"] = "LOCKED"
            result = "Main Door is now LOCKED."
        else:
            result = f"Device '{device}' not found."

    elif action == "turn_off":
        if "light" in device:
            state["light"] = "OFF"
            result = "Living Room Light is now OFF."
        elif "fan" in device:
            state["fan"] = "OFF"
            result = "Fan is now OFF."
        elif "ac" in device:
            state["ac_status"] = "OFF"
            result = "AC is now OFF."
        elif "lock" in device:
            state["door_lock"] = "UNLOCKED"
            result = "Main Door is now UNLOCKED."
        else:
            result = f"Device '{device}' not found."

    elif action == "set_temp":
        try:
            temp = int(value)
            if 16 <= temp <= 30:
                state["ac_temp"] = temp
                state["ac_status"] = "ON"
                result = f"AC temperature is set to {temp}°C."
            else:
                result = "AC temperature must be between 16°C and 30°C."
        except Exception:
            result = "Invalid temperature value."

    elif action == "set_fan_speed":
        speed = str(value).upper().strip()
        if speed in ["OFF", "0"]:
            state["fan"] = "OFF"
            result = "Fan is now OFF."
        elif speed in ["1", "2", "3"]:
            state["fan"] = speed
            result = f"Fan speed set to {speed}."
        else:
            result = "Invalid fan speed. Use: OFF, 1, 2, or 3."

    elif action == "status":
        result = (
            f"Smart Home Status:\n"
            f"- Light: {state['light']}\n"
            f"- Fan Speed: {state['fan']}\n"
            f"- AC: {state['ac_status']} ({state['ac_temp']}°C)\n"
            f"- Main Door: {state['door_lock']}"
        )

    else:
        result = f"Unknown smart home action: '{action}'."

    _save_state(state)
    
    # Notify player UI to repaint simulated values
    if player:
        try:
            player.write_log(f"IoT: {result}")
            if hasattr(player, "update_smart_home_ui"):
                player.update_smart_home_ui()
        except Exception:
            pass

    if speak:
        speak(result)

    return result
