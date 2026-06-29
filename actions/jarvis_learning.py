# jarvis_learning.py
"""
Jarvis Self-Learning Action module.
Allows registering custom voice macro routines and user preferences.
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
_ROUTINES_PATH = _BASE / "memory" / "custom_routines.json"
_PREFS_PATH = _BASE / "memory" / "long_term_preferences.json"

def _load_routines() -> dict:
    try:
        if _ROUTINES_PATH.exists():
            return json.loads(_ROUTINES_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _save_routines(routines: dict):
    try:
        os.makedirs(_ROUTINES_PATH.parent, exist_ok=True)
        _ROUTINES_PATH.write_text(json.dumps(routines, indent=4), encoding="utf-8")
    except Exception as e:
        print(f"[Learning] Save routines failed: {e}")

def _load_prefs() -> dict:
    try:
        if _PREFS_PATH.exists():
            return json.loads(_PREFS_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _save_prefs(prefs: dict):
    try:
        os.makedirs(_PREFS_PATH.parent, exist_ok=True)
        _PREFS_PATH.write_text(json.dumps(prefs, indent=4), encoding="utf-8")
    except Exception as e:
        print(f"[Learning] Save preferences failed: {e}")

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

def jarvis_learning(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
    speak=None
) -> str:
    """Action worker for self-learning routines and preferences."""
    params = parameters or {}
    action = params.get("action", "").lower().strip()
    trigger = params.get("trigger", "").lower().strip()
    
    # Extract actions (could be passed as list or comma-separated string)
    raw_actions = params.get("actions", [])
    if isinstance(raw_actions, str):
        actions_list = [a.strip() for a in raw_actions.split(",") if a.strip()]
    else:
        actions_list = [str(a).strip() for a in raw_actions if str(a).strip()]

    result = "No changes made."

    if action == "learn_routine":
        if not trigger or not actions_list:
            return "Error: Both 'trigger' and 'actions' are required to learn a routine."
        
        routines = _load_routines()
        routines[trigger] = actions_list
        _save_routines(routines)
        
        result = f"I have successfully learned the routine '{trigger}'. Whenever you say '{trigger}', I will execute: {actions_list}"
        _log_player(player, f"AI-Learning: Learned new routine '{trigger}'")
        if player and hasattr(player, "update_routines_badge"):
            player.update_routines_badge()

    elif action == "save_preference":
        pref_key = params.get("preference_key", "").strip()
        pref_val = params.get("preference_value", "").strip()
        if not pref_key:
            return "Error: 'preference_key' is required to save a preference."
        
        prefs = _load_prefs()
        prefs[pref_key] = pref_val
        _save_prefs(prefs)
        
        result = f"I have saved your preference for '{pref_key}' as '{pref_val}'."
        _log_player(player, f"AI-Learning: Saved preference '{pref_key}' = '{pref_val}'")

    elif action == "list_routines":
        routines = _load_routines()
        if not routines:
            result = "I haven't learned any custom routines yet."
        else:
            result = "Learned custom routines:\n" + "\n".join(f"- '{k}': {v}" for k, v in routines.items())

    else:
        result = f"Unknown learning action: '{action}'."

    if speak:
        speak(result)

    return result
