# Disabled operational readiness — November 1, 2026

The owner separately selected email alerts, pre-close exits, reconciliation and
execution-readiness repairs. The offline implementation is **CODE_PASS**. Actual
activation is **BLOCKED**: live executor unavailable, real owner authorization
absent, approved live capital zero. Financial authority: **LIVE_NOT_AUTHORIZED**.
This is upstream repair work, not a new numbered prompt or completed M4/M5 pilot.
Historical reports and failed economic results remain unchanged.

## What changed

`operations/` adds a durable operational journal, bounded mail outbox, independent
health monitor, calendar-bound closeout controller, exact reconciliation contracts,
read-only ledger adapter, evidence report and deterministic integrated demo.
Owner-only Gmail transport lives behind `owner_runtime/email.py`. No broker
transport, actual strategy, capital or activation permission was added.

The additive Alembic head is `a61120261101`, following `f4b020261101`. It creates
five operational tables. Empty downgrade/upgrade works; downgrade refuses any
nonempty operational table. Financial history is never discarded to migrate.
Existing M7 mock-schema checks include these tables. The frozen execution-code
manifest includes the operational modules relevant to dispatch/health; modifying
them invalidates existing synthetic frozen artifacts.

## Evidence matrix

| Material risk | Implementation and observed check | Result / remaining limit |
| --- | --- | --- |
| Email leaks broker text or credentials | Fixed event codes and hash references only; private profile; no free-text broker data. Browser reads cannot construct sender/model/executor (`tests/operations/test_email.py`, `test_web.py`). | CODE_PASS; no real credential was read. |
| Duplicate mail, concurrency, crash or ambiguous SMTP DATA | Durable attempt before I/O, consent lock, message CAS, stable Message-ID, bounded retry only after definite negative response. UNKNOWN/SENDING recovery never automatically resends. Two-worker SQLite and PostgreSQL checks. | CODE_PASS; Message-ID is not a Gmail deduplication guarantee. |
| Audit outage or stale/wrong consent | Before-I/O failure sends nothing; after-I/O failure leaves recoverable ambiguity. Exact profile/run/scope/purpose/expiry/message budget required. Cross-run consent and acknowledgment rejected. | CODE_PASS; owner-issued mail consent is separate from financial authority. |
| Owner acknowledgment erased by delayed sender | Slow sender/recovery/owner acknowledgment regression preserves ACKNOWLEDGED and original attempt evidence. Failed resolution retains UNKNOWN/REJECTED; a later fresh acknowledgment is required. | CODE_PASS; SMTP acceptance alone is never inbox receipt. |
| Insecure mail transport | Fixed `smtp.gmail.com:465`, verified TLS >=1.2, credential supplier only at owner-runtime dispatch. Real local TLS SMTP sink exercises accepted DATA and connection loss. Fixture domain is rejected by GmailSender. | CODE_PASS for code/local TLS; actual Gmail and inbox/response drill EXTERNAL_VALIDATION_PENDING. |
| Executor death, stale/future health, restart, clock rewind | Separate-process test sees missing executor; persisted incident episodes avoid unchanged-alert floods. Monitor has no broker credential/dispatch interface and never resumes, renews or changes loss history. | CODE_PASS; deployed independence, durable health publisher and escalation drill EXTERNAL_VALIDATION_PENDING. |
| Entry after cutoff or mutable exit settings | Policy and explicit sessions/calendar digest bound into frozen mock envelope; checks run at reservation and final dispatch even if controller was not ticked. Failed/expired mail health denies new buys. | CODE_PASS; proposed timing is unapproved for real operation. |
| Closeout double-sell or manual position liquidation | Account fence, current strategy/run fill ownership, stable durable closeout job, cancel own working entries then fresh reconciliation, observe partial fills rather than submit another exit. Manual same-symbol or unrelated exposure blocks. | CODE_PASS on exact fake transport only. |
| False flat claim / unfilled exit / unknown broker state | Strict freshness on actual snapshot plus report; content-addressed persisted input/report proof and current ledger binding. FLAT requires observed zero and no orders. Missed deadline/unknown state pauses and preserves exposure/reservations. Regular and early-close cases tested. | CODE_PASS; no guaranteed liquidation during halts, outages, expired authority or broker approval. No market fallback or real protective authority. |
| False reconciliation from incomplete inventory or buying power | Nine required collections, account/run/mode/schema/source/currency/window binding, exact Decimal amounts, duplicates/unknown orders/approvals/audit differences. Settled cash remains UNKNOWN when missing. | CODE_PASS; official schema-bound read collector and actual settled-funds observations EXTERNAL_VALIDATION_PENDING. |
| Broker corrections overwrite accounting | Original and corrected observations/results append independently. Existing core ledger adapter refuses absent/wrong-account history and performs no seeding, flush or correction. PostgreSQL test confirms fills/ledger/snapshot counts unchanged. | CODE_PASS; native prior observations are not local-ledger reconciliation. |
| Migration or database failure destroys evidence | Normal PostgreSQL migrations, empty roundtrip, unrelated witness retention and populated-downgrade refusal; existing outage/recovery tests reused in full suite. | CODE_PASS on disposable PostgreSQL; owner production backup/restore drill pending. |
| Website reads gain authority or expose owner choices | Authenticated `/operations` and `/api/v1/operations`, scoped persisted fixture view, repeatable-read transaction, generic unavailable errors, all control POSTs 403. Browser checks desktop/narrow, foreign Origin, empty alien run, disabled controls; no external requests. | CODE_PASS; projection is bounded to 100 records/collection and is not a full-history certificate. |
| Software evidence becomes live permission or investment claim | `operations.readiness` fixes real executor/authorization/capital to false/false/0; even all external evidence flags cannot activate. Existing M6/M7 denial/adversarial tests reused. | CODE_PASS for denial. Activation BLOCKED; broker/operations and prospective investment EXTERNAL_VALIDATION_PENDING. |

## Pre-close proposal, not owner approval

Synthetic fixtures bind entry cutoff 30 minutes, entry cancellation 20 minutes,
exit start 15 minutes and flat confirmation deadline 5 minutes before the declared
regular-session close. These are engineering proposals, not approved real limits.
A limit sell uses the frozen champion's already-permitted held-position exit,
current quote/tick bounds and existing risk/authorization/reservation/final-wire
checks. There is no emergency market conversion or discretionary price widening.
A session may be closed early; do not infer close from a weekday or fixed UTC hour.
The November 27, 2026 early-close fixture follows the published
[Nasdaq calendar](https://nasdaqtrader.com/Trader.aspx?id=Calendar). Owner-run
calendar/broker validation for the actual intended pilot dates remains pending.

Only attributable pilot holdings and orders can be managed. Unexpected/manual
holdings, unknown orders or incomplete inventory stop dependent action. Missing
reconciliation never means an empty account. An email, pause, cancel request or
planned sale does not establish that holdings were liquidated. A failed exit can
leave overnight exposure; the code records/escalates this rather than asserting
that the requested overnight constraint was achieved.

## Exact verification and reproducible demo

The tests used the owned disposable `postgres:17` container
`trading-agent-operations-review`, bound only to `127.0.0.1:55433`. They never
connected to the normal project, dissertation or hockey databases. Review DBs
were freshly created; the stabilization fixture creates/drops only unique child
DBs. No broker or Gmail was contacted. The container and browser/server were
stopped after verification.

```sh
TRADING_AGENT_REVIEW_DB=postgresql+psycopg://review@127.0.0.1:55433/review \
TRADING_AGENT_M6_REVIEW_DB=postgresql+psycopg://review@127.0.0.1:55433/m6_review \
TRADING_AGENT_M7_REVIEW_DB=postgresql+psycopg://review@127.0.0.1:55433/m7_review \
TRADING_AGENT_STABILIZATION_DB=postgresql+psycopg://review@127.0.0.1:55433/stabilization \
uv run pytest -q
uv run ruff check src tests
uv run mypy
uv run trading-agent operations demo --out-dir .data/operations-review
uv run trading-agent check-config
```

Actual results: **376 passed**, one Starlette/httpx deprecation warning, **65.91s**;
Ruff PASS; mypy PASS across **135 source files**. Changed Python files pass
format checks; the optional whole-tree formatter still flags two pre-existing
unrelated files (`data/provider.py`, `owner_runtime/auth.py`), left untouched.
After formatting the changed files, `uv run pytest -q tests/operations tests/autonomy`
passed **113**, with **5 PostgreSQL opt-in checks skipped** because the disposable
service had already been removed; those checks passed in the full run above.
Initial focused runs caught
adapter asset classification, a nonexistent ledger column and freshness-proof
binding defects; fixes passed the complete suite. Failed local logs remain under
ignored `.data/stabilization/evidence/operations-*`; they were not replaced with
passing claims. Earlier economic failures remain in `docs/evidence`.

The final demo yielded `FLAT_CONFIRMED`, cash `999.98` from a synthetic `1000`,
zero positions, zero duplicate closeout submissions, four fake broker calls,
fixture mail ACCEPTED and UNKNOWN with no ambiguous resend, and missing-runtime
monitor detection. It made **zero real emails and zero real broker calls**.
Each run creates a new private fixture journal and report. UUID paths vary;
financial outcomes and decisions are deterministic. Fixture artifacts expire
and are not live account/owner authority.

Browser verification used `tests/operations/browser_checks.js` through the
Playwright skill wrapper with an authenticated public synthetic session on
loopback port 8029, normal migrations and persisted synthetic PostgreSQL data.
It passed three disabled controls, four denied writes, cross-run/Origin isolation,
zero page errors and zero external requests. Screenshots at 1440 and 390 pixels
were visually reviewed; a narrow-screen evidence-hash overflow was fixed. The
initial login redirect visited an Overview without a core simulation run and
produced expected missing-bootstrap/favicon 404s; the dedicated Operations check
ran independently. Browser artifacts are ignored under `output/playwright/`.

`operations report` without supplied evidence deliberately reports BLOCKED for
unverified software fields; it does not infer test success from the source tree.
The demo supplies its actual fixture evidence separately.

## Owner-operated integration, still pending

Follow [email owner setup](email_owner_setup.md) privately, outside Codex. No
credential, real message, monitoring service, login or activation was created by
this work. Owner sender/service/responder choices and the unapproved timing draft
are preserved only in the private unsigned owner-review artifact. The existing
requested capital and universe were not applied to runtime configuration.

Before any separately selected live implementation/review: exact official schema
normalization and account binding; account-wide reconciliation including settled
funds and unexpected holdings; real executor/owner signing with privilege
isolation; actual broker approvals, ambiguity/cancel/fill/revocation behavior;
verified market calendar and frozen executable strategy; approved risk limits,
price/fee bounds and closeout policy; monitored email receipt/response/backup
escalation and independent stop/restart drills; owner start/expiry and unsigned
package decisions; and prospective operational/investment evidence remain.
There is no next numbered prompt after 12. No automatic advancement or activation.

**Current financial authority: LIVE_NOT_AUTHORIZED.**
