"""One-shot agent: search Wellfound by name/filters, then auto-apply.

Two ways to drive it:

  * Flags (works now, no API key):
      python wf_agent.py --skills React,Node --remote --locations "San Francisco" --max 5 --send

  * Natural language (needs `pip install anthropic` + ANTHROPIC_API_KEY):
      python wf_agent.py --query "remote react jobs in SF, apply to 5" --send

It searches with a CLEAN filter (only what you ask for), keeps Wellfound-
native + not-yet-applied jobs, then batch-applies up to --max with delays.
DRY-RUN unless --send. Skips jobs with required screening questions (do
those with `wf_apply.py apply --answer`).

Either way the pieces are the same: resolve names → tag IDs (wf_resolve),
search (wf_search), apply (wf_apply).
"""
import argparse
import json
import sys
import time

import wf_apply as AP
import wf_replay as W
import wf_resolve as R
import wf_search as S

SORT_MAP = {"recommended": "RECOMMENDED", "recent": "LAST_POSTED", "active": "LAST_ACTIVE"}


def parse_query(query):
    """Turn a natural-language request into a filter dict via Claude.

    Returns None if the anthropic SDK / API key isn't available, so the
    caller can fall back to flags.
    """
    try:
        import os
        import anthropic
    except Exception:
        return None
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None

    schema_hint = (
        "Return ONLY JSON with any of these keys (omit unknowns): "
        '{"skills":[str],"markets":[str],"locations":[str],"remote":bool,'
        '"job_types":[str from full_time,contract,internship,cofounder],'
        '"salary_min":int,"keywords":[str],"exclude_keywords":[str],'
        '"company_sizes":[str like SIZE_1_10],"investment_stages":[str like SEED_STAGE],'
        '"sort":"recommended|recent|active","max_apply":int}'
    )
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=512,
        system="You extract Wellfound job-search filters from a user's request. " + schema_hint,
        messages=[{"role": "user", "content": query}],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1]) if start >= 0 else None


def build_overrides(cap, spec, session):
    """spec is a dict (from flags or NL) → Wellfound filterConfigurationInput overrides."""
    o = {}
    if spec.get("skills"):
        o["skillTagIds"] = R.resolve_many(cap, "skill", spec["skills"], session)
    if spec.get("markets"):
        o["marketTagIds"] = R.resolve_many(cap, "market", spec["markets"], session)
    if spec.get("locations"):
        o["locationTagIds"] = R.resolve_many(cap, "location", spec["locations"], session)
    if spec.get("remote"):
        o["remotePreference"] = "REMOTE_OPEN"
    if spec.get("job_types"):
        o["jobTypes"] = spec["job_types"]
    if spec.get("keywords"):
        o["keywords"] = spec["keywords"]
    if spec.get("exclude_keywords"):
        o["excludedKeywords"] = spec["exclude_keywords"]
    if spec.get("company_sizes"):
        o["companySizes"] = spec["company_sizes"]
    if spec.get("investment_stages"):
        o["investmentStages"] = spec["investment_stages"]
    if spec.get("salary_min") is not None:
        o["salary"] = {"min": spec["salary_min"], "max": None}
    if spec.get("sort"):
        o["sortBy"] = SORT_MAP.get(spec["sort"], "RECOMMENDED")
    return o


def main():
    ap = argparse.ArgumentParser(description="Search Wellfound by name + filters, then auto-apply.")
    ap.add_argument("--query", help="natural-language request (needs ANTHROPIC_API_KEY)")
    ap.add_argument("--skills"); ap.add_argument("--markets"); ap.add_argument("--locations")
    ap.add_argument("--keywords"); ap.add_argument("--exclude-keywords")
    ap.add_argument("--job-types"); ap.add_argument("--company-sizes"); ap.add_argument("--investment-stages")
    ap.add_argument("--remote", action="store_true")
    ap.add_argument("--salary-min", type=int)
    ap.add_argument("--sort", choices=tuple(SORT_MAP))
    ap.add_argument("--max", type=int, default=5, help="max jobs to apply to")
    ap.add_argument("--max-pages", type=int, default=3)
    ap.add_argument("--delay", type=float, default=40.0, help="seconds between applies")
    ap.add_argument("--note", default="")
    ap.add_argument("--send", action="store_true", help="actually apply (else dry-run)")
    ap.add_argument("--capture", default=None)
    args = ap.parse_args()

    cap = __import__("pathlib").Path(args.capture) if args.capture else W.find_latest_capture()
    if not cap or not cap.exists():
        print("No capture found. Run `python record_api.py` first.")
        sys.exit(1)

    # Build the filter spec from --query (NL) or the flags.
    csv = lambda s: [x.strip() for x in s.split(",") if x.strip()] if s else None
    if args.query:
        spec = parse_query(args.query)
        if spec is None:
            print("Natural-language mode needs `pip install anthropic` + ANTHROPIC_API_KEY.")
            print("Use flags instead, e.g. --skills React --remote --max 5")
            sys.exit(1)
        print("Parsed your request into:", json.dumps(spec))
    else:
        spec = {
            "skills": csv(args.skills), "markets": csv(args.markets), "locations": csv(args.locations),
            "keywords": csv(args.keywords), "exclude_keywords": csv(args.exclude_keywords),
            "job_types": csv(args.job_types), "company_sizes": csv(args.company_sizes),
            "investment_stages": csv(args.investment_stages), "remote": args.remote,
            "salary_min": args.salary_min, "sort": args.sort,
        }
    max_apply = spec.get("max_apply") or args.max

    session = W.build_session(W.load_cookies(cap))
    overrides = build_overrides(cap, spec, session)
    print("Filter:", json.dumps(overrides))

    # 1. Search (clean filter), keep native + not-yet-applied.
    jobs = S.search(cap, overrides, 1, args.max_pages, clean=True)
    jobs = [j for j in jobs if not j["applied"] and not j["ats"]]
    print(f"\n{len(jobs)} applicable job(s) found; will {'APPLY to' if args.send else 'DRY-RUN'} up to {max_apply}:")
    for j in jobs[:max_apply]:
        print(f"  {j['jobListingId']}  {str(j['title'])[:55]!r} @ {j['company']}")

    # 2. Apply (or dry-run).
    s, modal_t, apply_t = AP.load_templates(cap)
    if not s:
        return
    targets = jobs[:max_apply]
    tally = {}
    for i, j in enumerate(targets, 1):
        if i > 1 and args.send and args.delay:
            time.sleep(args.delay)
        status, detail = AP.apply_one(s, modal_t, apply_t, j["jobListingId"], args.note, {}, args.send)
        tally[status] = tally.get(status, 0) + 1
        icon = {"applied": "✅", "already": "ℹ️", "dry": "•", "needs_answers": "⏭", "blocked": "⛔", "error": "✗"}.get(status, "?")
        print(f"  [{i}/{len(targets)}] {icon} {j['jobListingId']} {status}")
        if status == "blocked":
            print("  Stopping — DataDome challenge. Re-capture with record_api.py.")
            break
    print("\nSummary:", ", ".join(f"{k}={v}" for k, v in tally.items()) or "nothing to do")
    if not args.send:
        print("DRY-RUN — nothing applied. Add --send to apply for real.")


if __name__ == "__main__":
    main()
