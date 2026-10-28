# Local Trading Website Specification

**Revision:** 2026-10-28

**Owner request:** Build a local website that shows all trading activity and its supporting details.

**Status:** Specification only; implementation is pending.

**Governing plan:** [Robinhood Local AI Trading Build Plan](Robinhood_Local_AI_Trading_Build_Plan.md), especially sections 4, 14–20, and 21.

**Initial authority:** LIVE_NOT_AUTHORIZED; approved live capital is zero.

## 1. Product outcome and scope

The owner can open one local browser website and answer: What is happening now? What happened during a selected period? Why did the system trade, reject, or HOLD? How did orders become fills and positions? What were the actual costs and results? What needs attention?

"All activity" means all retained, permitted activity within the approved account and selected mode/run scope, including incomplete and adverse events. The website must disclose coverage and active filters. It must not imply access to every Robinhood account or promise data that the official gateway has not supplied.

This is the trading application's website, backed by its persisted state. It runs independently of an open Codex session. The first working version uses synthetic simulation data; paper and authorized read-only shadow data arrive in later milestones.

## 2. Local architecture and access

- Extend the plan's FastAPI backend with server-rendered templates, minimal browser JavaScript, locally bundled styles/fonts/chart assets, and a scoped read API. Reuse an established frontend stack if one exists and a change is not justified.
- Proposed local address: `http://127.0.0.1:8000/`; the port is configurable and must not conflict with LM Studio's configured port. Record the actual address in startup output and the README.
- Bind to loopback by default. Public hosting, tunnels, router changes, and remote/LAN access are outside this revision. A narrow mobile layout improves usability but does not imply a phone can access another machine's loopback address.
- Authenticate the owner, including read APIs, event streams, and exports. Use an owner-controlled bootstrap and protected sessions; do not ship a shared default password or put bootstrap secrets in source control.
- Validate Host/Origin, restrict cross-origin access, and protect command routes against CSRF. Use HttpOnly/SameSite session cookies with cookie security appropriate to the actual local scheme.
- The browser talks only to the application. Robinhood MCP authentication, account filtering, data ingestion, and LM Studio requests stay in their appropriate backend processes.
- No broker token, raw account number, unrestricted database access, or privileged executor endpoint reaches the browser.
- Read queries, chart navigation, replay, page refresh, and exporting do not submit orders, run model inference, or change strategy settings.
- Keep the read service separate from command handling. UI visibility or disabled buttons are never the authorization mechanism.
- Serve installed UI assets locally. The fixture demo must make no runtime requests to CDNs, third-party chart widgets, analytics, external fonts, paid services, Robinhood, or cloud inference.

## 3. Shared website behavior

Every page displays a persistent mode label (SIMULATION, PAPER, SHADOW, or an explicitly authorized later live mode), approved account alias, selected strategy/run, display timezone, data source, last successful update, and connection/reconciliation status.

Simulation and paper values have unmistakable labels. Broker-confirmed, locally observed, simulated, estimated, corrected, stale, unavailable, and pending-validation values are distinguishable in text. Do not rely on color alone.

Use canonical UTC storage and the plan's configurable owner display timezone. Show exchange time where useful. Date filters convert unambiguously to UTC, respect daylight-saving transitions, and record the effective interval.

Provide consistent date, instrument, strategy, mode/run, account alias, event type, order status, and severity filters where relevant. Preserve filters in navigation using nonsensitive identifiers. Always show the active scope and result count.

Support loading, empty, failed, disconnected, stale, and partially available states. Missing marks, costs, benchmarks, or integration data display as unavailable with a reason, never a fabricated zero. Existing stored activity remains inspectable during an LLM or broker outage.

Use a readable desktop layout, narrower responsive views, keyboard navigation, visible focus, accessible tables, text descriptions of chart states, and a reduced-motion option. Tables are searchable, sortable on supported indexed fields, and paginated without loading all records into the browser.

## 4. Required pages and details

| Page | Required content and drill-down |
| --- | --- |
| Overview | Equity, cash, available versus reserved cash, positions, working orders, pending exposure, realized/unrealized P&L, strategy and product net results, benchmark comparison, drawdown, recent activity, incidents, and source/reconciliation freshness. Each card links to its underlying records. |
| Activity | Durable chronological feed of decisions, HOLD/ABSTAIN, risk passes/rejections, approvals/expiries, order attempts and status changes, fills/corrections, cancellations, reconciliation differences, manual/external activity, account flows, corporate actions, research/model failures, jobs, incidents, and policy/promotion changes. |
| Orders and fills | Searchable order and fill tables with origin, instrument, side, quantities, requested/remaining/filled amounts, order type, prices, fees, timestamps, local and sanitized broker status, and reconciliation state. Open an order's full lifecycle and individual fills. |
| Portfolio and instruments | Current and historical holdings, cash ledger, average cost or supported lot view, mark and mark age, value, realized/unrealized P&L, allocation/exposure, pending reservations, and instrument detail charts with linked decisions, orders, and fills. |
| Performance | Equity and drawdown curves; strategy and product net P&L; separately itemized fees/income/operating costs; cash-flow-adjusted returns and benchmarks; exposure/turnover; period and instrument/strategy attribution; trade statistics with definitions, sample size, and limitations. |
| Research and decisions | Candidate and action/HOLD, concise rationale, verified facts versus inference, conflicting evidence, source references, availability cutoff, input snapshot, model/prompt/strategy versions, uncertainty, parsing status, abstention and risk rejection reasons, and subsequent matured outcomes. |
| Risk and approvals | Current versus permitted exposure, concentration, pending capacity, loss/drawdown triggers, stale-state blockers, authorization scope and expiry, risk decisions, and a read-only approval queue. Readiness screens explain unmet prerequisites. |
| Learning | Current champion, challengers, all attempted/failed experiments, data/split manifests, trial count, cost assumptions, matured versus pending labels, results/uncertainty, promotion history and permitted change class. |
| Operations | Application/gateway/model/data/job health, current mode and authorization, last successful ingest/reconciliation, queue lag, time synchronization, incidents, alert status, redacted diagnostics, recovery checklist, and separately scoped operational controls. |
| Reports and preferences | Filtered CSV/JSON exports and session summaries; visible export scope/methodology; display timezone/theme/table preferences; read-only summaries of source, model, universe, capital, risk, and authorization configuration. |

### Order and decision detail contract

The drill-down must reconstruct linked records across the decision, risk check, approval if applicable, intent, submission attempts, broker order, individual fills, ledger effects, reconciliation, and measured outcome.

Show:

- Application-generated correlation IDs and sanitized record references, account alias, mode/run, strategy and policy versions, and event origin.
- Instrument identity, side, intended target/quantity, price constraints, expiry, quote/source/as-of time, requested and actual quantities, and the exact risk outcome.
- Recorded concise rationale, verified evidence references, missing/conflicting information, and model identity where that decision actually used a model. Deterministic decisions are labeled accordingly.
- The complete order timeline, including awaiting approval, rejected, submission pending, acknowledged, partially filled, cancellation requested, cancellation confirmed, filled, expired, UNKNOWN, reconciling, and manual-review states as applicable.
- Each fill's timestamp, quantity, execution price, fee, correction linkage, and aggregate volume-weighted execution price calculated by backend code.
- Before/after cash, inventory, reservations and exposure; realized and unrealized results where attribution is supported; relevant costs and cost-basis methodology.
- Relevant errors, retries, state uncertainty, broker/local differences, and owner actions needed. Redacted diagnostics must be safe to view and export.

One decision can lead to multiple orders, and one order can have multiple fills. Do not flatten this into a misleading one-to-one "trade" record. Closed-position/round-trip statistics must declare their grouping and cost-basis method. Externally initiated activity is visible but is not automatically attributed to the strategy.

A cancellation request is not a confirmed cancellation; a canceled order may retain fills. A timed-out submission must stay UNKNOWN until reconciled. The website must not mark these states successful or release reserves on its own.

## 5. Visualizations and replay

- Overview: equity versus appropriate benchmark, drawdown, allocation/exposure, and recent activity.
- Instrument detail: price/candlestick chart where licensed OHLC data exists, optional volume, and time-aligned decision/order/fill markers. Offer a line chart when bars are unavailable.
- Order detail: execution timeline and linked fills, with requested versus actual amounts and visible unresolved state.
- Performance: return/P&L by period and instrument/strategy, cost breakdown, turnover and exposure; show uncertainty and sample size for statistics where applicable.
- Research and learning: outcome maturity, experiment comparisons, failed/blocked candidates, and champion/promotion history.

Every chart names its mode, currency/units, source, time interval, timezone, price adjustment basis, mark method, and relevant sampling/aggregation. Distinguish decisions from submissions and fills. Display gaps and stale intervals without inventing prices or interpolating executions.

Zoom, range selection, tooltips, and linked table rows must agree with the backend record. Chart downsampling may reduce plotted points but must preserve accounting totals, extremes used in risk reporting, execution events, and access to full table/export data. Disclose aggregation.

A replay view may inspect persisted synthetic or historical sessions with a visible REPLAY/SIMULATION label. Its playback clock and controls are isolated from the active runtime and cannot create orders or approvals.

## 6. Read model, events, and freshness

Use the existing ledger and audit events as authoritative inputs; dashboard projections are rebuildable views, not a second financial ledger.

The application should expose internal resources for summary, activity, decisions, orders, fills, positions, timeseries, performance, risk, research, experiments, health, and exports. These are application designs, not claims about Robinhood tool names.

Each read response includes scope (account alias, mode/run and strategy where applicable), an as-of timestamp or snapshot watermark, source/provenance, freshness/quality flags, and pagination where needed. Stable links and cursors must be opaque and validated.

Write consequential financial state and its audit/outbox event atomically in the existing transaction. Build derived views from committed records with idempotent projection updates and a documented watermark. Preserve corrections as linked events; never rewrite adverse history to improve a chart.

Provide authenticated server-sent events, or an equivalent supported local stream, for bounded sanitized notifications. Bootstrap a consistent snapshot and resume from its committed cursor. Deduplicate reconnects and detect gaps; an expired/gapped cursor requires an explicit snapshot resynchronization. Preserve the owner's current filters and visible disconnect banner.

Use bounded read-API polling as a fallback. UI refresh queries persisted local state; it must not increase broker polling, exceed provider limits, or trigger model calls. Handle slow clients with bounded queues and explicit resynchronization rather than unbounded memory growth.

Proposed local acceptance targets, to be measured on recorded hardware:

- Normal stream updates: p95 no more than 2 seconds from committed application event to visible update.
- Poll fallback: configurable, initially 5 seconds, with a visible degraded-connection state.
- Initial overview: target under 3 seconds after the local services are ready using a fixture dataset with 10,000 activity events and 1,000 historical orders.
- Paginated responses and chart payloads remain bounded. Record measured dataset size, context, hardware, and results; do not label an unmeasured target passed.

Stream heartbeat time, last data observation, quote age, and last successful reconciliation are separate facts. Receiving a heartbeat must not make stale financial data look fresh. Existing risk-policy freshness requirements remain authoritative.

## 7. Accounting and disclosure rules

Authoritative values are computed by backend ledger/performance services using the plan's Decimal/integer money and precision rules. Serialize exact amounts as decimal strings or explicitly scaled integers; browser floating-point chart coordinates never become financial state or the source of displayed account totals.

Use a consistent snapshot for related cards, tables, and charts, or expose their differing as-of times. Round for display only after aggregation, using the declared currency/instrument precision.

Separate realized P&L, unrealized P&L, income, external cash flows, strategy costs, and product operating costs. Show gross/net labels and the cost methodology. Deposits are not profits. Do not double-subtract spread/slippage already embedded in fills. Benchmark returns use the same period, capital/exposure conventions, and explicit distributions/cost assumptions.

Never combine simulated, paper, shadow, and actual live financial totals. Multi-mode views show distinct sections/series with their own provenance. Historical model studies retain the plan's leakage disclosures. Missing or unreconciled inputs cannot produce a green "verified" result.

## 8. Controls and security boundaries

The requested visualization website is read-only first. Preserve the plan's existing operator controls as separate capability-gated commands; adding screens does not activate them.

- M1 implements navigation, filters, detail pages, replay/exports where included, and simulated activity inspection. No broker-write controls exist.
- M5 may implement the existing local operational controls within the selected mode: pause new risk, request entry cancellation, and separately authorized protective reduction. In simulation/paper these affect simulated state only. In shadow all broker mutations remain denied.
- Broker-mutating and live-activation paths stay unavailable under LIVE_NOT_AUTHORIZED. Later readiness stages can show disabled controls, unmet prerequisites, and mocked tests without granting authority.
- Any later owner command requires server authentication, CSRF protection, explicit scope and confirmation, execution-side authorization/risk validation, and an auditable result. A stale page cannot bypass current state.
- Pausing is distinct from cancellation, confirmed cancellation, liquidation, and revoking broker authorization. The UI describes what happened and what remains exposed.
- Financial configuration is read-only in the initial website. Ordinary theme/timezone/table preferences cannot change account, capital, risk limits, strategy, broker permissions, or live mode.
- M6/M7 owner controls must include the plan section 24 pilot-authorization review, prefilled with the owner's requested USD 1,000 ceiling as an inactive draft. Bind consent to the exact account, strategy/instruments, mode, risk limits, and start/expiry; unresolved fields or failed readiness gates block activation. Display requested versus active capital separately, preserve broker approval requirements, and audit activation/expiry/revocation. The initial M1/M5 website does not activate this flow.
- Keep session state and credentials out of URL/query strings, browser storage used for preferences, telemetry, exports, and errors. Do not render source/model text as trusted HTML.
- Export the approved scope only, redact sensitive identifiers, enforce source rights, bound resource use, and prevent spreadsheet-formula execution when exporting CSV text. Exporting must not modify trading state.

No direct browser-to-MCP connection or free-text "trade" action may bypass the existing application controls.

## 9. Delivery sequence

| Stage | Website deliverable | Required evidence |
| --- | --- | --- |
| M0 / Prompt 1 | Document routes, read contracts, local startup/auth approach, shared mode/scope design, and a page-to-backend dependency map. | Architecture and concrete backlog; no claim that UI exists. |
| M1 / Prompt 2 | Runnable local website with Overview, Activity, Orders/fills with order detail, and Portfolio/instrument detail; basic equity/price charts and order/fill markers backed by the persisted synthetic run. | Clean-checkout local startup and meaningful browser checks against the known fixture ledger. |
| M2–M3 / Prompts 4–6 | Persist research/model and evaluation data needed by the eventual Research and Performance pages; make incremental views useful where implemented. | Truthful unavailable/pending labels, provenance, and reconciliation with report artifacts. |
| M4 / Prompt 7 | Feed normalized authorized read-only gateway snapshots into the same read model when independently connected by the owner. | Contract tests first; authenticated observations remain pending until actually performed. |
| M5 / Prompt 8 | Complete all required pages, live local updates, filters, detailed charts/timelines, exports, responsive/accessibility states, incident/recovery views, and permitted paper controls. | Browser workflow, financial consistency, reconnect/staleness, privacy/security, and measured local performance evidence. |
| Prompt 10 | Review the website's concrete failure and security paths. | Reuse adequate tests; add checks for uncovered material risks and fixes. |
| M6–M7 / Prompts 11–12 | Readiness/authorization display and any explicitly scoped control code, still inactive by default. | Disabled real dispatch, mocked flows only, LIVE_NOT_AUTHORIZED visible. |

Keep the original one-numbered-prompt-at-a-time workflow. This revision specifies future development; it does not execute a milestone or authorize connection, hosting, or trading.

## 10. Acceptance scenarios

1. Start the documented offline demo and local website from a clean checkout; the persistent SIMULATION label and exact synthetic cash/position state are visible.
2. Follow a fixture decision through risk approval or rejection, order attempts, multiple fills, ledger effects, position changes, costs, and reconciliation from the browser alone.
3. Find HOLD, rejected, expired, partially filled, cancel-requested, cancel-confirmed, UNKNOWN, corrected-fill, and external/manual fixture events; no adverse outcome is silently excluded.
4. Reconcile every displayed financial total with backend ledger/report values, including a deposit that does not increase measured profit and fees/distributions counted once.
5. Verify mode/run/account filters across every route, stream, detail link, and export. Changing filters cannot mix paper results with authorized broker state.
6. Interrupt and reconnect the update stream. Deduplicate resumed events, expose stale data, resynchronize on a missing cursor, and retain historical detail during model/broker outages.
7. Restart the application and rebuild derived views without duplicated orders, fills, events, or displayed economic effects.
8. Verify unauthenticated reads/streams/exports are denied; check CSRF/Origin/Host controls, escaped untrusted text, redaction, scope checks, CSV formula protection, and rejection of attempted broker writes.
9. Verify empty/loading/error/partial-data states, responsive layouts, keyboard navigation, meaningful chart labels, supported sorting/pagination, and timezone/DST date filters.
10. Record observed update/initial-render timing and bounded payloads on the documented fixture dataset. Do not substitute target numbers for measurements.
11. Capture representative page screenshots using synthetic data for implementation QA, inspect legibility/layout, and attach the actual browser test commands and outcomes to the milestone report.
12. Confirm that reading a page, refreshing, filtering, opening a chart, replaying history, or exporting invokes zero broker mutations and zero model calls.

## Consequences / Boundaries

Make minimal, reviewable changes within the selected milestone and preserve existing work. Use fixtures and persisted simulation state for development and browser checks. No financial-account linking, broker credentials, broker mutations, funding, paid feeds, cloud inference, public hosting, tunnels, production deployment, push, or merge is authorized by this specification.

Preserve the official Robinhood MCP route, deterministic risk/execution authority, existing limits and accounting conventions, adverse history, and one-prompt-at-a-time workflow. Do not infer trading authority from a chart, a UI toggle, a roadmap, or passing mocked tests. Record unavailable dependencies honestly, continue independent offline work, and stop at the selected milestone with concrete evidence.
