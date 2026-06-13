# wellfound-bot — Agent Operating Manual

This is a **self-contained runbook**. An agent (or human) can follow it
end-to-end without reading the source. It tells you what the tool does,
the exact commands, the reverse-engineered API, and how to recover from
errors.

> ⚖️ **Personal/educational use only.** Operate only the owner's own
> account. Automating Wellfound violates its ToS and risks suspension.
> Always confirm before submitting **real** applications. Keep volume low.

---

## 0. TL;DR — the mental model

Two phases:

1. **Capture (needs a VISIBLE Chrome, ~1 min, done occasionally).**
   `record_api.py` opens real Chrome; the human logs in (if needed) and
   does **one manual apply** + an optional search. This records Wellfound's
   API calls + cookies into `captures/api-<timestamp>/`. This is the only
   step that touches a browser.

2. **Operate (pure HTTP, no browser, invisible).**
   `wf_search.py` / `wf_apply.py` / `wf_agent.py` replay those captured
   API calls over HTTP with a Chrome TLS fingerprint (`curl_cffi`). This is
   how all searching/applying happens. No window, nothing visible.

**Critical facts:**
- Wellfound uses **DataDome** anti-bot. A **headless browser is instantly
  CAPTCHA-walled** → the capture step must be **headed (visible)**. Never
  headless.
- The external HTTP client **passes DataDome** (verified: HTTP 200 apply).
- The captured `x-apollo-signature` is **time-limited**. When applies start
  failing (`blocked` / `unauthorized` / a `datadome` body) → **re-capture**
  (re-run phase 1).
- The tools always use the **latest** `captures/api-*` folder automatically.
- `captures/` and `user_data/` hold **live session secrets** — gitignored,
  never commit or share.

---

## 1. One-time setup

```bash
cd wellfound-bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

macOS + real Google Chrome installed is assumed (path
`/Applications/Google Chrome.app/...`). Python 3.10+.

---

## 2. Phase 1 — Capture / refresh the session (headed, ~1 min)

Run this the first time, and again whenever applies start getting blocked.

```bash
python record_api.py
```

Then **in the Chrome window that opens** (do this by hand):
1. Go to `wellfound.com/jobs`; log in if asked (any method).
2. **Apply to ONE job manually** (this captures the apply API + a fresh
   signature). Pick one the owner is fine submitting.
3. *(Optional but recommended)* set the filters you care about and run a
   search; type a few letters in the Skills / Markets / Location boxes (to
   capture autocomplete).
4. Back in the terminal, press **Ctrl-C** (or just close Chrome).

Output: `captures/api-<timestamp>/requests.jsonl` + `cookies.json`.
You can now close the browser; everything below is browser-free.

---

## 3. Phase 2 — Operate (the commands)

All read the latest capture automatically. Add `--capture <dir>` to force one.

### Search (read-only)
```bash
# by NAME (resolved to tag IDs via autocomplete):
python wf_search.py --skills React,Node --remote --locations "San Francisco" --native-only --exclude-applied
# by raw tag IDs:
python wf_search.py --skill-tags 16681 --remote --max-pages 3
# just the ids (to pipe into apply):
python wf_search.py --ids-only --skills iOS --remote --exclude-applied
```
Defaults to a **clean** filter (only what you pass). Add `--from-capture`
to instead paginate the exact filter set on the site during capture.

### Apply
```bash
python wf_apply.py jobs                                  # list job ids in the capture
python wf_apply.py apply --job 4174674                   # DRY-RUN (no application)
python wf_apply.py apply --job 4174674 --send            # REAL application
python wf_apply.py apply --job 4174674 --answer 263758="my answer" --send   # required screening Q
python wf_apply.py batch --ids 4329855,4329859 --max 2 --delay 25 --send    # several
python wf_search.py --ids-only --skills iOS --remote | python wf_apply.py batch --max 5 --delay 45 --send
```

### Agent (one shot: search → apply)
```bash
python wf_agent.py --skills React --remote --max 5             # DRY-RUN
python wf_agent.py --skills React --remote --max 5 --send      # REAL
python wf_agent.py --query "remote react jobs in SF, apply to 5" --send   # NL (needs anthropic + ANTHROPIC_API_KEY)
```

### Resolve a name → tag id (debug)
```bash
python wf_resolve.py skill "React"
python wf_resolve.py location "San Francisco"
python wf_resolve.py market "Healthcare"
```

---

## 4. Agent decision tree (given a user request like "apply to 5 remote React jobs with pay")

1. **Parse** the request into: skills/markets, location, remote?, salary
   floor, job types, sort, and **count N**.
2. **Search** (dry) to get candidates:
   `wf_search.py --skills <…> [--remote] [--locations <…>] --native-only --exclude-applied`
   - "with pay" → keep jobs whose `compensation` field is non-empty (a
     real salary, not equity-only). `--native-only` keeps only jobs our
     apply can do (drops external-ATS).
3. **Show the shortlist** (title, company, pay, location) and **get the
   user's confirmation** before sending — applications are real + irreversible.
4. **Apply**: `wf_apply.py batch --ids <id1,id2,…> --max N --delay 30 --send`
5. **Interpret results** per job:
   - `applied` ✅ done.
   - `already` → already applied, skip.
   - `needs_answers` → job has a **required** screening question; re-run
     `wf_apply.py apply --job <id> --answer <qid>="<text>" --send`.
   - `blocked` ⛔ → DataDome/expired session → **go to Phase 1 (re-capture)**.
6. Keep N small (≤5) and `--delay ≥ 30`. Never burst.

---

## 5. The reverse-engineered API (reference)

Endpoint: `POST https://wellfound.com/graphql` (persisted queries; the
operation is referenced by `extensions.operationId`, body carries
`operationName` + `variables`). Auth is via cookies (incl. `datadome`)
plus headers replayed from the capture (notably the time-limited
`x-apollo-signature`, `x-wf-cfp`, `x-apollo-operation-name`,
`apollographql-client-name: talent-web`, `x-requested-with: XMLHttpRequest`).

| Operation | Variables | Returns / use |
|---|---|---|
| `JobSearchResultsX` | `{filterConfigurationInput:{…}}` | `data.talent.jobSearchResults` → `hasNextPage`, `totalStartupCount`, `startups.edges[].node` (`id`, `startupId`, `name`, `highlightedJobListings[]`) |
| `JobApplicationModal` | `{jobListingId}` | `startupId` + screening `questions[]` (`{id, question, required}`) |
| `CreateJobApplication` | `{input:{sourceId,jobListingId,product:"job search",questionResponseSets:null,customQuestionAnswers:[…],startupId,userNote}}` | success → `data.jobListing.currentUserApplied=true`; dup → error `"You've already applied to this job!"` |
| `SkillTagAutocompleteField` | `{query}` | skill suggestions `{id,name}` |
| `MarketTagAutocompleteField` | `{query}` | market suggestions `{id,name}` |
| `LocationTagAutocompleteField` | `{options:{excludeIds},query}` | location suggestions `{id,name}` |

Each `highlightedJobListings[]` job has: `id` (jobListingId), `title`,
`currentUserApplied`, `atsSource` (non-null = external apply, skip),
`compensation` (string, e.g. `"$120k – $180k"`), `primaryRoleTitle`,
`locationNames`, `remote`, `liveStartAt`, `lastRespondedAt`.

---

## 6. Filter field reference (`filterConfigurationInput`)

| Field | Type | Notes / enum |
|---|---|---|
| `page` | int | 1-based |
| `roleTagIds` | [id] | role = fixed list (no autocomplete) |
| `skillTagIds` | [id] | resolve names via `SkillTagAutocompleteField` |
| `marketTagIds` | [id] | resolve via `MarketTagAutocompleteField` |
| `locationTagIds` | [id] | resolve via `LocationTagAutocompleteField` |
| `remoteCompanyLocationTagIds` | [id] | "remote companies based in" |
| `jobTypes` | [str] | `full_time`, `contract`, `internship`, `cofounder` |
| `remotePreference` | str | `REMOTE_OPEN`, `REMOTE_ONLY`, `NO_REMOTE` |
| `keywords` | [str] | included keywords |
| `excludedKeywords` | [str] | excluded keywords |
| `companySizes` | [str] | `SIZE_1_10` confirmed; pattern `SIZE_11_50`, `SIZE_51_200`, `SIZE_201_500`, `SIZE_501_1000`, `SIZE_1001_5000`, `SIZE_5000_PLUS` (verify) |
| `investmentStages` | [str] | `SEED_STAGE`, `SERIES_A` confirmed; also `SERIES_B`, `GROWTH`, `IPO`, `ACQUIRED` (verify) |
| `salary` | {min,max} | numbers, in `currencyCode` |
| `currencyCode` | str | e.g. `USD` |
| `equity` | {min,max} | percent (e.g. 0.5) |
| `yearsExperience` | {min,max} | years |
| `mostlyOrFullyRemote` | bool | distributed/remote-culture companies |
| `highlyResponsiveToIncomingApplications` | bool | responsiveness toggle |
| `allowInternationalApplicants` | bool | visa/immigration toggle |
| `hideOffPlatformJobs` | bool | hide external-apply jobs |
| `includeJobsWithoutSalary` | bool | include jobs w/o listed salary |
| `sortBy` | str | `RECOMMENDED`, `LAST_POSTED` (most recent), `LAST_ACTIVE` |

CLI name→field: `--skills/--markets/--locations` (names) and
`--role-tags/--skill-tags/--market-tags/--location-tags/--remote-company-tags`
(ids); `--job-types --remote --keywords --exclude-keywords --company-sizes
--investment-stages --salary-min/--salary-max --currency
--equity-min/--equity-max --years-min/--years-max --mostly-remote
--responsive --visa --hide-external --include-no-salary --sort
recommended|recent|active`.

---

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `0 jobs` | filter too narrow, or inherited a narrow captured filter | default is already clean; loosen flags; don't use `--from-capture` unless intended |
| response is HTML / `captcha-delivery` / `datadome`, status `blocked` | signature/cookies expired, or DataDome challenge | **re-run Phase 1** (`record_api.py`, headed, one manual apply) |
| `needs_answers` | job has a **required** screening question | `wf_apply.py apply --job <id> --answer <qid>="…" --send` |
| `already` | already applied | skip, it's fine |
| capture missing templates | no manual apply/search recorded | redo Phase 1 and actually apply once / search once |
| headless gets CAPTCHA | DataDome blocks headless | capture must be **headed**; applying needs no browser at all |

---

## 8. Safety rules (for the agent)

- **Always** show the shortlist and get explicit confirmation before
  `--send` (real applications are irreversible).
- Keep `--max ≤ 5` and `--delay ≥ 30s`; never burst.
- Never run a browser **headless** against Wellfound.
- Treat `captures/` + `user_data/` as secrets; never commit or share them.
- If unsure whether the session is valid, do a dry-run first (it makes a
  read-only modal fetch and reports `blocked` if the session is dead).

---

## 9. Lessons learned (proven on a real run)

What actually worked vs. what got the session flagged, from a 178-job run:

- ✅ **Paced external API batches work.** 171 applications went out in one
  run (`wf_apply.py batch`, 14–28s apart, stop-on-block) with **zero
  DataDome blocks**. Read-only searches in the same range are fine too.
- ❌ **Do NOT rapidly drive a real browser.** Automating the filter UI with
  fast typing/clicking (to scrape role IDs) is what tripped DataDome — and
  once the browser session is flagged, even the HTTP API starts returning
  `403` + a captcha. The warning sign was `geo.captcha-delivery.com` bodies.
- ❌ **Never `pkill -f "Google Chrome"`** — it kills the user's personal
  Chrome too. Target the specific process (`--remote-debugging-port=NNNN`)
  or just the bot profile; clear `user_data/SingletonLock` instead of killing.
- 🔄 **Recovering from a flag:** open Wellfound once in the **bot profile**
  (headed), solve the CAPTCHA / sign in, close it; cookies flush to
  `user_data` and the API works again. Re-export cookies into the latest
  `captures/api-*/cookies.json`.
- 💬 **Vary the cover note per job.** Use `wf_apply.py batch --note-file
  note.txt` with `---`-separated variants; identical notes across hundreds
  of applies look like spam. See `note.example.txt`.
- 🎚️ **Roles are a fixed list (no autocomplete API).** Filter by **skills**
  (`--skills`) or **keywords** instead — those resolve via the invisible API
  and need no browser.
