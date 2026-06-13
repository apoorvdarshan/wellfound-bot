"""Capture-assist: YOU drive your real Chrome; this only records.

Safe for your account. It never navigates and never clicks. It opens
your real Chrome (real profile, real fingerprint, navigator.webdriver
stays false — verified) with the DevTools port open, attaches read-only,
and saves the page's DOM + a screenshot whenever you press Enter. To
DataDome it's just you, browsing normally.

Usage:
  1. python capture_assist.py
  2. A Chrome window opens. Browse Wellfound; log in if needed.
  3. Come back here and press Enter to capture the page you're looking at
     (works for the apply modal too). Type q then Enter to finish.

The result is ./captures/assist-<timestamp>/ — flow.jsonl plus a .html
and .png per capture — exactly the trace you feed to an agent.
"""
import socket
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from wellfound.browser import USER_DATA_DIR
from wellfound.capture import FlowRecorder

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9222


def port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def launch_chrome(port: int, profile: str) -> subprocess.Popen:
    """Launch real Chrome with the DevTools port open. No --enable-automation,
    so navigator.webdriver stays false (verified)."""
    proc = subprocess.Popen(
        [
            CHROME,
            f"--user-data-dir={profile}",
            f"--remote-debugging-port={port}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        if port_open(port):
            return proc
        time.sleep(0.2)
    raise RuntimeError(f"Chrome did not open a debug port on {port}.")


def pick_active_page(ctx):
    """The tab you're actually looking at: the visible, non-blank one,
    preferring the most recently focused."""
    pages = [pg for pg in ctx.pages if not pg.is_closed()]
    for pg in reversed(pages):
        try:
            if pg.evaluate("() => document.visibilityState") == "visible":
                return pg
        except Exception:
            continue
    return pages[-1] if pages else None


def capture(rec: FlowRecorder, page) -> dict:
    """Record the current page — pure read (content + screenshot)."""
    return rec.record(page, "manual_capture", detail=page.url)


def main() -> None:
    launched = None
    if port_open(PORT):
        print(f"Chrome already listening on {PORT} — attaching to it.")
    else:
        print("Opening your real Chrome (real profile, no automation flags)…")
        try:
            launched = launch_chrome(PORT, str(USER_DATA_DIR))
        except (FileNotFoundError, RuntimeError) as e:
            print(f"Couldn't launch Chrome: {e}")
            print(f"Check the path: {CHROME}")
            return

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        rec = FlowRecorder(run_name=time.strftime("assist-%Y%m%d-%H%M%S"))

        print("\nConnected, read-only. Browse Wellfound in the Chrome window.")
        print("Press Enter here to capture the page you're on; type q to quit.\n")

        count = 0
        while True:
            try:
                cmd = input("capture> ").strip().lower()
            except EOFError:
                break
            if cmd in ("q", "quit", "exit"):
                break
            page = pick_active_page(ctx)
            if not page:
                print("  no open page found — is the Chrome window still open?")
                continue
            try:
                entry = capture(rec, page)
                count += 1
                title = (entry["title"] or "")[:60]
                print(f"  saved #{entry['step']}: {title}  [{entry['url']}]")
            except Exception as e:
                print(f"  capture failed: {e}")

        browser.close()  # detaches CDP only; your Chrome keeps running
        print(f"\nDone — {count} capture(s) in ./{rec.dir.relative_to(Path.cwd())}")

    if launched:
        print("Your Chrome window stays open; close it yourself when finished.")


if __name__ == "__main__":
    main()
