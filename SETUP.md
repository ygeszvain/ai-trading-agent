# Setup and operation

This guide describes the November 1, 2026 development snapshot. Start with the
verified synthetic CLI workflow. Website, model, data-source, and gateway code
have additional limitations in [publication status](docs/publication_status.md).

## 1. Install and validate

Install Git, Python 3.13, and uv using their official installation instructions.
On macOS with Homebrew, `brew install uv` is one option. Docker Compose is optional
and needed only for the supplied PostgreSQL service. No Node.js toolchain is
required; browser assets are bundled locally.

```bash
git clone https://github.com/ygeszvain/ai-trading-agent.git
cd ai-trading-agent
uv sync --locked
uv run trading-agent check-config
uv run trading-agent status
```

Run commands from the repository root. This release supports a source checkout;
wheel-only installation is not a complete deployment because configuration and
migrations are resolved relative to the checkout.

## 2. Configuration

`config/simulation.yaml` is the default. To customize it, create an ignored local
profile, preserving simulation mode and all disabled live settings:

```bash
mkdir -p .data
cp config/simulation.yaml .data/local.yaml
uv run trading-agent --config .data/local.yaml check-config
```

Path precedence is `--config`, then `TRADING_AGENT_CONFIG`, then the default
profile. Recognized environment variables override the selected YAML. Unknown
YAML keys and invalid financial settings fail validation. Keep money and
fractional limits as quoted decimal strings.

`.env.example` documents environment names. The Python configuration loader does
**not** automatically load `.env`; export needed variables in your shell or use a
protected runtime injection method. Docker Compose reads its own `.env` handling.
No secret is required for synthetic runs. Never put a real secret in YAML,
terminal transcripts, source control, screenshots, or an issue.

Required development defaults:

- `app.mode: simulation`, `broker.provider: simulator`, `broker.shadow_enabled: false`.
- `live.enabled: false`, `live.approved_capital_usd: "0"`.
- `llm.allow_cloud_fallback: false`, `research.enabled: false`.
- Paid data budget zero, paid subscriptions disabled, non-synthetic sources disabled.

The live template is an inert design aid. Do not fill it in to activate trading.

## 3. Run the verified synthetic workflow

```bash
uv run trading-agent backtest run
uv run trading-agent eval TEST_A --out-dir reports/evaluation
```

The backtest emits a report directory and lists its files. `results.json` holds
the machine-readable snapshot, `equity.csv` and `fills.csv` hold tabular results,
and `equity_curve.svg` provides a standalone chart. Evaluation writes a versioned
JSON/Markdown pair. These are synthetic research artifacts with known numerical
and methodological limitations, not verified performance results.

`trading-agent --help`, `trading-agent backtest run --help`, and
`trading-agent eval --help` list the actual supported arguments. Date overrides
exist, but verify their effect in the resulting report; the current backtest
implementation has unresolved argument/application inconsistencies. Use the
checked-in default range for the reproducible smoke check.

The independent research learning demonstration is also offline:

```bash
uv run trading-agent learning demo
```

It writes immutable artifacts under `.data/learning/`, prints outcome counts,
records all four challenger trials, and prepares a blocked promotion proposal.
It cannot activate a champion. The printed `/learning?experiment_id=<hash>` link
opens the authenticated research page after website startup below. See
[research_learning.md](docs/research_learning.md) for contracts, budgets,
corrections, prospective-harness limits, and current checks. The initial
publication's failing learning fixtures have been repaired; three separate M3
economic-evaluation failures remain.

## 4. Optional local PostgreSQL and website

The file-based CLI demo needs no database. The persisted simulator and website
use PostgreSQL. The supplied Compose service binds only to `127.0.0.1:5433` and
creates database/user `trading_agent`. It uses trust authentication for a
**disposable local development database**, not a protected store for real
financial data. Do not load private account data or expose this database.

Inspect port availability and container names before starting; do not stop or
reconfigure unrelated databases to free a port. If needed, choose a free loopback
port in both Compose and your local YAML's `app.db_url`.

```bash
docker compose up -d
docker compose ps
```

Optional connectivity check if `psql` is installed:

```bash
psql -h 127.0.0.1 -p 5433 -U trading_agent -d trading_agent -c 'SELECT 1;'
```

Start the website:

```bash
uv run trading-agent serve
```

Startup applies migrations, bootstraps a per-installation owner token, and serves
`http://127.0.0.1:8000/auth/login`. Use that exact hostname so Host/Origin and
cookie checks agree. The first startup prints the login token locally. Keep it
private. It is stored with mode `0600` in `~/.trading-agent/webauth.json` outside
the repository. `TRADING_AGENT_WEB_AUTH_FILE` can select another protected path;
do not point it at a tracked file. Never paste the file or token into chat.

On subsequent starts, use your saved token. If lost, stop the server, remove only
your installation's owner-auth file, and restart to create a new one. This rotates
both the owner token and session-signing secret, invalidating existing cookies.
Changing `web.token` in YAML does not configure this server's authentication;
`web/auth.py` currently uses the owner-auth file.

Change the port with `uv run trading-agent serve --port 8001`. Bind only to
`127.0.0.1` or `localhost`. Use Ctrl-C to stop the server. Page reads query stored
state; file-based backtests do not seed the website database. A fresh database
may show empty data or incomplete-page errors in this snapshot.

The persisted simulation API is `TradingPipeline(config).run()` in
`src/trading_agent/engine/pipeline.py`. It is not exposed as a current CLI `demo`
command, and end-to-end seed/restart/browser acceptance has not been revalidated.
Do not assume the historical docs' `demo`, `migrate`, `capabilities`,
`broker setup`, or `--probe-llm` commands exist; inspect `--help`. This guide does
not present an unverified seed procedure as working.

Stop the disposable database, preserving its volume:

```bash
docker compose down
```

`docker compose down -v` additionally destroys this project's database volume;
use it only when you intend to discard that local fixture database.

## 5. Tests and packaging

```bash
uv sync --locked
uv run pytest -q
uv run ruff check src tests
uv run mypy
uv build
```

The current suite and static checks fail for documented pre-existing reasons.
Do not suppress failures, loosen risk limits, or change economic objectives to
produce a passing badge. The publication report records actual results. Tests
use fixtures; a subset exercises a local database, so full-suite results can
also depend on database availability. No test is permission to submit a real order.

## 6. LM Studio, data, and broker dependencies

No model server is required for the quick start. Local inference modules exist,
but full endpoint/model/authentication acceptance remains unverified in this
publication. Do not download weights or enable cloud fallback automatically.
Keep model requests on the configured loopback endpoint and credentials outside
source control. The [capability matrix](docs/capability_matrix.md) records older
observations, not proof of your current installation's capabilities.

Real-data fetching is disabled by default. `data status` currently raises an
AttributeError, and provider protocols, series identities, point-in-time rights,
and cache behavior need review before use. Do not enable a provider, purchase a
feed, or redistribute data based on this snapshot.

Gateway scaffolding is not an authenticated broker integration. This publication
performs no financial-account authentication, account setup, orders, cancellations,
transfers, or activation. Credentials belong in a separately controlled runtime
only after the corresponding integration/security milestones and owner decisions.

## 7. Troubleshooting

| Symptom | Action |
| --- | --- |
| `uv` is missing | Install uv from its official documentation; reopen the shell if needed. |
| Unsupported Python | Use Python 3.13 and rerun `uv sync --locked`. |
| Import of `trading_agent.data` fails | Use the published source tree, which includes this package, and resync the environment. |
| Configuration error | Read each validation message; compare your ignored local profile with the default. Do not enable live settings to bypass it. |
| Database unreachable | Check `docker compose ps`, port 5433, and `app.db_url`; do not use another project's database. |
| Website refuses Host or Origin | Open the configured loopback URL with the correct port, not a LAN address or proxy. |
| Blank/incomplete website | File reports do not populate database runs; website seeding/acceptance remains pending. |
| Test, lint, or type failures | Compare with the publication baseline and report a sanitized reproducer. |

For a bug report, include the commit, Python/uv versions, exact command, synthetic
configuration differences, and a sanitized error summary. Exclude tokens, owner
identity data, account numbers, private datasets, and full logs.
