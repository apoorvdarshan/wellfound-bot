"""Drive Wellfound with human-like timing and capture every step.

Prerequisite: run `python login.py` once so ./user_data holds your
session.

This is deliberately conservative:
  * It moves the mouse, hovers, and pauses the way a person does.
  * It rate-limits between jobs and caps how many it touches per run.
  * It defaults to DRY_RUN — it will NOT submit anything until you say so.

Wellfound's DOM changes over time, so the apply selectors below are
best-effort and listed as ranked fallbacks. The captures/ output exists
precisely so you (or an agent) can read the saved HTML and correct a
selector when one stops matching.
"""
import sys
import time

from playwright.sync_api import TimeoutError as PWTimeout, sync_playwright

import config
from wellfound import human
from wellfound.browser import launch_context
from wellfound.capture import FlowRecorder

# Multiple candidate selectors per action. find_first returns the first
# one that is actually visible, so a single DOM tweak won't break a run.
JOB_CARDS = [
    "[data-test='StartupResult'] a[href*='/jobs/']",
    "a[href*='/jobs/']",
]
APPLY_BUTTON = [
    "[data-test='JobApplication-Apply'] button",
    "button[data-test*='apply' i]",
    "button:has-text('Apply')",
    "a:has-text('Apply')",
]
MESSAGE_BOX = [
    "textarea[name='message']",
    "textarea[placeholder*='message' i]",
    "form textarea",
]
SUBMIT_BUTTON = [
    "button[type='submit']:has-text('Apply')",
    "button:has-text('Send application')",
    "button:has-text('Send')",
    "button:has-text('Submit')",
]


def find_first(page, selectors, *, timeout=4000):
    """Return (locator, selector) for the first visible candidate, or (None, None)."""
    for sel in selectors:
        loc = page.locator(sel).first
        try:
            loc.wait_for(state="visible", timeout=timeout)
            return loc, sel
        except PWTimeout:
            continue
    return None, None


def ensure_logged_in(page, rec) -> bool:
    page.goto(config.JOBS_URL, wait_until="domcontentloaded")
    human.jittered_idle()
    rec.record(page, "open_jobs", detail=config.JOBS_URL)
    if "/login" in page.url or "/signup" in page.url:
        print("Not logged in — run `python login.py` first.")
        return False
    return True


def collect_job_links(page, limit):
    _, sel = find_first(page, JOB_CARDS, timeout=8000)
    if not sel:
        return []
    cards = page.locator(sel)
    seen, links = set(), []
    for i in range(cards.count()):
        href = cards.nth(i).get_attribute("href")
        if href and "/jobs/" in href and href not in seen:
            seen.add(href)
            links.append(href)
        if len(links) >= limit:
            break
    return links


def apply_to_job(page, rec, href) -> bool:
    url = href if href.startswith("http") else "https://wellfound.com" + href
    page.goto(url, wait_until="domcontentloaded")
    human.jittered_idle(2.5, 6.0)
    human.human_scroll(page, amount=400)  # skim the post before acting
    rec.record(page, "open_job", detail=url)

    apply_btn, sel = find_first(page, APPLY_BUTTON)
    if not apply_btn:
        rec.record(page, "no_apply_button", detail=url)
        print(f"  no Apply button found — captured {url} for review")
        return False

    human.human_click(page, apply_btn)
    rec.record(page, "click_apply", selector=sel)

    # The message box is optional, and only filled outside of a dry run.
    if config.DEFAULT_MESSAGE and not config.DRY_RUN:
        box, bsel = find_first(page, MESSAGE_BOX)
        if box:
            human.human_type(page, box, config.DEFAULT_MESSAGE)
            rec.record(page, "type_message", selector=bsel)

    submit, ssel = find_first(page, SUBMIT_BUTTON)
    if not submit:
        rec.record(page, "no_submit_button", detail=url)
        print("  apply opened but no submit control found — captured for review")
        return False

    if config.DRY_RUN:
        rec.record(page, "dry_run_stop_before_submit", selector=ssel)
        print("  DRY_RUN: stopped before submitting (apply form captured)")
        return True

    human.human_click(page, submit)
    human.jittered_idle()
    rec.record(page, "submitted", selector=ssel)
    print("  submitted")
    return True


def main() -> None:
    run_name = time.strftime("%Y%m%d-%H%M%S")
    rec = FlowRecorder(run_name=run_name)

    with sync_playwright() as p:
        ctx = launch_context(p, headless=config.HEADLESS)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        if not ensure_logged_in(page, rec):
            ctx.close()
            sys.exit(1)

        human.human_scroll(page, amount=600)
        links = collect_job_links(page, config.MAX_JOBS_PER_RUN)
        print(f"Found {len(links)} job(s) to walk through.")

        for i, href in enumerate(links, 1):
            print(f"[{i}/{len(links)}] {href}")
            try:
                apply_to_job(page, rec, href)
            except Exception as e:  # keep going; the error is captured
                rec.record(page, "error", detail=f"{type(e).__name__}: {e}")
                print(f"  error: {e}")
            if i < len(links):
                lo, hi = config.DELAY_BETWEEN_JOBS
                human.human_pause(lo, hi)

        print(f"\nDone. Captures saved in ./captures/{run_name}/")
        ctx.close()


if __name__ == "__main__":
    main()
