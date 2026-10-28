# Migration record

Date: 2026-10-28
Scope: transfer the recovered Trading agent project context into a Codex-ready dedicated local repository.

## Recovered source artifacts

| Original artifact | Source creation date | Repository destination |
| --- | --- | --- |
| Robinhood_Local_AI_Trading_Build_Plan.md | 2026-10-26 | `docs/Robinhood_Local_AI_Trading_Build_Plan.md` |
| Trading_Agent_Codex_Prompts.txt | 2026-10-26 | `docs/Trading_Agent_Codex_Prompts.txt` |

The original prompt pack labels itself prepared October 27, 2026. The initial migration preserved it as supplied; its source creation timestamp and document date were recorded without reconciling them.

Both documents were initially copied verbatim. The original bytes remain in commit `fa4f8e402494674459f3b104a26a15cf743b97e1`. The current documents include the subsequent website revision described below. `SOURCE_MANIFEST.json` distinguishes original and current hashes. Historical platform claims are not reverified financial-platform guidance from this revision.

## Decisions

1. Package recovered context in a new dedicated local Git repository, matching the existing prompt pack.
2. Preserve the specification and prompt pack; add concise execution instructions and a truthful pending-work ledger.
3. Use the newer sequential prompt pack for task scope. Prompt 1 is M0 only, even though section 26 of the earlier plan includes M0 and M1.
4. Set the next task to Prompt 1. Do not invent existing application code, completed tests, installed models, or broker capabilities.
5. Leave remote repository selection unresolved. Discovery found `ygeszvain/tradingbot`, whose README installs an unofficial Robinhood dependency. That repository was not established as the destination and was not modified.
6. Preserve live authority at LIVE_NOT_AUTHORIZED and approved live capital at zero.

## Initial migration verification

Verification was limited to this handoff:

- Exact byte comparison and SHA-256 matching of both original documents.
- Exact extraction of Prompt 1 from the original prompt pack.
- Preservation of every section 23 boundary in `AGENTS.md`.
- Presence of all 12 numbered prompts, with a Consequences / Boundaries section in each.
- Local relative Markdown links resolve.
- Handoff checksums match the packaged files.
- Git whitespace checks pass for authored handoff files; original source whitespace is preserved. The migration commit leaves a clean working tree.
- Archive content matches the local repository, contains its Git history, and passes ZIP integrity checks.

No application or broker verification is implied. Current handoff/specification verification results and reproducible integrity commands are recorded in `migration_verification.txt`.

## Local trading website revision — 2026-10-28

The owner requested a local website to inspect all trading activity and details. Build-plan section 18 now specifies Overview, Activity, Orders/fills and full detail, Portfolio/instruments, Performance, Research/decisions, Risk/approvals, Learning, Operations, and Reports/preferences.

Added `Local_Trading_Website_Spec.md` with page/data contracts, financial-display rules, locally served charts/assets, authenticated read/update/export flows, failure states, and concrete browser acceptance scenarios. Updated the stack/layout/interfaces/audit/test sections and M0/M1/M5 definitions to make the website an implementation deliverable.

Updated the 12-prompt pack, current kickoff, AGENTS.md, README, and status ledger. Prompt 2 provides useful persisted simulation pages; Prompt 8 completes the full website. Other affected prompts prepare the source/research/evaluation/gateway read data and verify website boundaries. The numbered sequence remains unchanged.

Current revision checks validate only specifications and packaging: original Git source hashes, current document hashes, prompt numbering/boundaries and kickoff consistency, required-page and milestone cross-references, unchanged financial configuration/official MCP route, link resolution, whitespace, and archive/Git integrity. Application/browser/integration checks are future acceptance requirements and have not run.

Live capital stays zero and authority remains LIVE_NOT_AUTHORIZED. No application code, account connection, runtime service, remote repository, or public hosting was created by this revision.

## Remaining handoff

Extract the archive, open the dedicated project folder in Codex, and use `CODEX_START.md`. The archive does not move the original ChatGPT chat history, select a remote repository, install Codex, or start a Codex task on the owner's device.
