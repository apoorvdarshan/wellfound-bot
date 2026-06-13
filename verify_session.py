"""Read-only check that the saved session works — SAFE for your account.

It opens your jobs feed in real Chrome, confirms you're logged in, and
counts the job cards it can see. It does NOT click Apply, fill anything,
or submit. Nothing leaves the browser. Run after login.py:

    python verify_session.py
"""
import sys

from playwright.sync_api import sync_playwright

import config
import run as R
from wellfound.browser import launch_context
from wellfound.capture import FlowRecorder


def main() -> int:
    with sync_playwright() as p:
        # Headed only: headless trips Wellfound's DataDome CAPTCHA wall.
        ctx = launch_context(p, headless=False)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            rec = FlowRecorder(run_name="verify")

            if not R.ensure_logged_in(page, rec):
                print("\nRESULT: NOT LOGGED IN — run `python login.py` again.")
                return 2

            print("\nLogged in ✓  Reading the jobs feed (read-only, no clicks)…")
            links = R.collect_job_links(page, 3)
            rec.record(page, "verify_feed", detail=f"{len(links)} job cards found")

            print(f"Job cards detected: {len(links)}")
            for href in links:
                print("   ", href)

            if links:
                print("\nRESULT: WORKING ✓  Session + feed + job-card selectors all OK.")
                print(f"Proof + page HTML saved in ./captures/verify/")
                return 0
            print("\nRESULT: Session OK, but no job cards matched. The feed may need a")
            print("filtered JOBS_URL in config.py, or JOB_CARDS needs tuning — check")
            print("the captured HTML in ./captures/verify/.")
            return 1
        finally:
            ctx.close()


if __name__ == "__main__":
    sys.exit(main())
