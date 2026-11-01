# AI Trading Agent

An open source, local Python application for trading research, synthetic market
simulation, and inspecting persisted trading activity. Research inference is
designed for LM Studio. Deterministic configuration, risk, authorization, ledger,
and reconciliation services govern financial behavior.

**Experimental development snapshot — November 1, 2026.** The repository includes
simulation, backtesting, economic evaluation, research, gateway scaffolding,
learning experiments, and an authenticated local website. These components are
at different stages of verification. The full test suite currently has failures;
see [current security review](docs/security_readiness_review.md) and the
historical [publication baseline](docs/publication_status.md).

Prompt 9's research-only learning workflow is now implemented in this source
checkout. Run `uv run trading-agent learning demo` for matured and incomplete
labels, bounded challenger comparisons, a frozen champion, and a blocked
promotion proposal. Read [research learning](docs/research_learning.md) for current
acceptance and limitations; the publication report remains historical evidence.

Prompt 11 adds [supervised-readiness controls](docs/supervised_readiness.md),
a read-only approval/audit view and an [unsigned pilot worksheet](docs/supervised_activation_package.unsigned.json).
`uv run trading-agent supervised demo` exercises a separate child process and
injected fake transport. `uv run trading-agent supervised package` prints the
unresolved worksheet. Neither command can activate or access a financial account.

Prompt 12 adds [bounded-autonomy control readiness](docs/bounded_autonomy_readiness.md)
and an [unsigned owner review](docs/bounded_autonomy_owner_review.unsigned.json).
`uv run trading-agent autonomy demo` runs three synthetic sessions under a frozen
envelope with an independent monitor process and injected fake transport. There
are zero per-intent application approvals in that fixture. The read-only
`/autonomy` view exposes bindings, health and denied changes. Actual authority
stays absent; the automatic change class is `NONE`, and promotion only prepares
review evidence. No activation, renewal or real dispatch is implemented.

**Financial authority: LIVE_NOT_AUTHORIZED. Approved live capital: USD 0.**
Profitability is an unproven research hypothesis. Synthetic reports demonstrate
software behavior and do not establish an investment edge. This is research
software, not a supported live trading product.

## Quick start

Prerequisites: Git, [uv](https://docs.astral.sh/uv/getting-started/installation/),
and Python 3.13. The project pins Python through `.python-version`; `uv` can
provision it if necessary. Installing dependencies needs network access; the
synthetic commands below require no broker, model server, data key, or database.

```bash
git clone https://github.com/ygeszvain/ai-trading-agent.git
cd ai-trading-agent
uv sync --locked
uv run trading-agent --help
uv run trading-agent check-config
uv run trading-agent status
uv run trading-agent backtest run
```

The default profile uses fictional `TEST_A`, `TEST_B`, and `TEST_C` instruments.
Real data, research inference, and broker shadow polling are disabled in that
profile. Live execution, cloud inference fallback, and paid subscriptions remain
disabled. Monetary values use Decimal or integer units in backend services.

The backtest writes `report.md`, `results.json`, `equity.csv`, `fills.csv`, and
`equity_curve.svg` under `reports/<backtest-id>/`. Reports and local state are
ignored by Git. Report generation currently succeeds, but accounting/benchmark
and evaluation limitations remain open; do not rely on its metrics for capital
allocation. Backtest capital and the persisted simulator's paper capital are
separate settings; inspect `backtest` and `paper` in the configuration.

For a versioned synthetic economic-evaluation report:

```bash
uv run trading-agent eval TEST_A --out-dir reports/evaluation
```

## Local website and complete instructions

Follow [SETUP.md](SETUP.md) for configuration, optional PostgreSQL, migrations,
owner-token login, website startup, tests, troubleshooting, and shutdown.
The website binds to `http://127.0.0.1:8000` and reads persisted database state;
running a file-based backtest does not populate its portfolio. The delivered
pages cover Overview, Activity, Orders/fills, Portfolio, and instrument details.
Core persisted browser failure checks now pass in the isolated review fixture.
Normal startup is blocked by a detected migration/schema mismatch; full M5
website acceptance remains pending. See the [security evidence matrix](docs/security_readiness_review.md).

Do not publish the application server, expose a tunnel, or connect a financial
account as part of this quick start. Publishing this source repository does not
activate trading or deploy a service.

## Development and contribution

```bash
uv sync --locked
uv run pytest -q
uv run ruff check src tests
uv run mypy
```

These are real checks, not an all-green claim. Known failures are recorded in
[security review](docs/security_readiness_review.md) and the historical
[publication_status.md](docs/publication_status.md). Please retain failed results
and evaluation objectives when contributing. Read [CONTRIBUTING.md](CONTRIBUTING.md)
and [AGENTS.md](AGENTS.md) before changing code. Use synthetic data and keep
credentials, account data, and private logs out of issues and pull requests.
See [SECURITY.md](SECURITY.md) for vulnerability reporting.

## Project map

| Location | Purpose |
| --- | --- |
| `src/trading_agent/config`, `contracts`, `gates` | Typed settings, contracts, activation checks |
| `src/trading_agent/fixtures`, `data`, `strategies` | Synthetic inputs, data-provider scaffolding, numerical rules |
| `src/trading_agent/risk`, `execution`, `ledger` | Risk checks, execution state, accounting and reconciliation |
| `src/trading_agent/engine`, `backtest`, `evaluation` | Persisted simulation, file reports, evaluation protocols |
| `src/trading_agent/research`, `learning`, `gateway` | Experimental research, challengers, gateway contracts |
| `src/trading_agent/web` | FastAPI routes, local templates and assets |
| `migrations` | Alembic database revisions |
| `tests` | Unit, property, evaluation, and experimental learning checks |

The [build plan](docs/Robinhood_Local_AI_Trading_Build_Plan.md),
[prompt pack](docs/Trading_Agent_Codex_Prompts.txt), and
[website specification](docs/Local_Trading_Website_Spec.md) describe the intended
product and boundaries. [Build status](docs/build_status.md) retains the original
M0 acceptance evidence; the publication addendum distinguishes the current
snapshot from completed milestones. No later milestone is certified by this
publication. Prompts 9–11 were explicitly selected separately. M6 mock controls pass their
focused checks; actual readiness remains **BLOCKED** (full suite: 222 passed /
3 existing failures). The next numbered task is **Prompt 12**, only when
selected; earlier acceptance and operational dependencies remain unresolved.

## License

[MIT](LICENSE), copyright 2026 Randy Geszvain and contributors. Dependencies,
model weights, broker services, and datasets retain their own licenses and terms.
No model weights, financial credentials, or market datasets are distributed here.
