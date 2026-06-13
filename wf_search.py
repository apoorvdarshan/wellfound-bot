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
import wf_resolve as R
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


def search(capture_dir, overrides, start_page, max_pages, clean=True):
    reqs = W.load_requests(capture_dir)
    tmpl = template(reqs, "JobSearchResultsX")
    if not tmpl:
        print("No JobSearchResultsX template in the capture.")
        print("Re-run `python record_api.py` and do a search on the site first.")
        return []

    base = json.loads(tmpl["post_data"])
    # clean=True builds the filter from ONLY what you asked for (right for
    # constructing a fresh query); clean=False inherits the exact filter you
    # set on the site (right for paginating it).
    captured = base["variables"].get("filterConfigurationInput", {})
    fci = {} if clean else dict(captured)
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


# Friendly --sort values → Wellfound's sortBy enum.
SORT_MAP = {"recommended": "RECOMMENDED", "recent": "LAST_POSTED", "active": "LAST_ACTIVE"}


def main():
    ap = argparse.ArgumentParser(description="External Wellfound job search (capture-replay).")
    ap.add_argument("--capture", default=None)
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("--max-pages", type=int, default=3)
    # Tag-based facets — these are tag IDs, not names. Easiest to set them on
    # the site during a capture; pass here only if you know the IDs.
    ap.add_argument("--role-tags", help="roleTagIds, comma list")
    ap.add_argument("--skill-tags", help="skillTagIds, comma list")
    ap.add_argument("--market-tags", help="marketTagIds, comma list")
    ap.add_argument("--location-tags", help="locationTagIds, comma list")
    ap.add_argument("--remote-company-tags", help="remoteCompanyLocationTagIds, comma list")
    # Name-based facets (resolved to IDs via the autocomplete API) — friendlier.
    ap.add_argument("--skills", help="skill NAMES, comma list (e.g. React,iOS)")
    ap.add_argument("--markets", help="market NAMES, comma list (e.g. Healthcare,Fintech)")
    ap.add_argument("--locations", help="location NAMES, comma list (e.g. \"San Francisco\",Bangalore)")
    # Value facets.
    ap.add_argument("--job-types", help="full_time,contract,internship,cofounder")
    ap.add_argument("--remote", help="remotePreference: REMOTE_OPEN / REMOTE_ONLY / NO_REMOTE")
    ap.add_argument("--keywords", help="included keywords, comma list")
    ap.add_argument("--exclude-keywords", help="excluded keywords, comma list")
    ap.add_argument("--company-sizes", help="SIZE_1_10,SIZE_11_50,SIZE_51_200,…")
    ap.add_argument("--investment-stages", help="SEED_STAGE,SERIES_A,SERIES_B,GROWTH,IPO,ACQUIRED")
    ap.add_argument("--salary-min", type=int)
    ap.add_argument("--salary-max", type=int)
    ap.add_argument("--currency", help="currencyCode, e.g. USD")
    ap.add_argument("--equity-min", type=float)
    ap.add_argument("--equity-max", type=float)
    ap.add_argument("--years-min", type=int)
    ap.add_argument("--years-max", type=int)
    # Boolean filter switches.
    ap.add_argument("--mostly-remote", action="store_true", help="distributed/remote-culture companies only")
    ap.add_argument("--responsive", action="store_true", help="highly-responsive companies only")
    ap.add_argument("--visa", action="store_true", help="visa-sponsoring companies only")
    ap.add_argument("--hide-external", action="store_true", help="hide off-platform (external-apply) jobs")
    ap.add_argument("--include-no-salary", action="store_true", help="include jobs without a listed salary")
    ap.add_argument("--sort", choices=tuple(SORT_MAP), help="recommended / recent / active")
    # Client-side conveniences.
    ap.add_argument("--exclude-applied", action="store_true")
    ap.add_argument("--native-only", action="store_true", help="also drop external-ATS jobs client-side")
    ap.add_argument("--from-capture", action="store_true",
                    help="inherit the exact filter you set on the site (else build only from flags)")
    ap.add_argument("--ids-only", action="store_true", help="print just job ids (for piping)")
    args = ap.parse_args()

    cap = Path(args.capture) if args.capture else W.find_latest_capture()
    if not cap or not cap.exists():
        print("No capture found. Run `python record_api.py` first.")
        sys.exit(1)

    def csv(s):
        return [x.strip() for x in s.split(",") if x.strip()]

    o = {}
    if args.role_tags: o["roleTagIds"] = csv(args.role_tags)
    if args.skill_tags: o["skillTagIds"] = csv(args.skill_tags)
    if args.market_tags: o["marketTagIds"] = csv(args.market_tags)
    if args.location_tags: o["locationTagIds"] = csv(args.location_tags)
    if args.remote_company_tags: o["remoteCompanyLocationTagIds"] = csv(args.remote_company_tags)
    if args.job_types: o["jobTypes"] = csv(args.job_types)
    if args.remote: o["remotePreference"] = args.remote
    if args.keywords: o["keywords"] = csv(args.keywords)
    if args.exclude_keywords: o["excludedKeywords"] = csv(args.exclude_keywords)
    if args.company_sizes: o["companySizes"] = csv(args.company_sizes)
    if args.investment_stages: o["investmentStages"] = csv(args.investment_stages)
    if args.salary_min is not None or args.salary_max is not None:
        o["salary"] = {"min": args.salary_min, "max": args.salary_max}
    if args.currency: o["currencyCode"] = args.currency
    if args.equity_min is not None or args.equity_max is not None:
        o["equity"] = {"min": args.equity_min, "max": args.equity_max}
    if args.years_min is not None or args.years_max is not None:
        o["yearsExperience"] = {"min": args.years_min, "max": args.years_max}
    if args.mostly_remote: o["mostlyOrFullyRemote"] = True
    if args.responsive: o["highlyResponsiveToIncomingApplications"] = True
    if args.visa: o["allowInternationalApplicants"] = True
    if args.hide_external: o["hideOffPlatformJobs"] = True
    if args.include_no_salary: o["includeJobsWithoutSalary"] = True
    if args.sort: o["sortBy"] = SORT_MAP[args.sort]
    # Name-based facets resolve to tag IDs and override the raw-id versions.
    if args.skills: o["skillTagIds"] = R.resolve_many(cap, "skill", csv(args.skills))
    if args.markets: o["marketTagIds"] = R.resolve_many(cap, "market", csv(args.markets))
    if args.locations: o["locationTagIds"] = R.resolve_many(cap, "location", csv(args.locations))

    jobs = search(cap, o, args.page, args.max_pages, clean=not args.from_capture)
    if args.exclude_applied:
        jobs = [j for j in jobs if not j["applied"]]
    if args.native_only:
        jobs = [j for j in jobs if not j["ats"]]  # keep Wellfound-native apply only

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
