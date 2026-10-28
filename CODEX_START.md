# Codex starting task

Run this one task in the extracted repository. Read AGENTS.md and docs/build_status.md first. Read docs/Local_Trading_Website_Spec.md for the requested local website and its staged delivery. The numbered prompt pack is the current task sequence; the older plan section 26 does not expand this task to M1.

## Current Prompt 1

```text
PROMPT 1 — ESTABLISH THE REPOSITORY AND NONNEGOTIABLE BOUNDARIES

Read docs/Robinhood_Local_AI_Trading_Build_Plan.md and every applicable AGENTS.md.
Read docs/Local_Trading_Website_Spec.md for the required local website and its
M0/M1/M5 delivery split. Plan the UI now; do not claim it is implemented in M0.
Implement M0 only. Inspect the working tree and preserve existing work. If the
plan is missing, identify that missing prerequisite; do not reconstruct it from
memory. Continue safe environment inspection that does not depend on the file.

Objective
Establish the smallest suitable foundation for a single-owner local trading
application using LM Studio for inference and eventually Robinhood's official
external-agent MCP interface. Profitability is an unproven research hypothesis.

Implement
- Inspect only the relevant repository, OS/runtime, available hardware, and
  installed project tooling, Codex, and LM Studio. Do not scan personal files.
- Record installed versions and unknowns. Consult current primary documentation
  for uncertain flags, APIs, authorization, and integration capabilities.
- Follow the plan's modular Python design and preserve an established stack
  unless a change is justified. Use a supported pinned Python version, uv,
  a lockfile, typed configuration, and appropriate lint/type/test commands.
- Create or update AGENTS.md without discarding existing instructions. Persist
  the Consequences / Boundaries below and the plan's section 23.
- Create docs/architecture.md, docs/capability_matrix.md,
  docs/decision_log.md, and docs/build_status.md. Record actual facts separately
  from assumptions and capabilities that still need owner-run verification.
- Document website routes, local startup/auth, account/mode/run scoping,
  persisted read-model/event contracts, page-to-backend dependencies, and the
  M1 core-page versus M5 full-website backlog. Preserve the FastAPI/minimal-JS
  design unless an established stack or measured need justifies a change.
- Create blank-secret configuration examples. Defaults:
  TRADING_MODE=simulation; LIVE_TRADING_ENABLED=false;
  approved live capital=0; LLM_ALLOW_CLOUD_FALLBACK=false;
  paid data budget=0. Simulation may use a separate fictional symbol allowlist.
- Establish a broker interface whose unavailable implementation explicitly
  rejects execution; never return fabricated brokerage success.

Acceptance criteria
A clean checkout has documented setup and validation commands, a minimal
configuration smoke check, and no usable live execution path. Invalid financial
configuration fails clearly. The milestone backlog and unresolved dependencies
are concrete.

Consequences / Boundaries
Make minimal, reviewable, reversible edits in this repository. Preserve unrelated
files and user changes. Do not authenticate to financial accounts, access live
credentials, attach broker tools to Codex, place/cancel/modify orders, move money,
change broker settings, buy services, download model weights, enable cloud
inference, expose a public service, deploy, push, or merge. Do not change global
Codex/LM Studio settings. Do not use unofficial broker APIs or browser workarounds.
Resolve uncertain protocols from primary docs; record unknowns and block only
dependent work. Stop after M0 and report changed files, checks/results, exact
commands, and the Prompt 2 handoff.
```
