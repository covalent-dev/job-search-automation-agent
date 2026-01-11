#!/usr/bin/env python3

"""
Session Setup - Uses persistent Chrome profile for better captcha bypass
"""

import os
from pathlib import Path
from playwright.sync_api import sync_playwright

# Use a persistent browser profile directory
USER_DATA_DIR = Path.home() / ".job-search-automation" / "browser-profile"
SESSION_FILE = "config/session.json"


def setup_session():
    """Open browser with persistent profile for manual captcha solving"""
    print("\n" + "="*60)
    print("🔐 SESSION SETUP (Persistent Profile)")
    print("="*60)
    print(f"\nUsing profile: {USER_DATA_DIR}")
    print("\nThis will open a browser window.")
    print("1. Move mouse around, scroll a bit (act human)")
    print("2. Solve the captcha if prompted")
    print("3. Wait for job listings to load")
    print("4. Press Enter here when done")
    print("\n" + "="*60 + "\n")

    # Create profile directory
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        # Launch with persistent context (like a real Chrome profile)
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            headless=False,
            viewport={"width": 1280, "height": 800},
            # Use default Chrome user agent (more natural)
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-first-run",
                "--no-default-browser-check",
            ]
        )

        page = context.pages[0] if context.pages else context.new_page()

        # Navigate to Indeed
        print("🌐 Opening Indeed...")
        page.goto("https://www.indeed.com/jobs?q=python+developer&l=Remote")

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
            session_path = Path(SESSION_FILE)
            session_path.parent.mkdir(parents=True, exist_ok=True)
            context.storage_state(path=str(session_path))
            print(f"\n✅ Session saved to {session_path}")
            print(f"✅ Browser profile saved to {USER_DATA_DIR}")
            print("\n   You can now run main.py!")

        context.close()


if __name__ == "__main__":
    setup_session()
