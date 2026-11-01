# Architecture — current boundary and historical M0 foundation

**Status:** M0 (Prompt 1) complete, 2026-10-31.
**Governing spec:** [Robinhood Local AI Trading Build Plan](Robinhood_Local_AI_Trading_Build_Plan.md) (sections 5–7, 14, 16–18, 22).
**Financial authority:** LIVE_NOT_AUTHORIZED. Approved live capital: USD 0.

This document describes the M0 foundation: trust planes, module map, the
typed configuration system, the broker interface, the live-activation gate,
and the persistence strategy. The website contract is specified in
[website.md](website.md). Facts, assumptions, and pending verifications are
kept separate in [capability_matrix.md](capability_matrix.md); rationale for
each choice is in [decision_log.md](decision_log.md).

## November 1 security review boundary

Read [the Prompt 10 matrix](security_readiness_review.md) for current observed
behavior. M0 details below are historical. Coding/research/owner/execution/
monitoring are logical planes; separate OS identities, privileged secret
injection and independent monitoring have **not** been deployed. Python imports
under one owner are not a security sandbox. Research has no financial activation
method, browser APIs read persisted scoped state, and live dispatch always
rejects even with hypothetical healthy runtime/authorization. Real broker/OAuth
paths remain quarantined. The owner website session authorizes reads only.

A read-only repeatable-read database transaction protects each core API response;
it does not supply a multi-request stream snapshot handshake. DB outage denies
session access and displays unavailable data. A pause/stop in this disconnected
application cannot guarantee cancellation or liquidation at a broker. Runtime
and account monitoring/secret separation require independent owner validation.
Overall readiness is FAIL; do not infer a safe deployed system from module names.

## M6 mock control boundary — November 1

The [M6 report](supervised_readiness.md) documents immutable scope/consent,
transactional reservations, durable attempts, final executor revalidation and
monotonic generation fencing. A child-process demonstration accepts only a
bounded typed MOCK script and the exact offline FakeTransport. The website reads
persisted mock scope and cannot issue approvals/activation; its command routes
always deny. The fixture signer is public test material, not an owner identity
service. Real dispatch, credential injection, separate deployed OS privileges,
monitoring and broker authorization remain unavailable. An unsigned owner
worksheet cannot activate anything. The prior schema/readiness failures remain.

## 1. Product shape and trust planes

One owner, one local installation, one dedicated trading account. The system
uses LM Studio for local research inference and will eventually reach
Robinhood through the official external-agent MCP interface
(https://agent.robinhood.com/mcp/trading). Profitability is an unproven
research hypothesis; the plan's operational success and investment success
criteria remain separate (plan section 3).

Trust planes (plan section 5) and their M0 status:

| Plane | Role | M0 status |
| --- | --- | --- |
| Development | Codex edits source, runs tests, docs | Active (this repository) |
| Research | Bounded evidence retrieval, experiments | Not started (M2) |
| Execution | Typed authorized requests only; broker writes | Interface only; adapters reject (M1/M4) |
| Control | Owner-authenticated mode/capital/policy | Config contract validated (full UI M5) |
| Monitoring | Health, reconciliation age, incidents | Not started (M5) |

The unattended trading application will run independently of any Codex
session. The development environment contains no live broker credentials, no
privileged executor socket, and no model-triggered authority (plan section 5;
AGENTS.md).

## 2. Module map

Layout follows plan section 7. M0 ships the shaded set; the rest are planned
by milestone.

| Module | Milestone | Contents |
| --- | --- | --- |
| `config/` | **M0 (done)** | Typed models (Pydantic v2), YAML + environment loading, fail-closed rules |
| `contracts/` | **M0 (done)** | Broker capabilities, minimal order request/result, order status enum, error taxonomy |
| `execution/` | **M0 (done, placeholder)** | `BrokerAdapter` ABC, simulator placeholder, explicitly unavailable Robinhood stub, factory |
| `gates/` | **M0 (done)** | Deterministic live-activation gate |
| `cli/` | **M0 (done)** | `check-config`, `capabilities`, `version` |
| `money.py` | **M0 (done)** | Decimal parse/format helpers |
| `ingestion/`, `data/` | M3 | Source registry, point-in-time store, manifests |
| `llm/` | M2 | LM Studio provider, capability probe, structured output |
| `research/`, `features/`, `strategies/` | M1/M3 | Deterministic strategy, baselines, evaluation |
| `portfolio/`, `risk/` | M1 | Risk engine, reservations, P&L |
| `execution/` (full) | M1/M4 | Order state machine, fills, reconciliation, real gateway |
| `learning/` | M8 | Champion/challenger, promotion gate |
| `jobs/`, `audit/`, `monitoring/` | M1/M5 | Durable jobs, outbox, watchdog |
| `api/`, `web/` | M1/M5 | FastAPI app, read models, templates, scoped read API |
| `migrations/` | M1 | SQLAlchemy/Alembic schema for the plan section 16 entities |

Deliberately absent from M0 (plan section 6): Kubernetes, Kafka, agent
frameworks, vector databases. Complexity enters only when a measured
requirement justifies it.

## 3. Configuration system

- Source of truth: `config/simulation.yaml` (committed) and, for the future
  live stage, `config/live.template.yaml` (all live fields inert on purpose).
  Environment overlays use exactly the plan section 9 variable names
  (`TRADING_MODE`, `LIVE_TRADING_ENABLED`, `LLM_PROVIDER`,
  `LM_STUDIO_BASE_URL`, `LM_STUDIO_MODEL_ID`, `LM_STUDIO_API_TOKEN`,
  `LLM_ALLOW_CLOUD_FALLBACK`, plus `TRADING_AGENT_*` app variables). Secrets
  are read from `.env` (gitignored; `.env.example` ships blanks only).
- All money and NAV-fraction values are `Decimal` parsed from quoted strings;
  floats are converted via their shortest string form (plan section 6).
- Unknown top-level sections and unknown keys are rejected (versioned
  contract).
- Fail-closed rules (each violation is a startup error, not a warning):
  - `llm.allow_cloud_fallback` must be `false`; non-loopback LLM/base URLs are
    rejected (accidental cloud inference is impossible by configuration).
  - The website host must be loopback (127.0.0.1/localhost).
  - Deferred v1 asset classes (shorts, margin, options, crypto, leveraged/
    inverse, extended hours, fractional) must all be off (plan section 3).
  - `emergency_liquidation_enabled` must be false (plan section 13).
  - `live_auto_promotion_enabled` must be false and no live change classes
    may be listed (plan section 12).
  - Synthetic `TEST_*` fixture symbols can never appear in the live instrument
    allowlist; the live allowlist and the synthetic universe must be disjoint
    (plan section 22).
  - A live mode requires: `live.enabled=true`, nonzero approved capital, a
    recorded owner-authorization reference, an unexpired authorization
    timestamp, `broker.provider=robinhood`, a bound account alias, and a
    non-empty live allowlist — all or nothing.
  - Paid subscriptions require a positive monthly budget (budget is USD 0).
  - Risk limits must be internally consistent: single order ≤ max position;
    pending entries ≤ max gross; gross + minimum cash ≤ 1.0.

The same rules make "invalid financial configuration fails clearly"
(Prompt 1 acceptance) true: `trading-agent check-config` exits 2 and lists
every violation.

## 4. Broker interface and adapters

`BrokerAdapter` (plan sections 7/14) defines `capabilities()`,
`account_snapshot()`, `submit_order()`, and `cancel_order()`. M0 invariant:
**no adapter can fabricate brokerage success.**

| Provider | M0 behavior |
| --- | --- |
| `simulator` | Reports `connected=True` (local venue) but `reads=execution=False`; every read/execution call raises a classified `BrokerError` pointing at M1. The real engine (order lifecycle, fills, reservations, ledger) is Prompt 2. |
| `robinhood` | Reports `connected=False`; every call raises `BrokerUnavailable` — no MCP client, no transport, no credential handling exists in M0. Real gateway is Prompt 7 (M4) behind owner-run authorization. |

Errors are classified (`BrokerUnavailable`, `BrokerStateNotAvailable`,
`BrokerExecutionNotAvailable`, `BrokerExecutionDenied`) and safe to display.
The full normalized order lifecycle (plan section 14 state machine) is
represented by `NormalizedOrderStatus`; persistence of that state machine
arrives in M1.

## 5. Live-activation gate

`gates.live_activation.evaluate_live_activation(config, broker)` re-evaluates
twelve deterministic prerequisites (plan section 17): live-enabled flag, live
mode, nonzero approved capital, recorded owner authorization, unexpired
authorization, bound account alias, configured instrument allowlist,
official-gateway provider, connected broker, verified capability digest,
healthy reconciliation, and an active strategy. **A single environment
variable is never sufficient.** In M0 the gate can never authorize (no
connection, no strategy, no reconciliation); even a fully populated live
profile plus a hypothetical verified gateway still fails on the two runtime
prerequisites that do not exist yet. Every unmet prerequisite is named in the
result, and the CLI prints them. This gate is the code-level guarantee of
"no usable live execution path" and will be re-run before every financial
mutation in later milestones.

## 6. Persistence strategy

- PostgreSQL 17 in a dedicated, loopback-only container
  (`docker compose up -d`; binds `127.0.0.1:5433`; named volume
  `trading-agent-pgdata`; trust auth acceptable at loopback). Host port
  5432 is occupied by the unrelated dissertation `fda-postgres` container and
  must never be targeted.
- M0 validates the setup but ships no schema: the plan section 16 entity set
  (source registry, instruments, observations, decisions, risk evaluations,
  authorizations, reservations, order intents, submission attempts,
  broker orders, fills, ledger events, portfolio snapshots, labels,
  experiments, promotions, incidents, activity outbox, dashboard
  projections) is implemented with migrations in M1.
- All financial state is append-only and reconcilable; dashboard projections
  are rebuildable views, never a second money ledger (plan sections 16/18).

## 7. Local website

The website is a planned product component, not an M0 deliverable. The full
contract — routes, local startup/authentication, account/mode/run scoping,
persisted read-model and event contracts, page-to-backend dependency map,
and the M1 core-page / M5 full-website backlog — is in
[website.md](website.md). The FastAPI/templates/minimal-JS design of plan
section 18 is preserved; the M0 lockfile already pins FastAPI and uvicorn so
M1 builds on a stable stack. **No UI code exists yet and none is claimed.**

## 8. Quality gates (M0)

- `uv` + committed `uv.lock`, Python 3.13 pinned (`.python-version`).
- `uv run ruff check .` (lint), `uv run mypy` (strict), `uv run pytest`
  (51 tests: config validation, adapter rejections, activation gate, CLI,
  property tests for risk-limit invariants).

## 9. Evidence tracks (plan section 1 / prompt pack)

| Track | M0 state |
| --- | --- |
| Software | Foundation passes offline tests; no trading engine exists yet |
| Integration/operations | Local LM Studio server observed reachable; broker integration not performed (owner-run, M4) |
| Investment | Nothing measured; profitability unproven |
