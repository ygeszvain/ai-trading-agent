# Trading agent — project instructions

## Purpose and current scope

Build a single-owner local research/trading application. Codex develops the software; LM Studio supplies local research inference. The unattended application must operate independently of an interactive Codex session. Deterministic risk, authorization, ledger, and reconciliation services govern financial behavior. Profitability is an unproven research hypothesis.

Prompt 1 (M0) is complete as of 2026-10-31: the foundation, typed fail-closed configuration, broker interface with explicitly rejecting adapters, live-activation gate, verified disposable database, and the M0 documentation set exist (see docs/build_status.md). The next task is Prompt 2 (M1). Inspect docs/build_status.md before claiming progress.

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
