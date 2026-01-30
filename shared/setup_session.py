#!/usr/bin/env python3

"""
Session Setup - Uses persistent browser profile for better captcha bypass.

This script is board-aware:
- Preferred: set `JOB_BOT_BOARD=<board>` and run from repo root.
- Convenience: if `JOB_BOT_BOARD` is not set, it attempts to infer the board
  from the current working directory (e.g. `cd boards/linkedin`).
"""

from pathlib import Path
from playwright.sync_api import sync_playwright
from config_loader import load_config

import os
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
BOARDS_ROOT = REPO_ROOT / "boards"


def _infer_board_from_cwd() -> Optional[str]:
    try:
        rel = Path.cwd().resolve().relative_to(BOARDS_ROOT)
        if rel.parts:
            return rel.parts[0]
    except Exception:
        return None
    return None


BOARD_NAME = os.environ.get("JOB_BOT_BOARD") or _infer_board_from_cwd() or "default"

# Use a persistent browser profile directory per board
PROFILE_ROOT = Path.home() / ".job-search-automation"
USER_DATA_DIR = PROFILE_ROOT / f"job-search-automation-{BOARD_NAME}-profile"

BOARD_DIR = BOARDS_ROOT / BOARD_NAME
CONFIG_PATH = BOARD_DIR / "config" / "settings.yaml"
SESSION_PATH = BOARD_DIR / "config" / "session.json"

# Board-specific starting URLs for session setup
BOARD_START_URLS = {
    "indeed": "https://www.indeed.com/jobs?q=python+developer&l=Remote",
    "linkedin": "https://www.linkedin.com/jobs/search/?keywords=python+developer&location=Remote",
    "glassdoor": "https://www.glassdoor.com/Job/remote-python-developer-jobs-SRCH_IL.0,6_IS11047_KO7,23.htm",
    # NOTE: "remotejobs" board targets remotejobs.io (not remote.co).
    "remotejobs": "https://www.remotejobs.io/remote-jobs?search=python+developer&location=Remote",
    "remoteafrica": "https://remoteafrica.io/jobs",
    "default": "https://www.indeed.com/jobs?q=python+developer&l=Remote",
}


def setup_session():
    """Open browser with persistent profile for manual captcha solving"""
    if BOARD_NAME == "default" or not BOARD_DIR.exists():
        available = []
        try:
            available = sorted([p.name for p in BOARDS_ROOT.iterdir() if p.is_dir()])
        except Exception:
            pass
        print("❌ Board not set or not found.")
        print("   Set JOB_BOT_BOARD=<board> or run from inside boards/<board>.")
        if available:
            print(f"   Available boards: {', '.join(available)}")
        raise SystemExit(2)

    if not CONFIG_PATH.exists():
        print(f"❌ Config file not found: {CONFIG_PATH}")
        raise SystemExit(2)

    print("\n" + "="*60)
    print("🔐 SESSION SETUP (Persistent Profile)")
    print("="*60)
    print(f"\nBoard: {BOARD_NAME}")
    print(f"Using profile: {USER_DATA_DIR}")
    print(f"Will save storage state to: {SESSION_PATH}")
    print("\nThis will open a browser window.")
    print("1. Move mouse around, scroll a bit (act human)")
    print("2. Solve the captcha if prompted")
    print("3. Wait for job listings to load")
    print("4. Press Enter here when done")
    print("\n" + "="*60 + "\n")

    # Create profile directory
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    config = load_config(str(CONFIG_PATH))
    channel = config.get_browser_channel() or None
    executable_path = config.get_browser_executable_path() or None
    launch_timeout = config.get_launch_timeout()

    if executable_path and not Path(executable_path).exists():
        print(f"⚠️  Browser executable not found: {executable_path}")
        executable_path = None

    with sync_playwright() as p:
        # Launch with persistent context (like a real Chrome profile)
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            headless=False,
            viewport={"width": 1280, "height": 800},
            channel=channel,
            executable_path=executable_path,
            timeout=launch_timeout,
            # Use default Chrome user agent (more natural)
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-first-run",
                "--no-default-browser-check",
            ]
        )

        page = context.pages[0] if context.pages else context.new_page()

        # Navigate to the appropriate board
        start_url = BOARD_START_URLS.get(BOARD_NAME, BOARD_START_URLS["default"])
        board_display = BOARD_NAME if BOARD_NAME != "default" else "Indeed"
        print(f"🌐 Opening {board_display}...")
        page.goto(start_url)

        # Wait for user
        input("\n✋ Solve the captcha (if shown), wait for results to load, then press Enter...")

        # Check if we got past captcha
        content = page.content()
        if "Additional Verification" in content or "Verify you are human" in content:
            print("\n⚠️  Still showing captcha. Try:")
            print("   - Move mouse around naturally")
            print("   - Wait a few seconds before clicking verify")
            print("   - Try again")
        else:
            # Save session cookies separately for portability
            SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
            context.storage_state(path=str(SESSION_PATH))
            print(f"\n✅ Session saved to {SESSION_PATH}")
            print(f"✅ Browser profile saved to {USER_DATA_DIR}")
            print("\n   You can now run main.py!")

        context.close()


if __name__ == "__main__":
    setup_session()
