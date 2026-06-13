"""External job search for Wellfound (Idea 2). Read-only.

Replays the captured JobSearchResultsX with adjustable filters + pagination
and returns matching job listings (jobListingId + startupId + title), so you
can feed them into wf_apply.

The role/location filters are TAG IDs, not free text. Easiest way to set
them: apply the filters you want on wellfound.com while record_api.py is
recording — the capture then holds your exact filter and this just
paginates it. You can still tweak the simple fields below.

Usage:
  python wf_search.py                              # paginate the captured filter
  python wf_search.py --max-pages 5 --exclude-applied
  python wf_search.py --job-types full_time --remote REMOTE_OPEN --salary-min 100000
  python wf_search.py --role-tags 157714,103480 --location-tags 2203
  python wf_search.py --ids-only --exclude-applied   # pipe into: wf_apply.py batch
"""
import argparse
import json
import sys
from pathlib import Path

import wf_replay as W
from wf_apply import template


def collect(resp_json):
    """Return (jobs, has_next, total) from a JobSearchResultsX response."""
    jr = (((resp_json or {}).get("data") or {}).get("talent") or {}).get("jobSearchResults") or {}
    jobs = []
    for edge in (jr.get("startups") or {}).get("edges") or []:
        node = edge.get("node") or {}
        sid = str(node.get("startupId") or node.get("id") or "")
        for j in node.get("highlightedJobListings") or []:
            jobs.append({
                "jobListingId": str(j.get("id")),
                "title": j.get("title"),
                "role": j.get("primaryRoleTitle"),
                "locations": j.get("locationNames"),
                "remote": j.get("remote"),
                "applied": bool(j.get("currentUserApplied")),
                "startupId": sid,
                "company": node.get("name"),
                # Used for client-side sort + the native-apply filter. An
                # external atsSource means you'd apply on the company's own
                # site — which our CreateJobApplication can't do anyway.
                "ats": j.get("atsSource"),
                "live_at": j.get("liveStartAt") or 0,
                "active_at": j.get("lastRespondedAt") or 0,
            })
    return jobs, jr.get("hasNextPage"), jr.get("totalStartupCount")


def search(capture_dir, overrides, start_page, max_pages):
    reqs = W.load_requests(capture_dir)
    tmpl = template(reqs, "JobSearchResultsX")
    if not tmpl:
        print("No JobSearchResultsX template in the capture.")
        print("Re-run `python record_api.py` and do a search on the site first.")
        return []

    base = json.loads(tmpl["post_data"])
    fci = dict(base["variables"]["filterConfigurationInput"])
    fci.update(overrides)
    s = W.build_session(W.load_cookies(capture_dir))
    method, url, headers, _ = W.reconstruct(tmpl, [])

    jobs, page = [], start_page
    for _ in range(max_pages):
        fci["page"] = page
        base["variables"]["filterConfigurationInput"] = fci
        resp = s.request(method, url, headers=headers, data=json.dumps(base), timeout=30)
        try:
            j = resp.json()
        except Exception:
            if "datadome" in (resp.text or "").lower() or "captcha-delivery" in (resp.text or ""):
                print("⚠️  DataDome blocked the search — re-capture with record_api.py.")
            else:
                print(f"Non-JSON response on page {page} (HTTP {resp.status_code}).")
            break
        page_jobs, has_next, total = collect(j)
        jobs.extend(page_jobs)
        print(f"  page {page}: {len(page_jobs)} jobs (≈{total} companies total)")
        if not has_next:
            break
        page += 1
    return jobs


def main():
    ap = argparse.ArgumentParser(description="External Wellfound job search (capture-replay).")
    ap.add_argument("--capture", default=None)
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("--max-pages", type=int, default=3)
    ap.add_argument("--job-types", default=None, help="comma list, e.g. full_time,contract")
    ap.add_argument("--remote", default=None, help="remotePreference, e.g. REMOTE_OPEN")
    ap.add_argument("--salary-min", type=int, default=None)
    ap.add_argument("--salary-max", type=int, default=None)
    ap.add_argument("--role-tags", default=None, help="comma list of roleTagIds")
    ap.add_argument("--location-tags", default=None, help="comma list of locationTagIds")
    ap.add_argument("--exclude-applied", action="store_true")
    ap.add_argument("--native-only", action="store_true",
                    help="drop external-ATS jobs (the only ones our auto-apply can't do)")
    ap.add_argument("--sort", choices=("recommended", "recent", "active"), default="recommended",
                    help="recommended=API order, recent=liveStartAt, active=lastRespondedAt")
    ap.add_argument("--ids-only", action="store_true", help="print just job ids (for piping)")
    args = ap.parse_args()

    cap = Path(args.capture) if args.capture else W.find_latest_capture()
    if not cap or not cap.exists():
        print("No capture found. Run `python record_api.py` first.")
        sys.exit(1)

    overrides = {}
    if args.job_types:
        overrides["jobTypes"] = args.job_types.split(",")
    if args.remote:
        overrides["remotePreference"] = args.remote
    if args.salary_min is not None or args.salary_max is not None:
        overrides["salary"] = {"min": args.salary_min, "max": args.salary_max}
    if args.role_tags:
        overrides["roleTagIds"] = args.role_tags.split(",")
    if args.location_tags:
        overrides["locationTagIds"] = args.location_tags.split(",")

    jobs = search(cap, overrides, args.page, args.max_pages)
    if args.exclude_applied:
        jobs = [j for j in jobs if not j["applied"]]
    if args.native_only:
        jobs = [j for j in jobs if not j["ats"]]  # keep Wellfound-native apply only
    if args.sort == "recent":
        jobs.sort(key=lambda j: j["live_at"], reverse=True)
    elif args.sort == "active":
        jobs.sort(key=lambda j: j["active_at"], reverse=True)

    if args.ids_only:
        for j in jobs:
            print(j["jobListingId"])
        return

    print(f"\n{len(jobs)} job(s):")
    for j in jobs:
        mark = "  ✓already-applied" if j["applied"] else ""
        loc = ",".join(j["locations"] or []) if j["locations"] else "-"
        print(f"  {j['jobListingId']}  {str(j['title'])[:50]!r} @ {j['company']}  [{loc}]{mark}")


if __name__ == "__main__":
    main()
