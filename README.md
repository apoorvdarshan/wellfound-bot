# wellfound-bot

Human-like Wellfound automation in Python + Playwright. Log in once in a
real Chrome window, reuse that session forever, and **capture the full
click-flow + page HTML of each step** so you can hand it to AI agents.

It is built to *not* look like a bot: real mouse movement, hovers,
think-pauses, randomized timing, rate limits, and a dry-run default.

## How it works

| File | Role |
|------|------|
| `login.py` | Open Chrome once, log in by hand, save the session into `user_data/`. |
| `run.py` | Reuse that session, walk jobs with human-like clicks, capture every step. |
| `config.py` | Your search URL, batch size, delays, dry-run toggle. |
| `wellfound/human.py` | The "click properly" logic — motion, hovers, timing. |
| `wellfound/browser.py` | Persistent Chrome profile + anti-fingerprint setup. |
| `wellfound/capture.py` | Writes `captures/<run>/flow.jsonl` + per-step `.html` / `.png`. |

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
