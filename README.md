# Global Trade Intelligence

Interactive analytics over UN Comtrade merchandise trade data, published at
**https://analytics.mrzeynalli.xyz/trade**.

The application answers, for any reporting country: what it trades, with whom,
how much, how that has changed, what it depends on, how diversified it is, and
where it appears comparatively strong. It is a demonstration analytics product
built on public statistics, not a data redistribution service.

---

## 1. Architecture

```
UN Comtrade v1 API
        │  background worker only, rate limited and budgeted
        ▼
raw response cache            data/raw/**.json.zst        (Zstandard)
        │  Polars normalisation + validation
        ▼
analytical facts              data/parquet/**/part.parquet (Parquet + ZSTD)
        │  DuckDB scans, column and partition pruning
        ▼
FastAPI  ── in-process LRU ── ETag/304 ── gzip ──► browser
        ▲
React + TypeScript + Apache ECharts, served from the same origin under /trade
```

| Layer | Choice | Why |
| --- | --- | --- |
| Frontend | React 19, TypeScript, Vite, Apache ECharts 6 | Matches the existing GDELT project on this host; ECharts as specified |
| Backend | Python 3.13, FastAPI, uvicorn | Async HTTP with a small footprint |
| ETL | Polars | Fast columnar transforms without a database round trip |
| Query | DuckDB | Reads Parquet directly with predicate and column pruning |
| Analytical storage | Parquet, ZSTD level 9, dictionary encoding | Compact and directly queryable |
| Raw cache | Zstandard-compressed JSON | Reproducibility and rebuildability |
| Control plane | SQLite in WAL mode | Durable job queue, quota ledger, dataset versions |
| Serialisation | orjson | Fast JSON with the FastAPI ORJSONResponse |
| Process model | systemd units, Nginx reverse proxy | Consistent with the rest of this server; no Docker |

Docker is deliberately not used. The GDELT project on this host is
containerised, but this application needs a persistent data directory, a
long-running worker and a systemd timer, all of which the host already manages
natively for the other services here (`cibim-*`). Adding a container would add a
layer without removing one.

### Layout of concerns

```
SQLite   = state and control (jobs, quota, versions, raw-cache index)
Parquet  = analytical facts
DuckDB   = analytical query engine
Polars   = extract/transform
```

---

## 2. Directory layout

```
/root/analytics/trade/                 source repository
├── backend/
│   ├── trade_api/
│   │   ├── config.py         every tunable constant, environment-overridable
│   │   ├── logging_setup.py  structured JSON logging with secret redaction
│   │   ├── state.py          SQLite control plane (WAL)
│   │   ├── keys.py           canonical request hashing
│   │   ├── comtrade.py       API client: auth, rate limit, retries, quota
│   │   ├── refs.py           reporter/partner/HS dimension tables
│   │   ├── etl.py            normalisation, atomic Parquet IO, validation
│   │   ├── store.py          DuckDB read layer
│   │   ├── analytics.py      pure metric functions (HHI, RCA, CAGR, …)
│   │   ├── derive.py         precomputed concentration and growth tables
│   │   ├── insights.py       deterministic insight sentences
│   │   ├── ingest.py         request planning, batching, subdivision
│   │   ├── jobs.py           durable de-duplicated job queue
│   │   ├── worker.py         background ingestion loop
│   │   ├── cache.py          bounded in-process response cache
│   │   ├── api_common.py     validation, period selection, envelopes
│   │   ├── app.py            FastAPI application and static SPA serving
│   │   ├── cli.py            trade-admin
│   │   └── routers/          meta, country, drilldown, advanced, system
│   └── tests/                155 tests, no live API access
├── frontend/
│   └── src/                  React application (base path /trade)
│       └── tokens/           design-system tokens — see DESIGN.md (repo root)
├── deploy/
│   ├── install.sh            full deployment
│   ├── redeploy.sh           code-only refresh
│   ├── analytics-trade-*.service / *.timer
│   └── trade.location.conf   the Nginx include
└── backups/                  timestamped vhost backups

/opt/analytics-trade/                  deployed copy (root-owned, read-only to the service)
/etc/analytics-trade/trade.env         secrets, mode 600, owned by tradeapp
/var/lib/analytics-trade/              persistent data, owned by tradeapp
├── state/state.sqlite3
├── refs/{reporters,partners,hs,classifications}.parquet
├── raw/<aa>/<bb>/<sha256>.json.zst
├── parquet/
│   ├── totals/freq=A/reporter=031/part.parquet
│   ├── products_hs2/freq=A/reporter=031/part.parquet
│   ├── products_hs4/…
│   ├── partners/…
│   ├── product_partner/freq=A/reporter=031/hs=27/part.parquet
│   ├── partner_products/freq=A/reporter=031/partner=380/part.parquet
│   ├── global_hs2/year=2024/part.parquet
│   └── advanced/concentration/reporter=031/part.parquet
└── manifests/
```

### Why partitions stop at the reporter

The layout is `<dataset>/freq=<A|M>/reporter=<NNN>/part.parquet`, with `year` as
a sorted column rather than a directory. A per-year partition would make annual
totals two rows per file — the "millions of tiny files" failure mode. A single
reporter file is tens of kilobytes, matches the dominant access pattern (one
selected country), and DuckDB still prunes on `year` using row-group statistics.
`product_partner` and `partner_products` add one more level because they grow
per chapter and per partner.

### Why HS codes are strings

`hs_code` is a dictionary-encoded Parquet string, not an integer. Dictionary
encoding makes it as compact as an integer on disk, and it removes an entire
class of bug: HS chapter `01` must never become `1`.

---

## 3. Environment variables

Set in `/etc/analytics-trade/trade.env` (mode 600, owned by `tradeapp`).

| Variable | Default | Meaning |
| --- | --- | --- |
| `COMTRADE_API_KEY` | — | **Required.** Primary subscription key. Server-side only. |
| `COMTRADE_API_KEY_SECONDARY` | — | Fallback key |
| `TRADE_DATA_DIR` | `/var/lib/analytics-trade` | Persistent data root |
| `TRADE_HOST` / `TRADE_PORT` | `127.0.0.1` / `8092` | Bind address. Never bind publicly. |
| `TRADE_BASE_PATH` | `/trade` | Subpath the app is mounted at |
| `TRADE_STATIC_DIR` | repo `frontend/dist` | Built frontend location |
| `COMTRADE_DAILY_CALL_BUDGET` | `450` | Soft daily ceiling on remote calls |
| `COMTRADE_INTERACTIVE_RESERVE` | `50` | Reserved for user-triggered work |
| `COMTRADE_GLOBAL_BACKFILL_BUDGET` | `100` | Sub-budget for global backfill |
| `COMTRADE_MIN_REQUEST_INTERVAL_SECONDS` | `1.2` | Minimum spacing between calls |
| `COMTRADE_MAX_RECORDS` | `100000` | Truncation threshold (service hard limit) |
| `COMTRADE_MAX_PERIODS` | `12` | Periods per request (service hard limit) |
| `COMTRADE_MAX_RETRIES` | `4` | Retry ceiling for idempotent GETs |
| `TRADE_ANNUAL_HISTORY_START` | `2010` | First year of an annual pack |
| `TRADE_MONTHLY_HISTORY_MONTHS` | `36` | Length of a monthly pack |
| `TRADE_BOOTSTRAP_COUNTRIES` | ten demo countries | Prefetched on bootstrap |
| `TRADE_GROWTH_MIN_BASELINE` | `1000000` | Minimum base for a growth ranking |
| `TRADE_GROWTH_MIN_SHARE` | `0.0005` | …or this share of total trade |
| `TRADE_ANOMALY_MIN_MONTHS` | `24` | History required for anomaly detection |
| `TRADE_ANOMALY_Z_THRESHOLD` | `3.0` | Robust z-score cut-off |
| `TRADE_JOB_RATE_LIMIT_PER_HOUR` | `12` | Job creations per client IP per hour |
| `TRADE_LRU_CACHE_ENTRIES` / `_MAX_BYTES` | `256` / `64 MiB` | Response cache bounds |
| `USE_FIXTURE_DATA` | `false` | Serve fixtures instead of calling the API |

---

## 4. Comtrade API setup

1. Register at the UN Comtrade Developer Portal and subscribe to **comtrade — v1**.
2. Put the primary key in `/etc/analytics-trade/trade.env`:

   ```sh
   sudo install -o tradeapp -g tradeapp -m 600 /dev/null /etc/analytics-trade/trade.env
   sudo -u tradeapp tee /etc/analytics-trade/trade.env >/dev/null <<'EOF'
   COMTRADE_API_KEY=…
   TRADE_DATA_DIR=/var/lib/analytics-trade
   TRADE_STATIC_DIR=/opt/analytics-trade/frontend/dist
   EOF
   sudo systemctl restart analytics-trade-api analytics-trade-worker
   ```
3. The key is sent as the `Ocp-Apim-Subscription-Key` **header**, never as a
   query parameter, so it cannot appear in an intermediary's access log. Every
   string that reaches a log line, an error payload or an HTTP response passes
   through `config.redact()` first.

### Service behaviour verified against the live API

| Behaviour | Value |
| --- | --- |
| Maximum periods per request | 12 (rejected with an explicit error beyond that) |
| Maximum records per response | 100 000, **silently truncated** with no error flag |
| Omitting `reporterCode` | returns every reporter |
| Omitting `partnerCode` | returns every partner **and** the World aggregate |
| Rate limit response | HTTP 429, "Try again in N seconds" |
| `getDa` | per-dataset `datasetChecksum`, `firstReleased`, `lastReleased` |
| `getLiveUpdate` | the 50 most recent dataset publications |

Silent truncation is the dangerous one: a result at exactly 100 000 records is
treated as truncated and subdivided deterministically (periods → flows →
commodity codes → reporters), then recombined and de-duplicated locally.

---

## 5. Local development

```sh
cd /root/analytics/trade

# Backend
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt
TRADE_ENV_FILE=$PWD/.env .venv/bin/python -m uvicorn trade_api.app:app \
    --app-dir backend --reload --port 8092

# Frontend (proxies /trade/api to the backend above)
cd frontend && npm install && npm run dev     # http://localhost:5174/trade/
```

### Fixtures

Tests never touch the live API. Each test runs against a temporary data
directory with `respx`-mocked HTTP. For UI work without quota:

```sh
USE_FIXTURE_DATA=true TRADE_FIXTURE_DIR=backend/tests/fixtures ...
```

A fixture file is named after its canonical request key; print the key with:

```python
from trade_api.keys import canonical_key
canonical_key("/data/v1/get/C/A/HS", {"reporterCode": 31, "period": "2024"})
```

---

## 6. Data bootstrap and manual prefetch

```sh
trade-admin bootstrap-refs                    # reporters, partners, HS (no quota cost)
trade-admin refresh-imf                       # IMF ITG recent totals (no quota cost)
trade-admin refresh-eurostat                  # EU intra/extra split (no quota cost)
trade-admin bootstrap --monthly               # reference data + the ten demo countries
trade-admin cache-country AZE                 # annual pack, 2010 → latest
trade-admin cache-country AZE --monthly       # last 36 months
trade-admin cache-country DEU --from 2005     # a longer history
trade-admin cache-hs4 AZE                     # HS4 for every chapter at once
trade-admin cache-product AZE 27              # partner breakdown for one chapter
trade-admin cache-partner AZE ITA             # bilateral HS2 composition
trade-admin backfill-global-hs2 2024          # world HS2 matrix, one call per flow
trade-admin cache-country BRA --background    # queue it for the worker instead
```

### Sources

| Source | Covers | Lag | Cost |
| --- | --- | --- | --- |
| **UN Comtrade** | Everything with partner or product detail. The spine of the product. | 12–24 months for a reference year to fill in | Metered, `COMTRADE_DAILY_CALL_BUDGET` |
| **IMF ITG** | Headline goods exports/imports by country, annual and monthly. Totals only. | 2–3 months | Keyed but unmetered |
| **Eurostat** | Intra/extra-EU split and Broad Economic Category mix, monthly, for the 27 member states. Euro, not dollars. | ~6 weeks | Public, unauthenticated |
| **World Bank** | GDP, population, GDP per capita, for ratios. | annual | Public, unauthenticated |

The trade sources are **never summed**. A period is sourced from one of them,
whole, and the payload says which — adding a Comtrade reporter to an IMF country
would double-count wherever both published. `/world/overview` is entirely
Comtrade, `/world/recent` entirely IMF, `/world/europe` entirely Eurostat.

Eurostat reports in euro while everything else is US dollars, so no Eurostat
value is ever added to another source's. The interface leans on its **shares**,
which are currency-invariant, and labels the euro values that do appear.

Eurostat is also the only source here that can state the intra/extra-EU split:
Comtrade sees the Union as 27 reporters with bilateral partners, so
reconstructing it would mean summing 26 partners per country per period.

At the time of writing IMF ITG held 2025 for 173 countries against Comtrade's
98, and monthly figures through June 2026, which is why the landing page can
state a more recent reading than the year its own charts are drawn from.

### What a country costs

| Pack | Requests |
| --- | --- |
| Annual 2010–2025 (totals + all partners + HS2 composition) | **5** |
| Monthly, last 36 months | **7** |
| HS4 for every chapter, 12 years | **1** |
| Partner breakdown for one chapter, 12 years | **1** |
| Global HS2 matrix for one year, both flows | **2** |

One request returns twelve periods, every partner and the World aggregate
together, which is why a whole country costs single-digit calls rather than
hundreds.

---

## 7. Scheduled synchronisation

```
analytics-trade-sync.timer   03:40 daily  (+ up to 25m jitter)
analytics-trade-refs.timer   Sundays 04:20
analytics-trade-sources.timer 02:40 daily  (+ up to 25m jitter)  IMF + Eurostat
```

The nightly job is source-aware, not TTL-based:

1. Read `getLiveUpdate` for recently republished datasets.
2. Intersect that with the reporters held locally.
3. For anything still ambiguous, call `getDa` and compare `datasetChecksum`
   and `lastReleased` against `sync_state`.
4. Queue a refresh for **only** the affected reporter/period partitions.
5. The worker refetches those, rewrites the partitions atomically and
   recomputes dependent aggregates.

Historical years that have not been revised are never refetched. The cache is
never wiped and rebuilt.

---

## 8. Deployment

```sh
cd /root/analytics/trade/frontend && npm run build
cd /root/analytics/trade && sudo bash deploy/install.sh
```

`install.sh` is idempotent. It creates the `tradeapp` system account, copies the
code to `/opt/analytics-trade`, builds the virtualenv, sets permissions,
installs the systemd units, **backs up the Nginx vhost to `backups/`**, adds one
include line, runs `nginx -t`, starts the services, waits for the health
endpoint and only then reloads (not restarts) Nginx.

For a code-only change:

```sh
sudo bash deploy/redeploy.sh
```

### Nginx

The only change to `analytics.mrzeynalli.xyz` is a single include placed before
the existing catch-all `location /`:

```nginx
include snippets/trade.location.conf;
```

`/trade` is a longer prefix than `/`, so it wins the location match without any
reordering, and `/`, `/gdelt` and every other route are untouched. The snippet
denies `/trade/healthz` publicly and proxies the rest to `127.0.0.1:8092`.

HTTPS is unchanged: the existing Let's Encrypt certificate and TLS
configuration are reused, and all frontend traffic is same-origin HTTPS.

**Rollback:**

```sh
sudo cp /root/analytics/trade/backups/analytics.mrzeynalli.xyz.<stamp>.conf \
        /etc/nginx/sites-available/analytics.mrzeynalli.xyz
sudo nginx -t && sudo systemctl reload nginx
sudo systemctl disable --now analytics-trade-api analytics-trade-worker \
        analytics-trade-sync.timer analytics-trade-refs.timer
```

### systemd

| Unit | Role |
| --- | --- |
| `analytics-trade-api.service` | uvicorn, 2 workers, bound to 127.0.0.1:8092 |
| `analytics-trade-worker.service` | the only process that contacts Comtrade |
| `analytics-trade-sync.service` + `.timer` | nightly source-aware refresh |
| `analytics-trade-refs.service` + `.timer` | weekly reference metadata refresh |

All run as `tradeapp` with `ProtectSystem=strict`, `PrivateTmp`, an empty
capability bounding set, and `ReadWritePaths=/var/lib/analytics-trade` as the
only writable location. `Restart=on-failure` plus `WantedBy=multi-user.target`
means the application survives a reboot.

---

## 9. Operations

```sh
trade-admin status              # quota, worker, jobs, cached countries, disk
trade-admin jobs --limit 20     # recent jobs and their errors
trade-admin cache-size          # disk breakdown
trade-admin verify AZE          # reconciliation report for a country
trade-admin sync-updates        # run the nightly refresh now
trade-admin retry-failed-jobs
trade-admin compact             # rewrite Parquet partitions, deduplicated
trade-admin work-once           # process one queued job in the foreground
```

### Logs

```sh
journalctl -u analytics-trade-api    -f
journalctl -u analytics-trade-worker -f
journalctl -u analytics-trade-sync   --since today
journalctl -u analytics-trade-worker -o cat | jq 'select(.level=="ERROR")'
```

Log lines are JSON with request id, route, status, duration, cache state,
dataset version, job id, remote status, records fetched and retry count. The
subscription key cannot appear: every line passes through the redactor.

### Checking the API budget

```sh
trade-admin status | grep -i calls
```

The ledger is in SQLite:

```sh
sudo -u tradeapp sqlite3 /var/lib/analytics-trade/state/state.sqlite3 \
  "SELECT day, calls_made, backfill_calls FROM quota_ledger ORDER BY day DESC LIMIT 7;"
sudo -u tradeapp sqlite3 /var/lib/analytics-trade/state/state.sqlite3 \
  "SELECT ts_utc, request_type, reporter, periods, http_status, record_count, cache_status
   FROM api_calls ORDER BY id DESC LIMIT 20;"
```

### Clearing and rebuilding the cache

```sh
trade-admin clear-cache --dataset products_hs4 --yes     # one dataset
trade-admin clear-cache --reporter AZE --yes             # one country
trade-admin clear-cache --raw --yes                      # compressed API responses
trade-admin cache-country AZE                            # rebuild
```

Normalised analytical history is never deleted automatically, even when the raw
cache grows. Raw responses can always be dropped: they are a debugging and
rebuild convenience, and everything can be refetched.

### Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `/trade` returns 502 | `systemctl status analytics-trade-api`; check `journalctl -u analytics-trade-api -n 50` |
| "Frontend build not found" | `npm run build` in `frontend/`, then `deploy/redeploy.sh` |
| Country stuck on "Preparing…" | `trade-admin jobs`; if the worker is down, `systemctl start analytics-trade-worker` |
| Jobs failing with quota errors | budget spent for the day; they requeue automatically and run after midnight UTC |
| `COMTRADE_API_KEY is not configured` | the env file is missing or unreadable by `tradeapp` |
| Advanced tab shows "Not enough data" | the global HS2 matrix is not cached: `trade-admin backfill-global-hs2 <year>` |
| Disk growing | `trade-admin cache-size`, then `trade-admin compact` and `clear-cache --raw` |

---

## 10. Backup and restore

Back up what cannot be recreated:

```sh
sudo -u tradeapp sqlite3 /var/lib/analytics-trade/state/state.sqlite3 \
    ".backup /var/backups/trade-state-$(date +%F).sqlite3"
sudo tar czf /var/backups/trade-config-$(date +%F).tar.gz \
    /etc/analytics-trade /etc/nginx/snippets/trade.location.conf \
    /etc/systemd/system/analytics-trade-*
```

Priority order: source code, configuration, `state.sqlite3`, manifests. Parquet
is optional — it is rebuildable from Comtrade.

**The environment file contains the subscription key.** Keep it out of any
archive that leaves the host or enters version control. `.gitignore` already
excludes `.env`.

Restore: reinstall, put back `state.sqlite3` and the env file, then
`trade-admin bootstrap` to repopulate the analytical cache.

---

## 11. Tests

```sh
cd backend && ../.venv/bin/python -m pytest        # 155 tests
cd frontend && npx vitest run                      # 35 tests
cd frontend && npx tsc -b                          # type check
```

Coverage:

* **Client** — header authentication, key redaction in errors/logs/ledger, rate
  limiter spacing, retry on 429/5xx/timeout, no retry on 4xx, quota lanes and
  reserve, canonical key stability, silent-truncation detection, malformed JSON
  and unexpected schema.
* **Cache** — a cache hit makes zero remote calls, atomic writes leave no
  partial file, one prior raw version retained on change, job de-duplication.
* **Data** — HS leading zeros, missing values never becoming zero, filler
  weights becoming null, impossible months rejected, World rows kept out of the
  partner table, scoped replacement removing withdrawn records.
* **Analytics** — balance, shares, YoY, CAGR, HHI, effective number, dependency
  shares, RCA, world share, mirror discrepancy, complementarity, export
  similarity, unit value, robust z-scores.
* **API** — a full page visit makes zero Comtrade requests, ETag/304, the Other
  bucket equals the remainder, parameter validation, degraded sections.
* **Frontend** — country search by name and ISO code, URL state for frequency,
  tab, product and partner, drilldown open/close, preparing/error/empty/partial
  states, number formatting.

Known formula cases pinned by the suite:

```
HHI(0.5, 0.3, 0.2)        = 0.38
effective number          = 1 / 0.38 ≈ 2.6316
mirror X=120, M=100       → difference 20, relative 20/110 ≈ 18.18%
```

---

## 12. Adding a derived metric

1. **Write the formula** in `analytics.py` as a pure function returning `None`
   when the inputs cannot support it. No IO, no globals.
2. **Test it** in `tests/test_analytics.py`, including at least one case with
   missing or non-positive input.
3. **Get the inputs** from `store.py` — add a query there if the shape you need
   does not exist yet. Never scan Parquet from a router.
4. **Precompute** in `derive.py` only if it needs a full pass over history; call
   it from `worker.handle` after the relevant ingestion.
5. **Expose it** from the appropriate router, wrapped in `envelope(data, meta)`,
   with `apply_http_cache(...)` listing every dataset scope the result depends
   on so the ETag invalidates correctly.
6. **Add the type** to `frontend/src/types.ts` and render it. If the metric can
   be unavailable, render "Not enough data" — never a placeholder number.
7. **Document it** in `Methodology.tsx` with the formula and its limits.

---

## 13. Data semantics that the code enforces

* **No double counting.** `partner_code = 0` (World) is split into the `totals`
  dataset at ingestion time; the `partners` dataset can never contain it, and
  validation fails the write if it does.
* **Missing is not zero.** A period a country did not report is absent from the
  Parquet file, returns `null` from the API and draws a gap in the chart.
  Nothing is interpolated.
* **Partial periods are labelled.** Annual views default to the latest complete
  year; an incomplete period carries a "partial" badge.
* **Reconciliation is recorded, not enforced.** The sum of partners is compared
  with the reported World figure, and the sum of HS chapters with the reported
  total; differences are stored in `dataset_versions.coverage_json` and shown by
  `trade-admin verify`. Data is never rescaled to force agreement.
* **World denominators are labelled as reported coverage**, with the number of
  contributing reporters attached.
* **Mirror differences are not attributed.** The methodology page lists the
  benign explanations; the UI never implies misreporting.
* **HS revisions are not silently harmonised.** Codes are shown as reported for
  each period.

---

## 14. Source and attribution

Source: **UN Comtrade**. Values are trade value in current US dollars as
reported. Every country page footer shows the latest complete annual period,
the latest available monthly period and the local cache date, all read from the
cache rather than hard-coded.

Full methodology: <https://analytics.mrzeynalli.xyz/trade/methodology>
