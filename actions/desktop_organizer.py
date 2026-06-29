# desktop_organizer.py
"""
AI-Powered Desktop Organizer and Summarizer.
Scans files in a watched folder, renames them descriptively, and organizes them into category folders.
"""
import os
import sys
import json
import shutil
from pathlib import Path

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

_BASE = _base_dir()
_KEYS_PATH = _BASE / "config" / "api_keys.json"

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

def organize_desktop(player=None) -> str:
    """Scan and organize files on the desktop or watched local downloads/backups folder using Gemini."""
    api_key = _get_api_key()
    if not api_key:
        return "API key not configured."

    # Watched folder: default is MyProjects/Mark-XXXIX/backups/downloads (since it receives phone downloads!)
    watched_dir = os.path.join(_BASE, "backups", "downloads")
    if not os.path.exists(watched_dir):
        # Fallback to desktop
        watched_dir = str(Path.home() / "Desktop")
        
    dest_base = os.path.join(_BASE, "backups", "organized")
    os.makedirs(dest_base, exist_ok=True)

    _log_player(player, f"SYS: Organizing folder: {watched_dir}")

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")

        files = [f for f in os.listdir(watched_dir) if os.path.isfile(os.path.join(watched_dir, f))]
        if not files:
            msg = "No files found to organize."
            _log_player(player, f"SYS: {msg}")
            return msg

        count = 0
        for filename in files:
            # Skip hidden/system files
            if filename.startswith(".") or filename.startswith("~"):
                continue

            filepath = os.path.join(watched_dir, filename)
            ext = os.path.splitext(filename)[1].lower()
            
            # Read first 500 characters of text if text file for better classification
            content_snippet = ""
            if ext in [".txt", ".csv", ".json", ".xml", ".html", ".md"]:
                try:
                    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                        content_snippet = f.read(500)
                except Exception:
                    pass

            prompt = f"""You are an expert filing system organizer. Categorize and rename this file for a clean desktop.
Original File Name: "{filename}"
File Extension: "{ext}"
Text Content Snippet: "{content_snippet}"

Based on the file name and content, provide:
1. Category Folder: Choose a general category (e.g. "Invoices", "Documents", "Images", "Programming", "Receipts", "Downloads").
2. Clean File Name: Rename the file to a clean, descriptive name using snake_case or standard format (keep extension: {ext}).

Your response must be a valid JSON object:
{{
  "category": "Invoices",
  "clean_name": "clean_descriptive_name{ext}",
  "reason": "brief reason for categorization"
}}
Do not write markdown, return only raw JSON."""

            try:
                response = model.generate_content([prompt])
                text_resp = response.text.strip()
                
                # clean markdown codeblocks
                if text_resp.startswith("```json"):
                    text_resp = text_resp.split("```json", 1)[1].split("```", 1)[0].strip()
                elif text_resp.startswith("```"):
                    text_resp = text_resp.split("```", 1)[1].split("```", 1)[0].strip()
                
                result = json.loads(text_resp)
                category = result.get("category", "General").strip().title()
                clean_name = result.get("clean_name", filename).strip()
                reason = result.get("reason", "")
                
                # Make sure folder exists
                dest_dir = os.path.join(dest_base, category)
                os.makedirs(dest_dir, exist_ok=True)
                
                # Prevent duplicate filename overwrites
                target_path = os.path.join(dest_dir, clean_name)
                base, extension = os.path.splitext(clean_name)
                i = 1
                while os.path.exists(target_path):
                    clean_name = f"{base}_{i}{extension}"
                    target_path = os.path.join(dest_dir, clean_name)
                    i += 1
                
                # Move and rename
                shutil.move(filepath, target_path)
                count += 1
                
                msg = f"Organized '{filename}' -> '{category}/{clean_name}' ({reason})"
                _log_player(player, f"SYS: [AI-Organizer] {msg}")
                print(f"[AI-Organizer] {msg}")

            except Exception as e:
                err_msg = f"Failed to organize '{filename}': {e}"
                _log_player(player, f"SYS: [ERROR] {err_msg}")
                print(f"[AI-Organizer] [ERROR] {err_msg}")

        return f"AI Desktop Organizer complete. Successfully organized {count} file(s) into backups/organized/."
        
    except Exception as e:
        return f"AI Desktop Organizer failed: {e}"
