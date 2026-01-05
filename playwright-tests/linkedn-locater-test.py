from playwright.sync_api import sync_playwright
import os

def test_locators():
    session_file = "linkedin_session.json"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        
        if os.path.exists(session_file):
            context = browser.new_context(storage_state=session_file)
        else:
            context = browser.new_context()
        
        page = context.new_page()
        
        print("Loading job search page...")
        page.goto("https://www.linkedin.com/jobs/search/?keywords=python%20developer", 
                  wait_until="domcontentloaded",
                  timeout=60000)
        print("✓ Page loaded\n")
        
        print("=== Manual Step ===")
        print("1. Find a job listing with 'Easy Apply' button")
        print("2. Click on it")
        print("3. Wait for job details to load")
        print("4. Press Enter here when ready...\n")
        
        input()
        
        print("\n=== Testing Different Locator Methods ===\n")
        
        # Method 1: get_by_role
        try:
            btn = page.get_by_role("button", name="Easy Apply")
            if btn.count() > 0 and btn.first.is_visible():
                print(f"✅ Method 1 (get_by_role): FOUND and visible")
            else:
                print("⚠️  Method 1 (get_by_role): Found but not visible")
        except Exception as e:
            print(f"❌ Method 1 (get_by_role): FAILED - {e}")
        
        # Method 2: get_by_text
        try:
            btn = page.get_by_text("Easy Apply", exact=True)
            count = btn.count()
            if count > 0:
                print(f"✅ Method 2 (get_by_text): FOUND {count} matches")
            else:
                print("❌ Method 2 (get_by_text): No matches")
        except Exception as e:
            print(f"❌ Method 2 (get_by_text): FAILED - {e}")
        
        # Method 3: CSS :has-text
        try:
            btn = page.locator("button:has-text('Easy Apply')")
            count = btn.count()
            if count > 0:
                print(f"✅ Method 3 (CSS :has-text): FOUND {count} matches")
            else:
                print("❌ Method 3 (CSS :has-text): No matches")
        except Exception as e:
            print(f"❌ Method 3 (CSS :has-text): FAILED - {e}")
        
        # Method 4: XPath
        try:
            btn = page.locator("xpath=//button[contains(., 'Easy Apply')]")
            count = btn.count()
            if count > 0:
                print(f"✅ Method 4 (XPath): FOUND {count} matches")
            else:
                print("❌ Method 4 (XPath): No matches")
        except Exception as e:
            print(f"❌ Method 4 (XPath): FAILED - {e}")
        
        print("\n=== Key Takeaway ===")
        print("The method(s) that found the button are what you'll use in Job Bot")
        print("get_by_role and get_by_text are usually most reliable\n")
        
        input("Press Enter to close...")
        browser.close()

if __name__ == "__main__":
    test_locators()

    