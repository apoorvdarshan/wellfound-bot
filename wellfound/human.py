"""Human-like interaction helpers for Playwright.

Bot-detection systems flag the patterns that scripts fall into: clicks
that land on the exact pixel-center of an element, zero think-time
between actions, whole strings typed in a single keystroke, and a mouse
that teleports instead of moving. Every helper here adds realistic
timing and motion so the activity reads as a person, not a macro.
"""
import math
import random
import time

from playwright.sync_api import Locator, Page

# Last known cursor position, tracked across calls so each move starts
# where the previous one ended — continuous motion, never a teleport to
# a fresh random point. Seeded to a plausible mid-screen spot.
_cursor = {"x": 640.0, "y": 360.0}


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
    """Glide the cursor from its last position to (x, y).

    The path starts at the real previous position (no teleport), bends
    through one or two eased waypoints with jitter that shrinks as it
    nears the target, and uses more steps for longer travel — roughly the
    velocity profile of a hand.
    """
    sx, sy = _cursor["x"], _cursor["y"]
    dist = math.hypot(x - sx, y - sy)
    waypoints = 1 if dist < 250 else 2

    for i in range(waypoints):
        t = (i + 1) / (waypoints + 1)
        jitter = (1 - t) * min(40.0, dist * 0.15)
        wx = sx + (x - sx) * t + random.uniform(-jitter, jitter)
        wy = sy + (y - sy) * t + random.uniform(-jitter, jitter)
        page.mouse.move(wx, wy, steps=random.randint(5, 12))
        human_pause(0.02, 0.10)

    page.mouse.move(x, y, steps=max(8, int(dist / 12)))
    _cursor["x"], _cursor["y"] = x, y


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
