"""Launch a persistent Chrome profile.

Persisting the profile does two jobs at once: your login survives
between runs (no re-auth), and the browser fingerprint looks like a
normal returning user instead of a fresh automation sandbox.
"""
from pathlib import Path

from playwright.sync_api import Playwright

# Stored next to the project; gitignored because it holds your session
# cookies — treat this folder like a password.
USER_DATA_DIR = Path(__file__).resolve().parent.parent / "user_data"

# A realistic, current desktop Chrome UA. Bump this every few months so
# it doesn't drift far behind the real Chrome release.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

# Runs before any page JS, hiding the tells sites probe for to detect
# automation (navigator.webdriver, empty plugin list, missing chrome obj).
_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
window.chrome = window.chrome || { runtime: {} };
"""

_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-default-browser-check",
    "--no-first-run",
]


def launch_context(playwright: Playwright, *, headless: bool = False):
    """Open the persistent context, preferring real Chrome over Chromium.

    Real Chrome (channel="chrome") has a cleaner fingerprint than the
    bundled Chromium, but isn't always installed — fall back gracefully.
    """
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    common = dict(
        user_data_dir=str(USER_DATA_DIR),
        headless=headless,
        args=_LAUNCH_ARGS,
        user_agent=USER_AGENT,
        viewport={"width": 1366, "height": 850},
        locale="en-US",
        timezone_id="America/New_York",
        ignore_default_args=["--enable-automation"],
    )

    try:
        context = playwright.chromium.launch_persistent_context(channel="chrome", **common)
    except Exception:
        # Chrome not present — use Playwright's bundled Chromium instead.
        context = playwright.chromium.launch_persistent_context(**common)

    context.add_init_script(_STEALTH_JS)
    context.set_default_timeout(30_000)
    return context
