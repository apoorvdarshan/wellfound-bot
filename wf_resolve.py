"""Resolve Wellfound filter NAMES → tag IDs via the autocomplete API.

skills / markets / locations each have a typeahead operation we captured;
this replays it (read-only) so you can search by name instead of hunting
tag IDs. Used by wf_search's --skills/--markets/--locations name flags and
by the natural-language agent.
"""
import json
import sys

import wf_replay as W
from wf_apply import template

AUTOCOMPLETE = {
    "skill": "SkillTagAutocompleteField",
    "market": "MarketTagAutocompleteField",
    "location": "LocationTagAutocompleteField",
}


def _suggestions(resp_json):
    out = []

    def walk(x):
        if isinstance(x, dict):
            if "id" in x and any(k in x for k in ("name", "displayName", "title", "label")):
                nm = x.get("name") or x.get("displayName") or x.get("title") or x.get("label")
                out.append((str(x["id"]), nm))
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(resp_json)
    return out


def resolve(capture_dir, kind, query, session=None):
    """Return ((id, name), all_suggestions) for the best match of `query`."""
    op = AUTOCOMPLETE.get(kind)
    if not op:
        return None, []
    tmpl = template(W.load_requests(capture_dir), op)
    if not tmpl:
        return None, []
    s = session or W.build_session(W.load_cookies(capture_dir))
    body = json.loads(tmpl["post_data"])
    body["variables"] = {**body.get("variables", {}), "query": query}
    method, url, headers, _ = W.reconstruct(tmpl, [])
    resp = s.request(method, url, headers=headers, data=json.dumps(body), timeout=30)
    try:
        sugg = _suggestions(resp.json())
    except Exception:
        return None, []
    # Prefer an exact (case-insensitive) name match, else the top suggestion.
    best = next(((sid, nm) for sid, nm in sugg if nm and nm.lower() == query.lower()), None)
    if not best and sugg:
        best = sugg[0]
    return best, sugg


def resolve_many(capture_dir, kind, names, session=None):
    """Resolve a list of names → list of tag ids (best match each)."""
    s = session or W.build_session(W.load_cookies(capture_dir))
    ids = []
    for n in names:
        best, _ = resolve(capture_dir, kind, n, s)
        if best:
            ids.append(best[0])
    return ids


def main():
    if len(sys.argv) < 3:
        print("usage: python wf_resolve.py <skill|market|location> <name>")
        sys.exit(1)
    kind, query = sys.argv[1], " ".join(sys.argv[2:])
    cap = W.find_latest_capture()
    best, sugg = resolve(cap, kind, query)
    print(f"best match for {query!r} ({kind}): {best}")
    for sid, nm in sugg[:8]:
        print(f"   {sid}  {nm}")


if __name__ == "__main__":
    main()
