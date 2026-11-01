# Setup and operation

This guide describes the November 1, 2026 development snapshot. Start with the
verified synthetic CLI workflow. Current checks and remaining integration limits are in the
[repair report](docs/stabilization_and_auth_readiness.md); the
[publication status](docs/publication_status.md) is historical.

## 1. Install and validate

Install Git, Python 3.13, and uv using their official installation instructions.
On macOS with Homebrew, `brew install uv` is one option. Docker Compose is optional
and needed only for the supplied PostgreSQL service. No Node.js toolchain is
required; browser assets are bundled locally.

```bash
git clone --branch codex/offline-stabilization https://github.com/ygeszvain/ai-trading-agent.git
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
publication's failed results remain archived; reviewed economic assertions and
causal accounting fixes now pass without changing the evaluation protocol.

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

Normal startup now passes on the repaired schema. For a **new disposable
synthetic database**, migrate, populate a persisted $500 fixture, then serve:

```bash
uv run trading-agent migrate --config config/pilot500.simulation.yaml
uv run trading-agent demo --config config/pilot500.simulation.yaml
uv run trading-agent serve --config config/pilot500.simulation.yaml
```

For an existing database, first make an owner-reviewed backup and inspect the
migration. Legacy M3 tables are retained under `legacy_m3_*`; ambiguous ledger
ordering is blocked for manual review, not guessed. Populated downgrade refuses
to discard evidence. Never bypass schema validation or use another project's DB.
The repair review used its own disposable PostgreSQL on 55433 and did not touch
the owner's existing 5433 database.

Startup applies migrations, bootstraps a per-installation owner token, and serves
`http://127.0.0.1:8000/auth/login`. Use that exact hostname so Host/Origin and
cookie checks agree. Startup prints the protected file path, never its token.
Retrieve the token locally for the login form and keep it private. It is stored
with mode `0600` in `~/.trading-agent/webauth.json` outside the repository. `TRADING_AGENT_WEB_AUTH_FILE` can select another protected path;
do not point it at a tracked file. Never paste the file or token into chat.

On subsequent starts, use your saved token. If lost, stop the server, remove only
your installation's owner-auth file, and restart to create a new one. This rotates
both the owner token and session-signing secret, invalidating existing cookies.
Changing `web.token` in YAML does not configure this server's authentication;
`web/auth.py` currently uses the owner-auth file.

Change the port with `uv run trading-agent serve --port 8001`. Bind only to
`127.0.0.1` or `localhost`. Use Ctrl-C to stop the server. Page reads query stored
state; file-based backtests do not seed the website database. An incompatible
database stops before serving; a compatible empty database returns unavailable
data rather than invented amounts.

`demo` now uses `TradingPipeline(config).run()` and persists the fictional run.
A repeated completed run returns `already-complete`; crash/restart and competing
worker paths are tested. At $500 the whole-share fixture produces zero strategy
orders under existing limits; this is an honest feasibility result. Backtests
still write files separately. `migrate` and `demo` require simulation/simulator
settings. `capabilities`, `broker setup` and `--probe-llm` are not current commands.
Inspect `--help` for actual commands; use the separate owner-runtime guide for
authentication instead of legacy token-paste examples.

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

The latest full review passed 325 tests, Ruff and mypy. Use the four explicit
disposable PostgreSQL opt-ins in the [repair report](docs/stabilization_and_auth_readiness.md)
to exercise all database cases; otherwise some skip. Original failed evidence
and fixture-expectation review remain available. Never point test URLs at an owner
database. No test is permission to submit a real order. A wheel-only deployment
is not certified by these checks.

### Supervised readiness is an offline mock task

```bash
uv run trading-agent supervised package
uv run trading-agent supervised demo
```

These commands use no broker token or live transport and never activate a pilot.
The demo writes a new fictional journal/report/unsigned package each time. Read
[the M6 report and owner runbook](docs/supervised_readiness.md) for mock browser
QA, exact checks, unresolved fields and future owner-operated procedures.
`config/pilot.simulation.yaml` is a separate USD 1,000 synthetic feasibility
profile; live capital remains zero and the original limits remain unchanged.
Actual live dispatch remains unavailable. A new USD 500 simulation profile and
[unsigned owner draft](docs/pilot500_owner_request.unsigned.json) record the later
request; the historical USD 1,000 worksheet remains unchanged. Do not remove
schema or live-dispatch guards to run integration checks.

## 6. LM Studio, data, and broker dependencies

No model server is required for the quick start. Local inference modules exist,
and two harmless local HOLD smoke probes passed; full model/authentication and
artifact acceptance remain pending. Do not download weights or enable cloud fallback automatically.
Keep model requests on the configured loopback endpoint and credentials outside
source control. The [capability matrix](docs/capability_matrix.md) records older
observations, not proof of your current installation's capabilities.

Real-data fetching is disabled by default. `data status` now succeeds without fetching.
Real provider protocols, series identities and point-in-time rights still require
review before financial use. Do not enable a provider, purchase a
feed, or redistribute data based on this snapshot.

The real trading gateway and legacy OAuth paths stay quarantined. The new
[owner-runtime guide](docs/owner_runtime_setup.md) provides PKCE browser OAuth
and schema-only discovery under the owner-approved `randygeszvain` or separate
`ai-trading-executor` OS identity. It has been
tested with fake transport; actual broker behavior remains pending. No broker
authentication or protected MCP request was performed in this review. Setting
shadow/live flags cannot activate dispatch. Keep real credentials outside the
model context and coding tools; same-user storage is not OS isolation.
Setup/demo never funds, trades or activates.

## 6a. Disabled bounded-autonomy review (Prompt 12)

```sh
uv run trading-agent autonomy package
uv run trading-agent autonomy demo
```

These offline commands need no model, financial account, credential or existing
database. A new private journal under `.data/autonomy/` records three fictional
sessions, a frozen synthetic envelope, independent monitor process, six fake
fills and denied changes. One initial fixture resume covers the sessions; this
does not supply real authorization or waive broker-required approvals. The
automatic change class stays NONE and no promotion/renewal/activation exists.

Read [the M7 report and owner review](docs/bounded_autonomy_readiness.md) for
commands, limits, persisted-data browser inspection and the unsigned worksheet.
The `/autonomy` page is read-only. Normal website startup now works after the reviewed migration;
the explicitly named fixture harness cannot trade. Owner-
operated real integration checks, account/capital/limits/monitoring/recovery
decisions and investment evidence remain pending. Setup never activates live mode.

## 7. Troubleshooting

| Symptom | Action |
| --- | --- |
| `uv` is missing | Install uv from its official documentation; reopen the shell if needed. |
| Unsupported Python | Use Python 3.13 and rerun `uv sync --locked`. |
| Import of `trading_agent.data` fails | Use the published source tree, which includes this package, and resync the environment. |
| Configuration error | Read each validation message; compare your ignored local profile with the default. Do not enable live settings to bypass it. |
| Database unreachable | Check `docker compose ps`, port 5433, and `app.db_url`; do not use another project's database. |
| Website refuses Host or Origin | Open the configured loopback URL with the correct port, not a LAN address or proxy. |
| Schema compatibility failure | Stop; use the missing-table/column list for a reviewed migration. Do not bypass validation. |
| Empty website | File reports do not populate database runs; run the persisted simulation `demo` against your disposable synthetic DB. |
| Test, lint, or type failures | Compare with the publication baseline and report a sanitized reproducer. |

For a bug report, include the commit, Python/uv versions, exact command, synthetic
configuration differences, and a sanitized error summary. Exclude tokens, owner
identity data, account numbers, private datasets, and full logs.
