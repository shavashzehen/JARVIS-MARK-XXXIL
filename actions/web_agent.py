# web_agent.py
"""
Autonomous Web Agent for browser task automation.
Loops through browser screenshots and uses Gemini Vision to determine the next browser action.
"""
import json
import time
import os
import sys
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

def run_autonomous_web_task(goal: str, player=None) -> str:
    """Run an autonomous looping agent to accomplish a web goal using browser screenshots and Gemini Vision."""
    api_key = _get_api_key()
    if not api_key:
        return "API key not configured."

    try:
        import google.generativeai as genai
        from actions.browser_control import browser_control
        
        _log_player(player, f"Agent: Initializing browser for goal: '{goal}'")
        
        # Ensure a browser session is running
        browser_control({"action": "go_to", "url": "https://www.google.com"}, player=player)
        time.sleep(2)

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")

        history = []
        max_steps = 8
        
        for step in range(1, max_steps + 1):
            _log_player(player, f"Agent: Analyzing step {step}/{max_steps}...")

            # 1. Take a screenshot of the browser
            screenshot_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scratch", f"agent_step_{step}.png")
            os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)
            
            # Save screenshot
            browser_control({"action": "screenshot", "path": screenshot_path}, player=player)
            time.sleep(1)
            
            if not os.path.exists(screenshot_path):
                # Fallback path if custom path wasn't used
                fallback = str(Path.home() / "Desktop" / "jarvis_screenshot.png")
                if os.path.exists(fallback):
                    import shutil
                    shutil.move(fallback, screenshot_path)
                else:
                    return f"Agent failed: Could not capture browser screenshot."

            img_bytes = Path(screenshot_path).read_bytes()

            # 2. Query Gemini for the next action
            prompt = f"""You are an autonomous AI web agent operating a browser to achieve the user's goal.
User Goal: "{goal}"

Current Step: {step}/{max_steps}
Action History so far: {history}

Analyze this browser screenshot and determine the next action. You can click elements, type text, go to URLs, scroll, or finish.
If the goal is fully accomplished, return action="finish".
To click something, return action="click" and specify "selector" OR "text" to click. Prefer clicking text if visible.
To type something, return action="type" and specify "selector" OR "description" and the "text" to type.
To go to a URL, return action="go_to" and "url".
To scroll, return action="scroll" and "direction" ("up" or "down").
To press Enter or another key, return action="press" and "key" (e.g. "Enter").

YOUR RESPONSE MUST BE A VALID JSON OBJECT matching this structure:
{{
  "action": "click" | "type" | "go_to" | "scroll" | "press" | "finish",
  "url": "https://...",
  "text": "text to type or text to click",
  "selector": "playwright selector (optional)",
  "description": "description of element (for smart_type)",
  "direction": "up" | "down",
  "key": "Enter",
  "thought": "your brief reasoning of what to do next"
}}
Do not write any markdown blocks, only return the raw JSON object."""

            contents = [
                prompt,
                {"mime_type": "image/png", "data": img_bytes}
            ]

            response = model.generate_content(contents)
            text_resp = response.text.strip()
            
            # Clean up potential markdown formatting
            if text_resp.startswith("```json"):
                text_resp = text_resp.split("```json", 1)[1].split("```", 1)[0].strip()
            elif text_resp.startswith("```"):
                text_resp = text_resp.split("```", 1)[1].split("```", 1)[0].strip()

            try:
                decision = json.loads(text_resp)
            except Exception:
                _log_player(player, f"Agent: Error parsing decision: {text_resp[:60]}")
                decision = {"action": "finish", "thought": "Failed to parse JSON response."}

            action = decision.get("action", "finish").lower().strip()
            thought = decision.get("thought", "")
            
            log_msg = f"Agent Thought: {thought}"
            _log_player(player, f"Agent: {log_msg}")

            if action == "finish":
                _log_player(player, f"Agent: Goal reached or task finished. {thought}")
                break

            # 3. Execute the browser action
            _log_player(player, f"Agent executing action: {action.upper()}...")
            
            # Map decision keys to browser_control parameters
            cmd_params = {"action": action}
            if action == "go_to":
                cmd_params["url"] = decision.get("url", "")
            elif action == "click":
                if decision.get("selector"):
                    cmd_params["selector"] = decision.get("selector")
                if decision.get("text"):
                    cmd_params["text"] = decision.get("text")
                if not cmd_params.get("selector") and not cmd_params.get("text") and decision.get("description"):
                    cmd_params["action"] = "smart_click"
                    cmd_params["description"] = decision.get("description")
            elif action == "type":
                cmd_params["text"] = decision.get("text", "")
                if decision.get("selector"):
                    cmd_params["selector"] = decision.get("selector")
                elif decision.get("description"):
                    cmd_params["action"] = "smart_type"
                    cmd_params["description"] = decision.get("description")
            elif action == "scroll":
                cmd_params["direction"] = decision.get("direction", "down")
            elif action == "press":
                cmd_params["key"] = decision.get("key", "Enter")

            # Run action
            res = browser_control(cmd_params, player=player)
            history.append(f"Step {step}: {action} -> {res}")
            
            # Wait for page updates
            time.sleep(3)

        return f"Autonomous agent run completed. History: {history}"

    except Exception as e:
        err = f"Autonomous web agent failed: {e}"
        _log_player(player, f"Agent: [ERROR] {err}")
        return err
