# Prompt 11 — supervised-live readiness without activation

Implemented November 1, 2026 on `codex/supervised-readiness`, based on `f1092d7`.
Scope is M6 control code and mocked verification only. **Actual readiness remains
BLOCKED; financial authority is LIVE_NOT_AUTHORIZED, with USD 0 approved.**
No accounts were linked or funded; no financial credentials, broker requests,
permission changes, deployment, merge or push occurred.

The requested USD 1,000 ceiling is preserved in
[the unsigned package](supervised_activation_package.unsigned.json). Account,
approved capital, instruments, overnight policy, actual limits, dates, operator,
monitoring, observation, recovery and consent are unresolved. The package is a
worksheet, has no signature, and has no activation loader.

## What is implemented

| Control | Implementation and observed verification |
| --- | --- |
| Complete readiness predicate | `supervised/readiness.py` checks selected supervised mode, separate enabled flag, exact nonzero grant-bound capital, account fingerprint/alias, approved universe, fresh eligibility/session/precision, full policy hash, frozen strategy manifest/settings, fresh data/reconciliation/audit/account, owner grant start/expiry, resume/revocation, exact intent and repeated deterministic risk. Every report also contains an unconditional failed live-dispatch check. |
| Exact per-intent approval | Immutable strict contracts bind account, run, instrument, side, whole-share quantity, target, LIMIT/DAY, price constraints, maximum fee, full strategy/policy and evidence/risk hashes, issue time and expiry. Any material change breaks the hash. Stored approval is consumed transactionally once, and revocation/expiry is rechecked. |
| Owner identity boundary | All executable consent in this build is explicitly `M6_MOCK_ONLY`, issuer `fixture-owner`, signed with public fixture material. It is intentionally incapable of authenticating a real owner or creating live authority. A real signing/identity service is absent and blocked. Browser sessions authorize reads only. |
| Separate executor role/process | `supervised/worker.py` accepts a bounded strict JSON fixture script in a child process. `MockExecutor` accepts only the exact injected `FakeTransport` class and fictional `MOCK_` instruments; it has no real transport/secret/socket implementation. `LiveExecutor` rejects dispatch, cancel and resume. Existing live gate/adapter refusals remain unchanged. |
| Revalidation and fencing | Each account write locks its account row (PostgreSQL) or uses BEGIN IMMEDIATE (SQLite fixture). Startup advances a durable executor generation and requires fresh explicit resume. Old workers are rejected even if a boot label is reused. A durable attempt precedes I/O; a final trusted clock/consent/risk check holds the account lock through the bounded fake call. |
| Capacity and audit | Cash uses worst permitted price plus fee budget; pending sells reserve inventory. Current reservations feed the existing risk engine, including exposure/turnover/count constraints. Approval consumption, reservation, attempt and before/after audit commit together. Five additive tables have primary/unique/foreign-key constraints. |
| Unknown outcomes | Timeout/exception yields UNKNOWN, retains reserves and pauses. The approval cannot replay; no blind retry, exactly-once broker claim or broker idempotency assumption exists. Restart converts interrupted submission attempts to UNKNOWN. Failed post-response persistence leaves the prior durable attempt for recovery. |
| Broker approval | A mock broker-required approval remains a separate state/reference. App approval does not clear it or cause resubmission. Only an independent fake broker observation can advance that state. Actual broker schema/approval verification remains external and blocked. |
| Fills/cancel/reconciliation | Stable fills deduplicate, partial fills retain remaining capacity, entry/exit fees are counted once, and cancel request differs from confirmation. Fill can win a cancel race. Invalid/conflicting evidence is retained for manual review without changing balances. Reconciliation preserves discrepancies instead of reversing manual/external changes. Pause/revocation do not cancel orders. |
| Read-only website | `/readiness` and `/api/v1/readiness` show requested versus approved capital, unmet runtime prerequisites, exact mock intent/risk/evidence bindings, expiry, consumed/revoked approvals and bounded before/after events. Scope is explicitly simulation/m6-fixture with a proposed supervised target mode. Every control POST returns 403, independently of disabled HTML. Counts disclose bounded history coverage. |
| Small-account profile | `config/pilot.simulation.yaml` retains existing risk limits, fictional TEST symbols, false live/shadow flags and zero live capital. Paper/backtest capital is USD 1,000. An unaffordable whole-share order must HOLD/reject; no fractional/order-type/limit change is made to force feasibility. |

The ordinary simulation profile remains USD 100,000 of fictional money. The
mock affirmative gate fixture uses an in-memory/serialized hypothetical
supervised configuration, not an enabled application profile. Its explicit
MOCK domain is mandatory. Neither its public fixture signer nor a successful
mock gate can be connected to real broker dispatch in this build.

## Reproducible offline commands

From the repository root, with the existing locked Python environment:

```bash
uv sync --locked
uv run trading-agent supervised package
uv run trading-agent supervised demo
uv run pytest tests/supervised -q
uv run ruff check src/trading_agent/supervised tests/supervised src/trading_agent/db/schema.py src/trading_agent/web/app.py src/trading_agent/cli/main.py
uv run mypy --follow-imports=silent -p trading_agent.supervised
```

The demo always runs a new fictional journal under `.data/supervised/mock-<id>/`.
It does not load live credentials or activate a selected runtime configuration.
Each directory preserves the input fixture script, private SQLite journal,
child result, report and unsigned package. A failed run remains for review;
there is no automatic retry. The parent/child PIDs differ; two fictional fills
leave cash 989.990, no reserved cash and an explicit-resume requirement. These
amounts are software fixtures, not investment results.

For optional browser QA of that generated journal (a **fixture server**, not
normal setup):

```bash
uv run python -m tests.supervised.serve_fixture --journal <printed-journal-path> --port 8028
# Separate shell; open http://127.0.0.1:8028/readiness.
# Fixture-only owner token: fixture-m6-web-owner
```

The fixture harness redirects its landing page to Readiness and supplies mock
authentication. It reads/writes only that fixture's local journal and auth rows.
It does not seed or certify the rest of the website. Stop it with Ctrl-C.
Normal `serve` remains blocked by Prompt 10's schema compatibility failure;
do not bypass that guard or treat this harness as a production workaround.

## Actual verification, November 1

- **CODE_PASS:** 66 focused tests, including the two PostgreSQL concurrency/
  fencing tests when the dedicated DB was selected. Tests otherwise skip those
  two honestly. Strict intent mutation tests exercise 18 material fields.
- **CODE_PASS:** repository-only scan of 193 files found no specific provider-token/private-key pattern matches. This is limited pattern evidence, not universal secret detection.
- **CODE_PASS:** scoped Ruff; strict scoped mypy for 11 new source files;
  compileall and JavaScript syntax checks.
- **FAIL retained:** full suite **222 passed / 3 failed**, one upstream
  Starlette/httpx deprecation warning. The three unchanged economic tests are
  `test_regime_earns_paper_test_on_real_data`, `test_whipsaw_trend_is_rejected`,
  and `test_fold_edges_are_benchmarked` in `tests/evaluation/test_econ_eval.py`.
- **FAIL retained:** repository-wide Ruff has 61 findings; mypy has 122 errors
  in 24 files (108 source files checked). New scoped code passes.
- **CODE_PASS:** additive Alembic upgrade to `d8c302b4a611`, inspection of the
  five new tables/columns/foreign keys, downgrade to `c4a7e19b2d05`, and upgrade
  again in a separate disposable database. An unrelated fixture witness was
  preserved. Normal startup still reports the prior schema incompatibilities.
- **CODE_PASS:** Playwright at 1440×1000 and 390×844 against the persisted mock
  journal: exact risk/approval hashes, inactive USD 1,000 draft versus USD 0
  approved, disabled controls, all five control POSTs denied, disclosed audit
  coverage, no horizontal page overflow, zero page errors/external origins.
  Synthetic screenshots were visually inspected. The mock fixture had one
  filled order and 13 committed events; historical approvals correctly appear
  stale/consumed when viewed after their expiry.

Disposable PostgreSQL used a cached postgres:17 image and fictional identity:

```bash
docker run --pull never --name trading-agent-m6-review \
  --publish 127.0.0.1:55433:5432 --env POSTGRES_HOST_AUTH_METHOD=trust \
  --env POSTGRES_USER=review --env POSTGRES_DB=review --detach postgres:17
# Wait for pg_isready, then create m6_review and m6_migrations in this container.
TRADING_AGENT_M6_REVIEW_DB=postgresql+psycopg://review@127.0.0.1:55433/m6_review uv run pytest tests/supervised -q
TRADING_AGENT_REVIEW_DB=postgresql+psycopg://review@127.0.0.1:55433/review TRADING_AGENT_M6_REVIEW_DB=postgresql+psycopg://review@127.0.0.1:55433/m6_review uv run pytest -q
```

The guards accept only these exact disposable URLs. Never run the destructive
fixtures against an existing owner database. The review container and browser
were removed/closed after checks; no other service was stopped. Port 8021 was
occupied, so this review used 8028 without changing the existing service.

Browser command (after fixture login and a fresh snapshot):

```bash
/Users/randygeszvain/.codex/skills/playwright/scripts/playwright_cli.sh -s=m6-review run-code --filename tests/supervised/browser_checks.js
```

Local logs under `.data/m6-review/evidence/` retain focused/full results,
scoped/global lint/types, migrations and browser results. Screenshots are
`output/playwright/m6-readiness-{desktop,narrow}.png`. An initial browser attempt
mixed a hot-reloaded template with old Python projection code; after restarting
the fixture server, the final check passed. Early development test errors were
fixture/import issues, not passing evidence. No prior failed economic evidence,
objective, holdout, or unrelated work was rewritten.

## Owner-run startup, reconciliation, resume, shutdown and revocation

These are a future operational review procedure, **not instructions to activate
this build**. Current supported operation is the offline demo above. Do not
remove the hard dispatch block, complete brokerage onboarding, change approvals,
fund an account or submit an order as part of setup/testing.

1. **Startup review:** resolve the prior schema/pipeline/recovery failures,
   install an independently reviewed frozen release, and verify the complete
   unsigned package with the owner. Independently validate least-privilege OS
   identity, protected secret injection, outbound restrictions, a single
   executor, independent monitoring and stop acknowledgements. No production
   service command or working privileged socket is shipped by this milestone.
2. **Reconcile before resume:** the separately approved owner runtime must
   establish the exact dedicated account and fresh official cash, holdings,
   open orders, fills/corrections and external flows. Preserve UNKNOWN and
   differences; keep reservations until confirmed. Do not resubmit an ambiguous
   attempt or reverse an owner's manual action. Verify cash-flow-adjusted loss
   history and high-water marks after restart/restore. Record evidence rather
   than resetting drawdown or performance history.
3. **Explicit resume:** after an incident/restart and satisfactory reconciliation,
   obtain new expiring consent bound to the current generation/state, unchanged
   approved package and account. Recheck every gate at dispatch. No automatic
   recovery, environment flag, account deposit or UI checkbox renews authority.
   Current `LiveExecutor.resume` and website commands remain denied.
4. **Shutdown/pause:** block new risk first, preserve attempts/audit/reservations,
   inspect outstanding orders and existing exposure, and keep independent
   monitoring/reconciliation running when available. Request entry cancellations
   only through a separately authorized supported path; record confirmations
   individually. Local pause, process exit and token revocation are not
   cancellation or liquidation. A disconnected application cannot guarantee
   any broker action; do not invent an emergency liquidation policy.
5. **Official broker revocation:** the owner must use Robinhood's own account/
   connected-agent controls and follow the current official flow or contact
   [Robinhood Support](https://robinhood.com/contact). First identify the
   exact MCP account and connection, arrange continued independent observation
   of working orders/holdings, revoke that connection through the broker, and
   retain a redacted confirmation. A separately approved read-only runtime must
   then verify revoked authorization is rejected without a mutation. Removing
   a local MCP entry, stopping this program or deleting a local token file does
   not establish server-side revocation. No revocation endpoint, exact menu
   wording, refresh-token behavior or account-specific effect has been attested
   here; record the actual owner-run procedure/evidence before activation. If
   the broker does not expose/confirm it, remain blocked and use official support.

Robinhood's current public [trade-approval documentation](https://robinhood.com/us/en/support/articles/trading-with-your-agent/)
says the broker may require owner review/manual placement, including for some
orders when its general approval setting is off. The application must preserve
that requirement; no fake response proves its account-specific behavior. The
[external-agent onboarding documentation](https://robinhood.com/us/en/support/articles/onboarding-an-external-agent/)
describes broad account read access and dedicated-account trading, which is why
exact downstream account binding remains required. Public documentation was
read without account access. The verified menu path for trade approvals is not
an attestation of a revocation path, and no broker setting was changed.

## Remaining blockers and owner decisions

| Track | Current status / evidence needed |
| --- | --- |
| Software | New M6 mock controls CODE_PASS; upstream migration and integrated recovery/state-machine failures remain FAIL/BLOCKED. Additive M6 migration does not repair or reinterpret prior data tables. |
| Integration/operations | EXTERNAL_VALIDATION_PENDING: official account eligibility, exact schemas/arguments, approvals, minimums/precision/settlement, idempotency semantics, tokens/revocation, real crash/partition/cancel races, deployed privilege isolation, monitor/stop, backup/restore. |
| Investment | EXTERNAL_VALIDATION_PENDING: prospective paper/shadow record, independent decisions, net execution/operating costs, uncertainty, survivorship/dividend and credible strategy evidence. Software fixtures cannot pass it. |
| Owner scope | Account/fingerprint, exact universe/strategy, approved capital (currently zero), all actual risk/loss limits, overnight/session policy, start/expiry, monitoring responsibilities, pilot duration/observation, recovery/revocation and signed consent remain unresolved. |

Separate-process execution was demonstrated; separate OS identities, real secret
injection and a deployed privileged service were **not** established. Only
SQLite fixture and disposable PostgreSQL behavior were tested. No real token,
model inference, financial account, live submission/cancellation, production
restore, prospective session or actual broker approval/revocation was tested.
The frozen research champion, evaluation objectives and existing limits remain
unchanged. Prompt 12 is next only when explicitly selected, with these blockers
still in force. Stop at Prompt 11; no activation or scope expansion.

Current financial authority: **LIVE_NOT_AUTHORIZED**.
