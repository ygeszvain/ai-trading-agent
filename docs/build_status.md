# Trading agent build status

Recorded: 2026-10-28
Current financial authority: **LIVE_NOT_AUTHORIZED**
Approved live capital: **0 USD**
Next task: **Prompt 1 — M0**

## Verified state

The specification and 12-prompt implementation pack were initially recovered verbatim. They are now revised for the requested local trading website; the initial Git commit preserves the originals. The handoff includes updated repository instructions, the exact current Prompt 1, source/current hashes, and a dedicated local Git repository.

No application implementation has been verified or included in this repository. Do not infer completed milestones from the presence of planning documents or the migration commit.

## Website scope revision — 2026-10-28

Requested: a local website to see all trading activity and details. The expanded contract is in `Local_Trading_Website_Spec.md` and build-plan section 18. Prompt 1 plans its contracts; Prompt 2 builds the first persisted simulation website; Prompt 8 completes all pages, charts, detail, updates, exports, and operations. Prompt 10 verifies material browser/read-model risks.

This is a specification change only. Website implementation, browser screenshots, actual UI performance, and all application acceptance checks remain pending. No financial, account-connection, or hosting authority changed.

## Milestone ledger

| Prompt | Scope | Status |
| --- | --- | --- |
| 1 | Repository, environment, and persistent boundaries (M0) | Pending |
| 2 | First offline trading slice and local website (M1) | Pending |
| 3 | Accounting, execution, and recovery hardening | Pending |
| 4 | Local LM Studio research integration (M2) | Pending |
| 5 | Permitted data and point-in-time storage (M3) | Pending |
| 6 | Strategy and economic evaluation (M3) | Pending |
| 7 | Official Robinhood gateway with writes disabled (M4) | Pending |
| 8 | Full local trading website, monitoring, and forward paper mode (M5) | Pending |
| 9 | Controlled learning in research | Pending |
| 10 | Security and failure-readiness review | Pending |
| 11 | Supervised-live readiness; activation disabled (M6) | Pending |
| 12 | Bounded-autonomy readiness; activation disabled (M7/M8) | Pending |

## Evidence tracks

| Track | Current evidence |
| --- | --- |
| Migration / specification | Original sources retained in Git; current prompt/spec consistency, archive contents, links, hashes, and local Git state checked; see migration record |
| Software | No application build, unit tests, or configuration smoke checks have run |
| Integration / operations | No target-machine, LM Studio, data-provider, or broker behavior verified |
| Investment | No measured strategy results; profitability remains unproven |

## Unresolved dependencies

- Owner's target folder or remote repository and Codex environment.
- Actual runtime, hardware, installed tooling, and available local model IDs.
- Data-source permissions and real historical coverage.
- Official broker capabilities, account eligibility, and owner-operated integration setup.
- Separately scoped authorization for any future financial action.

These dependencies do not block Prompt 1's authorized offline development. Inspect the actual target environment, document facts and assumptions separately, and block only dependent work.

## Next action and completion contract

Read `AGENTS.md`, `CODEX_START.md`, and the full build plan. Execute Prompt 1 only. Create the M0 foundation and its required evidence; do not count this migration as M0 completion.

At each milestone, record changed files, acceptance evidence, exact commands and results, limitations, software/integration/investment status, and the next numbered prompt. Keep current financial authority explicit.
