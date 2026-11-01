# Contributing

Contributions are welcome under the [MIT license](LICENSE). By submitting a
contribution, you agree that it may be distributed under that license and that
you have the right to contribute it.

1. Read [AGENTS.md](AGENTS.md), [SETUP.md](SETUP.md), the build plan, and
   [publication status](docs/publication_status.md). Work on one focused task.
2. Fork the repository and create a branch. Preserve unrelated work and the
   sequential milestone boundaries; a feature in the roadmap is not authorization
   to connect an account or trade.
3. Use fixtures and simulated money. Never include broker credentials, real
   account identifiers, market data without redistribution rights, owner tokens,
   private logs, or model weights. Keep financial arithmetic exact.
4. Run `uv sync --locked`, `uv run pytest -q`, `uv run ruff check src tests`, and
   `uv run mypy`. Report actual results, including existing failures. Add meaningful
   invariant/failure checks when behavior warrants them.
5. Open a pull request describing the problem, resulting behavior, validation,
   remaining limitations, and any configuration or migration effects.

Do not weaken authorization, risk policy, temporal splits, accounting invariants,
or failed research results to make a change look successful. Record software,
real integration/operations, and investment evidence separately. No contribution
or passing test grants live authority. Do not use real financial mutations as tests.

Report ordinary bugs through [GitHub issues](https://github.com/ygeszvain/ai-trading-agent/issues)
with synthetic reproduction steps. Follow [SECURITY.md](SECURITY.md) for sensitive
vulnerabilities. No response-time or production-support commitment is offered.
