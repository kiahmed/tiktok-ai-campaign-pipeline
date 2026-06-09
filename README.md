# TikTok Ad Creative Automation

Production-ready Python service that automates the **creative + ad** lifecycle
for products you sell online:

1. Generate a TikTok ad **script** (Gemini by default)
2. Generate a short vertical **video** (Pexo AI by default)
3. **Download** the video locally (`generated_videos/`)
4. **Upload** the video to TikTok
5. Create a **creative + ad inside an existing TikTok ad group**
6. **Monitor** ad performance hourly
7. **Auto-pause** underperforming ads

> The system **never creates campaigns or ad groups**. Campaigns and ad groups
> already exist and are supplied via configuration (`TIKTOK_CAMPAIGN_ID`,
> `TIKTOK_ADGROUP_ID`). This service only manages creatives and ads.

Every external service sits behind an interface, so **any provider can be
swapped by editing `.env` only** — no code changes.

| Concern        | Default      | Drop-in alternatives          |
|----------------|--------------|-------------------------------|
| Script         | **Gemini**   | OpenAI, Claude                |
| Video          | **Veo 3.1** (Gemini API) | Pexo, Creatify, Arcads, Kling     |
| Ad platform    | **TikTok**   | — (TikTok only)               |
| Database       | **SQLite**   | PostgreSQL (change one URL)   |

---

## Architecture

Clean architecture + dependency injection + SOLID. Business logic depends only
on **interfaces** (`ScriptGenerator`, `VideoGenerator`, `AdPlatform`); the DI
container ([`app/containers.py`](app/containers.py)) binds the concrete provider
chosen by configuration via [`app/factories.py`](app/factories.py).

```
app/
  config.py            # pydantic-settings (.env) — provider selection lives here
  containers.py        # dependency-injector wiring (settings -> repos -> providers -> services)
  factories.py         # config string -> concrete provider (the only place that knows the registry)
  main.py              # FastAPI app + lifespan (DB init + scheduler)
  cli.py               # run the pipeline once without the server

  core/
    interfaces/        # ScriptGenerator, VideoGenerator, AdPlatform  (abstractions)
    entities/          # ProductInput, ScriptResult, VideoResult, AdCreativeResult, PerformanceMetrics
    exceptions.py      # domain exception hierarchy
    retry.py           # shared tenacity retry policy

  providers/
    gemini/  openai/  claude/        # ScriptGenerator implementations
    pexo/  creatify/  arcads/  kling/ # VideoGenerator implementations (share base_video.py)
    tiktok/                           # AdPlatform implementation (TikTok only)

  services/
    creative_service.py    # orchestrates the full pipeline
    video_storage.py       # downloads videos to generated_videos/
    pause_rules.py         # pure auto-pause rule engine
    monitoring_service.py  # pulls metrics, stores history, pauses losers

  repositories/        # ProductRepository, ScriptRepository, VideoRepository, AdRepository, MetricRepository
  database/            # SQLAlchemy models + session/engine factory
  scheduler/           # APScheduler hourly monitoring job
  api/                 # FastAPI routes + pydantic schemas

generated_videos/      # downloaded MP4s  (product_slug_timestamp.mp4)
logs/                  # rotating log files
tests/                 # unit tests (pause rules)
```

### Why this is swappable

- The pipeline ([`CreativeService`](app/services/creative_service.py)) calls
  `script_generator.generate(...)`, `video_generator.generate(...)`,
  `ad_platform.upload_video(...)`, etc. It has **no import** of Gemini, Pexo or
  TikTok.
- Adding a provider = implement the interface + add one line to the relevant
  registry in [`factories.py`](app/factories.py).

---

## Quick start (local, SQLite)

Requires **Python 3.12** (the Docker image pins 3.12).

```bash
cp .env.example .env          # then fill in your API keys + TikTok IDs
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

uvicorn app.main:app --reload
```

Open the **dashboard** at <http://localhost:8000/dashboard> (or the root URL),
or the interactive API docs at <http://localhost:8000/docs>.

### Generate a creative + ad

```bash
curl -X POST http://localhost:8000/products/generate \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Rosemary Hair Growth Oil",
    "image_url": "https://example.com/product.jpg",
    "description": "A natural rosemary oil that supports hair growth.",
    "benefits": ["Reduce hair shedding", "Promote thicker hair", "Natural ingredients"]
  }'
```

Or without the server:

```bash
python -m app.cli \
  --name "Rosemary Hair Growth Oil" \
  --image https://example.com/product.jpg \
  --description "A natural rosemary oil that supports hair growth" \
  --benefit "Reduce hair shedding" --benefit "Promote thicker hair"
```

### Testing with a prepared script (skip Gemini) / video-only

Two request options let you test without the script provider and/or without
deploying to TikTok:

- **`script`** — supply a prepared script. The configured script provider
  (Gemini) is **skipped** and your text is used verbatim (stored with
  `provider="manual"`).
- **`deploy: false`** — stop after the video is generated and downloaded; **no
  TikTok upload and no ad** is created. Only Pexo (video) runs.

API — prepared script + video only (no Gemini, no TikTok):

```bash
curl -X POST http://localhost:8000/products/generate \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Pure Purc Hair Oil",
    "image_url": "https://officialpurepurc.com/cdn/shop/files/71UtauMZxdL._AC_UF1000_1000_QL80.jpg",
    "benefits": ["Reduce hair shedding", "Promote thicker hair", "Natural ingredients"],
    "script": "Tired of thinning hair? I was too. Pure Purc Hair Oil regrew mine in weeks. Tap to try it risk-free!",
    "deploy": false
  }'
```

CLI equivalent:

```bash
python -m app.cli \
  --name "Pure Purc Hair Oil" \
  --image "https://officialpurepurc.com/cdn/shop/files/71UtauMZxdL._AC_UF1000_1000_QL80.jpg" \
  --script "Tired of thinning hair? I was too. Pure Purc Hair Oil regrew mine in weeks. Tap to try it risk-free!" \
  --no-deploy
```

The response has `deployed: false` and the deploy-only fields (`ad_id`,
`creative_id`, `platform_video_id`) are `null`; `local_video_path` points at the
downloaded MP4 in `generated_videos/`. (You can also pass `--script-file PATH`
to read the script from a file.)

---

## Docker

```bash
cp .env.example .env          # fill in credentials
docker compose up --build
```

The container exposes port `8000` and persists `generated_videos/`, `logs/` and
`app.db` to the host via volumes. A `/health` healthcheck is built in.

---

## Dashboard

A built-in monitoring dashboard is served at the root:

```
http://localhost:8000/dashboard      (/, redirects here)
```

It's a single self-contained HTML page (no build step) that auto-refreshes every
minute, with three tabs:

- **Ads** — summary cards (total/active/paused/failed, spend, conversions, avg
  ROAS) and a per-ad table (spend, impressions, clicks, CTR, CPC, conversions,
  CPA, ROAS). Click an ad to expand an in-browser **video preview**, the TikTok
  ids, and a **metric-history chart**. **“Run monitoring now”** triggers a
  metrics + auto-pause pass on demand.
- **Jobs** — every agent-pipeline job with its status, chosen **angle/hook**,
  **QC verdict + failure codes**, attempt count, video link, and discard reason.
- **Strategy Brain** — per product, the **angle/hook performance ranking**
  (CTR×ROAS) the Strategist exploits, plus the "will avoid" chips (overused
  angles/hooks + recent rejection codes). This is the feedback loop made visible.

## API

### Agent pipeline (jobs)

Beyond the one-shot `/products/generate`, the system runs a **5-agent pipeline**
as a persisted state machine — submit a job and it flows through the agents,
with a Quality Review gate that can reject and loop back:

```
① Creative Strategist → ② Video Production → ③ Quality Review ─┬─ APPROVE → ④ TikTok Ad → LIVE
        ▲                                                       └─ REJECT → save reason → retry → DISCARD
        └────────────── ⑤ Performance + QC reasons feed the Knowledge store ──────────────┘
```

- **State machine** (`creative_jobs`): `DRAFT → SCRIPTED → VIDEO_READY → APPROVED|REJECTED → LIVE`,
  with `REJECTED → DRAFT` retries up to `JOB_MAX_ATTEMPTS`, then `DISCARDED`.
- **Creative Strategist** (Phase 2) reads the Knowledge store and picks an
  **angle + hook + audience segment** with an exploit/explore policy (favour
  angles with the best historical CTR×ROAS, sometimes explore unused ones,
  exclude overused), prompts the LLM, and returns structured
  `{hook_type, angle, audience_segment, script}`. A **novelty check** rejects
  duplicates and retries with stronger differentiation. Two pluggable backends
  ([`strategy/novelty.py`](app/services/strategy/novelty.py), set via
  `NOVELTY_METHOD`): **`lexical`** (3-gram word overlap — offline, zero-dep,
  default) or **`embedding`** (cosine over a **local** sentence-transformers
  model — catches *reworded* duplicates lexical misses; no API, runs offline;
  `pip install -r requirements-embeddings.txt`). In embedding mode each script's
  vector is **cached** in `scripts.embedding`, so history is embedded once and
  only the new candidate is embedded per run. Taxonomy lives in
  [`strategy/taxonomy.py`](app/services/strategy/taxonomy.py).
- **Quality Review** runs deterministic **rules** (≤50 words, CTA present, banned
  claims, 9:16 video present, duration, **file size ≤ limit, MP4/MOV format**, and
  optionally **1080×1920 / 30fps via ffprobe** when `VIDEO_CHECK_MEDIA=true`) then
  an **LLM judge** (Phase 3) for the
  qualitative call — hook strength, brand-voice fit, clear problem/solution/CTA,
  policy risk, length coherence. Their `failure_codes` are merged; if the LLM is
  unavailable it **degrades to rules-only** (never hard-fails). Every verdict is
  written to `qc_reviews`. Judge LLM = `QC_PROVIDER` (defaults to the script
  provider); toggle with `QC_LLM_ENABLED`.
- **Knowledge store** = past scripts (with angle/hook) + QC rejections +
  per-angle/hook CTR/ROAS; the Strategist reads it to prioritise winners and
  avoid repeating mistakes. Brand voice, audience segments, QC rules and tested
  **creative directives** load from [`config/profiles.json`](config/profiles.json)
  — the `creative` block (`narrator`, `format`, `music`, `notes`) steers both the
  script (e.g. male first-person transformation story) and the video render
  (presenter gender / background-music style passed to the video provider where
  its API supports them).
- **Ad agent keeps the original constraint** — posts the ad inside the existing
  campaign/ad group only; never creates campaigns or ad groups.

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"name":"Pure Purc Hair Oil","image_url":"https://example.com/p.jpg",
       "benefits":["Reduce shedding"],
       "prepared_script":"Tired of thinning hair? Pure Purc fixed mine. Tap to try it!"}'
```

> All four build phases are implemented: (1) the job state machine + agents,
> (2) the LLM Creative Strategist with angle/hook selection + novelty, (3) the
> LLM QC judge over the rules, and (4) the Performance feedback + Strategy Brain
> dashboard. Run several jobs against the same `product_id` and the Strategist
> measurably shifts toward higher-CTR/ROAS angles and away from overused ones.

## API

| Method | Path                      | Description                                            |
|--------|---------------------------|--------------------------------------------------------|
| POST   | `/jobs`                   | Create + run a job (`product_id` to reuse a product, or `name`+`image_url`) |
| GET    | `/jobs`                   | List all jobs and their state                          |
| GET    | `/jobs/{id}`              | Job detail incl. QC reviews                            |
| POST   | `/jobs/{id}/measure`      | Run the Performance agent once for a LIVE job          |
| GET    | `/api/jobs/overview`      | Jobs + strategy + latest QC (dashboard)                |
| GET    | `/api/strategy/insights`  | Per-product angle/hook performance + avoid list        |
| GET    | `/dashboard`              | Built-in monitoring dashboard (HTML)                   |
| GET    | `/api/overview`           | Aggregated JSON powering the dashboard                 |
| GET    | `/videos/{file}`          | Serves a downloaded video (preview/download)           |
| GET    | `/health`                 | Status + which providers are active                    |
| POST   | `/products/generate`      | Run the full pipeline for one product                  |
| POST   | `/monitoring/run`         | Trigger a monitoring pass now (same logic as scheduler)|
| GET    | `/ads`                    | List all ads and their status                          |
| GET    | `/ads/{id}/metrics`       | Metrics history for an ad                              |

---

## Monitoring & automatic pause rules

[`MonitoringScheduler`](app/scheduler/scheduler.py) runs hourly (configurable via
`MONITOR_INTERVAL_HOURS`). Each pass pulls **spend, impressions, clicks, CTR,
CPC, conversions, CPA, ROAS** for every active ad, stores a history snapshot in
`metrics`, and applies [`PauseRuleEngine`](app/services/pause_rules.py):

| Rule | Pause when                                            |
|------|-------------------------------------------------------|
| 1    | `spend > $50` **AND** `conversions == 0`              |
| 2    | `CTR < 0.5%`                                           |
| 3    | `ROAS < 1.0` (once the ad has conversions)            |

A spend floor (`PAUSE_MIN_SPEND_TO_EVALUATE`, default `$5`) gives new ads a fair
chance before any rule can fire. Paused ads are disabled on the platform and
**remain in the database** with a `pause_reason`. All thresholds are configurable
in `.env`.

---

## Switching providers (no code changes)

The **script** and **video** providers are swappable by editing `.env` only
(the ad platform is TikTok only):

```env
# Gemini -> OpenAI
SCRIPT_PROVIDER=openai
OPENAI_API_KEY=sk-...

# Pexo -> Kling
VIDEO_PROVIDER=kling
KLING_API_KEY=...
```

Restart the service. The DI container resolves the new providers automatically.

---

## Upgrading SQLite → PostgreSQL

1. `pip install -r requirements-postgres.txt`
2. Set in `.env`:
   ```env
   DATABASE_URL=postgresql+psycopg2://user:password@host:5432/tiktok_ads
   ```
3. (Docker) uncomment the `db` service and `depends_on` block in
   `docker-compose.yml`.

No code changes — the engine is built from `DATABASE_URL`.

---

## Reliability

- **Retries**: every external HTTP call uses a shared exponential-backoff retry
  policy ([`core/retry.py`](app/core/retry.py)) that retries only transient
  network/timeout errors.
- **Error handling**: low-level `requests` failures (DNS, connection refused,
  timeout, TLS, bad JSON) are translated at the provider boundary into the
  domain exception hierarchy ([`core/exceptions.py`](app/core/exceptions.py)) via
  [`translate_network_errors`](app/core/http.py), so business code never sees a
  raw transport error. Centralised handlers in [`main.py`](app/main.py) then map
  every error to a clean JSON response — **a vendor traceback never reaches the
  client**:

  | Exception | HTTP | Body |
  |-----------|------|------|
  | `ConfigurationError` | 400 | `{"error": "...", "detail": "..."}` |
  | `NotFoundError` | 404 | `{"error": "...", "detail": "..."}` |
  | `ProviderError` (Gemini/Pexo/TikTok failed) | 502 | `{"error": "...", "detail": "..."}` |
  | anything unexpected | 500 | `{"error": "InternalServerError", "detail": "..."}` (full trace logged server-side only) |

  A failed ad creation is additionally recorded with status `FAILED` rather than
  lost.
- **Logging**: structured logs to stdout (for containers) and a rotating file in
  `logs/`.
- **Scheduler safety**: the monitoring job is coalesced and limited to one
  concurrent instance; a job exception never kills the scheduler.

---

## Tests

```bash
pytest
```

Covers the pure pause-rule logic and derived-metric computation.

---

## Provider API notes

The script providers (Gemini/OpenAI/Claude) target the vendors' current REST
endpoints. The video providers (Pexo/Creatify/Arcads/Kling) follow the common
**submit-job → poll-status** pattern; endpoint paths and JSON field names are
declared as class constants/hooks in each provider and in
[`base_video.py`](app/providers/base_video.py), so if your specific plan uses
different field names you adjust **only those constants** — the interface
contract and all downstream business logic are unchanged.
```
