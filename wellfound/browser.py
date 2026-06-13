"""Launch a persistent Chrome profile.

Stealth philosophy (informed by review): a *real* Chrome is the best
disguise, so we do as little as possible. We use the installed Chrome
binary, turn off the automation flags that set `navigator.webdriver`,
and otherwise leave the fingerprint untouched.

We deliberately do NOT inject fake user-agent strings, plugin lists,
languages, or locale. Those disagree with Chrome's real User-Agent
Client Hints and become their own tell — patching less is safer than
patching more. The one unavoidable weakness is headless mode, which
leaks "HeadlessChrome" in the UA; run headed for real use.
"""
import sys
from pathlib import Path

from playwright.sync_api import Error as PWError, Playwright

# Stored next to the project; gitignored because it holds your session
# cookies — treat this folder like a password.
USER_DATA_DIR = Path(__file__).resolve().parent.parent / "user_data"

# Only the automation tells we can remove *coherently*. Disabling
# AutomationControlled makes navigator.webdriver report its natural
# `false`, with no JS patching that could contradict client hints.
_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-default-browser-check",
    "--no-first-run",
]


def launch_context(playwright: Playwright, *, headless: bool = False):
    """Open the persistent context using the real installed Chrome.

    Falls back to Playwright's bundled Chromium only if Chrome is missing
    — and says so loudly, because Chromium's fingerprint is weaker.
    """
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    if headless:
        print(
            "  ! HEADLESS=True: headless Chrome leaks 'HeadlessChrome' in its\n"
            "    user-agent and is easier to flag. Run headed for best stealth.",
            file=sys.stderr,
        )

    opts = dict(
        user_data_dir=str(USER_DATA_DIR),
        headless=headless,
        args=_LAUNCH_ARGS,
        ignore_default_args=["--enable-automation"],
        no_viewport=True,  # inherit the real window size, not a forced box
    )

    try:
        context = playwright.chromium.launch_persistent_context(channel="chrome", **opts)
    except PWError as e:
        first_line = str(e).splitlines()[0][:120]
        print(
            f"  ! Real Chrome unavailable ({first_line}); falling back to bundled\n"
            "    Chromium, which has a weaker fingerprint. Install Google Chrome\n"
            "    for better stealth.",
            file=sys.stderr,
        )
        context = playwright.chromium.launch_persistent_context(**opts)

    context.set_default_timeout(30_000)
    return context
