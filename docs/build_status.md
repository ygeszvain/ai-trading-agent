# Trading agent build status

**Last updated:** 2026-11-01 (Prompt 11 mock supervised-readiness controls; historical evidence retained)
**Current financial authority:** LIVE_NOT_AUTHORIZED
**Approved live capital:** 0 USD (requested USD 1,000 pilot: recorded, activation pending — plan section 24)
**Next numbered task:** Prompt 12 only if selected — actual live readiness remains blocked

## Prompt 11 — Supervised-live readiness, without activation (M6 controls)

Implemented the explicitly selected control-code/mock-verification scope on
`codex/supervised-readiness`. **Live readiness remains BLOCKED / LIVE_NOT_AUTHORIZED**.
The [implementation report and owner runbook](supervised_readiness.md) and
[concrete unsigned package](supervised_activation_package.unsigned.json) retain
unresolved decisions and distinguish software, integration and investment evidence.

### What works

- Strict immutable scope/grant/intent/approval contracts; all material amounts,
  target, price constraints, versions, evidence, risk snapshot and expiry bind
  into canonical hashes. Single-use approval and revocation/expiry checks.
- Full mock readiness gate, existing deterministic risk engine recheck, frozen
  strategy manifest/settings and complete policy bindings, fresh account/data/
  reconciliation/audit/eligibility/session evidence. Actual dispatch always denied.
- Separate child-process executor demonstration, exact injected fake transport,
  no real transport or credentials. Transactional account locking, monotonic
  worker-generation fencing, explicit resume, worst-case capacity reservations,
  and durable before/after attempt/audit records. Final locked clock/consent/risk
  check immediately before the fake call. No broker idempotency claim.
- UNKNOWN/reserved state on exceptions; no automatic retry or silent restart.
  Separate broker-approval requirement, partial/duplicate fills, cancel/fill race,
  fee-inclusive buy/sell accounting, discrepancy/rejected-evidence preservation,
  shutdown/pause/revocation that do not claim cancellation or liquidation.
- Read-only `/readiness` + `/api/v1/readiness`, exact mock bindings and audit
  coverage, USD 1,000 inactive request versus USD 0 approved. Every actual control
  POST is server-denied. Browser reads invoke no executor, broker or model calls.
- Five additive SQLAlchemy/Alembic M6 journal tables; prior incompatible schema
  contracts remain unrepaired/blocked. A separate USD 1,000 synthetic feasibility
  profile preserves zero live capital, disabled live mode and existing limits.

### Exact commands and observed results

| Command / check | Actual result |
| --- | --- |
| `uv run trading-agent supervised package` | Prints UNSIGNED_BLOCKED owner worksheet; no signature, no activation loader, capital 0 |
| `uv run trading-agent supervised demo --out-dir .data/m6-review` | **PASS**, separate child PID, injected fake, two fills; cash 989.990, reserves 0.000, explicit resume required; reports LIVE_NOT_AUTHORIZED and external evidence pending |
| `TRADING_AGENT_M6_REVIEW_DB=postgresql+psycopg://review@127.0.0.1:55433/m6_review uv run pytest tests/supervised -q` | **66 passed**, 1 existing deprecation warning; includes real disposable PostgreSQL lock/fence tests, no skipped DB cases |
| Both dedicated review DB env vars + `uv run pytest -q` | **222 passed, 3 failed**, 1 warning; unchanged economic regime/whipsaw/fold-edge assertions remain failing |
| `uv run ruff check src/trading_agent/supervised tests/supervised src/trading_agent/db/schema.py src/trading_agent/web/app.py src/trading_agent/cli/main.py` | **PASS** |
| `uv run mypy --follow-imports=silent -p trading_agent.supervised` | **PASS**, 11 source files; imported broader code excluded from this scoped result |
| `uv run ruff check src tests` | **FAIL**, 61 existing broader findings |
| `uv run mypy` | **FAIL**, 122 errors / 24 files, 108 checked |
| `uv run python -m compileall -q src tests`; `node --check src/trading_agent/web/static/app.js`; `node --check tests/supervised/browser_checks.js` | **PASS** |
| Disposable M6 migration upgrade / inspect / downgrade / upgrade | **PASS** five new tables/columns/FKs, unrelated fixture witness retained; new head `d8c302b4a611`; prior schema compatibility guard still blocks normal startup |
| Playwright `-s=m6-review run-code --filename tests/supervised/browser_checks.js` | **PASS** persisted mock read page, exact hashes, disabled controls + five POST denials, explicit evidence tracks/coverage, desktop 1440×1000 and narrow 390×844, zero page errors/external origins; screenshots inspected |

Changed files: new `supervised/{contracts,readiness,journal,executor,fake,fixtures,
worker,demo,view,package}.py` + package marker; additive schema/migration; CLI;
readiness template/routes/navigation/styles; small simulation profile; focused
control/process/PostgreSQL/read-only API/browser tests; package/runbook and
README/SETUP/architecture/website/AGENTS/status documentation. No original live
gate/refusing broker adapter, champion, objective, holdout, failing economic
assertion or existing risk limit was relaxed.

### Boundaries and remaining evidence

Only mocked consent is executable: literal M6_MOCK_ONLY/fixture-owner and public
fixture signing material. It cannot authenticate a real owner. A separate mock
process was demonstrated; separate deployed OS privilege, real signing/secret
injection and broker runtime remain absent. Normal website startup still stops
at the earlier schema guard. Existing pipeline, recovery, M4/M5, economic and
independent-monitoring defects remain FAIL/BLOCKED. No live integration, broker
mutation/approval/revocation, prospective track record, production restore or
actual activation was performed. Owner-run checks and unknown official
revocation details are explicit in the runbook; do not invent an endpoint/menu.

Owner fields remain unresolved: exact account/eligibility, approved capital
(currently zero), instruments/strategy, actual limits and overnight policy,
start/expiry, monitoring operator/channel, observation duration and independent
decisions, recovery/revocation evidence and scoped signed consent. Requested
USD 1,000 remains a draft ceiling, not authority or funding. Stop at Prompt 11;
Prompt 12 is next only when explicitly selected, with all blockers preserved.

## Prompt 10 — Security and failure readiness review

Completed the explicitly requested offline review on `codex/security-readiness`.
**Overall readiness: FAIL; no live or investment readiness certificate.** The
[evidence matrix and prioritized defect report](security_readiness_review.md)
distinguish CODE_PASS, EXTERNAL_VALIDATION_PENDING, BLOCKED and FAIL.

### Concrete fixes and acceptance evidence

- Correct risk sizing returned to execution; protective BUY cannot bypass
  controls; fresh account/quote, identity/version bindings and pending exposure
  checks. Fully populated hypothetical live activation still always rejects.
- No wildcard inference endpoints or credential-forwarding redirects; explicit
  read tool set and RPC response identity; legacy OAuth and unvalidated real
  gateway quarantined. Disabled construction does not read runtime credentials.
- Protected atomic owner/runtime files; no bootstrap token printing; persisted
  session expiry/revocation; exact Host/port and Origin; POST-only logout.
- Core website row queries and account/mode/run scope repaired; read-only,
  repeatable-read PostgreSQL requests; exact decimals, escaped/redacted evidence,
  unavailable NAV, visible gaps and failures, and run-preserving navigation.
- Fee-inclusive ledger basis/replay, duplicate raw-fill detection, stale-writer
  rejection, fail-closed audit errors/missing marks; ambiguous equal-timestamp
  replay blocks pending durable-order migration. Passive benchmark fees and
  composite starting capital corrected without changing economic assertions.
- Fresh-install schema drift is now an explicit startup error rather than an
  apparent successful head stamp followed by failed reads. The underlying
  migration mismatch is unresolved; synthetic website tests use full metadata.

| Exact command / check (2026-11-01) | Actual result |
| --- | --- |
| `TRADING_AGENT_REVIEW_DB=postgresql+psycopg://review@127.0.0.1:55433/review uv run pytest tests/security -q` | **29 passed**, 1 upstream deprecation warning; disposable PostgreSQL exercised, none skipped |
| Same env + `uv run pytest -q` | **156 passed, 3 failed**, 1 warning; same three `tests/evaluation/test_econ_eval.py` failures retained |
| `uv run ruff check src/trading_agent/security tests/security tests/auth_helpers.py src/trading_agent/db/migrate.py` | **PASS** |
| `uv run ruff check src tests` | **FAIL**, 61 findings; broader pre-existing lint debt remains |
| `uv run mypy` | **FAIL**, 122 errors / 24 files, 97 source files checked; broader typing debt remains |
| `uv run python -m compileall -q src tests` | **PASS** |
| `node --check src/trading_agent/web/static/app.js` | **PASS** |
| Playwright named-session `run-code --filename tests/security/browser_checks.js` against persisted fixture server on 127.0.0.1:8020 | **PASS** core scope, exact money, UNKNOWN/partial fills, escaped evidence, HOLD/rejection/cancel/correction, explicit missing session, network failure, logout; no external browser origins or JS page errors. Desktop/narrow screenshots visually inspected. |
| Synthetic `pg_dump -Fc` / `pg_restore --exit-on-error`, separate `review_restore` DB | **PASS** all 25 table counts, cash 1008, realized P&L 8, historical max equity 1200 |
| Fresh Alembic `run_migrations(config)` in isolated `review_migrations` DB | **FAIL** compatibility after head `c4a7e19b2d05`; new guard blocks startup; missing tables/columns listed in review |
| Repository-only provider-token/private-key pattern scan | 169 files + 8 revisions; no pattern matches. Limited scan; no unrelated private files/stores inspected. |

### Remaining prioritized defects and limits

1. **FAIL:** Alembic/current schema incompatibility and integrated pipeline
   readiness; metadata fixture success is not installation success.
2. **BLOCKED/FAIL:** durable ordering for equal-time ledger history, account-wide
   concurrent reservation/job fencing, legal lifecycle transitions, broker
   corrections/manual trades/external flows and integrated crash recovery.
3. **FAIL:** three existing economic verdict/fold assertions; old same-close
   backtest path; incomplete survivorship/dividend/total-return evidence.
4. **BLOCKED:** independent watchdog/stop controls, separated privileged runtime,
   full M5 pages/stream bootstrap-gap-reconnect/exports/controls.
5. **EXTERNAL_VALIDATION_PENDING:** actual broker capabilities/account binding,
   authentication/partitions/races, owner-operated restore/stop and prospective
   record. None can pass from mocks; no such check was performed.

Changed areas: `config`, `gates`, `risk`, `execution`/MCP, `ledger`, `research`,
`data`, `backtest`, `engine`, `db/migrate`, `security`, and core `web` routes,
queries/templates/assets; targeted tests in `tests/security`, existing auth/gate
checks, and current documentation. The detailed review links risks to specific
implementation/test names and preserves the original failed observations. No
objectives, holdouts, failed economic assertions, account limits or unrelated
work were overwritten. No push, deployment, alert, broker call or credential
extraction occurred. The disposable review service was removed after checking.

Stop at Prompt 10. Prompt 11 is the next number only when explicitly selected;
it is not authority to bypass these blockers. Owner-operated checks are listed
separately in the report. Financial authority: **LIVE_NOT_AUTHORIZED**.

## Prompt 9 — Controlled research learning (M8 research only)

The owner explicitly selected Prompt 9. Its independent offline scope is
implemented on `codex/research-learning`; this is not acceptance of earlier
M1–M5 milestones or a live strategy. See [research_learning.md](research_learning.md).

### What works and acceptance

- Frozen decision/evidence/portfolio/intent/fill/cost/version snapshots, explicit
  session horizons and observation cutoffs, 64 mature / 4 pending / 1 incomplete
  outcomes in the deterministic demo, linked corrections, preserved predecessors.
- Four prespecified challengers, unchanged objective and holdout, causal
  next-session modeled execution, cost/turnover/drawdown/safety comparisons and
  3x cost stress. All four fixture candidates have inadequate evidence and remain
  unqualified. Fold dispersion is disclosed without a confidence claim.
- Immutable champion and isolated trial configurations; verified operational
  notes have no path into prompts, model weights, strategy settings, or policy.
- Write-once, content-addressed plan/dataset/champion/trial/incident/report files.
  Started, failed, budget-exhausted and completed attempts are auditable.
- Synthetic forward harness with registration/cursor checks, 45 reserved forward
  steps in addition to 1,200 historical steps, missing-data/drawdown/feature-drift
  pauses, and no replacement. Real prospective observations remain PENDING.
- Versioned blocked proposal with exact diff, all trial references, prerequisites,
  absent authorization, rollback target, and an always-rejecting activation API.
  Legacy evaluation/challenger/paper entry points also cannot promote.
- Authenticated read-only Learning page with fixture account/mode/run scope,
  exact values, all failures, correction linkage, and explicit mechanism labels.

### Exact commands and actual results

| Command | Actual result |
| --- | --- |
| `uv run trading-agent learning demo` | Exit 0; 69 outcomes (64 MATURED / 4 PENDING / 1 INCOMPLETE), four trials, unchanged champion, BLOCKED_RESEARCH_PROPOSAL, synthetic shadow paused |
| `uv run pytest -q tests/learning tests/test_learning*.py` | **45 passed**, one existing Starlette/httpx deprecation warning |
| `uv run ruff check src/trading_agent/cli/main.py src/trading_agent/web/app.py src/trading_agent/config/models.py src/trading_agent/learning tests/test_learning*.py tests/learning` | All checks passed |
| `uv run ruff format --check src/trading_agent/cli/main.py src/trading_agent/web/app.py src/trading_agent/learning tests/test_learning*.py tests/learning` | 20 files already formatted |
| `uv run mypy --follow-imports=silent -p trading_agent.learning` | Success, 11 learning source files; imported dependencies excluded from this scoped type result |
| `uv run pytest -q` | **127 passed, 3 failed**, one warning; 5.89 seconds. The three existing `tests/evaluation/test_econ_eval.py` regime/whipsaw/fold-edge failures remain unchanged |
| `uv run mypy` | **141 errors in 26 files**, 95 checked; pre-existing broader integration/type debt remains |
| `uv run ruff check src tests --output-format json` | **85 broader findings** remain; scoped learning/integration files pass |

A clean copy of all tracked/unignored source files (excluding Git history,
virtual environments, local state and browser artifacts) also passed
`uv sync --locked`, `uv run trading-agent learning demo`, and the 45-test focused
suite. Its generated experiment hash matched the working checkout exactly:
`9464a3e351f28646eb5be20f29ed00027285fc798c9e8397088ef874d2b89c27`.
The source-copy test used a separate virtual environment; no PostgreSQL, model,
or broker service was used by that focused workflow.

Browser: Playwright CLI synthetic preview (database engine stubbed, fixture
session only) verified login redirect, authenticated research rendering, mechanism
and failure labels, Desktop 1440×1000 and narrow 390×844 layouts. Requests were
loopback page/CSS/JavaScript only; the sole console error was an unrelated missing
favicon. Screenshot paths: `output/playwright/learning-desktop.png` and
`output/playwright/learning-narrow.png`. API tests prove page reads write no
artifacts and construct no model/broker clients. Full PostgreSQL website startup
and unrelated pages were not revalidated by this preview.

### Changed files and limitations

New: `learning/{records,workflow,demo}.py`,
`tests/learning/test_research_workflow.py`, the Learning template and this
research guide. Updated: legacy learning contracts/labels/dataset/evaluation/
memory/paper/store APIs and fixture tests; CLI, one research-store configuration
field, authenticated route/navigation/scoped styles, `.gitignore`, README,
SETUP, AGENTS, and this ledger. No migration, risk-policy, live-default,
M3 objective/holdout, or failing M3 evaluation test was changed.

Integration/operations: no financial-account connection, real provider,
LM Studio inference, real prospective sessions, broker mutation, or production
operation. Owner-run integration and prior M1–M5 acceptance are still unresolved.
Investment: no prospective economic evidence; profitability remains unproven.
The next numbered prompt is **Prompt 10**, subject to explicit selection and
these dependencies. Do not auto-advance or activate any proposal.

## Open source publication — November 1, 2026

The owner authorized publishing the code to the public repository
https://github.com/ygeszvain/ai-trading-agent. README, setup instructions, MIT
license, contribution/security guidance, package metadata, and local-state
exclusions were prepared. Existing later-stage source and working-tree changes
are included as an **experimental snapshot**, not as accepted milestones.

The earlier broad `data/` ignore rule hid the required source package; it is now
anchored to repository-root runtime data. The simulation profile disables broker
shadow polling. Live capital remains zero and cloud fallback remains disabled.

Clean-export checks: configuration/status/backtest/evaluation commands pass;
pytest reports **87 passed, 21 failed**; Ruff reports **149 findings**; mypy reports
**168 errors in 31 files**. Build succeeds. Full commands, changed-file categories,
source/history review, acceptance gaps, and owner-run checks not performed are in
[publication_status.md](publication_status.md). Read that report and
[SETUP.md](../SETUP.md) before using historical commands below.

The following M0 report is historical evidence from October 31. Its assertions
about absent source/UI are not current feature inventory. The numbered task
handoff remains **Prompt 2 acceptance reconciliation** before advancing; this
publication does not certify M1 or any later milestone.

## M0 — Repository, environment, and persistent boundaries

### What works now

- Clean-checkout setup and validation commands are documented (README) and were
  executed successfully on this host: `uv sync`, `uv run ruff check .`,
  `uv run mypy` (strict), `uv run pytest` (51 tests), and
  `uv run trading-agent check-config`.
- Typed configuration with fail-closed rules (plan section 22 contract,
  `.env.example`, `config/simulation.yaml`, `config/live.template.yaml`,
  `config/source_registry.yaml`). Invalid financial configuration exits 2 and
  lists every violation; a missing file, malformed YAML, or a bad env value
  all fail clearly.
- No usable live execution path: the Robinhood adapter is explicitly
  unavailable, the simulator placeholder rejects all execution, and the
  deterministic activation gate (12 prerequisites) can never authorize in M0
  — even for a fully populated live profile plus a hypothetical verified
  gateway.
- Disposable local database: `docker compose` PostgreSQL 17 on
  127.0.0.1:5433 (container `trading-agent-postgres`, healthy, verified with
  a SQL round-trip; port 5432 belongs to the unrelated dissertation
  `fda-postgres`).
- Website contract documented (routes, startup/auth, scoping, read-model and
  event contracts, page-to-backend map, M1/M5 backlog) in
  [website.md](website.md). **No UI exists; none is claimed.**

### Acceptance criteria (Prompt 1)

| Criterion | Result |
| --- | --- |
| Clean checkout has documented setup and validation commands | PASS — README; all commands run successfully (results in the M0 evidence section below) |
| Minimal configuration smoke check | PASS — `uv run trading-agent check-config` (exit 0 on `config/simulation.yaml`; exit 2 + per-violation messages on invalid configs) |
| No usable live execution path | PASS — gate + adapter rejections, covered by 51 tests including property tests |
| Invalid financial configuration fails clearly | PASS — every violation class tested (negative/NaN/malformed capital, cloud fallback, non-loopback URLs, TEST_* in live allowlist, over-unity limits, unknown keys, live-mode requirement matrix) |
| Milestone backlog and unresolved dependencies are concrete | PASS — ledger below; capability matrix lists pending owner-run items and what each blocks |

### Changed files (M0)

- New: `pyproject.toml`, `uv.lock`, `.python-version`, `.env.example`,
  `docker-compose.yml`, `config/simulation.yaml`, `config/live.template.yaml`,
  `config/source_registry.yaml`
- New source: `src/trading_agent/{__init__,exceptions,money}.py`,
  `src/trading_agent/config/{__init__,models,loading}.py`,
  `src/trading_agent/contracts/{__init__,broker}.py`,
  `src/trading_agent/execution/{__init__,broker_interface,simulator,robinhood_mcp,factory}.py`,
  `src/trading_agent/gates/{__init__,live_activation}.py`,
  `src/trading_agent/cli/{__init__,__main__,main}.py`
- New tests: `tests/conftest.py`, `tests/unit/{test_config_validation,test_broker_adapters,test_live_activation_gate,test_cli}.py`,
  `tests/property/test_config_invariants.py`, package `__init__.py` files
- New docs: `docs/architecture.md`, `docs/website.md`,
  `docs/capability_matrix.md`, `docs/decision_log.md`
- Updated: `docs/build_status.md` (this file), `README.md`, `AGENTS.md`
- Preserved unchanged: the two recovered source documents, the prompt pack,
  `CODEX_START.md`, `migration_record.md`, `CHECKSUMS.sha256`,
  `SOURCE_MANIFEST.json` (originals remain in Git history; current hashes
  match the migration manifest)

### Exact commands and actual results (run 2026-10-31 on the target host)

| Command | Result |
| --- | --- |
| `brew install uv` | uv 0.13.6 installed (Homebrew bottle) |
| `uv sync` | Resolved 35 packages; wrote `uv.lock`; created `.venv` (Python 3.13.2); pydantic 2.14.2, PyYAML 6.0.3, FastAPI/uvicorn locked; installed `trading-agent 0.1.0` (editable) |
| `uv sync --reinstall-package trading-agent` | Rebuilt the editable install after source files were added |
| `uv run ruff check .` | All checks passed (after formatting) |
| `uv run ruff format --check .` | All files formatted |
| `uv run mypy` | Success: no issues found in 18 source files (strict) |
| `uv run pytest -q` | **51 passed** in ~0.3 s |
| `uv run trading-agent check-config --probe-llm` | exit 0; mode SIMULATION; broker simulator (execution disabled); gate: 11 unmet prerequisites, LIVE_NOT_AUTHORIZED; LM Studio probe: reachable, 4 models loaded; `result: OK` |
| `uv run trading-agent check-config --config /tmp/bad-trading-config.yaml` | exit 2; listed 3 violations (cloud fallback, negative capital, over-unity limits) with clear messages |
| `docker compose up -d` | `trading-agent-postgres` started (reused cached postgres:17 image); healthy |
| `psql -h 127.0.0.1 -p 5433 -U trading_agent -d trading_agent -c "select version();"` | `PostgreSQL 17.9 ... on aarch64-unknown-linux-gnu`; SQL round-trip OK |

### Checks not run (honest limitations)

- No website, browser, or UI check — no UI exists (M1).
- No LM Studio inference performed: only read-only route probes in M0
  (decision D15). Functional endpoint/model capability tests are M2.
- No broker interaction of any kind; no MCP client installed.
- No trading engine, ledger, or strategy: simulator execution and all plan
  section 16 persistence arrive in M1.
- LM Studio authentication state unverified (plan section 9; M2).
- Host security observation (dissertation `fda-postgres` on 0.0.0.0:5432)
  recorded but not acted on — outside this repository.

### Evidence tracks

| Track | State |
| --- | --- |
| Software | Foundation passes offline tests (lint/type/51 tests/CLI); no trading engine yet |
| Integration/operations | LM Studio server observed reachable (4 models); local Postgres verified; broker: nothing performed (PENDING owner-run, M4) |
| Investment | Nothing measured. Profitability remains unproven. |

### Unresolved dependencies (concrete)

1. **Owner-run broker authorization + capability discovery** (M4/Prompt 7) —
   blocks the real gateway, shadow mode, and every live mode.
2. **LM Studio functional capability tests + model selection** (M2/Prompt 4) —
   blocks model-dependent research; deterministic work does not wait.
3. **Owner pilot fields** (account, limits, dates, mode, overnight policy,
   funding) — blocks M6/M7 activation screens; not needed for M1.
4. **Data provider/budget decision** (M3) — blocks real historical data;
   fixtures proceed.
5. **Remote repository selection** — resolved for publication on November 1:
   `ygeszvain/ai-trading-agent`; see the publication addendum. Historical M0
   evidence below predates that selection.

None of these block Prompt 2's offline work.

## Milestone ledger

| Prompt | Scope | Status |
| --- | --- | --- |
| 1 | Repository, environment, and persistent boundaries (M0) | **Complete 2026-10-31** — evidence above |
| 2 | First offline trading slice and local website (M1) | Next |
| 3 | Accounting, execution, and recovery hardening | Pending |
| 4 | Local LM Studio research integration (M2) | Pending |
| 5 | Permitted data and point-in-time storage (M3) | Pending |
| 6 | Strategy and economic evaluation (M3) | Pending |
| 7 | Official Robinhood gateway with writes disabled (M4) | Pending |
| 8 | Full local trading website, monitoring, and forward paper mode (M5) | Pending |
| 9 | Controlled learning in research | **Offline research scope implemented 2026-11-01**; evidence above, real prospective integration pending |
| 10 | Security and failure-readiness review | **Review complete 2026-11-01**; concrete fixes/tests and matrix recorded; overall readiness FAIL |
| 11 | Supervised-live readiness; activation disabled (M6) | **Mock control scope implemented 2026-11-01**; actual readiness BLOCKED |
| 12 | Bounded-autonomy readiness; activation disabled (M7/M8) | Pending |

## Next action

Prompt 11 stops with reviewed control code, mocked verification, an unsigned
package and owner/integration dependencies. Prompt 12 is next only when
explicitly selected. Resolve earlier schema, integrated recovery, economic and
monitoring failures before any real readiness claim. No account linking,
funding, promotion, production deployment or trading is authorized.

Current financial authority: **LIVE_NOT_AUTHORIZED**.
