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
import re
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
    "textarea",
]
# Ordered unambiguous-first. The generic submit is last, and the
# identity guard in apply_to_job stops it resolving back to the Apply
# button we already clicked.
SUBMIT_BUTTON = [
    "button:has-text('Send application')",
    "button:has-text('Submit application')",
    "button:has-text('Send')",
    "button:has-text('Submit')",
    "button[type='submit']",
]
# The apply UI is an in-page modal; scope post-Apply searches to it.
DIALOG = "[role='dialog'], [aria-modal='true'], [data-test*='modal' i]"
# A login form is the clearest "not logged in" signal.
LOGIN_FORM = ["input[type='password']", "input[name='password']"]
# Require a job-id-shaped slug so nav/footer "/jobs/" chrome is ignored.
JOB_HREF = re.compile(r"/jobs/\d")


def find_first(scope, selectors, *, timeout=4000):
    """Return (locator, selector) for the first visible candidate, or (None, None).

    `scope` is a Page or a Locator (e.g. a modal), so the same helper
    works for whole-page and modal-scoped lookups.
    """
    for sel in selectors:
        loc = scope.locator(sel).first
        try:
            loc.wait_for(state="visible", timeout=timeout)
            return loc, sel
        except PWTimeout:
            continue
    return None, None


def ensure_logged_in(page, rec) -> bool:
    try:
        page.goto(config.JOBS_URL, wait_until="domcontentloaded", timeout=45_000)
    except PWTimeout:
        print("Timed out loading Wellfound — check your connection and retry.")
        return False

    human.jittered_idle()
    rec.record(page, "open_jobs", detail=config.JOBS_URL)

    # A visible password field, or a login/signup URL, means no session.
    login_visible = False
    for sel in LOGIN_FORM:
        loc = page.locator(sel).first
        try:
            if loc.count() and loc.is_visible():
                login_visible = True
                break
        except Exception:
            continue
    if "/login" in page.url or "/signup" in page.url or login_visible:
        print("Not logged in — run `python login.py` first.")
        return False
    return True


def collect_job_links(page, limit):
    """Gather up to `limit` job links, scrolling to load more as needed.

    Wellfound's feed is infinite-scroll: only a few cards exist until you
    scroll and more are fetched. So we re-read all matches each pass,
    scroll, let the network settle, and stop once we have enough or the
    card count stops growing.
    """
    _, sel = find_first(page, JOB_CARDS, timeout=8000)
    if not sel:
        return []

    seen, links = set(), []
    stale_passes = 0
    while len(links) < limit and stale_passes < 3:
        hrefs = page.locator(sel).evaluate_all("els => els.map(e => e.getAttribute('href'))")
        before = len(seen)
        for href in hrefs:
            if href and JOB_HREF.search(href) and href not in seen:
                seen.add(href)
                links.append(href)
                if len(links) >= limit:
                    break
        if len(links) >= limit:
            break

        human.human_scroll(page, amount=900)  # pull in more lazy-loaded cards
        try:
            page.wait_for_load_state("networkidle", timeout=4000)
        except PWTimeout:
            pass
        stale_passes = stale_passes + 1 if len(seen) == before else 0

    return links


def apply_to_job(page, rec, href) -> bool:
    url = href if href.startswith("http") else "https://wellfound.com" + href
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45_000)
    except PWTimeout:
        rec.record(page, "job_nav_timeout", detail=url)
        print("  navigation timed out — skipped")
        return False

    human.jittered_idle(2.5, 6.0)
    human.human_scroll(page, amount=400)  # skim the post before acting
    rec.record(page, "open_job", detail=url)

    apply_btn, sel = find_first(page, APPLY_BUTTON)
    if not apply_btn:
        rec.record(page, "no_apply_button", detail=url)
        print(f"  no Apply button found — captured {url} for review")
        return False

    apply_handle = apply_btn.element_handle()
    human.human_click(page, apply_btn)
    rec.record(page, "click_apply", selector=sel)

    # The real apply UI opens as an in-page modal. Scope everything below
    # to it, so we never grab controls from the underlying page. If no
    # modal appears, the apply didn't open — don't claim success.
    dialog = page.locator(DIALOG).first
    try:
        dialog.wait_for(state="visible", timeout=6000)
        scope = dialog
        rec.record(page, "apply_modal_opened", selector=DIALOG)
    except PWTimeout:
        rec.record(page, "apply_modal_not_detected", detail=url)
        print("  Apply clicked but no modal detected — captured for review")
        return False

    # Locate the optional message box even in a dry run, so the capture
    # validates the selector. Only actually type when not a dry run.
    box, bsel = find_first(scope, MESSAGE_BOX)
    if box:
        rec.record(page, "message_box_found", selector=bsel)
        if config.DEFAULT_MESSAGE and not config.DRY_RUN:
            human.human_type(page, box, config.DEFAULT_MESSAGE)
            rec.record(page, "type_message", selector=bsel)

    submit, ssel = find_first(scope, SUBMIT_BUTTON)
    # Guard: the submit control must not be the Apply button we just
    # clicked (a generic submit selector can otherwise re-match it).
    if submit and apply_handle:
        try:
            if submit.evaluate("(node, other) => node === other", apply_handle):
                submit = None
        except Exception:
            pass
    if not submit:
        rec.record(page, "no_submit_button", detail=url)
        print("  apply modal open but no distinct submit control — captured for review")
        return False

    if config.DRY_RUN:
        rec.record(page, "dry_run_stop_before_submit", selector=ssel)
        print("  DRY_RUN: stopped before submitting (apply modal captured)")
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
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            if not ensure_logged_in(page, rec):
                return

            human.human_scroll(page, amount=600)
            links = collect_job_links(page, config.MAX_JOBS_PER_RUN)
            if not links:
                rec.record(page, "no_jobs_found", detail=config.JOBS_URL)
                print(
                    "No job links found. Either the feed didn't load, the filters\n"
                    "returned nothing, or JOB_CARDS needs updating — check the\n"
                    f"captured HTML in ./captures/{run_name}/."
                )
                return

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
        except KeyboardInterrupt:
            print("\nInterrupted — closing the browser cleanly.")
        finally:
            ctx.close()


if __name__ == "__main__":
    main()
