"""External auto-apply for Wellfound (Idea 2, external). HIGH RISK.

Uses the API templates + cookies captured by record_api.py, replayed with
a Chrome TLS fingerprint (via wf_replay). DRY-RUN by default, capped, with
delays. It's your account and your call — keep volume low.

Per job it makes two replayed GraphQL calls:
  1. JobApplicationModal {jobListingId}   -> startupId + screening questions  (read-only)
  2. CreateJobApplication {input...}       -> applies                          (only with --send)

The captured `x-apollo-signature` is time-limited, so re-run record_api.py
(apply to ONE job by hand) shortly before using this.

Usage:
  python wf_apply.py jobs                              # job ids in the capture
  python wf_apply.py apply --job 4174674               # DRY-RUN: read modal, show plan
  python wf_apply.py apply --job 4174674 --note "Keen to help" --send
  python wf_apply.py apply --job 4174674 --answer 263758="Loved your mission" --send
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

import wf_replay as W


def load_notes(note, note_file):
    """Return a list of cover-note variants. A --note-file may hold several
    variants separated by a line containing only '---'; batch rotates through
    them per job so applications aren't byte-identical. Falls back to --note.
    Keep your note file out of git (it's personal) — note.txt is gitignored."""
    if note_file:
        text = Path(note_file).read_text(encoding="utf-8")
        variants = [v.strip() for v in re.split(r"(?m)^---\s*$", text) if v.strip()]
        if variants:
            return variants
    return [note or ""]


def template(reqs, op):
    """Latest captured request for a given GraphQL operationName."""
    cands = [r for r in reqs if f'"{op}"' in (r.get("post_data") or "")]
    return cands[-1] if cands else None


def parse_modal(resp_json):
    """Pull startupId + screening questions out of a JobApplicationModal response."""
    startups, questions, seen_q = set(), [], set()

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "startupId" and isinstance(v, (str, int)):
                    startups.add(str(v))
                if k == "startup" and isinstance(v, dict) and v.get("id"):
                    startups.add(str(v["id"]))
                if "uestion" in k and isinstance(v, list):
                    for q in v:
                        if isinstance(q, dict) and q.get("id") and ("question" in q or "questionType" in q):
                            qid = str(q["id"])
                            if qid not in seen_q:
                                seen_q.add(qid)
                                questions.append({
                                    "id": qid,
                                    "question": q.get("question"),
                                    "required": bool(q.get("required")),
                                    "type": q.get("questionType"),
                                })
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(resp_json)
    return next(iter(startups), None), questions


def list_jobs(reqs):
    """jobListingIds + titles from any JobSearchResultsX response in the capture."""
    out, seen = [], set()

    def walk(o):
        if isinstance(o, dict):
            if o.get("__typename") in ("JobListing", "JobListingSearchResult") and o.get("id") and o.get("title"):
                if o["id"] not in seen:
                    seen.add(o["id"])
                    out.append((str(o["id"]), o.get("title")))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    for r in reqs:
        if '"JobSearchResultsX"' in (r.get("post_data") or ""):
            walk(r.get("response_json"))
    return out


def _send(session, captured, body):
    """Send a request reusing a captured request's method/url/headers but a new body."""
    method, url, headers, _ = W.reconstruct(captured, [])
    resp = session.request(method, url, headers=headers, data=body, timeout=30)
    try:
        return resp, resp.json()
    except Exception:
        return resp, None


def _blocked(resp, j):
    if j is not None:
        return False
    text = (resp.text or "")[:500].lower()
    return "captcha-delivery" in text or "datadome" in text


def cmd_jobs(capture_dir):
    jobs = list_jobs(W.load_requests(capture_dir))
    if not jobs:
        print("No jobs found in the capture's search results.")
        return
    print(f"{len(jobs)} job(s) in the capture:\n")
    for jid, title in jobs:
        print(f"  --job {jid}   {title}")


def load_templates(capture_dir):
    """Return (session, modal_template, apply_template) or (None, None, None)."""
    reqs = W.load_requests(capture_dir)
    modal_t = template(reqs, "JobApplicationModal")
    apply_t = template(reqs, "CreateJobApplication")
    if not modal_t or not apply_t:
        print("Capture is missing JobApplicationModal / CreateJobApplication templates.")
        print("Re-run `python record_api.py` and apply to ONE job by hand first.")
        return None, None, None
    return W.build_session(W.load_cookies(capture_dir)), modal_t, apply_t


def apply_one(s, modal_t, apply_t, job_id, note, answers, send):
    """Run the two-step apply for one job. Returns (status, detail).

    status ∈ {applied, dry, already, needs_answers, blocked, error}. This is
    pure logic + I/O so both `apply` and `batch` share the exact same path.
    """
    # 1. Read-only modal fetch → startupId + questions.
    resp, j = _send(s, modal_t, json.dumps({**json.loads(modal_t["post_data"]),
                                            "variables": {"jobListingId": str(job_id)}}))
    if _blocked(resp, j):
        return "blocked", "modal fetch"
    startup_id, questions = parse_modal(j)
    if not startup_id:
        return "error", "no startupId from modal"

    cqa, missing = [], []
    for q in questions:
        if q["id"] in answers:
            cqa.append({"jobListingQuestionId": q["id"], "answer": answers[q["id"]],
                        "jobListingQuestionOptionId": None})
        elif q["required"]:
            missing.append(q)
    if missing:
        return "needs_answers", missing

    body_obj = json.loads(apply_t["post_data"])
    inp = body_obj["variables"]["input"]
    inp["jobListingId"] = str(job_id)
    inp["startupId"] = str(startup_id)
    inp["userNote"] = note or ""
    inp["customQuestionAnswers"] = cqa

    if not send:
        return "dry", {"startupId": startup_id, "questions": questions, "answers": len(cqa)}

    resp, j = _send(s, apply_t, json.dumps(body_obj))
    if _blocked(resp, j):
        return "blocked", "apply"
    jl = ((j or {}).get("data") or {}).get("jobListing") or {}
    if jl.get("currentUserApplied"):
        return "applied", resp.status_code
    errs = (j or {}).get("errors")
    if errs:
        msg = errs[0].get("message", "")
        return ("already" if "already applied" in msg.lower() else "error"), msg
    return "error", f"HTTP {resp.status_code}: {json.dumps(j)[:200]}"


def cmd_apply(capture_dir, job_id, note, answers, send, delay):
    s, modal_t, apply_t = load_templates(capture_dir)
    if not s:
        return
    if delay:
        time.sleep(delay)
    status, detail = apply_one(s, modal_t, apply_t, job_id, note, answers, send)
    if status == "needs_answers":
        print(f"\njob {job_id}: required question(s) need --answer <id>=\"...\":")
        for q in detail:
            print(f"   --answer {q['id']}=\"...\"   ({q['question']!r})")
    elif status == "dry":
        print(f"\njob {job_id}: startupId={detail['startupId']}, "
              f"{len(detail['questions'])} question(s), {detail['answers']} answered")
        print("DRY-RUN — apply NOT sent. Add --send to apply for real.")
    elif status == "applied":
        print(f"\n✅ Applied to {job_id} (HTTP {detail}).")
    elif status == "already":
        print(f"\nℹ️  {job_id}: {detail}")
    elif status == "blocked":
        print(f"\n⚠️  DataDome blocked the {detail} — stop and re-capture.")
    else:
        print(f"\n{job_id}: {detail}")


def cmd_batch(capture_dir, job_ids, notes, send, max_n, delay):
    s, modal_t, apply_t = load_templates(capture_dir)
    if not s:
        return
    job_ids = job_ids[:max_n]
    print(f"Batch over {len(job_ids)} job(s) (send={send}, delay={delay}s, {len(notes)} note variant(s)):\n")
    tally = {}
    for i, jid in enumerate(job_ids, 1):
        if i > 1 and delay:
            time.sleep(delay)
        note = notes[(i - 1) % len(notes)]  # rotate variants so applies differ
        status, detail = apply_one(s, modal_t, apply_t, jid, note, {}, send)
        tally[status] = tally.get(status, 0) + 1
        icon = {"applied": "✅", "already": "ℹ️", "dry": "•", "needs_answers": "⏭", "blocked": "⛔", "error": "✗"}.get(status, "?")
        extra = ""
        if status == "needs_answers":
            extra = f"skipped — {len(detail)} required Q (use single `apply` with --answer)"
        elif status in ("already", "error"):
            extra = str(detail)[:70]
        print(f"  [{i}/{len(job_ids)}] {icon} {jid} {status} {extra}")
        if status == "blocked":
            print("  Stopping batch — DataDome challenge.")
            break
    print("\nSummary:", ", ".join(f"{k}={v}" for k, v in tally.items()))


def main():
    ap = argparse.ArgumentParser(description="External Wellfound auto-apply (capture-replay).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("jobs").add_argument("--capture", default=None)

    a = sub.add_parser("apply")
    a.add_argument("--job", required=True)
    a.add_argument("--note", default="")
    a.add_argument("--note-file", default=None, help="read the cover note from a file (gitignore it)")
    a.add_argument("--answer", dest="answers", action="append", default=[],
                   help='Screening answer as QUESTIONID="text" (repeatable)')
    a.add_argument("--send", action="store_true")
    a.add_argument("--delay", type=float, default=0.0)
    a.add_argument("--capture", default=None)

    b = sub.add_parser("batch", help="apply to many job ids (from args or stdin)")
    b.add_argument("--ids", default=None, help="comma list of job ids; omit to read stdin")
    b.add_argument("--note", default="")
    b.add_argument("--note-file", default=None,
                   help="cover note file; '---' lines separate variants rotated per job")
    b.add_argument("--send", action="store_true")
    b.add_argument("--max", type=int, default=5, help="cap on how many to apply (default 5)")
    b.add_argument("--delay", type=float, default=30.0, help="seconds between jobs (default 30)")
    b.add_argument("--capture", default=None)
    args = ap.parse_args()

    capture_dir = Path(args.capture) if args.capture else W.find_latest_capture()
    if not capture_dir or not capture_dir.exists():
        print("No capture found. Run `python record_api.py` first.")
        sys.exit(1)

    if args.cmd == "jobs":
        cmd_jobs(capture_dir)
    elif args.cmd == "apply":
        answers = {}
        for a_ in args.answers:
            qid, _, val = a_.partition("=")
            answers[qid.strip()] = val
        note = load_notes(args.note, args.note_file)[0]
        cmd_apply(capture_dir, args.job, note, answers, args.send, args.delay)
    elif args.cmd == "batch":
        if args.ids:
            ids = [x.strip() for x in args.ids.split(",") if x.strip()]
        else:
            ids = [line.strip() for line in sys.stdin if line.strip()]
        if not ids:
            print("No job ids given (pass --ids or pipe them in).")
            sys.exit(1)
        cmd_batch(capture_dir, ids, load_notes(args.note, args.note_file), args.send, args.max, args.delay)


if __name__ == "__main__":
    main()
