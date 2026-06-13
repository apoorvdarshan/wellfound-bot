"""Human-like interaction helpers for Playwright.

Bot-detection systems flag the patterns that scripts fall into: clicks
that land on the exact pixel-center of an element, zero think-time
between actions, whole strings typed in a single keystroke, and a mouse
that teleports instead of moving. Every helper here adds realistic
timing and motion so the activity reads as a person, not a macro.
"""
import random
import time

from playwright.sync_api import Locator, Page


def human_pause(lo: float = 0.4, hi: float = 1.2) -> None:
    """Sleep a random, human-scale amount of time."""
    time.sleep(random.uniform(lo, hi))


def jittered_idle(lo: float = 2.0, hi: float = 6.0) -> None:
    """A longer idle, as if reading the page before acting."""
    human_pause(lo, hi)


def _point_in(box: dict, bias: float = 0.5, spread: float = 0.22):
    """Pick a point inside a bounding box, biased toward the center.

    People don't click dead-center every time, but they also don't click
    the corners. A clamped gaussian gives that natural spread.
    """
    fx = min(max(random.gauss(bias, spread), 0.15), 0.85)
    fy = min(max(random.gauss(bias, spread), 0.15), 0.85)
    return box["x"] + box["width"] * fx, box["y"] + box["height"] * fy


def human_mouse_to(page: Page, x: float, y: float) -> None:
    """Move the cursor to (x, y) through a couple of jittered waypoints.

    Playwright's mouse.move with steps draws a straight line; routing it
    through intermediate points with perpendicular jitter makes the path
    curved and uneven, the way a real hand moves.
    """
    # Begin from a random nearby point (we don't know the true position).
    px = x + random.uniform(-180, 180)
    py = y + random.uniform(-140, 140)
    page.mouse.move(px, py, steps=random.randint(4, 8))

    for i in range(random.randint(1, 2)):
        t = (i + 1) / 3
        wx = px + (x - px) * t + random.uniform(-30, 30)
        wy = py + (y - py) * t + random.uniform(-25, 25)
        page.mouse.move(wx, wy, steps=random.randint(5, 10))
        human_pause(0.02, 0.12)

    page.mouse.move(x, y, steps=random.randint(12, 26))


def human_click(page: Page, locator: Locator, *, settle: bool = True) -> None:
    """Scroll to, approach, hover, and click an element like a person.

    The press has a real (short) duration via separate down/up events,
    rather than the instantaneous click a script normally emits.
    """
    locator.scroll_into_view_if_needed()
    human_pause(0.25, 0.8)

    box = locator.bounding_box()
    if not box:
        # No geometry (e.g. hidden parent) — fall back to a plain click.
        locator.click()
    else:
        tx, ty = _point_in(box)
        human_mouse_to(page, tx, ty)
        human_pause(0.05, 0.22)
        page.mouse.down()
        human_pause(0.04, 0.12)  # press-and-hold duration
        page.mouse.up()

    if settle:
        human_pause(0.6, 1.6)


def human_type(page: Page, locator: Locator, text: str) -> None:
    """Focus a field and type with per-character delays and think-pauses."""
    human_click(page, locator, settle=False)
    human_pause(0.2, 0.5)

    for ch in text:
        page.keyboard.type(ch)
        time.sleep(random.uniform(0.04, 0.17))
        if ch in ".!?,\n" and random.random() < 0.5:
            human_pause(0.2, 0.7)   # pause after punctuation
        elif random.random() < 0.04:
            human_pause(0.25, 0.8)  # occasional mid-thought pause

    human_pause(0.3, 0.9)


def human_scroll(page: Page, amount: int | None = None) -> None:
    """Scroll down by a human-ish amount, in several uneven wheel ticks."""
    total = amount if amount is not None else random.randint(300, 900)
    done = 0
    while done < total:
        tick = min(random.randint(80, 220), total - done)
        page.mouse.wheel(0, tick)
        done += tick
        human_pause(0.08, 0.3)
