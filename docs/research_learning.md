# Controlled learning in research — Prompt 9

Implemented November 1, 2026. This is the research portion of M8, explicitly
selected by the owner while earlier milestone acceptance remains unresolved.
It neither certifies those milestones nor grants financial authority.

## Run and inspect

From the source checkout:

```bash
uv sync --locked
uv run trading-agent learning demo
```

The demo writes content-addressed JSON under `.data/learning/` and prints the
exact experiment path and `/learning?experiment_id=<hash>` link. Repeating it
with identical source, lockfile, and fixtures produces identical bytes; an
existing artifact cannot be replaced with different contents. The generated
23-decision fixture includes ENTER, HOLD, and rejected intents, exact numeric evidence windows with missing-session flags,
portfolio references, two simulated ledger fills, explicit fees, operating
costs, and source/model/prompt/strategy/policy/code/dependency identities.
No model, financial account, database, or external data connection is used.
The fixture calendar uses declared weekdays at 21:00 UTC; it is not an attested
exchange holiday/DST calendar. Real calendar validation remains an integration dependency.

For the Learning page, follow [SETUP.md](../SETUP.md)'s optional disposable local
PostgreSQL and owner-token website procedure, then:

```bash
docker compose up -d
uv run trading-agent serve
```

Log in at `http://127.0.0.1:8000/auth/login` using your private owner token and
open the exact link printed by the demo. This page reads research JSON; it does
not need a persisted trading run or invoke model/broker services. The existing
website startup still requires PostgreSQL/migrations. A custom `--out-dir` must
match `learning.research_store_dir` in your ignored local YAML to be visible.

The page is authenticated, read-only, selected by validated artifact hash, and
currently restricted to the simulation `research-fixture` account scope. Other
accounts/modes are denied rather than blended. It shows the learning mechanism,
source/as-of, immutable champion, all failures, correction references, exact
Decimal strings, costs/turnover, fold dispersion, proposal blockers, and pauses.
Journal updates are not model-weight training.

## Contracts and enforcement

- `learning/records.py` provides frozen Pydantic contracts with tuple-based
  collections. Evidence content hashes are checked and evidence must have been
  observed by decision time. The scope, intent, fills and their corrections,
  portfolio reference, exact monetary values, and versions remain auditable.
- Labels use an **explicit supplied session calendar**. The target is exactly
  the Nth session after the decision. Missing reference/target data leaves
  INCOMPLETE; an unclosed target is PENDING. Later available rows cannot shift
  the horizon. Availability and session-close cutoffs both apply. `released_at`
  records when the required observations and target close became available.
- Market returns are hypothetical marks, or modeled counterfactuals for rejected
  intents. Reconciled realized P&L is a separate field, released only within a
  mature horizon that includes the reconciliation timestamp. Fees are counted
  within that horizon. Simulation provenance remains attached even to the
  fixture's realized ledger outcome; it is never actual brokerage profit.
- Revisions retain old labels, link `supersedes`, and link the prior dataset
  snapshot. Previous decisions cannot disappear from a revision. Source-price
  corrections require their exact predecessor hash. Final holdout outcomes
  and overlapping horizons are excluded from `training_outcomes()`.
- `learning/workflow.py` freezes the champion, dependencies, model/prompt,
  feature definition, universe, and research protocol. Only lookback and
  entry/exit candidates in the registered grid may vary. Weight, feature set,
  policy and capital are unchanged. Only `close_momentum` is supported; no new
  feature families or model-generated executable code can be introduced.
- The default demonstration declares four candidates (5/10-session lookbacks,
  0.02/0.05 entries, zero exits), 40 prior sessions, three subsequent 20-session
  evaluation windows, and a separate final holdout. It compares each candidate
  with the frozen champion, passive investment, and cash. There is no parameter
  fitting or in-window retuning; the earlier window supplies signal history.
- The objective remains `cost_adjusted_edge_vs_passive`. Thresholds, splits,
  3x cost stress, trial count, source kind, and compute budget are hashed in the
  plan before evaluation. The M3 `standard_protocol()` and its existing failures
  were not altered. This separate versioned small-fixture protocol is a software
  demonstration, not a substitute for real historical economic validation.
- Simulation decisions use prior completed closes and execute at the next
  session close. Decimal precision is explicitly 28 with half-even rounding;
  modeled cash/fees/equity use eight places and fictional quantities round down
  to eight places. Slippage is embedded in prices and attributed as cost, never
  deducted twice. Raw imported ledger amounts remain exact. Caller Decimal
  settings cannot change the output.
- Bounds are deterministic operation reservations: at most four trials and
  2,000 simulation session-steps in the demo, with observation/grid/input limits.
  Each historical candidate reserves five books per test session (candidate,
  champion, passive, cash, stressed candidate). Forward-harness recomputation
  also consumes the remaining budget. Validation failures and budget exhaustion
  remain trials. STARTED records are saved before evaluation; a process failure
  can leave an auditable incomplete attempt rather than fabricated success.
- Artifacts are stored as write-once hashes in `datasets/`, `champions/`, `plans/`,
  `trials/`, `incidents/`, and `experiments/`. Repeated identical runs reuse those
  artifacts; source/lockfile/config changes create different identities. The
  CLI refuses a disabled learning configuration or a configured trial allowance
  below four. Weekly scheduling and a shared multi-experiment quota manager are
  not implemented by this research-only command.
- Operational memory accepts verified incident/data-quality/execution notes with
  evidence hashes. It is stored separately and is never consumed as a prompt,
  strategy setting, policy update, or training weight. Verification is an input
  contract; fixture verification does not establish real-world source truth.
- Shadow registration binds a specific evaluated rule to the experiment. The
  forward interface rejects old, future, duplicate, reordered, corrected, and
  wrong-source observations. A real-data candidate must qualify first. Synthetic
  candidates may exercise the harness even when rejected; their events are
  explicitly a software demonstration, not elapsed prospective evidence.
- Missing data, drawdown, and a predeclared change in recent mean session returns
  relative to the original training window produce research pause alerts. A
  paused shadow stream cannot continue. Alerts contain no replacement strategy
  and do not pause, replace, or activate a financial account's strategy.
- Promotion packages contain hypothesis, exact parameter diff, dataset and plan
  identities, every trial hash, full trial evidence in the parent report,
  source/model/prompt/code manifests, prerequisites, research change class,
  absent authorization, and immutable rollback target. `activate()` always
  rejects. Legacy evaluation, challenger transition, and paper promotion entry
  points also cannot promote. The runtime does not read research artifacts as
  an active strategy, shared prompt, feature configuration, or risk policy.

## Acceptance and evidence

The deterministic demo produces 69 horizon outcomes: **64 MATURED, 4 PENDING,
1 INCOMPLETE**. It preserves a corrected-price predecessor, evaluates all four
candidates, rejects their inadequate/synthetic evidence, and prepares a
`BLOCKED_RESEARCH_PROPOSAL`. The active fixture champion hash is unchanged.
Nine synthetic forward events (including an explicit missing event) exercise the
shadow cursor and research pause. Historical trials reserve 1,200 steps and the
forward harness consumes 45 more; no activation is possible.

Focused tests cover the advertised workflow, maturity/availability, cost and
realized/mark separation, corrections, content integrity, bounded/failed trials,
unchanged champions, attempted self-authorization, injection-like operational
notes, final-holdout perturbation, next-session execution, Decimal context,
slippage accounting, shadow cursor/pause/drift, and authenticated read isolation.
Legacy labels also require an explicit session calendar and retain missing targets.
Legacy replay capital now follows the existing `PaperSettings` engineering
default; no live-capital or risk setting changed. Legacy fixture tests were
reconciled to the actual record names and immutable
return types. The old auto-promotion assertion was deliberately replaced with
an assertion that even a passing rally cannot create a champion. No economic
objectives or failing M3 investment-evaluation assertions were changed.

Exact offline checks and actual current results are recorded in
[build_status.md](build_status.md)'s Prompt 9 section. Browser inspection uses an
isolated synthetic preview with a stubbed database engine and fixture session,
not the owner's auth file or financial data. Desktop (1440×1000) and narrow
(390×844) screenshots are local artifacts at `output/playwright/learning-*.png`.
Network inspection showed only the loopback page and local CSS/JavaScript.
A favicon 404 was the only browser console error; no script error was observed.
This does not certify the other website pages or a full PostgreSQL startup.

## Limits and next dependency

Software evidence is separate from integration/operations and investment evidence.
The demo is deterministic synthetic research. Actual prospective sessions,
statistical independence/confidence, licensed data validity, clock/availability
attestation, live risk/recovery regressions, and owner-operated integration remain
unverified. Fold ranges show dispersion, not calibrated confidence intervals;
selection effects across all trials remain visible. All promotion proposals stay
blocked pending independent uncertainty review, real prospective evidence,
authorization, and earlier milestone acceptance. There is no activation service.

Earlier M1–M5 acceptance gaps and three existing M3 economic-evaluation failures
remain unresolved. The next numbered prompt is **Prompt 10 — security and failure
readiness review**, with those dependencies visible. Do not auto-advance or treat
this research implementation as permission to connect accounts, fine-tune a
model, deploy code, or promote a live strategy.

Current financial authority: **LIVE_NOT_AUTHORIZED**.
