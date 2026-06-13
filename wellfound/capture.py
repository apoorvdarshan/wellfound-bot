"""Record each step of a run so the flow can be replayed or handed to an
agent: the action taken, the URL, the selector used, plus a screenshot
and the full page HTML at that moment.

The capture is the point of this whole project. When a selector stops
matching (Wellfound's DOM shifts often), the saved HTML is exactly what
you — or an agent — read to find the new selector.
"""
import json
import time
from pathlib import Path

from playwright.sync_api import Page

CAPTURE_DIR = Path(__file__).resolve().parent.parent / "captures"


def _safe_title(page: Page) -> str:
    try:
        return page.title()
    except Exception:
        return ""


class FlowRecorder:
    """Append-only recorder. One directory per run, one row per step."""

    def __init__(self, run_name: str):
        self.dir = CAPTURE_DIR / run_name
        self.dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.dir / "flow.jsonl"
        self.step = 0

    def record(
        self,
        page: Page,
        action: str,
        *,
        detail: str | None = None,
        selector: str | None = None,
        save_html: bool = True,
    ) -> dict:
        self.step += 1
        n = f"{self.step:03d}"

        shot_name = None
        try:
            page.screenshot(path=str(self.dir / f"{n}.png"))
            shot_name = f"{n}.png"
        except Exception:
            pass

        html_name = None
        if save_html:
            try:
                (self.dir / f"{n}.html").write_text(page.content(), encoding="utf-8")
                html_name = f"{n}.html"
            except Exception:
                pass

        entry = {
            "step": self.step,
            "ts": time.time(),
            "action": action,
            "detail": detail,
            "selector": selector,
            "url": page.url,
            "title": _safe_title(page),
            "screenshot": shot_name,
            "html": html_name,
        }
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        return entry
