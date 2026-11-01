# Local trading website — M0 contract

**Current status — November 1:** core read pages and Learning exist; Prompt 10
exercised their material persisted synthetic failure paths in an isolated fixture.
See [security_readiness_review.md](security_readiness_review.md). Normal startup
is blocked by migration/schema incompatibility. Full M5 pages, stream cursor/
reconnect, exports, complete consistent bootstrap and owner controls remain
unimplemented/unverified. The M0 contract below describes requirements, not an
acceptance certificate. Browser reads do not authorize broker or model work.

**Governing specs:** [Local Trading Website Spec](Local_Trading_Website_Spec.md)
and build plan section 18.

## 1. Delivery model (preserved)

- FastAPI backend extended with server-rendered templates, minimal browser
  JavaScript, and locally bundled styles/fonts/chart assets (plan section 18).
  No build-time CDN dependency; the fixture demo makes zero runtime requests
  to CDNs, third-party widgets, analytics, external fonts, Robinhood, or
  cloud inference.
- Proposed local address `http://127.0.0.1:8000/`, configurable via
  `app.web_host` / `app.web_port` (already validated loopback-only in M0
  config). The port must not conflict with LM Studio (1234). The actual
  address is recorded in startup output and the README.
- Binds to loopback by default. Public hosting, tunnels, router changes, and
  LAN/remote access are out of scope.
- The application and website run independently of an open Codex session.

## 2. Local startup and authentication

- One documented command starts the site (M1): `uv run trading-agent serve`
  (command name final in M1) — starts the app bound to the configured
  loopback address and prints the actual URL.
- Owner bootstrap: first run generates an owner password/token stored in a
  protected local file (gitignored); a shared default password is never
  shipped, and bootstrap secrets never enter source control.
- All routes — pages, read APIs, event streams, exports — require an
  authenticated owner session. Sessions use HttpOnly, SameSite=Strict cookies
  with security flags appropriate to the actual local scheme.
- Host/Origin are validated on every request; cross-origin access is
  restricted. Command routes (added with M5's mode-permitted controls)
  require CSRF protection. UI visibility or disabled buttons are never the
  authorization mechanism.
- The browser talks only to the application. Robinhood MCP authentication,
  account filtering, data ingestion, and LM Studio requests stay in their
  backend processes. No broker token, raw account number, privileged executor
  endpoint, or unrestricted database access ever reaches the browser.

## 3. Scoping: account / mode / run

Every read response, stream, detail link, and export is scoped by:

- **account alias** (owner-controlled; never a raw account number),
- **mode** (SIMULATION | PAPER | SHADOW | authorized later live mode —
  rendered as a persistent label on every page),
- **run id** (a labeled application run; fixture demo runs are clearly
  synthetic),
- **strategy version** where applicable.

Scope is enforced server-side on every route; changing filters cannot mix
simulated and live results or blend modes. Display uses canonical UTC storage
plus the configured owner timezone (America/Chicago default) with exchange
time (America/New_York) where useful; date filters convert unambiguously to
UTC and record the effective interval.

## 4. Read-model and event contracts

Authoritative values are computed by backend ledger/performance services
(Decimal/integer). Exact amounts serialize as decimal strings or scaled
integers; browser chart coordinates are display approximations only.

**Read response envelope (all scoped reads):**

| Field | Meaning |
| --- | --- |
| `scope` | account alias, mode, run id, strategy version |
| `as_of` / `watermark` | snapshot timestamp / committed event watermark |
| `provenance` | source ids, data source, ingestion identity |
| `quality_flags` | stale / missing / unreconciled / corrected / unavailable |
| `pagination` | bounded page size + opaque validated cursor |
| `payload` | typed records with amounts as decimal strings |

**Activity/outbox event (persisted, plan section 16):** stable event
id/cursor, origin (strategy/manual/external/broker/system), mode/run/account
scope, event and observed timestamps, correlation references linking decision
→ risk → approval → intent → attempts → order → fills → ledger → outcome,
sanitized payload, and correction linkage. Consequential state and its outbox
event commit atomically; projections rebuild idempotently.

**Updates:** authenticated server-sent events with bounded sanitized
notifications; bootstrap from a consistent snapshot, resume by cursor,
deduplicate reconnects, detect gaps, and explicitly resynchronize on an
expired cursor. Bounded read-API polling (initially 5 s) is the fallback. UI
refresh reads local state only — it never increases broker polling or invokes
model inference. Stream heartbeat, last data observation, quote age, and last
successful reconciliation remain separate timestamps. Proposed local targets
(2 s p95 committed→visible; <3 s initial overview at 10 k events / 1 k
orders) are targets to be measured, not claims (plan section 18).

## 5. Route map (planned)

Page routes (server-rendered) and their scoped read APIs:

| Page | Route | Backing read APIs |
| --- | --- | --- |
| Overview | `/` | `/api/v1/overview`, `/api/v1/equity-curve`, `/api/v1/health` |
| Activity | `/activity` | `/api/v1/activity` (cursor pagination) |
| Orders and fills | `/orders`, `/orders/{id}` | `/api/v1/orders`, `/api/v1/orders/{id}`, `/api/v1/fills` |
| Portfolio and instruments | `/portfolio`, `/portfolio/{instrument}` | `/api/v1/positions`, `/api/v1/instruments/{id}`, `/api/v1/prices/{id}`, `/api/v1/cash-ledger` |
| Performance | `/performance` | `/api/v1/performance` |
| Research and decisions | `/research`, `/research/{decision}` | `/api/v1/decisions`, `/api/v1/decisions/{id}`, `/api/v1/research-runs` |
| Risk and approvals | `/risk` | `/api/v1/risk`, `/api/v1/authorizations` |
| Learning | `/learning` | `/api/v1/experiments`, `/api/v1/promotions` |
| Operations | `/operations` | `/api/v1/health`, `/api/v1/incidents`, `/api/v1/jobs` |
| Reports and preferences | `/reports` | `/api/v1/exports/{scope}` (CSV/JSON) |
| Auth | `/auth/login`, `/auth/logout` | — |
| Live updates | (per page) | `/api/v1/stream` (SSE, authenticated) |

Internal resources (summary, activity, decisions, orders, fills, positions,
timeseries, performance, risk, research, experiments, health, exports) are
application designs, not claims about Robinhood tool names.

## 6. Page-to-backend dependency map

| Page | Depends on (module) |
| --- | --- |
| Overview | ledger, portfolio marks, positions, reconciliation, risk state, health |
| Activity | activity_events/outbox, incident store, job log, reconciliation |
| Orders and fills | order intents, submission attempts, broker orders, fills, reservations, reconciliation |
| Portfolio and instruments | cash ledger, positions/lots, corporate actions, price history, decision/order/fill markers |
| Performance | performance service (backend-authoritative), benchmarks, cost model, labels |
| Research and decisions | research runs, evidence, model/prompt/strategy versions, matured outcomes |
| Risk and approvals | risk engine state, authorizations, readiness gates |
| Learning | experiment registry, champions/challengers, promotions/rollback |
| Operations | watchdog health, gateway/model/data/job status, alerts, diagnostics |
| Reports and preferences | exports service, stored preferences, configuration summaries |

## 7. Backlog

**M1 (Prompt 2) — core simulation pages:** Overview, Activity, Orders/fills
with full order detail, Portfolio/instrument detail; basic equity/price charts
with time-aligned decision/order/fill markers; owner authentication; loopback
startup; scoped read APIs backed by the persisted fixture ledger; locally
bundled assets; truthful SIMULATION labels and empty/stale states; zero
broker mutations and zero model calls from any read interaction.

**M2–M4 (Prompts 4–7):** persist research/model, evaluation, and sanitized
gateway data; incremental views where implemented with honest
unavailable/pending labels.

**M5 (Prompt 8) — full website:** all remaining pages, live local updates
(SSE) with reconnect/dedup/resync, full filtering, detailed charts/timelines,
scoped exports with CSV formula protection, responsive/keyboard-accessible
states, incident/recovery views, and mode-permitted paper controls (distinct,
capability-gated command routes).

**M6–M7 (Prompts 11–12):** owner pilot-authorization review screen (plan
section 24; USD 1,000 ceiling prefilled as an inactive draft), disabled
readiness controls, unmet prerequisites always visible; activation remains
impossible under LIVE_NOT_AUTHORIZED.
