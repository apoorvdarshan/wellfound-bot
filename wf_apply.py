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
import sys
import time
from pathlib import Path

import wf_replay as W


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


def cmd_apply(capture_dir, job_id, note, answers, send, delay):
    reqs = W.load_requests(capture_dir)
    modal_t = template(reqs, "JobApplicationModal")
    apply_t = template(reqs, "CreateJobApplication")
    if not modal_t or not apply_t:
        print("Capture is missing JobApplicationModal / CreateJobApplication templates.")
        print("Re-run `python record_api.py` and apply to ONE job by hand first.")
        return

    s = W.build_session(W.load_cookies(capture_dir))

    # 1. Read-only modal fetch → startupId + questions (runs even in dry-run).
    resp, j = _send(s, modal_t, json.dumps({**json.loads(modal_t["post_data"]),
                                            "variables": {"jobListingId": str(job_id)}}))
    if _blocked(resp, j):
        print("⚠️  DataDome blocked the modal fetch — re-capture with record_api.py.")
        return
    startup_id, questions = parse_modal(j)
    print(f"\njob {job_id}: startupId={startup_id}, {len(questions)} question(s)")
    for q in questions:
        tag = "required" if q["required"] else "optional"
        print(f"   - [{tag}] id={q['id']}: {q['question']!r}")
    if not startup_id:
        print("Couldn't determine startupId from the modal response — aborting.")
        return

    # Build screening-question answers; block only on unanswered REQUIRED ones.
    cqa, missing = [], []
    for q in questions:
        if q["id"] in answers:
            cqa.append({"jobListingQuestionId": q["id"], "answer": answers[q["id"]],
                        "jobListingQuestionOptionId": None})
        elif q["required"]:
            missing.append(q)
    if missing:
        print("\nRequired question(s) need an answer via --answer <id>=\"...\":")
        for q in missing:
            print(f"   --answer {q['id']}=\"...\"   ({q['question']!r})")
        print("Aborting until answered.")
        return

    # 2. Build the apply body from the captured template.
    body_obj = json.loads(apply_t["post_data"])
    inp = body_obj["variables"]["input"]
    inp["jobListingId"] = str(job_id)
    inp["startupId"] = str(startup_id)
    inp["userNote"] = note or ""
    inp["customQuestionAnswers"] = cqa
    body = json.dumps(body_obj)

    print("\n=== CreateJobApplication that would be sent ===")
    print(f"  jobListingId={job_id}  startupId={startup_id}  answers={len(cqa)}  note={note!r}")
    if not send:
        print("\nDRY-RUN — apply NOT sent. Add --send to apply for real.")
        return

    if delay:
        time.sleep(delay)
    resp, j = _send(s, apply_t, body)
    if _blocked(resp, j):
        print("⚠️  DataDome blocked the apply — stop and re-capture.")
        return
    jl = ((j or {}).get("data") or {}).get("jobListing") or {}
    if jl.get("currentUserApplied"):
        print(f"\n✅ Applied to {job_id} (HTTP {resp.status_code}).")
    elif (j or {}).get("errors"):
        print(f"\nServer responded (HTTP {resp.status_code}): {j['errors'][0].get('message')}")
    else:
        print(f"\nHTTP {resp.status_code}: {json.dumps(j)[:300]}")


def main():
    ap = argparse.ArgumentParser(description="External Wellfound auto-apply (capture-replay).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("jobs").add_argument("--capture", default=None)
    a = sub.add_parser("apply")
    a.add_argument("--job", required=True)
    a.add_argument("--note", default="")
    a.add_argument("--answer", dest="answers", action="append", default=[],
                   help='Screening answer as QUESTIONID="text" (repeatable)')
    a.add_argument("--send", action="store_true")
    a.add_argument("--delay", type=float, default=0.0)
    a.add_argument("--capture", default=None)
    args = ap.parse_args()

    capture_dir = Path(args.capture) if args.capture else W.find_latest_capture()
    if not capture_dir or not capture_dir.exists():
        print("No capture found. Run `python record_api.py` first.")
        sys.exit(1)

    if args.cmd == "jobs":
        cmd_jobs(capture_dir)
    else:
        answers = {}
        for a_ in args.answers:
            qid, _, val = a_.partition("=")
            answers[qid.strip()] = val
        cmd_apply(capture_dir, args.job, args.note, answers, args.send, args.delay)


if __name__ == "__main__":
    main()
