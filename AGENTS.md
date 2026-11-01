# Trading agent — project instructions

## Purpose and current scope

Build a single-owner local research/trading application. Codex develops the software; LM Studio supplies local research inference. The unattended application must operate independently of an interactive Codex session. Deterministic risk, authorization, ledger, and reconciliation services govern financial behavior. Profitability is an unproven research hypothesis.

Prompt 1 (M0) acceptance is recorded as of 2026-10-31. On 2026-11-01 the owner explicitly selected Prompt 9's research-only learning work despite unresolved earlier acceptance. Its local offline implementation and limitations are recorded in docs/build_status.md and docs/research_learning.md. This does not certify M1–M5 or authorize live promotion. Prompt 10's offline security review is complete with concrete patches and an evidence matrix in docs/security_readiness_review.md; overall readiness remains FAIL. Prompt 11's M6 control/mock scope is recorded in docs/supervised_readiness.md with a concrete unsigned package. The explicitly selected Prompt 12 M7/M8 control scope is recorded in docs/bounded_autonomy_readiness.md and its unsigned owner worksheet. Real readiness remains blocked: no live transport, real owner envelope, activation, automatic renewal or automatic promotion exists; permitted automatic change class is NONE. The numbered pack ends at Prompt 12. Stop for owner review and separately selected upstream repairs; do not infer new activation authority. Inspect docs/build_status.md before claiming progress.

## Owner-selected offline stabilization — November 1, 2026

The owner's later request selected prerequisite repairs without live activation.
See docs/stabilization_and_auth_readiness.md for schema/ledger/recovery/evaluation/
website fixes and the 325-test, Ruff and mypy results. Original failed economic
evidence and unchanged protocol are archived under docs/evidence; do not discard
or relabel synthetic results as investment evidence. Historical milestone reports
remain intact. The owner reports an existing Agentic account and USD 500, with
balance-only risk preference and a request for the best algorithm. These are in
docs/pilot500_owner_request.unsigned.json, inactive and unverified; no best strategy
is established, no risk widening or exact owner decisions are inferred.

The owner explicitly approved `randygeszvain` for owner-operated authentication
on November 1, 2026; `ai-trading-executor` also remains allowed. This supersedes
the separate-user authentication requirement only. Same-user filesystem permissions
do not isolate credentials from coding processes. Private storage outside the
checkout, ownership/mode/path checks, and all live-dispatch denials remain.
See docs/owner_runtime_setup.md for the private operator steps. Coding
must not authenticate, read real tokens or perform protected account/broker calls.
No real login, live transport, owner signer/activation loader or deployed privilege
isolation is certified. Current financial authority stays LIVE_NOT_AUTHORIZED.

## Owner-selected interactive Codex operation — November 1, 2026

Use this chat as the operator interface for status, research, simulations and
readiness. Ask concise non-secret questions here when material information is
missing, retain recorded answers, and continue independent authorized work while
waiting. The owner selected Robinhood integration readiness first. See
`docs/codex_operation.md` for the prepared native read-only check and evidence
boundaries. Native Robinhood tools being available does not verify connection
or integrate them with the project executor. The owner explicitly approved and
completed one native three-read readiness check: accessible account, portfolio and trade-approval setting. That one-check
exception is consumed. It did not grant ongoing monitoring or further account
reads. Keep raw identifiers/private broker observations out of source, fixtures
and logs; use identifiers internally only to scope approved reads. The base
protected-call prohibition remains outside an explicit owner request/exception.
No real credential reads or financial writes are inferred. Do not make the chat
the unattended engine or create schedules/alerts/deployments under this request.

The owner subsequently approved one account-scoped read-only inventory for
reconciliation preparation (cash/buying power, holdings, orders and pending
approvals across asset classes). It completed with all requested collections
covered; this exception is also consumed. It did not write the ledger or prove
reconciliation. Later instrument/mode choices are in the ignored private
`.data/owner-review/owner-request.current.json` pointer and its unsigned artifact.
These are owner decisions, not broker credentials or authorization. Preserve
unknown duration/overnight/monitoring fields; ask for them here without inventing
answers. Keep the private requested universe and all broker observations out of
public commits. Runtime capital stays zero and no live configuration is changed.

## Publication scope — November 1, 2026

The owner explicitly authorized open source publication to
`https://github.com/ygeszvain/ai-trading-agent` using existing GitHub
authentication. This grants the commit/push needed for this publication despite
the original milestone's no-push boundary. It does not grant service deployment,
financial-account access, live activation, or advancement through numbered prompts.
The public snapshot includes later-stage work whose acceptance is incomplete;
read `docs/publication_status.md` and reconcile Prompt 2 acceptance before claiming
milestone progress. Preserve the historical M0 evidence in `docs/build_status.md`.

## Read and execute

- Read applicable AGENTS.md files and inspect the working tree before editing. Preserve user work and any more specific applicable instructions.
- Read docs/Robinhood_Local_AI_Trading_Build_Plan.md in full for requirements, and docs/Trading_Agent_Codex_Prompts.txt for the selected numbered task.
- Read docs/Local_Trading_Website_Spec.md for the local website, scoped read/event contracts, page requirements, and browser acceptance scenarios. Plan it in M0, build core simulation pages in M1, and complete the website in M5; this revision does not execute those milestones.
- Use the newer prompt pack's sequence: one numbered prompt at a time. Prompt 1 (M0) is complete; do not execute the broader combined kickoff in section 26 of the older plan.
- CODEX_START.md contains the exact initial prompt. Later prompts come from the original prompt pack after the prior acceptance checks pass.
- Favor minimal, reviewable changes and meaningful checks. Finish authorized offline work using documented reasonable assumptions; ask only for facts that materially block dependent work.
- Use the plan's modular Python design. Preserve an established stack when integrating into an existing repository. Use Decimal or integer units for money and explicit precision/rounding.
- Record actual facts separately from assumptions. Resolve uncertain protocols, flags, and capabilities from current primary documentation; mark unavailable dependencies honestly.
- Track software evidence, integration/operations evidence, and investment evidence separately. Passing one does not establish the others.
- Update docs/build_status.md at each milestone with acceptance results, commands, limitations, unresolved dependencies, and the next numbered prompt.

## Initial operating defaults

Simulation/paper only. LIVE_TRADING_ENABLED=false; approved live capital=0; LLM_ALLOW_CLOUD_FALLBACK=false; paid data budget=0. Use fictional simulation symbols independently of any live allowlist. Current financial authority: LIVE_NOT_AUTHORIZED.

These are required defaults for implementation. M0 implements and tests the typed runtime configuration that enforces them (config/ + .env.example); invalid financial configuration fails startup clearly. The research model receives sanitized evidence and no live credentials, broker-write tools, privileged executor socket, or authority to change risk policy. Never substitute unofficial broker APIs for the planned official gateway.

The website is authenticated and loopback-only by default. It reads persisted, account/mode/run-scoped state; UI reads, filtering, charts, replay, and exports cannot invoke model inference or broker mutations. Financial calculations are authoritative in backend ledger/performance services. Preserve stale/UNKNOWN/corrected state, mode labels, source/as-of metadata, and exact financial amounts. No browser secrets, direct browser-to-MCP access, public hosting, tunnels, or new trading authority are granted by the website scope.

## Consequences / Boundaries

The following requirements are preserved from section 23 of the build plan:

- Make small, reviewable, reversible changes scoped to the current milestone.
- Read applicable repository instructions and inspect existing work before editing.
- Preserve unrelated files and existing behavior unless a requirement explicitly changes it.
- Use fixtures, simulation, and paper mode by default.
- Never place, cancel, or modify a real order as a development test.
- Never fund accounts, transfer assets, enable margin, change broker approvals, or increase capital.
- Never request or expose passwords, MFA codes, tokens, account numbers, or sensitive logs.
- Keep live broker credentials and execution privileges out of the coding environment.
- Do not use unofficial broker APIs, scraped sessions, credential replay, or browser workarounds.
- Do not install random third-party MCP servers or grant broad tools to the model.
- Do not enable cloud inference, paid feeds, subscriptions, or large downloads without explicit authorization.
- Do not deploy, merge into a protected branch, or change production unless separately instructed.
- Do not silently alter strategy objectives, risk policies, test splits, or failed results.
- Do not claim profitability from a backtest, a short pilot, or model self-reported confidence.
- If a financial or security assumption is unresolved, block dependent live behavior and continue independent offline work.
- Use current primary documentation to resolve protocol uncertainty; never invent tools, fields, flags, or account capabilities.
- On unclear mutation outcomes, preserve state and investigate; do not repeat the mutation blindly.
- Stop at the milestone's boundary with a reviewable result, test evidence, limitations, and the next dependency.
- A roadmap describing a future live stage does not authorize that stage's financial actions.

Prompt 1 additionally prohibited deployment, push, merge, model-weight downloads, global Codex/LM Studio settings changes, financial-account authentication, and exposing a public service. Those limits were preserved throughout M0 and remain in force for all later work (consult CODEX_START.md for the full original boundaries). Each subsequent numbered prompt carries its own Consequences / Boundaries in docs/Trading_Agent_Codex_Prompts.txt.

Do not auto-advance through the remaining prompts. Future readiness code does not authorize account connection or live activation. A missing external dependency blocks dependent work; continue independent offline work within the selected prompt.

## Completion report

Report what works, acceptance criteria passed, changed files, exact commands and actual results, checks not run, unresolved dependencies, and the next numbered prompt. Label owner-operated integration checks separately from offline commands. End with the current financial authority: LIVE_NOT_AUTHORIZED.
