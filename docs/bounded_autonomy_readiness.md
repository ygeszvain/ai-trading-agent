# Prompt 12 — bounded-autonomy readiness, without activation

Reviewed November 1, 2026 on `codex/bounded-autonomy-readiness`. This implements
the expressly selected M7 offline control scope and M8 authorized-change review
machinery. **Real readiness is BLOCKED. LIVE_NOT_AUTHORIZED. Approved capital is
USD 0.** There is no real envelope, activation endpoint, live executor transport,
automatic renewal, deployment, or permission to trade.

The [unsigned owner worksheet](bounded_autonomy_owner_review.unsigned.json) is a
concrete review artifact, not an authorization input. Owner identity, account,
capital, assets, overnight policy, limits, dates, monitoring, observation and
recovery decisions remain unresolved. USD 1,000 is the earlier requested ceiling;
the separate fictional fixture uses USD 1,000 without granting real authority.

## Delivered behavior

- Strict versioned `M7_MOCK_ONLY` envelope binds one fictional unleveraged ETF,
  exact account/run, capital, strategy/model/prompt/artifact versions, full
  configuration and risk digests, database/tool/permission schema digests,
  limit/day permissions, explicit sessions, overnight policy, independent
  monitoring, start/expiry and exact rollback target. Only one instrument is
  supported by this execution fixture; multi-asset valuation is not certified.
- Code, dependency lock, parameters, features, model, prompt and memory policy
  are content-addressed artifacts. Dispatch verifies all artifact bytes and
  compares execution source and dependency lock against the frozen copies.
  Operational notes are not strategy inputs. Model inference is absent from
  the fixture, rather than supplying trading decisions or updating weights.
- M6 accounting/reservation/attempt code is reused with a distinct M7 envelope
  authorization hook. Account row locks, monotonic executor generations and a
  final locked time/scope/risk check precede fake submission. The frozen
  flat/held strategy allows one working order at a time. A shared envelope can
  cover multiple orders; it is never represented as invented per-intent consent.
- Missing/stale/future evidence, unknown submissions, permission/schema drift,
  expired/revoked authority, incidents, risk failures and audit failures deny new
  exposure. Capacity remains reserved for ambiguous outcomes. Broker-required
  approval is a distinct unresolved state and cannot be bypassed by an app grant.
- An independently running monitor child opens a read-only fixture database
  transaction. It checks frozen artifacts, schema/permissions, freshness, unknown
  orders and forbidden overnight exposure. It continues recording after expiry
  or revocation. Missing or stale monitor evidence denies execution.
- Incidents durably pause execution, clear the authorized generation and queue
  a local notice for `fixture-human`. `Store.pause` is an independent reduction
  of authority and cannot cancel, issue consent or resume. Notices are explicitly
  **QUEUED_LOCAL_NOT_SENT**; no external channel was contacted or verified.
- Startup/restart requires a fresh exact owner-fixture resume command after
  reconciliation and monitor checks. Incident acknowledgement alone cannot
  resume. Normal matched fill reconciliation can continue an already authorized
  generation; it cannot recover a restart, revoked envelope or incident pause.
  Loss high-water marks survive sessions, incidents, rollback and restart.
  Daily counters reset only for a new listed forward session; clock rewind denies.
- Explicitly preapproved protection is limited to canceling a known entry order
  during a separate bounded protection interval. Its attempt commits before the
  fake call, followed by locked clock/schema/permission/fencing revalidation.
  Reserves remain until confirmation. No automatic sale, liquidation or real
  cancellation exists. Revocation blocks protection as well as new exposure.
- Rollback can select only a verified backup of the *same* approved champion.
  It records history, leaves damaged primary evidence intact, preserves loss
  history, and requires acknowledgement/resume. It cannot install a new strategy.

## M8 authorized-change boundary

The executable permitted automatic change class is **NONE**, fixed in the typed
envelope. Research gets a frozen read-only `ResearchView`, not an issuer, owner
signer, SQL handle, executor handle or authorization-update method.

`promotion.prepare_review` records a blocked proposal by default. A separately
owner-fixture-signed, expiring mandate can support a *review preview* for bounded
parameter/allocation changes. It binds original assets, explicit field bounds,
dataset/protocol, complete registered trials (including failures), verified
content hashes, matured-label count, shadow-session minimum, uncertainty bound,
turnover/drawdown limits, safety regressions and rollback. Candidate artifact and
parameter diffs are checked for hidden code/model/prompt/feature/rule changes.
Referenced datasets, protocols and every trial result must still be available.

Even an adequate synthetic review yields `REVIEW_READY_NO_ACTIVATION`. Neither
synthetic nor real automatic activation is implemented. `activate` always denies;
the active envelope, champion and class NONE remain unchanged. Future mandate
change counts and allocation execution are not exercised because no activation
exists. Code, risk, capital, tools, assets, model and prompt changes remain outside
the preview class. Synthetic evidence declarations are test inputs, not independent
proof of economic performance or 30 actual prospective shadow sessions.

## Evidence matrix

| Material requirement / risk | Implementation and observed verification | Result / residual limitation |
| --- | --- | --- |
| Exact, expiring envelope; no self-issued/renewed/widened authority | `autonomy/contracts.py`, `engine.py`, `research.py`; forbidden-operation, intent-binding, expiry and role tests | CODE_PASS for synthetic controls; real owner identity/signing absent |
| Hidden memory, prompt, feature/settings or source changes | `artifacts.py`, execution revalidation; tampered prompt/backup rollback, altered intent/settings and hidden candidate code tests | CODE_PASS; same-user Python is not an OS security boundary; installed dependency/runtime attestation pending |
| Duplicate/concurrent reservations and single executor | Reused M6 journal/executor; actual disposable PostgreSQL row-lock, shared-envelope round trip and reused-boot-label fencing tests | CODE_PASS; separate-host leases and real broker behavior unverified |
| Stale data, monitor loss, clock rewind, schema/permission drift | `_check_common`, monitor role/sequence and expiry checks; stale health/monitor, drift, rewind, role/replay tests | CODE_PASS; no real gateway discovery/permissions attestation |
| Ambiguous broker results, required broker approval, audit failure | Fake transport exceptions/timeout/approval cases, retained reservations, incident pause and pre-wire audit failure tests | CODE_PASS; real submission/approval/idempotency semantics EXTERNAL_VALIDATION_PENDING |
| Restart, independent stop, acknowledgement, revocation | Generation fencing, Store.pause, explicit owner resume; persisted restart/HWM, pause-after-reconciliation, acknowledgement and revoked-monitor tests | CODE_PASS; real independent host/OS stop/recovery drills EXTERNAL_VALIDATION_PENDING |
| Protective behavior and rollback bounds | Expired-primary/valid-protection cancellation, late wire clock denial, exact backup artifact tests | CODE_PASS; disconnected app cannot guarantee broker cancellation, liquidation or timely operator notification |
| Unauthorized promotion and misleading learning evidence | `promotion.py`; class NONE, separate mandate preview, forbidden classes, hidden diffs/trials, insufficient evidence and expiry tests | CODE_PASS for rejection/review; investment evidence EXTERNAL_VALIDATION_PENDING |
| Website isolation and untrusted evidence | `autonomy/view.py`, authenticated scoped routes; zero-write row counts, no signer/model/broker construction, Host/Origin/POST denial, escaping/redaction and integrity tests | CODE_PASS for this read model; earlier M5 stream/export gaps remain |
| Website persisted failure display | Browser against completed synthetic journal: six fills, paused/expired evidence, denied changes, 6 control POSTs denied, 0 page exceptions and 0 external requests; desktop 1440px and narrow 390px checked | CODE_PASS; one local missing-favicon 404, no external traffic |
| Additive database migration | Nine M7 tables: upgrade, inspect, downgrade to M6 and re-upgrade; unrelated witness preserved | CODE_PASS for M7 migration; global compatibility still BLOCKED by earlier missing tables/columns |
| General software, operations and investment readiness | Full suite and earlier review retained | Overall FAIL / BLOCKED; no positive investment readiness claim |

## Concrete fixes from this review

The M7 path reuses M6 mechanics through table-scoped journals and a permit hook;
M6 still requires its original exact per-intent approvals. Cross-domain M6 pause,
revocation and cancellation requests cannot control an M7 journal. The following
defects were fixed with regression coverage:

1. Diagnostic redaction lost the sensitive field name during recursion. Sensitive
   keys are now redacted before nested traversal; exact financial/hash bindings
   remain visible. This also protects the existing M6 read model.
2. A backward fixture observation could revisit an earlier session and reset
   daily counters. Persisted account time now rejects rewinds.
3. A new intent while a prior flat/held strategy order was still working could
   request duplicate exposure. The execution-side frozen rule now denies it.
4. Protective cancellation needed a committed attempt and a fresh wire-time
   check. Both now precede the injected fake call.
5. Owner-domain revocation originally stopped monitor ingestion as well as
   execution. Revoked envelopes now remain readable by monitoring, while all
   execution checks continue to deny.
6. SQLite's legacy driver did not begin a snapshot for SELECT. Website read
   dependencies now explicitly begin the SQLite transaction; PostgreSQL retains
   its read-only REPEATABLE READ transaction.
7. An early reservation audit outage could leave no durable incident and an
   otherwise reusable worker. Non-denial storage/artifact failures now latch the
   worker failed before incident recording; restoring storage cannot resume or
   dispatch that worker. Direct reserved dispatch also records unresolved broker
   outcomes, and protective failures pause through the incident path.

Failed intermediate runs are retained under `.data/m7-review/evidence/` alongside
the successful results. Earlier economic failures, holdouts and journal evidence
were not edited to pass. No existing risk policy or live settings were widened;
the separate mock target/slice are tightened to 1% for a whole-unit fixture.

## Reproduction and actual results

Offline commands (no broker/model/token or existing database required):

```sh
uv run trading-agent autonomy package
uv run trading-agent autonomy demo --out-dir .data/m7-review
uv run pytest -q tests/autonomy tests/supervised
uv run ruff check src/trading_agent/autonomy src/trading_agent/supervised tests/autonomy src/trading_agent/db/schema.py src/trading_agent/web/app.py src/trading_agent/cli/main.py
uv run mypy --follow-imports=silent -p trading_agent.autonomy -p trading_agent.supervised
uv run python -m compileall -q src tests/autonomy
node --check src/trading_agent/web/static/app.js
node --check tests/autonomy/browser_checks.js
```

The demo creates a new private SQLite journal and sealed artifacts on every run.
It advances an injected clock through three named synthetic sessions, executes
six fake fills using one initial owner-fixture resume and **zero per-intent app
approvals**, and then denies expiry, capital expansion and a prompt promotion.
Final cash is exactly **999.94**, reserves **0.00**, high-water mark **1000**.
This is a deliberately fee-losing test scenario, not a return projection.
Monitor process IDs differ from the executor PID. The envelope stays unchanged,
class remains NONE, and the final state is paused.

Database-backed verification used only a newly created `postgres:17` container
named `trading-agent-m7-review`, bound to `127.0.0.1:55433`, with disposable
`review`, `m6_review`, `m7_review`, and `m7_migrations` databases. Existing database
services and accounts were not contacted. The container was removed after review.
The explicit environment bindings for these checks are:

```sh
export TRADING_AGENT_REVIEW_DB=postgresql+psycopg://review@127.0.0.1:55433/review
export TRADING_AGENT_M6_REVIEW_DB=postgresql+psycopg://review@127.0.0.1:55433/m6_review
export TRADING_AGENT_M7_REVIEW_DB=postgresql+psycopg://review@127.0.0.1:55433/m7_review
uv run pytest -q tests/autonomy tests/supervised
uv run pytest -q
```

Final counts are recorded in [build_status.md](build_status.md). The three known
economic assertions remain failing: regime earns-paper-test, whipsaw rejection,
and fold-edge benchmarking. Global Ruff/mypy failures are also preserved; a
scoped pass is not a repository-wide pass. Migration head is `e71a4c09d522`.
The final full run is **292 passed / 3 existing failures**; focused M6/M7 is
**136 passed**. Scoped Ruff and mypy pass (24 source files). Repository-only
credential-pattern review found only the existing URL-denial test's fictional
`user:pass`; default simulation/pilot remain live-disabled with zero capital and
no cloud fallback, and the inactive live template rejects startup as required.

For optional browser-only inspection of an existing demo, copy the `journal`
path from its JSON report:

```sh
uv run python -m tests.autonomy.serve_fixture --journal /absolute/path/from/report/journal.sqlite --port 8028
```

Open loopback `/autonomy`. The *public synthetic fixture login* is
`fixture-m7-web-owner`; it is deliberately not the normal application's owner
credential and must never be used for a real service. Normal `trading-agent serve`
still fails on the known schema guard. This harness is not an activation/setup
bypass and cannot submit anything. `tests/autonomy/browser_checks.js` was run with
the Playwright skill wrapper. Local screenshots are in
`output/playwright/m7-autonomy-desktop.png` and `m7-autonomy-narrow.png` (ignored).

## Owner review and next dependency

**Code evidence:** review this change, the focused tests, migration evidence,
earlier FAIL findings and full-suite failures. M0–M5 completion is not inferred
from this later offline milestone. Repair upstream schema, integrated accounting/
recovery and economic evaluation defects before a real readiness claim.

**Broker/operations evidence — EXTERNAL_VALIDATION_PENDING:** separately operated
runtime secret injection, OS identities, authenticated independent monitor/stop,
exclusive execution across processes/hosts, real schema/account/tool permissions,
required approvals, cancellation/fill/correction semantics, backup/restore and
external reconciliation, clock/restart/loss-history drills, alert delivery and
human acknowledgement. Fixture HMAC keys are public and confer no real identity.
The scrubbed child environment and distinct PID demonstrate a process boundary,
not a deployed independent security or availability domain. No outbound alerts
were sent. Monitoring cannot repair a network partition or guarantee broker-side
protection. Official broker-revocation directions and their unresolved account
specifics remain in [the M6 owner runbook](supervised_readiness.md).

**Investment evidence — EXTERNAL_VALIDATION_PENDING:** independently checked
data/labels and cost assumptions, complete failed trials, unchanged protocol and
holdouts, meaningful uncertainty, prospective challenger shadowing and an actual
operating record. Synthetic checks and a software pass establish no edge.

The owner must independently decide and sign every unresolved envelope field,
including account, capital, eligible assets, sessions/overnight exposure, loss and
exposure limits, model/prompt/champion/risk versions, dates, observation period,
monitoring and recovery. These decisions are not supplied by this prompt or its
unsigned worksheet. Any future implementation/activation requires a separate
explicit request and evidence review. The numbered prompt pack ends here; do not
invent or auto-advance to Prompt 13. No production deployment, push, live account
connection, promotion, renewal, capital increase or trading occurred.

Current financial authority: **LIVE_NOT_AUTHORIZED**.
