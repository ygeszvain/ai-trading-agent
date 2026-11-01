# Open source publication verification

Date: November 1, 2026. Destination:
[ygeszvain/ai-trading-agent](https://github.com/ygeszvain/ai-trading-agent).
Scope: publish the existing development snapshot, add an MIT license and public
setup/contribution/security documentation, and verify the advertised offline
commands. This task does not execute or certify a later numbered milestone.

## Publication changes

- Rewrote README with current source scope and explicit verification limits.
- Added `SETUP.md`, `LICENSE`, `CONTRIBUTING.md`, and `SECURITY.md`.
- Added MIT metadata and project links in `pyproject.toml`.
- Anchored local-state ignore rules so `src/trading_agent/data` is included in
  Git; it was previously present locally but excluded by the broad `data/` rule.
- Excluded runtime reports/caches, `.data`, owner-auth files, database artifacts,
  and `.rebase-backup`. Recovery backups remain local and are not published.
- Disabled `broker.shadow_enabled` in the public simulation profile.
- Included existing working-tree implementation and tests for research/learning,
  web templates/assets, configuration, and backtesting without certifying their
  acceptance. Removed only trailing blank lines from three newly included files.
- Added publication context to `AGENTS.md` and the original build-status ledger.

## Offline software evidence

A clean export of the staged source was created with
`git checkout-index --all --prefix=<temporary-directory>/`. A separate virtual
environment was installed there with the committed lockfile; no original
working-tree imports were needed. Commands ran from that export on Python 3.13.

| Exact command | Actual result |
| --- | --- |
| `uv sync --locked` | Exit 0; clean environment installed successfully |
| `uv run trading-agent check-config` | Exit 0; SIMULATION, `result: OK`, LIVE_NOT_AUTHORIZED |
| `uv run trading-agent status` | Exit 0; synthetic enabled, FRED disabled, live disabled |
| `uv run trading-agent backtest run` | Exit 0; report directory contains Markdown, JSON, equity/fill CSVs and SVG |
| `uv run trading-agent eval TEST_A --out-dir reports/evaluation` | Exit 0; versioned synthetic JSON/Markdown reports |
| `uv run pytest -q` | Exit 1; **87 passed, 21 failed, 1 warning** in 6.94 seconds |
| `uv run ruff check src tests --output-format json` | Exit 1; **149 findings** after inclusion of the data source package |
| `uv run mypy` | Exit 1; **168 errors in 31 files**, 92 source files checked |
| `uv build` | Exit 0 in the working checkout; source distribution and wheel built |
| `git diff --cached --check` | Exit 0 after removal of trailing blank lines |

Wheel inspection confirmed inclusion of the data-provider modules, login
template, and browser JavaScript. Source-checkout operation remains the supported
setup: default configuration and migrations are resolved outside the wheel's
package directory.

`uv run trading-agent data status` was also attempted in the working checkout:
it fails with `AttributeError: 'RealDataCache' object has no attribute 'root'`.
It is not advertised as a working quick-start command.

## Known limitations and next work

- Three economic-evaluation tests fail around regime/whipsaw verdicts and fold
  edge expectations. Eighteen learning tests fail around incompatible record/API
  shapes, error classes, serialization/digests, paper lifecycle, and store errors.
  Those failures were preserved; no objective, risk policy, or assertion was
  changed to conceal them.
- Static checks include undefined names, interface/type mismatches, unused imports,
  formatting, and line-length issues. Building a package does not resolve them.
- The synthetic report has suspicious aggregate/benchmark scaling, nearly
  zero-volatility Sharpe behavior, and a first fold without a training window.
  Numerical and temporal validity require review before interpreting performance.
  The CLI's backtest range overrides also need implementation review.
- The new web test checks authentication-file creation and the Host gate. Its
  Host-gate check tolerates route/database errors; passing it does not establish
  that portfolio pages or financial totals work. Full seed/restart, browser,
  scope-isolation, financial reconciliation, staleness, accessibility, and
  performance acceptance have not been revalidated.
- Some tests touch the configured local PostgreSQL service; their success is
  environment dependent. A clean source/environment test is not a fresh-host
  or containerized PostgreSQL acceptance test.
- Legacy plan/status/migration documents preserve historical evidence. Their old
  CLI examples and "no UI exists" wording must not be read as present verification.
  `trading-agent --help` and `SETUP.md` describe this snapshot's actual CLI surface.
- The source contains later-stage scaffolding but does not prove sequential
  milestone completion. Reconcile **Prompt 2 (M1)** acceptance and the milestone
  ledger before advancing to Prompt 3 or claiming M2–M5 complete.

## Source and history review

Reviewed tracked history plus staged source with a bounded pattern check for
provider tokens, private keys, credentials embedded in HTTP URLs, and long literal
secret assignments. The initial scan covered 215 unique blobs and returned no
pattern candidates. Tracked-path checks found no `.data`, `.rebase-backup`, virtual
environment, private key, or database artifacts. Final authored documentation was
also checked before committing. This is not a comprehensive secret-detection or
security-audit guarantee. Runtime credentials/state are excluded from publication.

## Integration/operations and investment evidence

Owner-operated checks **not performed** by this publication: financial-account
onboarding or capability discovery, broker read/write calls, live execution,
LM Studio endpoint/model/auth acceptance, real-feed protocol/license verification,
prospective paper/shadow sessions, production deployment, or public website
hosting. No model weights or paid feeds were obtained.

No prospective investment evidence was collected. Profitability remains unproven.
Publishing source code does not authorize any financial action.

Current financial authority: **LIVE_NOT_AUTHORIZED**.
