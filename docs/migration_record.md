# Migration record

Date: 2026-10-28
Scope: transfer the recovered Trading agent project context into a Codex-ready dedicated local repository.

## Recovered source artifacts

| Original artifact | Source creation date | Repository destination |
| --- | --- | --- |
| Robinhood_Local_AI_Trading_Build_Plan.md | 2026-10-26 | `docs/Robinhood_Local_AI_Trading_Build_Plan.md` |
| Trading_Agent_Codex_Prompts.txt | 2026-10-26 | `docs/Trading_Agent_Codex_Prompts.txt` |

The prompt pack labels itself prepared October 27, 2026. Its content is preserved as supplied; the source creation timestamp and document date are recorded without reconciling them.

Both documents are copied verbatim. Their exact byte lengths and hashes are in `SOURCE_MANIFEST.json`. Their historical claims are not reverified financial-platform guidance from this migration.

## Decisions

1. Package recovered context in a new dedicated local Git repository, matching the existing prompt pack.
2. Preserve the specification and prompt pack; add concise execution instructions and a truthful pending-work ledger.
3. Use the newer sequential prompt pack for task scope. Prompt 1 is M0 only, even though section 26 of the earlier plan includes M0 and M1.
4. Set the next task to Prompt 1. Do not invent existing application code, completed tests, installed models, or broker capabilities.
5. Leave remote repository selection unresolved. Discovery found `ygeszvain/tradingbot`, whose README installs an unofficial Robinhood dependency. That repository was not established as the destination and was not modified.
6. Preserve live authority at LIVE_NOT_AUTHORIZED and approved live capital at zero.

## Migration verification

Verification was limited to this handoff:

- Exact byte comparison and SHA-256 matching of both original documents.
- Exact extraction of Prompt 1 from the original prompt pack.
- Preservation of every section 23 boundary in `AGENTS.md`.
- Presence of all 12 numbered prompts, with a Consequences / Boundaries section in each.
- Local relative Markdown links resolve.
- Handoff checksums match the packaged files.
- Git whitespace checks pass for authored handoff files; original source whitespace is preserved. The migration commit leaves a clean working tree.
- Archive content matches the local repository, contains its Git history, and passes ZIP integrity checks.

No application or broker verification is implied. Migration verification results and reproducible integrity commands are recorded in `migration_verification.txt`.

## Remaining handoff

Extract the archive, open the dedicated project folder in Codex, and use `CODEX_START.md`. The archive does not move the original ChatGPT chat history, select a remote repository, install Codex, or start a Codex task on the owner's device.
