# Prompt 10 — Security and failure readiness review

Date: November 1, 2026. Scope: local code, synthetic persisted records, disposable
PostgreSQL 17, localhost model-transport canary, and mocked broker transport.
Branch: `codex/security-readiness`, based on local Prompt 9 commit `c2612a3`.
No account authentication, broker request, alert, cloud inference, paid data,
production mutation, deployment, push, or live promotion was performed.

**Overall readiness: FAIL.** Concrete boundary defects are patched and scoped
checks pass, but migration compatibility, integrated recovery/execution, and
economic evidence remain inadequate. Approved live capital remains USD 0.
The build-level activation check always denies live dispatch, including with a
fully populated hypothetical authorization and healthy runtime. Research
promotion still always rejects activation. This review does not execute Prompt 11.

## Evidence vocabulary

- **CODE_PASS:** the named local property was observed using the stated fixture
  or test. It certifies neither all surrounding code nor an external service.
- **EXTERNAL_VALIDATION_PENDING:** a real service/owner-operated integration or
  prospective observation is necessary; mocks cannot establish it.
- **BLOCKED:** a prerequisite or implementation is absent; dependent operation
  must remain disabled.
- **FAIL:** a demonstrated defect or violated requirement remains unresolved.

## Prioritized findings and disposition

| Priority / ID | Finding | Disposition |
| --- | --- | --- |
| P0 S01 | Risk evaluation recorded REDUCE but returned the original quantity; the baseline fixture returned 1,000 shares after sizing to its cap. A caller-supplied protective flag also exempted BUY from entry controls. | Fixed: return actual reduced quantity, zero on rejection, forbid protective BUY. Fresh account/price, identity/version binding, pending gross exposure and fee-inclusive cash floor added. Focused risk checks pass. |
| P0 S02 | Authority could be advertised from one flag; hypothetical verified broker plus supplied runtime could satisfy the activation gate. | Fixed: authority remains LIVE_NOT_AUTHORIZED and unconditional build prohibition survives forged healthy runtime. Simulator rejects live cancel; official adapter submit/cancel return rejection without dispatch. |
| P1 S03 | Wildcard endpoints counted as loopback; model redirects could forward a bearer; public MCP call permitted absent allowlist, mismatched RPC responses, and legacy arbitrary dispatch. Secondary OAuth followed unverified discovery routes. | Fixed: endpoint validation, no redirects/proxy for local model/data clients, exact official broker origin, explicit read set, response identity, bounded/classified model errors. Legacy OAuth/dispatch quarantined. Real account-scoped gateway is disabled pending verified integration; no credentials loaded by normal disabled construction. |
| P1 S04 | Logout deleted a row but signed-cookie replay still authenticated. GET logout mutated state, missing login Origin accepted, Host ignored port. Bootstrap briefly wrote permissive files and printed its token. | Fixed: persisted session revocation/expiry checked on every authenticated request, nonce sessions, POST logout and exact Origin, exact Host/port, protected atomic mode-0600 files, no token print, symlink/public-permission rejection. |
| P1 S05 | Core website queries returned scalar IDs instead of rows; a requested run could escape configured account/mode scope. Page bootstrap did not run correctly; run selection was lost. | Fixed: full rows, scoped run resolution and bounded run listing, correct template API/page bootstrap, preserved run navigation. PostgreSQL read transactions use repeatable-read/read-only. |
| P1 S06 | Buy fees reduced cash but not realized cost basis. Raw-fill redelivery under a new delivery ID could apply twice; replay guessed missing side. Audit-write failures left reusable dirty memory and stale writers could overwrite accounting. | Fixed: buy fees in basis and replay, raw-ID/fingerprint deduplication, missing side/correction rejection, run-row lock and stale-writer rejection, poisoned instance after write failure. Reconstruct after rollback. Fixture cash is 1,008 and realized P&L 8, including restore. |
| P1 S07 | Equal-time ledger history sorted by hashed event key can restore the wrong cash. | Partially contained: restart rejects ambiguous equal-timestamp history instead of guessing. **BLOCKED:** durable application ordering and audited migration/replay of such histories remain required. Original failing evidence retained; no timestamps/history rewritten. |
| P1 S08 | Alembic head does not match current SQLAlchemy metadata. A normal installation could appear migrated and then fail at reads. | **FAIL:** fresh migration reaches `c4a7e19b2d05` but lacks required columns/tables. Startup now checks compatibility and blocks clearly. Existing alternate data-table contracts need a reviewed migration; this review does not silently reinterpret stored data. |
| P1 S09 | Duplicate jobs/account reservations lack a demonstrated owner lease/fencing protocol; `Order.transition` accepts arbitrary transitions. Simulator-only reconciliation does not implement real broker corrections/manual trades/external-flow recovery. | **FAIL:** integrated M1/M3 execution/recovery is incomplete. Hard live prohibition contains financial reach, but these components are not approved for unattended trading. |
| P1 S10 | Old file backtest can signal and fill at the same close; three existing economic verdict/fold tests fail. Universe/dividend/corporate-action/prospective evidence is incomplete. | **FAIL:** objectives, holdouts and failing tests preserved. Narrow defects fixed: passive benchmark must afford fees, average composite begins with full capital rather than capital divided twice, mixed provenance uses instrument classification. No investment-readiness claim. |
| P1 S11 | Independent stop/watchdog, privileged runtime isolation, full M5 controls, streams, exports and operational recovery are absent/unverified. | **BLOCKED:** a browser or coding session is not an independent monitor. A pause blocks new modeled risk; it cannot cancel or liquidate a disconnected real account. |
| P2 S12 | Missing marks could become zero-valued NAV, evidence strings could become markup/formulas, error bodies could expose secrets, and money display lost precision. Browser price view omitted API-declared gaps. | Fixed for reviewed paths: unavailable NAV, escaped/redacted evidence, CSV formula neutralization, exact decimal text, generic errors, explicit missing rows/flags, responsive authority labels. Pattern redaction is not universal secret detection; exports/streams remain incomplete. |

## Trust boundary: implemented versus intended

| Plane | Enforced local boundary | Residual limitation |
| --- | --- | --- |
| Coding | Source/test development only; no live credentials were read or account calls made in this review. | Same-owner Python imports/filesystem are not an OS sandbox. The repository cannot prove an arbitrary host has no credentials. |
| Research | Bounded loopback inference; sanitized input/strict output; M8 immutable champion, fixed search/protocol/trial budget and no activation method. Operational memory has no strategy/prompt/weight mutation path in the tested workflow. | A model's text remains untrusted. No live model integration was tested here; journal writes are not weight training. |
| Owner controls | Website session authenticates read access only. Config is typed, but flags/references cannot issue financial authority. | No owner authorization workflow/signature service or complete control UI exists. Owner-edited YAML is not an activation certificate. |
| Privileged execution | Live gate always denies; official adapter rejects mutations; real gateway/OAuth paths quarantined. Explicit mocked transport permits code tests only. | No separately deployed executor, credential injection, account-scoped official-tool binding, least-privilege DB roles, or independently verified broker behavior. |
| Monitoring | Persisted health/reconciliation read views and research pause rules. Unknown/missing state remains visible. | No independently operated watchdog/stop service, disconnected acknowledgement, or broker-side cancellation guarantee. |

Future runtime secrets must be injected/stored by a separately operated owner
runtime outside source, fixtures, reports and model context. The protected-file
helper checks ownership, regular-file status, no symlink, size and exact 0600
mode; replacement starts private and bootstrap is exclusive. These checks do
not supply process isolation or an operating-system keychain deployment.

Transport response matching and conservative read restrictions were checked
against the public [MCP transport specification](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports).
Tool names used in mocks are fixture names, not evidence of Robinhood's current
capabilities, authorization mechanism, response schema or account scope.

## Material-risk evidence matrix

Paths below are repository-relative. Test names identify the actual assertion,
not a general claim that a feature is complete.

| Risk | Implementation / evidence | Observed result | Residual / status |
| --- | --- | --- | --- |
| Unauthorized authority/mode change | `config/models.py`, `gates/live_activation.py`; `tests/security/test_boundaries.py::test_forged_runtime_cannot_activate_and_broker_mutations_never_dispatch`, existing activation/property tests | Even hypothetical healthy runtime cannot activate; mutation methods reject. | **CODE_PASS** for prohibition. Genuine owner activation service **BLOCKED**. |
| Authorization expiry | Existing `tests/unit/test_live_activation_gate.py::test_expired_authorization_is_unmet`; persisted web expiry/logout regression | Expired prerequisite/session denied; logout replay 401. | **CODE_PASS**; real broker token expiration **EXTERNAL_VALIDATION_PENDING**. |
| Reduced quantities, protective flag, stale state, clock skew | `risk/engine.py`; all four `tests/security/test_risk.py` cases | Actual cap returned; BUY cannot claim protective exemption; expired/future/stale/paused/binding/unknown-HWM states reject. Pending entries count toward gross. | **CODE_PASS** for supplied-state engine. Reliable production state acquisition **BLOCKED**. |
| Repositories/fixtures contain secrets | Bounded repository-only pattern scan of 169 current files and 8 revisions | No provider-token/private-key pattern matches. Fixture credentials are explicitly fictional. No unrelated personal files/private stores inspected. | **CODE_PASS** for limited scan only; arbitrary secret formats/history outside refs unverified. |
| Secret storage, logs, model context | `security/files.py`, `execution/credentials.py`, `research/model_client.py`, `config/loading.py`; protected-file, redirect-canary, config-error, structured-output regressions | Symlink/public mode rejected; canary not forwarded or echoed; malformed config withheld. Free-form website evidence redacted; exact money retained. | **CODE_PASS** for canaries. Separately operated secret injection/storage **BLOCKED**; global absence cannot be proven by regex. |
| Tool allowlist/schema drift | `execution/capability.py`, both MCP transports; schema/duplicate/legacy-dispatch regression | Missing read set, write name, changed/duplicate schema, tools/call on legacy transport denied before mocked wire. | **CODE_PASS**. Actual official names/schemas/account-scoped arguments **EXTERNAL_VALIDATION_PENDING**. |
| URL/redirect/response confusion | `security/loopback.py`, model/MCP/data clients; wildcard/userinfo, redirect/wrong-id and cache traversal tests | Wildcards and credential-bearing URLs denied; redirect only initial canary request; wrong RPC ID rejected; cache cannot escape root. | **CODE_PASS**. DNS/host/process compromise not simulated. Real gateway disabled. |
| Prompt injection / malformed output | `research/evaluation.py`; structured-output test plus M8 frozen champion/memory tests | Extra tool fields/wrong types denied; untrusted browser text escaped; failed research cannot edit champion/policy/prompt/feature settings. | **CODE_PASS** for these interfaces; model output never authorizes financial actions. |
| Duplicate fills / correction conflict | `ledger/ledger.py`; fee/restart and raw-redelivery tests | Same raw fill under different delivery ID is no-op; conflicting duplicate/corrected input requires review. | **CODE_PASS** containment. Arbitrary broker correction/reversal accounting **BLOCKED**. |
| Concurrent ledger writes / audit outage | Ledger stale-writer/audit-failure regression on PostgreSQL | Second stale writer rejects after first commit; audit failure rolls back; failed object cannot be reused; reconstructed cash remains 400. | **CODE_PASS** for ledger. Atomic account-wide reservations/job leases **FAIL** (S09). |
| Duplicate jobs/concurrent reservations | `engine/pipeline.py::run`, `_reserve`; static review | Run lookup then insert is not a demonstrated fencing/lease scheme; reservation records use fencing_token=0. | **FAIL**; no integrated concurrency assurance, no live execution allowed. |
| Ambiguous submission/cancel-fill race | Persisted UNKNOWN order with two partial fills and active reservation; browser + API checks | UNKNOWN and both fills retained; cancel-request event displayed without invented success. | **CODE_PASS** read representation only. Arbitrary lifecycle transitions and real cancel/fill ordering **FAIL / EXTERNAL_VALIDATION_PENDING**. |
| Broker corrections/manual trades/external flows | Simulator-only reconciliation inspected; persisted correction linkage and cash-flow ledger tests | Correction predecessor retained; ledger cash-flow/restore observed. No real recovery or external-flow-adjusted return verified. | **BLOCKED** integration; actual account behavior **EXTERNAL_VALIDATION_PENDING**. |
| Crash/restart / deterministic replay | Ledger restart regression; equal-timestamp witness; M8 content-addressed store tests | Unique-time fixture replays exact fees/P&L; ambiguous-time history now refuses replay; failed audit instance stays unusable. | **CODE_PASS** narrow cases. Ambiguous historical replay **BLOCKED**; full pipeline crash/fencing recovery **FAIL**. |
| Database outage / audit-write failure | Persisted web DB-partition/read-write rejection tests; ledger injected write failure | Signed session fails 503 if DB unavailable; read transaction cannot delete runs; rollback/reconstruct required after audit failure. | **CODE_PASS** injection tests. Long partition/recovery service deployment **EXTERNAL_VALIDATION_PENDING**. |
| Backup/restore/drawdown history | Synthetic `pg_dump -Fc` and `pg_restore --exit-on-error` into separate disposable DB | All 25 table counts match; cash 1,008, realized P&L 8, historical max equity 1,200 retained after restore. | **CODE_PASS** fixture only; no production backup or restore-to-service approval. |
| Startup/schema compatibility | Fresh Alembic upgrade plus metadata comparison; schema-drift regression | Head stamp succeeds but incompatible schema now raises `MigrationError` before service startup. Missing columns/table names recorded below. | **FAIL** migration chain; fail-closed check **CODE_PASS**. |
| Independent stop/disconnected behavior | Risk paused-state regression; M8 shadow/drift pause tests; static monitoring review | Supplied pause blocks new modeled entry; research alert cannot choose replacement. | **CODE_PASS** local predicates. Independent monitor/owner stop controls **BLOCKED**. No disconnected cancellation claim. |
| Training/evaluation leakage/hidden trials | Existing `tests/learning/test_research_workflow.py` holdout, causal-fill, trial-budget, immutability and tamper tests | Fixed M8 protocol/holdout, every trial/failure, costs and failed evidence preserved; champion cannot activate. | **CODE_PASS** research fixture. Older file backtest same-close path **FAIL**; prospective track record **EXTERNAL_VALIDATION_PENDING**. |
| Survivorship/dividends/costs/false readiness | Existing economic tests, execution-model cost tests; passive-affordability regression; source provenance review | Corrected narrow fee/basis/benchmark defects; three economic tests still fail unchanged. No universe/dividend evidence can be inferred from synthetic fixtures. | **FAIL** investment readiness; real point-in-time coverage/total-return validation **EXTERNAL_VALIDATION_PENDING**. |
| Website auth/CSRF/Host/Origin/session | `web/auth.py`, `web/app.py`; persisted authentication tests; browser login/logout | Unauthenticated API 401; bad/missing login Origin 403; wrong port 403; GET logout 405; logout replay/expired cookie 401. | **CODE_PASS** scoped loopback HTTP. TLS/remote exposure not authorized/tested. |
| Website account/mode/run isolation | `web/queries.py::_run_scope/resolve_run`; persisted API checks for every core endpoint | Only local-sim simulation fixture appears; alien account and paper run cannot be selected. Navigation retains run_id. | **CODE_PASS** tested scope; no approved real account connected. |
| Escaped evidence / redacted exports | Escaping in templates/`app.js`; `security/exports.py`; API redaction, CSV formula tests and browser injection canary | Literal script/image text does not create executable markup; private-key fields/bearer canary redacted. CSV formulas inert; negative amounts preserved exactly. | **CODE_PASS** reviewed paths. Pattern redaction is limited; full website exports absent (**BLOCKED**). |
| Financial snapshots / missing amounts | Repeatable-read/read-only sessions; `web/queries.py`, ledger missing-mark guard; persisted decimal/missing-NAV tests | Cash `123456789.12345678` exact; missing held mark yields null NAV/exposure including curve, never zero. Browser shows unavailable and explicit session gap. | **CODE_PASS** per request; multi-request atomic bootstrap/version handshake absent (**BLOCKED**). |
| Read-only browser / no inference | Persisted-view test forbids client construction and compares all table counts; read-only SQL failure; browser requests recorded | Every core API/page reads successfully; no state change or model/broker construction; only loopback browser requests. | **CODE_PASS** for delivered routes. Authentication writes are explicit login/logout exceptions. |
| Stream gaps/reconnect, stale responses | No stream route; aborted positions fetch in real browser; persisted gap fixture | Stream/export endpoints return 404; fetch failure shows unavailable warning; missing session displayed. No fabricated stream resume. | **CODE_PASS** failure display only. SSE cursor/gap/reconnect contract **BLOCKED**. |
| Full website failure scenarios | Overview/Activity/Orders/detail/Portfolio/instrument exercised; missing order/instrument API, gap, UNKNOWN, correction, auth and DB failures | Core persisted scenarios exercised with desktop/narrow viewport and screenshots. | Remaining spec pages (data/research/risk controls/performance/health/alerts/audit), complete replay/exports and all M5 browser scenarios **BLOCKED**. |

## Actual commands and results

The review PostgreSQL service was an owned, disposable container bound only to
`127.0.0.1:55433`, using fictional `review` identity, no account credentials, and
a cached image (no pull). It was removed after checks. Never point these destructive
fixture tests at an existing owner database. The env guard accepts only the exact
review URL; it does not make another service on that port disposable.

```bash
docker run --pull never --name trading-agent-security-review \
  --publish 127.0.0.1:55433:5432 --env POSTGRES_HOST_AUTH_METHOD=trust \
  --env POSTGRES_USER=review --env POSTGRES_DB=review --detach postgres:17
TRADING_AGENT_REVIEW_DB=postgresql+psycopg://review@127.0.0.1:55433/review uv run pytest -q
```

Final suite: **156 passed, 3 failed**, one upstream Starlette/httpx deprecation
warning. No skipped review database cases. The failures remain:

- `tests/evaluation/test_econ_eval.py::test_regime_earns_paper_test_on_real_data`
- `tests/evaluation/test_econ_eval.py::test_whipsaw_trend_is_rejected`
- `tests/evaluation/test_econ_eval.py::test_fold_edges_are_benchmarked`

The unchanged economic assertions disagree with verdict/fold behavior (observed
positive fold share 1.0 vs expected 0.8; whipsaw paper_test vs reject; first fold
edge +0.250493 vs expected negative). No test was weakened to hide these results.
The existing adequate M8/evaluation/unit/property checks were reused. New tests
cover actual uncovered boundaries/fixes in `tests/security/`.

```bash
TRADING_AGENT_REVIEW_DB=postgresql+psycopg://review@127.0.0.1:55433/review uv run pytest tests/security -q
uv run ruff check src/trading_agent/security tests/security tests/auth_helpers.py src/trading_agent/db/migrate.py
uv run ruff check src tests
uv run mypy
uv run python -m compileall -q src tests
node --check src/trading_agent/web/static/app.js
```

All **29** scoped security tests pass. The scoped Ruff command passes; the
repository-wide Ruff check reports **61 findings**, and mypy reports **122 errors
in 24 files** (97 source files checked). Compilation and JavaScript syntax pass.

Browser harness (the fixture server deliberately uses `metadata.create_all` to
exercise current read contracts independently of the broken migration chain):

```bash
TRADING_AGENT_REVIEW_DB=postgresql+psycopg://review@127.0.0.1:55433/review uv run python -m tests.security.serve_fixture
# Separate shell; fixture credentials only. Use a named Playwright session.
/Users/randygeszvain/.codex/skills/playwright/scripts/playwright_cli.sh -s=security-review open http://127.0.0.1:8020
# snapshot, fill the Owner token control with fixture-browser-owner, click Sign in
/Users/randygeszvain/.codex/skills/playwright/scripts/playwright_cli.sh -s=security-review run-code --filename tests/security/browser_checks.js
```

Browser script passed its assertions; zero JavaScript page errors and zero
external request origins. Initial favicon 404 and intentional aborted fetch are
noted separately from page exceptions. An initial browser run caught the hidden
missing-session defect; after the fix, the missing row/flag and authority label
were visually verified at 390px. Local screenshots are under
`output/playwright/security-review/`; logs under `.data/security-review/` are
ignored local synthetic artifacts, not distributed secrets.

Backup commands were `docker exec trading-agent-security-review pg_dump -U review
-d review -Fc` (captured to a private synthetic dump), `createdb -U review
review_restore`, and `docker exec -i trading-agent-security-review pg_restore -U
review -d review_restore --exit-on-error`. Source/restored table counts, ledger
cash/P&L and maximum historical equity were asserted in SQLAlchemy sessions.

Fresh installation was separately upgraded in `review_migrations` using
`run_migrations(config)` with that disposable URL. Missing compatibility includes
`market_bars.session_id/exchange_timezone`, `broker_snapshots`,
`broker_gateway_events`, and current columns in `data_snapshots`, `source_registry`
and `data_quality`. The new startup guard reports all names without credentials.
The schema-drift regression proves that guard blocks an incompatible DB; it does
not repair the migration history.

Failed pre-fix evidence remains locally in `.data/security-review/`:
`before.txt` (eight original regressions), `baseline-risk-witness.json` (original
risk behavior loaded from HEAD), `equal-timestamp-before.txt`, and `browser.txt`.
An initial risk-test run had an invalid test constructor; it is not evidence of
an application failure. Later correct baseline witness demonstrates S01. Final
logs: `full-final.txt`, `browser-final.txt`, `restore.txt`, `migration-final.txt`,
`secret-scan.json`, `lint-final.txt`, `mypy-final.txt`.

## Recovery and owner-operated checks that remain

Before any future operational restore, stop application workers and the website;
keep dispatch disabled. Restore into an isolated target, verify checksums/schema,
all ledger events/fills/corrections, cash/positions, historical high-water marks
and external flows. Ambiguous ordering must be reviewed, not re-timestamped.
Reconcile independently before resuming even paper processing. Rotate the owner
auth/signing file outside the DB after restore: an old backup can resurrect
session rows revoked after that backup, so DB restore alone cannot preserve
revocation. Do not treat a successful `pg_restore` as authorization.

Owner-operated integration checks were **not run**: actual broker authentication,
capability/account binding, partitions/ambiguous submissions/cancel-fill races,
manual trades/corrections/dividends, token refresh/expiry, separately injected
secrets, service restart/independent stop/watchdog, production restore and
prospective challenger/paper track record. They remain pending or blocked above.
No mocks can pass those checks. Do not run a future real-account check from this
coding environment or use unofficial API/browser workarounds.

Next numbered task is Prompt 11 only when selected, and it would remain blocked
on upstream readiness failures. First resolve S07–S11 with separately scoped,
reviewed work; do not silently advance milestones, alter holdouts, authorize,
deploy, or increase capital.

Current financial authority: **LIVE_NOT_AUTHORIZED**.
