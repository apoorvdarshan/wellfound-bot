"""Reverse-engineering recorder: see Wellfound's API as YOU use it.

Read-only and safe for your account. It attaches to your real Chrome
(same DevTools port as capture_assist) and logs every XHR/fetch/GraphQL
request + response while you browse and apply *manually*. This reveals
the real apply API with zero automated traffic for DataDome to see.

It also dumps your current cookies (including `datadome` and auth) to the
run folder, so we can see what a request actually needs. That folder is
gitignored — it holds live session secrets; never share it.

Run:
  1. python record_api.py        (launches/attaches to your Chrome)
  2. In Chrome, browse Wellfound and do ONE real apply by hand.
  3. Press Ctrl-C here to stop. Output: ./captures/api-<timestamp>/

Then send me requests.jsonl (NOT cookies.json) and I'll map the API.
"""
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from capture_assist import PORT, launch_chrome, port_open
from wellfound.browser import USER_DATA_DIR

OUT_ROOT = Path(__file__).resolve().parent / "captures"
# Only log the calls that carry real data, not images/fonts/css.
DATA_TYPES = ("xhr", "fetch")
SITE_HINTS = ("wellfound.com", "angel.co", "angellist")


def _interesting(req) -> bool:
    url = req.url
    if not any(h in url for h in SITE_HINTS) and "graphql" not in url:
        return False
    return req.resource_type in DATA_TYPES or "graphql" in url


def main() -> None:
    launched = None
    if not port_open(PORT):
        print("Opening your real Chrome (real profile, no automation flags)…")
        launched = launch_chrome(PORT, str(USER_DATA_DIR))
    else:
        print(f"Attaching to Chrome already on port {PORT}.")

    run = time.strftime("api-%Y%m%d-%H%M%S")
    out = OUT_ROOT / run
    out.mkdir(parents=True, exist_ok=True)
    log = (out / "requests.jsonl").open("a", encoding="utf-8")
    count = {"n": 0}

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()

        def on_response(resp):
            try:
                req = resp.request
                if not _interesting(req):
                    return
                body = None
                if "json" in resp.headers.get("content-type", ""):
                    try:
                        body = resp.json()
                    except Exception:
                        body = None
                entry = {
                    "ts": time.time(),
                    "method": req.method,
                    "url": req.url,
                    "resource_type": req.resource_type,
                    "request_headers": dict(req.headers),
                    "post_data": req.post_data,
                    "status": resp.status,
                    "response_json": body,
                }
                log.write(json.dumps(entry) + "\n")
                log.flush()
                count["n"] += 1
                tag = "graphql" if "graphql" in req.url else req.resource_type
                print(f"  [{count['n']:>3}] {req.method} {resp.status} {tag}: {req.url[:88]}")
            except Exception:
                pass  # never let logging interrupt the user's browsing

        def attach(page):
            page.on("response", on_response)

        for pg in ctx.pages:
            attach(pg)
        ctx.on("page", attach)

        print(f"\nRecording API traffic → ./captures/{run}/requests.jsonl")
        print("Browse + do ONE apply in Chrome. Press Ctrl-C here when done.\n")
        try:
            while True:
                # In the sync API, events only fire while a Playwright call
                # is running — so pump with a short wait on any open page.
                live = [pg for pg in ctx.pages if not pg.is_closed()]
                if live:
                    live[0].wait_for_timeout(400)
                else:
                    time.sleep(0.4)
        except KeyboardInterrupt:
            print("\nStopping…")

        # Snapshot cookies (your own) so we can see what a request needs.
        try:
            (out / "cookies.json").write_text(
                json.dumps(ctx.cookies(), indent=2), encoding="utf-8"
            )
        except Exception:
            pass
        browser.close()  # detach only; your Chrome stays open

    log.close()
    print(f"\nSaved {count['n']} request(s) → ./captures/{run}/requests.jsonl")
    print(f"Cookies snapshot → ./captures/{run}/cookies.json  (secret, gitignored)")
    if launched:
        print("Your Chrome window stays open; close it yourself when finished.")


if __name__ == "__main__":
    main()
