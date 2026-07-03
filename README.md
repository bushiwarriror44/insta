# Instagram Reels Auto-Publisher

Production-grade automation for publishing Reels across multiple Instagram
accounts with realistic anti-detection: per-account device fingerprints,
sticky residential/mobile proxies, true session reuse, behavior emulation
(warmup, human-like timing), randomized video uniquification via ffmpeg,
and a job scheduler with retries, dead-letter queue and Telegram alerts.

> **Disclaimer.** Automating Instagram is against the platform's Terms of
> Service. Use this only for accounts you own and explicitly understand the
> risks for. The authors take no responsibility for bans or legal
> consequences resulting from use.

## Features

- **One account = one device = one proxy = one session**, persistent across
  runs (stored on disk and in SQLite).
- **Correct session reuse** via instagrapi: cheap authed validation
  (`get_timeline_feed`) before any login attempt; full login only on
  `LoginRequired`.
- **Per-account Android fingerprint** drawn from a 30+ device pool, with
  locale/country/timezone aligned to the proxy geo. Hardware UUIDs are
  persisted forever; `client_session_id`/`pigeon_session_id` rotate every
  3–7 days to imitate app restarts.
- **Stealth Playwright first-login** for fresh accounts and hard
  challenges — UA + viewport derived from the device fingerprint, typing
  delays, mouse movement and cookie-banner dismissal.
- **Rich pre-publish warmup**: feed, stories, Direct inbox, news inbox,
  Explore page, `media_seen` before like, lognormal think-times.
- **Idle warmup loop** that exercises inactive accounts even on days
  without scheduled posts.
- **Post-publish settling** (`user_info_v1` + timeline) so a fresh
  upload is not the last thing the client does.
- **Auto 2FA / IMAP challenge solving** via `pyotp` (`totp_seed`) and
  optional IMAP polling (`email` + `email_password`).
- **Soft-block aware retries**: `FeedbackRequired` puts the account into
  `cooldown` for 24–48 h instead of hard-blocking, and retries clamp to
  the account's active hours.
- **ffmpeg-based video uniquifier**: random crop/zoom, color tweak, audio
  pitch+volume+atempo+EQ, resolution jitter, optional TikTok watermark
  crop, randomized CRF/keyframe interval, full metadata strip.
- **Caption tier system**: per-account `caption_profile` (nature /
  lifestyle / fitness / food / travel), localized bodies (EN/RU/DE/ES)
  and viral/medium/niche/longtail hashtag tiers.
- **Human-like schedule**: timezone-local active hours, prime-time
  weighted slots, daily caps, minimum gap between posts, per-day jitter,
  probabilistic off-days, cross-account spread to avoid bursts behind a
  shared proxy provider.
- **Proxy hygiene**: TLS reachability check against
  `i.instagram.com`, geo-IP verification (advertised vs actual country),
  10-minute health-check cache.
- **Persistent job queue** (SQLite): retries with exponential backoff and
  jitter, dead-letter on hard failures, daily statistics.
- **Telegram alerts** for challenges, blocks, proxy failures, repeated
  publish failures.

## Architecture

```
app/
  config.py              # pydantic-settings, .env
  logging_setup.py       # structlog + rotating file handler
  db/
    models.py            # SQLAlchemy: Account, Proxy, Device, PostJob, PostLog, DailyStat, Event
    session.py           # engine + SessionLocal + init_db
  accounts/
    device_factory.py    # per-account fingerprint generation/persistence
    session_manager.py   # build_client, login_or_resume, dump/load session
    challenge.py         # file-based challenge code handler
  proxies/
    pool.py              # health-check, upsert, masking
  video/
    uniquifier.py        # ffmpeg pipeline with randomized parameters
    caption_pool.py      # template renderer with emoji + hashtag rotation
  behavior/
    humanizer.py         # lognormal sleeps, coin flips
    warmup_instagrapi.py # pre-publish warmup via private API
    warmup_playwright.py # stealth browser first-login
  publisher/
    reels_publisher.py   # orchestrates login -> warmup -> upload
  scheduler/
    planner.py           # human-like slot generation
    worker.py            # poll DB, run jobs, retries, dead-letter
  alerts/
    telegram.py          # Telegram + Event persistence
  cli.py                 # Typer CLI
```

## Quick start (Windows / PowerShell)

```powershell
# 1. Install Python 3.11+ and ffmpeg (e.g. winget install Gyan.FFmpeg)
# 2. Create venv
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Install deps
pip install -r requirements.txt
playwright install chromium

# 4. Configure .env
Copy-Item .env.example .env
notepad .env  # set TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, etc.

# 5. Initialize database
python -m app.cli init-db

# 6. Register proxies — pick one approach:
#
# - Admin UI → Accounts → "Proxies" table (recommended): add/edit/delete proxies in the UI.
#
# - JSON import (bulk / repeatable):
python -m app.cli import-proxies examples/local-proxies.seed.json --skip-health-check

# - Single proxy via CLI:
python -m app.cli add-proxy --label res-de-1 `
    --url "http://login:pass@host:8000" `
    --country DE --timezone "Europe/Berlin"

# 7. Add an Instagram account, bound to that proxy
python -m app.cli add-account --username myaccount `
    --proxy res-de-1 --timezone "Europe/Berlin" `
    --daily-post-cap 3 --min-gap-hours 5

# 8. (Recommended) first-login via stealth browser
python -m app.cli first-login myaccount

# 9. Drop source videos into data/videos/source and plan a week
python -m app.cli plan-week --username myaccount --days 7

# 10. Start the worker (run as service in production)
python -m app.cli run-worker
```

## Docker quick start

**One command after `.env` exists** (worker + API + scheduler + UI):

```powershell
docker compose up -d --build
```

First-time setup:

```powershell
Copy-Item .env.example .env
notepad .env   # e.g. ADMIN_TOKEN, DATABASE_URL unchanged for local SQLite under ./data
docker compose up -d --build
```

On every start, `reels-worker` and `reels-api` run `init-db` automatically (safe to repeat).
To disable that, set `SKIP_AUTO_INIT_DB=1` in `.env`.

- Admin UI: [http://localhost:3000](http://localhost:3000)
- API docs: [http://localhost:8000/api/docs](http://localhost:8000/api/docs)

**CLI inside the stack** (no extra Compose profiles — use `exec` on the API container):

```powershell
# Optional before first stealth login in Docker — browsers go to volume playwright-browsers
docker compose exec reels-api python -m app.cli install-playwright

docker compose exec reels-api python -m app.cli import-proxies examples/local-proxies.seed.json --skip-health-check
docker compose exec reels-api python -m app.cli plan-week --username myaccount --days 7
docker compose exec reels-api python -m app.cli preflight
docker compose exec reels-api python -m app.cli status
docker compose exec reels-api python -m app.cli first-login myaccount
```

Operational:

```powershell
docker compose logs -f reels-worker
docker compose down
```

Notes:
- Runtime state lives in `./data` (bind-mounted); `.env` is mounted read-only.
- `docker compose exec reels-api python -m app.cli …` sees the same db/volumes as the worker.
- `reels-worker` has a Docker healthcheck (`python -m app.cli status`).
- Playwright browsers are installed on demand via `install-playwright` above (keeps `docker compose build` lighter).

**If `docker compose build` fails with `Unable to connect to deb.debian.org`:**

- Retry when the mirror is reachable; the Dockerfile uses **HTTPS mirrors** and APT **retries** to reduce flaky runs.
- On restrictive networks/VPN/firewall zones, temporarily use another outbound path (different VPN exit, tethering, DNS `8.8.8.8`, or disable IPv6 in Docker Desktop networking if IPv6 routing is broken).
- After changing `Dockerfile`, clear the failed cache once:  
  `docker builder prune -f`  
  then `docker compose build --no-cache`.

## Admin Web UI

A minimal but visually polished admin panel ships in `frontend/` (React 18 +
Vite + TypeScript + Tailwind 3). It talks to a small FastAPI backend in
`app/api/` that reuses all existing models / services — no business logic
duplication.

What it gives you:

- **Dashboard** — live stat-cards (active accounts, healthy proxies, queue,
  dead jobs) + recent events.
- **Accounts** — list/add accounts, attach proxy, pause/resume, see daily
  posts/failures.
- **Upload** — drag-and-drop a short `.mp4`/`.mov` into `data/videos/source/`
  and enqueue a job (immediately or scheduled, with optional caption).
- **Activity** — live job queue with filters (queued/running/done/dead/…),
  cancel button, plus the event log filtered by level.

Auth: simple Bearer token from `ADMIN_TOKEN` in `.env`. If left empty the
API runs in open mode (intended for `localhost`/VPN only).

### Run via Docker (recommended)

Use **`docker compose up -d --build`** as in [Docker quick start](#docker-quick-start).

`reels-frontend` is a static Nginx build that proxies `/api/*` to `reels-api`. All services share `./data/app.db`.

### Run in dev mode (hot reload)

```powershell
# Backend (hot-reload uvicorn)
python -m app.cli run-api --reload

# Frontend (Vite dev server, proxies /api -> http://localhost:8000)
cd frontend
npm install
npm run dev
# Open http://localhost:5173
```

### Frontend testing & lint

The admin SPA is fully covered by unit + integration tests on **Vitest** + **React Testing Library**, plus an **ESLint 9 (flat config)** linter. All checks run offline — `fetch` and the API client are mocked, no real backend is required.

```powershell
cd frontend
npm install        # one-time

# Lint
npm run lint            # eslint . — must pass with 0 errors
npm run lint:fix        # auto-fix where possible

# Tests
npm run test            # vitest run, single shot
npm run test:watch      # interactive watch mode
npm run test:coverage   # v8 coverage report under coverage/
```

What is covered (16 test files, 105 cases):

- `api/client.ts` — URL building, query encoding, Bearer header injection, JSON vs FormData bodies, 204 handling, error parsing (JSON detail / text fallback / generic), every method maps to the right endpoint.
- `context/AuthContext` — open mode, stored-token bootstrap, 401-cleanup, login/logout flows.
- `context/ToastContext` — push, auto-dismiss, manual close, multiple toasts.
- All shared components: `StatusBadge`, `StatCard`, `Card`, `Modal` (Escape / backdrop / X / inside-click), `DropZone` (input / drag&drop / disabled), `Loader`, `Layout` (sidebar nav, conditional Logout, open-mode hint).
- All five pages with mocked `api`: `Login`, `Dashboard` (cards, polling), `Accounts` (tables, modals, pause/resume, proxy add + check), `Upload` (file upload, schedule + ASAP enqueue, remove with confirm), `Activity` (job/event tables, status filter, cancel).
- `App.tsx` routing across `loading` / `needs-login` / `open` states.

Coverage on commit: **96.5% lines / 82% branches** across `src/`. Production build (`npm run build`) is also verified after changes.

### Programmatic API

All UI actions hit:

| Method | Path                                     | Purpose                              |
|-------:|------------------------------------------|--------------------------------------|
| GET    | `/api/health`                            | Liveness + auth-required flag        |
| GET    | `/api/dashboard`                         | Aggregated summary for stat-cards    |
| GET    | `/api/accounts`                          | List accounts + today's stats        |
| POST   | `/api/accounts`                          | Create / update account              |
| POST   | `/api/accounts/{username}/pause`         | Pause scheduling                     |
| POST   | `/api/accounts/{username}/resume`        | Resume                               |
| GET    | `/api/proxies`                           | List proxies                         |
| POST   | `/api/proxies`                           | Add proxy (with optional health-chk) |
| POST   | `/api/proxies/{label}/check`             | Force health-check                   |
| GET    | `/api/videos`                            | List uploaded source videos          |
| POST   | `/api/videos`                            | Upload a video (multipart)           |
| DELETE | `/api/videos/{filename}`                 | Remove a source video                |
| GET    | `/api/jobs?status=&username=&limit=`     | List jobs                            |
| POST   | `/api/jobs`                              | Enqueue a job                        |
| POST   | `/api/jobs/{id}/cancel`                  | Cancel queued/failed job             |
| GET    | `/api/events?level=&kind=&username=`     | Tail event log                       |

All endpoints except `/api/health` require `Authorization: Bearer <ADMIN_TOKEN>`
unless `ADMIN_TOKEN` is empty.

## Operational commands

```powershell
python -m app.cli list-accounts         # all accounts and bindings
python -m app.cli status                # today's posts, queue head, dead jobs
python -m app.cli pause-account NAME    # stop scheduling
python -m app.cli resume-account NAME
python -m app.cli rotate-proxy NAME LABEL
python -m app.cli enqueue-post --username NAME --video path\to\clip.mp4
```

When a challenge code is requested (Telegram alert), drop the code into
`data/challenges/<username>.code` (one line, no extra whitespace) or use:

```powershell
python -m app.cli provide-code myaccount 123456
```

The waiting worker picks it up within a few seconds.

## Anti-detection notes

The system layers protection across device, network, behavior and content
so that no single signal looks automated. Concrete pieces:

- **Per-account device fingerprint** — drawn from a 30+ pool of recent
  Android handsets (Pixel 8/8 Pro, Samsung S24/S24U, Xiaomi 14, OnePlus
  12, Nothing Phone 2 …) and Instagram app versions. UUIDs persist
  forever, except `client_session_id` / `pigeon_session_id`, which are
  rotated every **3–7 days per account** to imitate app restarts. Refresh
  the version pool whenever you have fresh data:
  `python -m app.cli refresh-app-versions data/app_versions.json`.
- **Stealth Playwright first-login** — the user-agent, viewport and
  locale are derived from the bound device fingerprint instead of being
  hardcoded. Inputs are typed character-by-character with random delays;
  the mouse is moved/clicked before each focus; cookie banners are
  dismissed automatically. Run headful with `PLAYWRIGHT_HEADLESS=false`
  in `.env` while debugging hard challenges.
- **Session reuse** — `instagrapi` is validated cheaply via
  `get_timeline_feed`; full `login()` runs only on `LoginRequired`. With
  `totp_seed` configured, the 6-digit code is generated locally with
  `pyotp` and injected automatically; with `email` + `email_password`
  set, IMAP polling can fetch a security-code email on its own.
- **Rich behavioral catalog** — pre-publish warmup browses feed,
  stories, Direct inbox, news inbox, Explore page, calls `media_seen`
  before any like, and emits randomized think-times. After a successful
  upload, a **post-publish settling** routine pulls `user_info_v1` and
  the timeline again to dilute the "login → upload → vanish" pattern.
- **Idle warmup loop** — even on days without scheduled posts the worker
  picks an inactive account every few hours and runs a publishless
  warmup, keeping behavioral baselines warm.
- **Captions tuned per topic** — every account can carry a
  `caption_profile` (`nature` / `lifestyle` / `fitness` / `food` /
  `travel`). Hashtags are mixed across **viral / medium / niche /
  longtail** tiers; bodies are localized (EN / RU / DE / ES) based on
  the account timezone.
- **Video uniquification** — randomized crop/zoom, color, audio pitch +
  volume + atempo, plus a single-band parametric **EQ shift**, a small
  **resolution jitter** (≈±0.5%) on top of the canonical 1080×1920
  output, full metadata strip, and an opt-in **TikTok watermark crop**
  on the upper-right corner. Mirror flip stays at ~5%.
- **Soft-block aware retries** — `FeedbackRequired` and "action blocked"
  errors no longer hard-block the account. Instead the account enters
  `cooldown` for a randomized **24–48 h**; the worker skips
  cooldown-bound accounts in `_claim_due_job` and the UI surfaces the
  status badge plus a "Cooldown till …" column. Regular retry backoffs
  also clamp to the account's **active hours**, so nothing wakes up at
  03:00 local time.
- **Scheduling** — slots inside the active window are **weighted toward
  prime time** (around lunch and 19–21 h, with weekend variations).
  Each account has a probabilistic ~8% **off-day** so it doesn't post
  every single day, and per-pool **cross-account spread** keeps two
  accounts behind the same proxy provider from publishing within ±2
  minutes of each other.
- **Proxy hygiene** — health-check now hits
  `https://i.instagram.com/api/v1/zr/dual_tokens/` (TLS-level proof that
  Instagram itself is reachable through the proxy) and runs a geo-IP
  verification (advertised vs actual country); a 10-minute cache
  prevents re-pinging on every job. The actual country is shown in the
  Proxies table and highlighted when it doesn't match the advertised
  one.

### Operational checklist (before going live)

Anti-detection is a stack — every layer matters. For each new account
work through the list:

1. **Proxy** — sticky residential / mobile, country/timezone matching the
   persona. Add it via the UI or `add-proxy`, hit "Check" once and
   verify both `is_healthy` and a sane `Geo (actual)` column.
2. **Account age** — prefer accounts ≥ 30 days old. Brand-new accounts
   should sit in `paused` for a few days; let the **idle warmup**
   exercise them and run `first-login myaccount` once a day.
3. **Caps** — keep `daily_post_cap ≤ 3` and `min_gap_hours ≥ 4` for
   accounts younger than 30 days; never raise above 4–5 even for
   warm accounts.
4. **Active hours** — set them to a realistic local-time window (e.g.
   `10`–`22`); retries and idle warmups stay inside it.
5. **Caption profile** — pick a `caption_profile` per account so
   captions and hashtag tiers feel topical, not generic.
6. **2FA / email** — fill in `totp_seed` (Base32) and, optionally,
   `email` + `email_password` so checkpoints can be solved without a
   human in the loop. The Accounts table tags accounts that have a
   TOTP seed configured.
7. **Source videos** — keep them reasonably varied. Even with strong
   uniquification, posting the same clip 50× across accounts is
   detectable via motion fingerprints.
8. **First login** — run `python -m app.cli first-login <username>` once
   per account; let Playwright finish the cookie banner and any pre-feed
   prompts. Re-run after `rotate-proxy`.
9. **Process model** — never share a Python process between accounts; if
   you need parallelism, run multiple `reels-worker` processes and
   spread accounts across separate proxy pools.

### Risk profiles and rollout

- Accounts are treated with conservative envelopes:
  - `new` (age < 30 days): stricter cap/gap and more off-days.
  - `warm`: normal production cadence.
  - `risky` (recent challenge/cooldown): stricter retries and quarantine bias.
- Worker can move accounts to a **quarantine** path on repeated soft
  auth/challenge signals (`risk.quarantine` event), requiring manual
  review before normal cadence is resumed.
- Recommended rollout for new safeguards:
  1. **shadow mode** (monitor events only),
  2. **canary** on 1-2 accounts,
  3. gradual pool-wide enablement after stable metrics for 7+ days.

If an account is moved to `cooldown` automatically after a soft block,
*do not* manually flip it back to `active`. Wait out the cooldown — the
worker will resume scheduling the next morning.

## What this replaces

The original prototype (single-file `main_pipeline.py` + helpers) had
these critical issues:

1. Hardcoded credentials and a literal `http://login:pass@ip:port` proxy.
2. `client.login()` invoked unconditionally after `load_settings`, forcing
   a full re-auth handshake every run.
3. No device fingerprint -> all clients looked identical to Instagram.
4. No challenge handler.
5. Deterministic, easily-detected video "uniquification" (only end trim).
6. Same caption across accounts.
7. No persistence, retries, alerts, or scheduling.

All addressed in this refactor.
