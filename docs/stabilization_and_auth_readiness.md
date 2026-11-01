# Offline stabilization and owner authentication readiness — November 1, 2026

This repair scope follows the owner's request to finish prerequisite work after
Prompts 9–12. It is not a new numbered milestone or financial activation.
Software checks pass below; **real readiness remains BLOCKED**. Approved live
capital is USD 0, real dispatch is unavailable, and automatic change class is NONE.

The owner reports an existing Agentic account containing USD 500, requests no
discretionary limit beyond its balance, and asks for the best algorithm. Account
setup and funds have not been independently verified. The request is recorded in
[pilot500_owner_request.unsigned.json](pilot500_owner_request.unsigned.json), not
applied as a risk-policy change. Existing conservative limits remain intact.
There is no demonstrated best strategy or investment edge.

## Defects, observed evidence, and residual limitations

CODE_PASS means the stated software path passed offline verification. It does
not pass external operations or investment evidence. Historical failed evidence
is retained; the earlier milestone reports describe their original snapshots.

| Material risk / defect | Concrete change and observed result | Status / residual limitation |
| --- | --- | --- |
| Normal CLI/website blocked by incompatible Alembic schema | `f4b020261101` adds missing contracts, preserves three legacy M3 tables under `legacy_m3_*`, and retains unrelated witness rows. Fresh upgrade, legacy-row preservation and populated downgrade refusal pass, including lease-only/fill-only/market-metadata evidence before any ledger exists. | CODE_PASS for disposable fixtures. Existing owner database was not contacted; backup and review before migration remain owner work. |
| Ledger replay depends on timestamp/key ordering; ambiguous legacy ties | Durable per-book `application_seq`, locked assignment, fail-closed ambiguous legacy history, no guessed ordering or old-key rewrite. Recovery tests pass. | CODE_PASS; tied legacy rows require evidence-based manual resolution. |
| Cross-run cash-flow collision and baseline fills missing/mixed | Cash-flow identity includes run/account/book, exact legacy repeats deduplicate, conflicts deny; all fill evidence carries portfolio book. Two native simulation runs coexist and reconcile. | CODE_PASS on synthetic events; real corrections/dividends/external flows still need broker verification. |
| Competing workers and restart duplication | Session advisory lock plus monotonic persisted lease/fence, revalidated under transaction; crash/restart and concurrent worker tests pass. Completed rerun performs no new work. | CODE_PASS; host/process/network-partition operation outside the tested fixture remains pending. |
| Invalid order resurrection/fills | Explicit state transitions, aware monotonic timestamps, quantity bounds and full-fill validation. Meaningful rejection tests pass. | CODE_PASS; broker state/approval semantics are unattested. |
| Same-close lookahead and misleading economic calculations | Signal executes on next listed close; missing execution bar expires it. Initial fees count as loss/drawdown, annualization uses calendar span, net edge is not charged twice, whole units honored. Independently restarted folds chain into an explicitly labeled research index; missing composite sessions are omitted. | CODE_PASS for causal/fee/calendar/whole-unit references; no real execution-price validation. |
| Three historical economic assertions did not describe their inputs | Original test source, dataset hashes, expected/observed failures and unchanged protocol digest retained in [economic expectation review](evidence/economic_expectation_review_20261101.json). The original periodic fixture remains tested; a separately versioned daily whipsaw input rejects. | CODE_PASS for reviewed fixture assertions; no profitability or prospective evidence. Objectives, parameter grid, holdouts and thresholds unchanged. |
| Advisory jobs used incompatible result types/JSON and lost failed jobs | Typed persisted valid/invalid/unavailable outputs, version/data-bound job identities, bounded calls, deterministic capability tasks and denominator. Failure/idempotence tests pass. | CODE_PASS; research remains advisory and cannot activate a strategy. |
| Data status and gateway fixture runtime errors | Cache/property/callback/date types, provider snapshot calls, synthetic gateway and JSON-RPC validation repaired; diagnostics expose exception classes instead of raw bodies. | CODE_PASS; no real feed, credentials or broker transport exercised. |
| Website incomplete read/reconnect/export paths | Normal `serve` works after migration. Scoped repeatable-read bootstrap, signed expiring cursor, bounded events/SSE with explicit gap reset, stale/disconnect handling, synthetic-only redacted CSV, and seven bounded review pages. Tests cover wrong scope, malformed/gapped cursors, outages and zero financial/model effects. | CODE_PASS for exercised paths; rich M5 UX, large-history latency, real-data rights and prospective operation are not certified. |
| Broker secrets entering coding/research | New `owner_runtime/auth.py` requires separate OS identity `ai-trading-executor` before network/browser/private-file access. PKCE/state/issuer/resource/redirect/profile drift, failed exchange, replay and protected-file tests use an injected exact fake transport. Coding-user command denies before creating its directory. | CODE_PASS for tested guards; OS isolation and actual OAuth remain EXTERNAL_VALIDATION_PENDING. Same-user imports are not a sandbox. |
| Mistaking schema discovery for trading permission | Owner flow lists schemas only; no `tools/call`, account enumeration, automatic refresh, authorization or order path. It records schema hash and emits bounded field types, never credentials or account values. | CODE_PASS mocked; actual gateway protocol/schema, account binding and approval behavior EXTERNAL_VALIDATION_PENDING. |
| Independent recovery and loss-history persistence | Synthetic PostgreSQL dump restored into a second disposable database: all 44 table counts and per-run strategy high-water marks reconstructed from equity snapshots match. | CODE_PASS for fixture restore only; production recovery, revocation, monitoring and independent stop remain pending. |
| False live readiness | Existing actual dispatch denial, zero live capital, empty live universe, absent owner authorization and class NONE retained. M6/M7 synthetic tests pass. | BLOCKED for real trading. No live transport, owner signer/activation loader or deployed privileged executor exists. |

## Exact verification

The PostgreSQL tests used only a newly created `postgres:17` container named
`trading-agent-stabilization-review`, bound to `127.0.0.1:55433`. Existing services
on 5432, 5433 and 55432 were untouched. Stabilization tests create and drop their
own uniquely named databases. Other review test suites use the named disposable
review databases; never point these variables at a real store.

```sh
TRADING_AGENT_REVIEW_DB=postgresql+psycopg://review@127.0.0.1:55433/review \
TRADING_AGENT_M6_REVIEW_DB=postgresql+psycopg://review@127.0.0.1:55433/m6_review \
TRADING_AGENT_M7_REVIEW_DB=postgresql+psycopg://review@127.0.0.1:55433/m7_review \
TRADING_AGENT_STABILIZATION_DB=postgresql+psycopg://review@127.0.0.1:55433/stabilization \
uv run pytest -q
```

Observed: **325 passed, 1 existing Starlette/httpx deprecation warning, 54.80s**.
All opted-in database cases ran. Intermediate failures remain under ignored
`.data/stabilization/evidence/`; final result is `full-publication-final.txt`.

| Command / check | Observed result |
| --- | --- |
| `uv run ruff check src tests` | PASS, full source and tests |
| `uv run mypy` | PASS, 124 source files |
| `uv run python -m compileall -q src tests` | PASS |
| `node --check src/trading_agent/web/static/app.js`; `node --check tests/stabilization/browser_checks.js` | PASS |
| `uv run trading-agent check-config --config config/pilot500.simulation.yaml` | Valid simulation, live disabled/zero, synthetic only |
| `uv run trading-agent data status` | PASS; disabled uncached external sources reported without fetching |
| `uv run trading-agent backtest run --config config/pilot500.simulation.yaml --out-dir .data/stabilization/backtests` | Synthetic report created; no real data or orders |
| Dedicated review profile + `uv run trading-agent migrate`; `uv run trading-agent demo` twice | Migration head `f4b020261101`; completed run, then `already-complete` without duplicate writes |
| Normal CLI `serve --config .data/stabilization/review-config.yaml --port 8028`, Playwright `-s=stabilization-review run-code --filename tests/stabilization/browser_checks.js` | Public synthetic login fixture; seven review pages, overview consistency, export, cursor scope/gap, 27 orders/48 strategy fills, desktop 1440×1000 and narrow 390×844; zero page errors/external requests |
| `uv run trading-agent owner-auth login --runtime-dir .data/stabilization/must-not-exist` as coding user | Exit 2, separate runtime identity required; no directory, browser or OAuth operation |

Browser screenshots were visually inspected. The owned review server/browser/
container are stopped after review; evidence and fixture backup remain local and
ignored. This is not a deployment. Full wheel-only installation and large-history
performance acceptance were not rerun/certified.

The [publication verification receipt](evidence/stabilization_verification_20261101.json)
records the bounded repository-only secret-pattern review, preserved source hash
and synthetic restore comparison. Only a pre-existing fictional credential-URL
rejection fixture matched. Pattern scans cannot prove the absence of every secret.

The readiness/autonomy pages explicitly identify their original USD 1,000
worksheets as historical and display the newer USD 500 request as unverified
and inactive. Historical package blocker text is not a current failure result.

## USD 500 feasibility observation

The normal persisted 128-session fixture run `sim-9342bacdbda13687` records
384 decisions, **zero strategy orders/fills**, and no holdings. Cash, strategy
NAV and cash baseline are `507.77790481`; passive synthetic NAV is `479.23404376`.
The simulated cash yield is a fixture assumption, not actual account interest or
profit. Whole-share and existing order limits are preserved. A second larger
fixture run `sim-7c59193abae1c584` records 27 strategy orders/48 strategy fills
and reconciles, so the no-trade result was not hidden by a missing execution path.
No risk widening, asset selection or strategy promotion was used to force trades.

## Local model and public metadata observations

The existing loopback LM Studio endpoint listed `qwen/qwen3.8-27b`. Two harmless
synthetic probes (missing evidence and injected instructions) returned parsed
HOLD with `missing_evidence`, in 3797ms and 2212ms. No financial/private evidence
was sent, no cloud fallback/weights download/global configuration change occurred.
This is a functional smoke check, not strategy validation, artifact attestation,
or a complete capability assessment. Anonymous local requests succeeded;
protected inference configuration remains owner-operated work. See
[LM Studio authentication](https://lmstudio.ai/docs/developer/core/authentication).

Only unauthenticated public OAuth metadata was fetched from official hosts;
[evidence](evidence/public_oauth_metadata_20261101.json) pins endpoints, PKCE S256,
public-client auth, resource and issuer. The advertised scope is `internal`, not
an attested read-only scope. Robinhood documents broad account read access and
Agentic-account-only trading in [external onboarding](https://robinhood.com/us/en/support/articles/agentic-trading-overview/).
Broker approvals vary and some trades still require approval; app approval cannot
override [Robinhood approvals](https://robinhood.com/us/en/support/articles/trading-with-your-agent/).
No registration, token exchange, protected MCP request, account read or real
financial mutation was performed by this review.

## Remaining prerequisites, in order

1. Owner reviews this source and runs the isolated [owner-runtime setup](owner_runtime_setup.md), completing official browser consent privately. This is integration work, not activation. No credentials belong in chat or the coding OS account.
2. Validate the observed protocol/schemas and implement a strictly allowlisted account-scoped read normalizer using actual official facts. Verify the dedicated account and settled cash privately; broader account data must not reach research or website exports.
3. Complete real data provenance/rights, fresh reconciliation, broker approval/ambiguous-submit/revocation semantics, separate signing/executor/monitor permissions, independent stop, recovery and alert delivery. Offline tests cannot pass these external checks.
4. Accumulate a prospective paper/shadow record and compare frozen strategies against cash/passive after costs and uncertainty. No validated live algorithm is selected by this work.
5. Resolve and sign an exact account-bound expiring owner package: assets, capital, strategy/model/prompt/policy versions, order/session/overnight permissions, loss/history rules, monitoring and recovery. The balance-only preference remains recorded but does not satisfy these bindings.
6. Only separately reviewed implementation and explicit activation could establish a real executor path. This delivered configuration has none; changing an environment flag or refreshing the dashboard cannot activate it.

There is no Prompt 13. No real authorization, automatic renewal/promotion,
account funding, broker mutation, alert sending or production deployment occurred.
**Current financial authority: LIVE_NOT_AUTHORIZED.**
