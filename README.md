# Trading agent — single-owner local research/trading application

A local application that will research (LM Studio, local inference) and
eventually trade through Robinhood's official external-agent MCP interface,
governed by deterministic risk, authorization, ledger, and reconciliation
services. **Profitability is an unproven research hypothesis.**

**Current state (2026-10-31): M0 foundation complete.** The repository
contains the project scaffolding, typed fail-closed configuration, a broker
interface whose unavailable implementations explicitly reject execution, a
deterministic live-activation gate, a verified disposable local database, and
the M0 documentation set. No trading engine, website, or financial integration
exists yet.

- Current financial authority: **LIVE_NOT_AUTHORIZED**
- Approved live capital: **0 USD** (requested USD 1,000 pilot: recorded in
  build plan section 24, activation pending)
- Next task: **Prompt 2 (M1)** — first offline trading slice + first website
  pages. One numbered prompt at a time from
  [docs/Trading_Agent_Codex_Prompts.txt](docs/Trading_Agent_Codex_Prompts.txt).

## Setup and validation (M0, all offline)

Prerequisite: `uv` (e.g. `brew install uv`).

```bash
uv sync                                  # create .venv (Python 3.13) from uv.lock
uv run ruff check .                      # lint
uv run mypy                             # strict type checks
uv run pytest                           # 51 tests
uv run trading-agent check-config        # configuration smoke check (exit 0)
uv run trading-agent check-config --probe-llm   # adds a read-only LM Studio model-list probe
uv run trading-agent capabilities        # sanitized broker capabilities + authority
```

Optional disposable database (loopback-only; never touches the dissertation
Postgres on port 5432):

```bash
docker compose up -d                     # PostgreSQL 17 on 127.0.0.1:5433
psql -h 127.0.0.1 -p 5433 -U trading_agent -d trading_agent
docker compose down                      # stop (data volume kept; add -v to remove)
```

Configuration lives in `config/simulation.yaml` with `.env.example` as the
blank-secret template (copy to `.env`, gitignored). Invalid financial
configuration fails at startup with every violation listed
(`trading-agent check-config` exits 2). Live trading cannot be activated by
any single flag: the activation gate requires twelve prerequisites, none of
which can be satisfied in the delivered configuration.

## Project files

| File | Purpose |
| --- | --- |
| [AGENTS.md](AGENTS.md) | Persistent scope, workflow, authority, and boundaries |
| [CODEX_START.md](CODEX_START.md) | The original Prompt 1 (M0) — now executed |
| [Build plan](docs/Robinhood_Local_AI_Trading_Build_Plan.md) | Governing product specification |
| [Prompt pack](docs/Trading_Agent_Codex_Prompts.txt) | 12-step implementation sequence; current task: Prompt 2 |
| [Website specification](docs/Local_Trading_Website_Spec.md) | Full website contract and acceptance scenarios |
| [Build status](docs/build_status.md) | Milestone ledger, M0 evidence, and next action |
| [Architecture](docs/architecture.md) | Trust planes, module map, config/gate/persistence design |
| [Website contract](docs/website.md) | Routes, auth, scoping, read-model/event contracts, M1/M5 backlog |
| [Capability matrix](docs/capability_matrix.md) | Facts / assumptions / pending owner-run verifications |
| [Decision log](docs/decision_log.md) | M0 decisions with rationale and reversibility |
| [Migration record](docs/migration_record.md) | What was recovered, verified, and left unresolved |
| [Source manifest](SOURCE_MANIFEST.json) | Original and current document hashes |
| [Checksums](CHECKSUMS.sha256) | Integrity checks for the handoff files |

## Scope and sequencing

Run the numbered prompt pack one prompt at a time. Prompt 1 (M0) is complete;
do not run the older plan's combined section 26 kickoff. The website starts
with persisted synthetic data in Prompt 2 (M1): Overview, Activity,
Orders/fills with detail, Portfolio/instrument detail, and basic charts
(see [docs/website.md](docs/website.md)). Prompt 8 (M5) completes all pages,
live updates, exports, and mode-permitted controls. No broker connection is
needed to build and inspect the website.

The owner's requested USD 1,000 observation pilot is recorded in build plan
section 24 with the future authenticated approval flow. Requested capital and
active trading authority are separate: checked-in live capital remains zero,
and no funding or activation has occurred.

## Authority and limits

- Development uses fixtures, simulation, and paper mode by default.
- Approved live capital is zero. Current financial authority:
  **LIVE_NOT_AUTHORIZED**.
- Original platform findings are dated source material; recheck uncertain
  APIs and capabilities against current primary documentation during
  implementation.
- No remote repository is configured; local commits only. Original source
  documents are preserved in Git history.

Codex project-instruction reference: [official AGENTS.md documentation](https://learn.chatgpt.com/docs/agent-configuration/agents-md).
