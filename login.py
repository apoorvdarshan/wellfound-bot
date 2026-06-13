"""Run this ONCE (or whenever your session expires):

    python login.py

It opens a real Chrome window. Log into Wellfound by hand — email,
Google, magic link, whatever you normally use. Once you can see your
logged-in dashboard, return to the terminal and press Enter. The session
is persisted into ./user_data and reused by every later run.py run, so
you never script your password.
"""
from playwright.sync_api import sync_playwright

from wellfound.browser import USER_DATA_DIR, launch_context


def main() -> None:
    with sync_playwright() as p:
        ctx = launch_context(p, headless=False)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto("https://wellfound.com/login", wait_until="domcontentloaded")

            print("\n  A Chrome window is open.")
            print("  1. Log into Wellfound however you normally do.")
            print("  2. Wait until you can see your dashboard / job feed.")
            print("  3. Return here and press Enter to save the session.\n")
            input("  Press Enter once you are logged in... ")

            # The persistent profile in user_data/ already holds the
            # cookies. Exporting storage_state is a bonus for inspection;
            # if the window was closed early it'll fail, but the login is
            # still saved in the profile, so treat that as non-fatal.
            try:
                ctx.storage_state(path=str(USER_DATA_DIR / "storage_state.json"))
                print(f"\n  Session saved to {USER_DATA_DIR}")
            except Exception as e:
                print(
                    f"\n  Couldn't export storage_state ({type(e).__name__}), but your\n"
                    f"  login is still saved in {USER_DATA_DIR} (persistent profile)."
                )
            print("  You can close the window — run.py will reuse this login.\n")
        finally:
            try:
                ctx.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
