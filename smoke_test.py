"""Self-contained smoke test — no Wellfound login required.

Verifies the machinery this project depends on, against a local HTML
page so it needs no network and touches no real site:
  * the persistent Chrome context launches,
  * the anti-fingerprint masking actually takes effect,
  * human_click / human_type / human_scroll do what they claim,
  * FlowRecorder writes its screenshot / HTML / jsonl.

It does NOT (and cannot) verify Wellfound's live apply selectors — those
need a real logged-in session. Run with:  .venv/bin/python smoke_test.py
"""
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

from wellfound import human
from wellfound.browser import launch_context
from wellfound.capture import FlowRecorder

RESULTS = []


def check(name, ok, info=""):
    RESULTS.append(bool(ok))
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f"  ({info})" if info else ""))


TEST_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>smoke</title>
<style>body{font-family:sans-serif;padding:24px}.spacer{height:2200px}</style></head>
<body>
  <h1>wellfound-bot smoke test</h1>
  <button id="btn" onclick="document.getElementById('out').textContent='clicked'">Apply</button>
  <div id="out">notclicked</div>
  <p><textarea id="ta" rows="4" cols="40" placeholder="message"></textarea></p>
  <div class="spacer"></div>
  <div id="bottom">bottom</div>
</body></html>"""


def main():
    tmp = Path(tempfile.gettempdir()) / "wf_smoke.html"
    tmp.write_text(TEST_HTML, encoding="utf-8")
    file_url = tmp.as_uri()

    with sync_playwright() as p:
        ctx = launch_context(p, headless=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(file_url, wait_until="domcontentloaded")

        print("\nAnti-detection masking:")
        wd = page.evaluate("() => navigator.webdriver")
        check("navigator.webdriver hidden", wd in (None, False), f"value={wd!r}")
        langs = page.evaluate("() => navigator.languages")
        check("navigator.languages spoofed", list(langs or []) == ["en-US", "en"], str(langs))
        plugins = page.evaluate("() => navigator.plugins.length")
        check("navigator.plugins non-empty", bool(plugins), f"len={plugins}")
        has_chrome = page.evaluate("() => !!(window.chrome && window.chrome.runtime)")
        check("window.chrome present", has_chrome)
        ua = page.evaluate("() => navigator.userAgent")
        check("custom user-agent applied", "Chrome/126" in ua, ua.split(") ")[-1])

        print("\nHuman-like interactions:")
        human.human_click(page, page.locator("#btn"))
        out = page.locator("#out").inner_text()
        check("human_click registered the click", out == "clicked", out)

        msg = "Hello team, excited about this role — happy to share more."
        human.human_type(page, page.locator("#ta"), msg)
        val = page.locator("#ta").input_value()
        check("human_type produced exact text", val == msg, f"{len(val)} chars")

        before = page.evaluate("() => window.scrollY")
        human.human_scroll(page, amount=800)
        after = page.evaluate("() => window.scrollY")
        check("human_scroll moved the page", after > before + 100, f"{before}->{after}")

        print("\nCapture system:")
        rec = FlowRecorder(run_name="smoke")
        entry = rec.record(page, "smoke_step", detail="self-test")
        check("screenshot written", bool(entry["screenshot"]) and (rec.dir / entry["screenshot"]).exists())
        check("page HTML written", bool(entry["html"]) and (rec.dir / entry["html"]).exists())
        check("flow.jsonl written", (rec.dir / "flow.jsonl").exists())

        # Leave a visible-page screenshot for the user to eyeball.
        proof = rec.dir / "proof.png"
        page.goto(file_url, wait_until="domcontentloaded")
        human.human_click(page, page.locator("#btn"))
        human.human_type(page, page.locator("#ta"), msg)
        page.screenshot(path=str(proof))
        print(f"\nProof screenshot: {proof}")

        ctx.close()

    passed = sum(RESULTS)
    total = len(RESULTS)
    print(f"\n{passed}/{total} checks passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
