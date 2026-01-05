from playwright.sync_api import sync_playwright
import time
import os

def test_linkedin_logged_in():
    # Path to save your session
    session_file = "linkedin_session.json"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        
        # Check if we have a saved session
        if os.path.exists(session_file):
            print("Loading saved LinkedIn session...")
            context = browser.new_context(storage_state=session_file)
        else:
            print("No saved session found. You'll need to log in manually.")
            context = browser.new_context()
        
        page = context.new_page()
        page.goto("https://www.linkedin.com/jobs/search/?keywords=python%20developer")
        
        # Give time to check if logged in
        time.sleep(2)
        
        # Check if we're on a login page
        if "login" in page.url or "authwall" in page.url:
            print("\n⚠️  Please log in to LinkedIn manually in the browser window")
            print("After logging in, press Enter here to save your session...\n")
        else:
            print("\n✓ Already logged in!")
            print("Press Enter when done testing...\n")
        
        input()
        
        # Save the session for next time
        context.storage_state(path=session_file)
        print(f"✓ Session saved to {session_file}")
        
        browser.close()

if __name__ == "__main__":
    test_linkedin_logged_in()
