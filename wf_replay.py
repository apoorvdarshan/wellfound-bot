"""External API replay (Idea 2, external) — highest risk, use carefully.

Instead of guessing Wellfound's API, this replays the REAL request you
already captured with record_api.py, but sends it from a standalone
client that:
  * impersonates Chrome's TLS/JA3 fingerprint (curl_cffi impersonate),
  * reuses your live cookies (incl. `datadome` + auth) from the capture,
  * replays the captured headers and body, with optional variable edits.

This is the most detectable approach — DataDome fingerprints more than
TLS, and the `datadome` cookie is browser-bound. Defaults to DRY-RUN
(prints what it WOULD send). Add --send to actually fire it. Keep volume
tiny.

Usage:
    python wf_replay.py list                       # show captured requests
    python wf_replay.py replay --index 7           # dry-run request #7
    python wf_replay.py replay --index 7 \
        --set variables.jobId=12345 --send         # really send it
"""
import argparse
import json
import sys
from pathlib import Path

from curl_cffi import requests as creq

CAPTURES = Path(__file__).resolve().parent / "captures"
IMPERSONATE = "chrome"  # latest Chrome profile curl_cffi ships

# Headers we must NOT replay verbatim — they're connection-specific or are
# managed by the client / cookie jar.
HEADER_DENYLIST = {
    "host", "content-length", "connection", "cookie",
    "accept-encoding", "content-encoding",
}


def find_latest_capture() -> Path | None:
    dirs = sorted(CAPTURES.glob("api-*"), reverse=True)
    return dirs[0] if dirs else None


def load_requests(capture_dir: Path) -> list[dict]:
    f = capture_dir / "requests.jsonl"
    if not f.exists():
        return []
    return [json.loads(line) for line in f.read_text().splitlines() if line.strip()]


def load_cookies(capture_dir: Path) -> list[dict]:
    f = capture_dir / "cookies.json"
    return json.loads(f.read_text()) if f.exists() else []


def _operation_name(post_data) -> str:
    """Pull the GraphQL operationName out of a request body, if any."""
    if not post_data:
        return ""
    try:
        obj = json.loads(post_data)
    except Exception:
        return ""
    if isinstance(obj, list):  # batched GraphQL
        return ",".join(str(o.get("operationName", "")) for o in obj if isinstance(o, dict))
    if isinstance(obj, dict):
        return str(obj.get("operationName", ""))
    return ""


def set_in(obj, dotted: str, value):
    """Set a nested key like 'variables.jobId' on a parsed JSON object."""
    keys = dotted.split(".")
    cur = obj
    for k in keys[:-1]:
        cur = cur[k]
    # numeric-looking values become ints, otherwise stay strings
    try:
        value = int(value)
    except (TypeError, ValueError):
        pass
    cur[keys[-1]] = value


def build_session(cookies: list[dict]) -> creq.Session:
    s = creq.Session(impersonate=IMPERSONATE)
    for c in cookies:
        try:
            s.cookies.set(c["name"], c["value"], domain=c.get("domain", ""), path=c.get("path", "/"))
        except Exception:
            pass
    return s


def reconstruct(captured: dict, overrides: list[str]):
    """Return (method, url, headers, body) for a captured request, applying
    any --set overrides to the JSON body."""
    method = captured.get("method", "GET")
    url = captured["url"]
    headers = {
        k: v for k, v in (captured.get("request_headers") or {}).items()
        if k.lower() not in HEADER_DENYLIST
    }
    body = captured.get("post_data")
    if body and overrides:
        obj = json.loads(body)
        for ov in overrides:
            key, _, val = ov.partition("=")
            set_in(obj, key.strip(), val.strip())
        body = json.dumps(obj)
    return method, url, headers, body


def cmd_list(capture_dir: Path):
    reqs = load_requests(capture_dir)
    if not reqs:
        print(f"No requests in {capture_dir}. Run record_api.py first.")
        return
    print(f"{len(reqs)} request(s) in {capture_dir.name}:\n")
    for i, r in enumerate(reqs):
        op = _operation_name(r.get("post_data"))
        op = f"  op={op}" if op else ""
        print(f"  [{i:>3}] {r.get('method'):4} {r.get('status')}  {r['url'][:80]}{op}")


def cmd_replay(capture_dir: Path, index: int, overrides: list[str], send: bool):
    reqs = load_requests(capture_dir)
    if not (0 <= index < len(reqs)):
        print(f"Index {index} out of range (0..{len(reqs)-1}).")
        return
    method, url, headers, body = reconstruct(reqs[index], overrides)

    print("\n=== Reconstructed request ===")
    print(f"{method} {url}")
    print("Headers (cookies sent separately from the jar):")
    for k, v in headers.items():
        print(f"  {k}: {v[:80]}")
    if body:
        print("Body:")
        print("  " + body[:600])

    if not send:
        print("\nDRY-RUN — not sent. Re-run with --send to actually fire it.")
        return

    cookies = load_cookies(capture_dir)
    if not cookies:
        print("\nNo cookies.json in the capture — can't authenticate. Aborting.")
        return
    print(f"\nSENDING for real (impersonate={IMPERSONATE}, {len(cookies)} cookies)…")
    s = build_session(cookies)
    resp = s.request(method, url, headers=headers, data=body, timeout=30)
    print(f"\n<- HTTP {resp.status_code}")
    ctype = resp.headers.get("content-type", "")
    if "json" in ctype:
        try:
            print(json.dumps(resp.json(), indent=2)[:1500])
        except Exception:
            print(resp.text[:1500])
    else:
        # A DataDome block usually shows up as an HTML/captcha body here.
        snippet = resp.text[:600]
        print(snippet)
        if "captcha-delivery" in snippet or "datadome" in snippet.lower():
            print("\n⚠️  Looks like a DataDome block/challenge — external replay was detected.")


def main():
    ap = argparse.ArgumentParser(description="Replay a captured Wellfound API request with Chrome TLS.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").add_argument("--capture", default=None)
    rp = sub.add_parser("replay")
    rp.add_argument("--index", type=int, required=True)
    rp.add_argument("--capture", default=None)
    rp.add_argument("--set", dest="overrides", action="append", default=[])
    rp.add_argument("--send", action="store_true")
    args = ap.parse_args()

    capture_dir = Path(args.capture) if args.capture else find_latest_capture()
    if not capture_dir or not capture_dir.exists():
        print("No capture found. Run `python record_api.py` first.")
        sys.exit(1)

    if args.cmd == "list":
        cmd_list(capture_dir)
    elif args.cmd == "replay":
        cmd_replay(capture_dir, args.index, args.overrides, args.send)


if __name__ == "__main__":
    main()
