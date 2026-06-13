# wellfound-bot

Human-like Wellfound automation in Python + Playwright. Log in once in a
real Chrome window, reuse that session forever, and **capture the full
click-flow + page HTML of each step** so you can hand it to AI agents.

It is built to *not* look like a bot: real mouse movement, hovers,
think-pauses, randomized timing, rate limits, and a dry-run default.

## ⚠️ Read this first — Wellfound uses DataDome

Wellfound runs **DataDome**, a serious commercial anti-bot. Testing showed:

- **Headless = instant CAPTCHA wall.** A headless browser hitting `/jobs`
  got served a DataDome CAPTCHA instead of the feed. Never run headless
  here.
- **A real, visible Chrome with your real profile is not flagged** — your
  manual login worked with no challenge, and attaching read-only to it
  keeps `navigator.webdriver` false.

So the **safest mode is capture-assist**: *you* drive your real Chrome,
and the tool only records. There is no automated navigation for DataDome
to catch. If you let the tool drive the browser (`run.py`), keep it
**headed**, slow, and small — and accept some residual risk.

## How it works

| File | Role |
|------|------|
| `capture_assist.py` | **Safest.** You browse your real Chrome; tool attaches read-only and records DOM + screenshot on each Enter. No automated clicks. |
| `login.py` | Open Chrome once, log in by hand; session saved into `user_data/`. Auto-detects login. |
| `run.py` | **Higher risk.** Drives the browser to walk jobs with human-like clicks. Headed + dry-run only. |
| `verify_session.py` | Headed read-only check that the saved session loads the feed. |
| `record_api.py` | Read-only API recorder: logs the GraphQL/XHR calls Wellfound fires while you browse, to reverse-engineer the apply API. |
| `wf_replay.py` | External replay client: re-sends a captured API request with a Chrome TLS/JA3 fingerprint + your cookies. **Highest risk**; dry-run default. |
| `wf_apply.py` | External auto-apply: `apply` one job or `batch` many; chains `JobApplicationModal` → `CreateJobApplication`, handling `startupId` + screening questions. **Highest risk**; dry-run default. |
| `wf_search.py` | External job search: replays `JobSearchResultsX` with filters + pagination, returns jobs (id, startupId, title, applied). Read-only. |
| `config.py` | Your search URL, batch size, delays, dry-run toggle. |
| `wellfound/human.py` | The "click properly" logic — motion, hovers, timing. |
| `wellfound/browser.py` | Persistent real-Chrome profile, minimal/coherent fingerprint. |
| `wellfound/capture.py` | Writes `captures/<run>/flow.jsonl` + per-step `.html` / `.png`. |

## Recommended: capture-assist (safe)

```bash
python capture_assist.py
```

A real Chrome window opens on your `user_data/` profile. Browse Wellfound
normally — search, open a job, open the apply modal. Whenever you want a
step recorded, switch to the terminal and press **Enter**; type **q** to
finish. Each capture saves the DOM + screenshot into
`captures/assist-<timestamp>/`, building the `flow.jsonl` trace you feed
to an agent. DataDome only ever sees your normal manual browsing.

## Reverse-engineering the API (read-only)

```bash
python record_api.py     # then browse + apply by hand, Ctrl-C to stop
```

This logs every GraphQL/XHR request + response Wellfound makes while *you*
use it, into `captures/api-<timestamp>/requests.jsonl` (plus a gitignored
`cookies.json`). It's the safe way to *see* the apply API.

**Don't replay it from a plain script.** Wellfound's DataDome also guards
the API and fingerprints the TLS handshake (JA3) and the `datadome`
cookie binding — a Python `requests` call with your cookies has a
non-Chrome TLS fingerprint and tends to get blocked *faster* than a
browser. If you want to act on the API, the safe path is to run `fetch()`
**inside the real Chrome** (correct TLS + live `datadome` cookie +
session), not an external client.

### External replay (`wf_replay.py`) — highest risk

If you choose the external route anyway, the least-bad version is to
replay Wellfound's *real* captured request (not a guess) with a Chrome
TLS fingerprint. Flow:

```bash
python record_api.py                       # capture: do ONE manual apply, Ctrl-C
python wf_replay.py list                   # find the apply request's index
python wf_replay.py replay --index 7       # DRY-RUN: prints what it would send
python wf_replay.py replay --index 7 \
    --set variables.jobId=12345 --send     # actually send (for a new job id)
```

`wf_replay.py` impersonates Chrome's JA3 (`curl_cffi`), loads your captured
cookies (incl. `datadome`), and replays the captured headers + body, with
`--set` to edit GraphQL variables. It defaults to dry-run; `--send` fires
it. If DataDome detects the external client it returns a CAPTCHA/`datadome`
body, which the script flags. **Keep volume tiny** — this is the easiest
mode to get an account flagged.

### External auto-apply (`wf_apply.py`)

Higher-level than raw replay: give it a job id and it does the two-step
flow itself.

```bash
python wf_apply.py jobs                          # job ids found in the capture
python wf_apply.py apply --job 4174674            # DRY-RUN: reads modal, prints the plan
python wf_apply.py apply --job 4174674 --note "Keen to contribute" --send
python wf_apply.py apply --job 4174674 --answer 263758="..." --send   # answer a screening Q
```

It fetches `JobApplicationModal` (read-only) to resolve `startupId` and any
screening questions, refuses to apply if a **required** question is
unanswered, then sends `CreateJobApplication`. Verified against Wellfound:
the external client gets an HTTP 200 application response (not a DataDome
block). Still the riskiest mode — apply to a few, slowly, and re-capture
when the signature ages out.

### Search + filters (`wf_search.py`) and the full pipeline

```bash
python wf_search.py                              # paginate the captured filter
python wf_search.py --max-pages 5 --exclude-applied --remote REMOTE_OPEN --salary-min 100000
python wf_search.py --role-tags 157714,103480 --location-tags 2203
```

Filters: `--job-types`, `--remote`, `--salary-min/--salary-max`,
`--role-tags`, `--location-tags`, `--page`, `--max-pages`. **Roles and
locations are tag IDs, not free text** — the simplest way to set them is to
apply your filters on wellfound.com while `record_api.py` records; the
capture then holds your exact filter and `wf_search` just paginates it.

Chain search → batch apply (capped + spaced; dry-run unless `--send`):

```bash
python wf_search.py --ids-only --exclude-applied | python wf_apply.py batch --max 5 --delay 45 --send
```

## Setup

```bash
cd wellfound-bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium      # one-time browser download
```

## 1. Log in (once)

```bash
python login.py
```

A real Chrome window opens. Log in however you normally do (email,
Google, magic link). When you see your dashboard, press Enter in the
terminal. Your session is saved to `user_data/`.

> The first login **must** be a visible window — you can't type a
> password into an invisible one. **Keep runs headed** for best stealth:
> headless Chrome leaks `HeadlessChrome` in its user-agent, which is easy
> to flag. `HEADLESS = True` exists in `config.py` but warns you for this
> reason.

## 2. Capture a run

Edit `config.py` first — at minimum paste your filtered `JOBS_URL`.
Leave `DRY_RUN = True` for now.

```bash
python run.py
```

It opens your job feed, walks up to `MAX_JOBS_PER_RUN` jobs, opens each
apply form with human-like clicks, and **stops before submitting**.
Everything is saved under `captures/<timestamp>/`.

## 3. Feed it to agents

Each run produces:

- `flow.jsonl` — one JSON row per step: `action`, `url`, `selector`,
  `title`, and the matching `screenshot` / `html` filenames.
- `NNN.html` — full DOM at that step (for finding/fixing selectors).
- `NNN.png` — screenshot at that step.

`flow.jsonl` is the structured trace to feed an agent — it describes the
exact sequence of actions and which selector produced each page, and the
HTML lets the agent reason about the next action or repair a selector.

## Actually applying

When the captures look right, set `DRY_RUN = False` in `config.py` (and
optionally a `DEFAULT_MESSAGE`). Now `run.py` clicks submit too. Keep
`MAX_JOBS_PER_RUN` small and run a few times a day rather than one huge
batch.

## Staying undetected

The disguise is **being a real Chrome, not a patched one.** The bot uses
your installed Chrome binary with a persistent profile, turns off the
automation flag (so `navigator.webdriver` is its natural `false`), and
otherwise leaves the fingerprint *untouched*. It deliberately does **not**
fake the user-agent, plugins, languages, or timezone — those would
disagree with Chrome's real User-Agent Client Hints and become their own
tell. Input is human-paced (curved continuous mouse motion, real press
durations, per-character typing, randomized think-time), and runs are
rate-limited and capped. Run headed for the cleanest fingerprint.

## Tests

- `python smoke_test.py` — checks the browser, masking, human helpers,
  and capture (no login needed).
- `python flow_test.py` — drives `run.py`'s real flow logic against local
  pages that mimic Wellfound's feed + apply modal (no login, no network).

## Notes & limits

- **Selectors are best-effort.** Wellfound's DOM changes; if a step
  reports "no Apply button found", open that step's `.html` to find the
  current selector and update the lists at the top of `run.py`.
- **Respect Wellfound's Terms of Service.** This is meant for automating
  *your own* applications from *your own* account. Don't scrape at scale
  or operate accounts that aren't yours.
- **`user_data/` holds your live login.** It's gitignored — never commit
  or share it.

## License

[MIT](LICENSE) © Apoorv Darshan
