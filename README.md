# Trading agent — Codex handoff

The recovered Trading agent specification and build prompts are packaged as a dedicated Git repository. The next task is **Prompt 1 (M0) only**.

This is a project handoff. It contains the updated specification, all 12 numbered prompts, a detailed local trading website contract, persistent project instructions, provenance, and a pending-work ledger. Application implementation and target-machine verification remain pending.

## Start in Codex

1. Extract the archive and open the `trading-agent-codex` folder in Codex.
2. Start a new task and send:

> Read AGENTS.md, docs/build_status.md, and CODEX_START.md. Execute Prompt 1 (M0) only, then report the actual checks and the Prompt 2 handoff. Consequences / Boundaries: follow AGENTS.md, preserve existing work, keep LIVE_NOT_AUTHORIZED, and stop after M0.

The full current Prompt 1 is in [CODEX_START.md](CODEX_START.md). If using an existing repository, reconcile its instructions and existing work before adding this handoff; do not overwrite its files or Git metadata.

## Project files

| File | Purpose |
| --- | --- |
| [AGENTS.md](AGENTS.md) | Persistent scope, workflow, authority, and boundaries |
| [CODEX_START.md](CODEX_START.md) | Exact current Prompt 1, ready for the next Codex task |
| [Build plan](docs/Robinhood_Local_AI_Trading_Build_Plan.md) | Product specification updated with the local trading website |
| [Prompt pack](docs/Trading_Agent_Codex_Prompts.txt) | Updated 12-step implementation sequence and browser acceptance checks |
| [Website specification](docs/Local_Trading_Website_Spec.md) | Pages, trading detail, charts, local access, updates, exports, and acceptance scenarios |
| [Build status](docs/build_status.md) | Implementation state and the next milestone |
| [Migration record](docs/migration_record.md) | What was recovered, verified, and left unresolved |
| [Source manifest](SOURCE_MANIFEST.json) | Original and current document hashes, with original sources retained in Git history |
| [Checksums](CHECKSUMS.sha256) | Integrity checks for the handoff files |

## Scope and sequencing

The product is a single-owner local research/trading application using LM Studio for research inference, deterministic risk and execution services, and an eventual official Robinhood gateway.

Run the newer numbered prompt pack one prompt at a time. Its Prompt 1 is M0 only. The older build plan's section 26 contains a broader M0-and-M1 kickoff; do not run that combined kickoff as the first task.

After a milestone passes its acceptance checks, update `docs/build_status.md` and hand off the next numbered prompt. This migration does not start later milestones or create a standing instruction to run all 12.

The website starts with persisted synthetic data in Prompt 2 (M1): Overview, Activity, Orders/fills and detail, Portfolio/instrument detail, and basic charts. Prompt 8 (M5) completes research, risk, learning, performance, operations, reports, live local updates, and all page/detail/export requirements. No broker connection is needed to build and inspect the website.

The owner has requested a USD 1,000 observation pilot. Build-plan section 24 records the amount, unresolved operating limits, and the future authenticated pilot-approval flow. Requested capital and active trading authority are separate: checked-in live capital remains zero, and no funding or activation has occurred.

## Current authority and limits

- Development uses fixtures, simulation, and paper mode.
- Approved live capital is zero. Current financial authority: **LIVE_NOT_AUTHORIZED**.
- No application code, dependency lockfile, model installation, or financial integration is included or verified.
- Original platform findings are dated source material. Recheck uncertain APIs and capabilities against current primary documentation during implementation.
- No remote repository or Codex task has been created. Local Git history records the initial handoff and the website specification revision; the original source documents are preserved in the initial commit.
- Full conversation history is not included. The two recovered source documents and this explicit handoff are the portable project context.

Codex project-instruction reference: [official AGENTS.md documentation](https://learn.chatgpt.com/docs/agent-configuration/agents-md).
