"""Run this ONCE (or whenever your session expires):

    python login.py

It opens a real Chrome window and waits. Log into Wellfound by hand —
email, Google, magic link, whatever you normally use. You do NOT need to
touch the terminal: the script watches the browser and, once it sees
you're logged in, saves the session into ./user_data and closes by
itself. That saved session is reused by every later run.py run, so you
never script your password.
"""
import time

from playwright.sync_api import sync_playwright

from wellfound.browser import USER_DATA_DIR, launch_context

# How long to wait for you to finish logging in before giving up.
DEADLINE_SECONDS = 600
# Require the "logged in" signal to hold this many consecutive polls, so
# a brief in-between page can't be mistaken for success.
STABLE_POLLS = 3
POLL_SECONDS = 2.0


def _looks_logged_in(page) -> bool:
    """True when a page is on Wellfound, off the login/signup forms, with
    no visible password field (so we're past the login screen)."""
    try:
        url = page.url
    except Exception:
        return False
    if "wellfound.com" not in url:
        return False  # still on an OAuth provider (Google, etc.)
    if "/login" in url or "/signup" in url:
        return False
    pw = page.locator("input[type='password']").first
    try:
        if pw.count() and pw.is_visible():
            return False
    except Exception:
        pass
    return True


def main() -> None:
    with sync_playwright() as p:
        ctx = launch_context(p, headless=False)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto("https://wellfound.com/login", wait_until="domcontentloaded")

            print("\n  A Chrome window is open.")
            print("  Log into Wellfound however you normally do.")
            print("  No need to touch this terminal — I'll detect when you're in.\n")

            stable = 0
            start = time.time()
            while time.time() - start < DEADLINE_SECONDS:
                pages = list(ctx.pages)
                if not pages:
                    print("  Browser was closed before login completed.")
                    return
                if any(_looks_logged_in(pg) for pg in pages):
                    stable += 1
                    if stable >= STABLE_POLLS:
                        break
                else:
                    stable = 0
                time.sleep(POLL_SECONDS)
            else:
                print("  Timed out waiting for login. Re-run `python login.py`.")
                return

            # Persistent profile in user_data/ already holds the cookies;
            # exporting storage_state is a bonus for inspection.
            try:
                ctx.storage_state(path=str(USER_DATA_DIR / "storage_state.json"))
            except Exception:
                pass
            print(f"  Logged in — session saved to {USER_DATA_DIR}.")
            print("  Closing the window; run.py will reuse this login.\n")
        finally:
            try:
                ctx.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
