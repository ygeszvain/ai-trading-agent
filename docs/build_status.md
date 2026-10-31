# Trading agent build status

**Last updated:** 2026-10-31 (Prompt 1 / M0 complete)
**Current financial authority:** LIVE_NOT_AUTHORIZED
**Approved live capital:** 0 USD (requested USD 1,000 pilot: recorded, activation pending — plan section 24)
**Next task:** Prompt 2 — first offline trading slice and local website (M1)

## M0 — Repository, environment, and persistent boundaries

### What works now

- Clean-checkout setup and validation commands are documented (README) and were
  executed successfully on this host: `uv sync`, `uv run ruff check .`,
  `uv run mypy` (strict), `uv run pytest` (51 tests), and
  `uv run trading-agent check-config`.
- Typed configuration with fail-closed rules (plan section 22 contract,
  `.env.example`, `config/simulation.yaml`, `config/live.template.yaml`,
  `config/source_registry.yaml`). Invalid financial configuration exits 2 and
  lists every violation; a missing file, malformed YAML, or a bad env value
  all fail clearly.
- No usable live execution path: the Robinhood adapter is explicitly
  unavailable, the simulator placeholder rejects all execution, and the
  deterministic activation gate (12 prerequisites) can never authorize in M0
  — even for a fully populated live profile plus a hypothetical verified
  gateway.
- Disposable local database: `docker compose` PostgreSQL 17 on
  127.0.0.1:5433 (container `trading-agent-postgres`, healthy, verified with
  a SQL round-trip; port 5432 belongs to the unrelated dissertation
  `fda-postgres`).
- Website contract documented (routes, startup/auth, scoping, read-model and
  event contracts, page-to-backend map, M1/M5 backlog) in
  [website.md](website.md). **No UI exists; none is claimed.**

### Acceptance criteria (Prompt 1)

| Criterion | Result |
| --- | --- |
| Clean checkout has documented setup and validation commands | PASS — README; all commands run successfully (results in the M0 evidence section below) |
| Minimal configuration smoke check | PASS — `uv run trading-agent check-config` (exit 0 on `config/simulation.yaml`; exit 2 + per-violation messages on invalid configs) |
| No usable live execution path | PASS — gate + adapter rejections, covered by 51 tests including property tests |
| Invalid financial configuration fails clearly | PASS — every violation class tested (negative/NaN/malformed capital, cloud fallback, non-loopback URLs, TEST_* in live allowlist, over-unity limits, unknown keys, live-mode requirement matrix) |
| Milestone backlog and unresolved dependencies are concrete | PASS — ledger below; capability matrix lists pending owner-run items and what each blocks |

### Changed files (M0)

- New: `pyproject.toml`, `uv.lock`, `.python-version`, `.env.example`,
  `docker-compose.yml`, `config/simulation.yaml`, `config/live.template.yaml`,
  `config/source_registry.yaml`
- New source: `src/trading_agent/{__init__,exceptions,money}.py`,
  `src/trading_agent/config/{__init__,models,loading}.py`,
  `src/trading_agent/contracts/{__init__,broker}.py`,
  `src/trading_agent/execution/{__init__,broker_interface,simulator,robinhood_mcp,factory}.py`,
  `src/trading_agent/gates/{__init__,live_activation}.py`,
  `src/trading_agent/cli/{__init__,__main__,main}.py`
- New tests: `tests/conftest.py`, `tests/unit/{test_config_validation,test_broker_adapters,test_live_activation_gate,test_cli}.py`,
  `tests/property/test_config_invariants.py`, package `__init__.py` files
- New docs: `docs/architecture.md`, `docs/website.md`,
  `docs/capability_matrix.md`, `docs/decision_log.md`
- Updated: `docs/build_status.md` (this file), `README.md`, `AGENTS.md`
- Preserved unchanged: the two recovered source documents, the prompt pack,
  `CODEX_START.md`, `migration_record.md`, `CHECKSUMS.sha256`,
  `SOURCE_MANIFEST.json` (originals remain in Git history; current hashes
  match the migration manifest)

### Exact commands and actual results (run 2026-10-31 on the target host)

| Command | Result |
| --- | --- |
| `brew install uv` | uv 0.13.6 installed (Homebrew bottle) |
| `uv sync` | Resolved 35 packages; wrote `uv.lock`; created `.venv` (Python 3.13.2); pydantic 2.14.2, PyYAML 6.0.3, FastAPI/uvicorn locked; installed `trading-agent 0.1.0` (editable) |
| `uv sync --reinstall-package trading-agent` | Rebuilt the editable install after source files were added |
| `uv run ruff check .` | All checks passed (after formatting) |
| `uv run ruff format --check .` | All files formatted |
| `uv run mypy` | Success: no issues found in 18 source files (strict) |
| `uv run pytest -q` | **51 passed** in ~0.3 s |
| `uv run trading-agent check-config --probe-llm` | exit 0; mode SIMULATION; broker simulator (execution disabled); gate: 11 unmet prerequisites, LIVE_NOT_AUTHORIZED; LM Studio probe: reachable, 4 models loaded; `result: OK` |
| `uv run trading-agent check-config --config /tmp/bad-trading-config.yaml` | exit 2; listed 3 violations (cloud fallback, negative capital, over-unity limits) with clear messages |
| `docker compose up -d` | `trading-agent-postgres` started (reused cached postgres:17 image); healthy |
| `psql -h 127.0.0.1 -p 5433 -U trading_agent -d trading_agent -c "select version();"` | `PostgreSQL 17.9 ... on aarch64-unknown-linux-gnu`; SQL round-trip OK |

### Checks not run (honest limitations)

- No website, browser, or UI check — no UI exists (M1).
- No LM Studio inference performed: only read-only route probes in M0
  (decision D15). Functional endpoint/model capability tests are M2.
- No broker interaction of any kind; no MCP client installed.
- No trading engine, ledger, or strategy: simulator execution and all plan
  section 16 persistence arrive in M1.
- LM Studio authentication state unverified (plan section 9; M2).
- Host security observation (dissertation `fda-postgres` on 0.0.0.0:5432)
  recorded but not acted on — outside this repository.

### Evidence tracks

| Track | State |
| --- | --- |
| Software | Foundation passes offline tests (lint/type/51 tests/CLI); no trading engine yet |
| Integration/operations | LM Studio server observed reachable (4 models); local Postgres verified; broker: nothing performed (PENDING owner-run, M4) |
| Investment | Nothing measured. Profitability remains unproven. |

### Unresolved dependencies (concrete)

1. **Owner-run broker authorization + capability discovery** (M4/Prompt 7) —
   blocks the real gateway, shadow mode, and every live mode.
2. **LM Studio functional capability tests + model selection** (M2/Prompt 4) —
   blocks model-dependent research; deterministic work does not wait.
3. **Owner pilot fields** (account, limits, dates, mode, overnight policy,
   funding) — blocks M6/M7 activation screens; not needed for M1.
4. **Data provider/budget decision** (M3) — blocks real historical data;
   fixtures proceed.
5. **Remote repository selection** (none exists) — blocks any push; local
   commits only for now.

None of these block Prompt 2's offline work.

## Milestone ledger

| Prompt | Scope | Status |
| --- | --- | --- |
| 1 | Repository, environment, and persistent boundaries (M0) | **Complete 2026-10-31** — evidence above |
| 2 | First offline trading slice and local website (M1) | Next |
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

## Next action

Read AGENTS.md, this file, the build plan, and `docs/Trading_Agent_Codex_Prompts.txt`
(Prompt 2). Implement M1: the first offline vertical slice — strict
configuration is done in M0; M1 adds typed data/decision/policy/order/fill/
ledger contracts, synthetic market fixtures, one deterministic strategy plus
HOLD, cash/passive baselines, the risk engine with reservations, the
simulated order lifecycle, the first website pages (Overview, Activity,
Orders/fills, Portfolio/instrument per `docs/website.md`), PostgreSQL
migrations, the documented offline demo, and the restart/idempotency
guarantees. Do not widen risk limits or change evaluation objectives to make
tests pass. Stop at M1 and report honestly.

Current financial authority: **LIVE_NOT_AUTHORIZED**.
