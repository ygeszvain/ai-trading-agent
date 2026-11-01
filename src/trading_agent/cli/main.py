"""Command line interface: `trading-agent [command]`.

Commands (v1, loopback-only; financial authority is always
LIVE_NOT_AUTHORIZED):

  status          show configuration, mode, data sources, and authority
  backtest run    M3: deterministic walk-forward backtest (report to stdout + reports/)
  data sync       M3: refresh registry data sources into the on-disk cache (fail-closed)
  data status     M3: show per-symbol cache coverage and staleness (offline)
  eval            M3: economic edge evaluation for a registered protocol (research only)

Configuration precedence: --config flag > TRADING_AGENT_CONFIG environment
variable > config/simulation.yaml. Environment overrides follow build plan
section 9. Fail-closed: configuration errors and missing data abort clearly;
nothing here can move real money (live.enabled stays false).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from ..backtest.engine import BookSettings, CloseSeries, run_backtest
from ..backtest.report import render_markdown, write_report_package
from ..config.loading import ConfigEnvironment, load_config
from ..config.models import BacktestSettings, TradingConfig
from ..data.provider import MarketDataProvider, SyntheticMarketProvider
from ..data.realdata import (
    RealDataCache,
    RealMarketProvider,
    build_real_providers,
    fetch_source,
    run_quality_checks,
)
from ..exceptions import ConfigError
from ..fixtures.synthetic import build_synthetic_market
from ..research import EvalProtocol, standard_protocol
from ..research.econ_eval import (
    evaluate_protocol,
    render_report_markdown,
    write_report,
)

#: Environment variable holding the FRED API key (never the key itself).
FRED_API_KEY_ENV = "FRED_API_KEY"


def _sha256(payload: bytes | str) -> str:
    return hashlib.sha256(
        payload.encode("utf-8") if isinstance(payload, str) else payload
    ).hexdigest()


def _config_digest(config: TradingConfig) -> str:
    canonical = config.model_dump_json(indent=None)
    return _sha256(canonical)[:32]


def _spec_digest(config: TradingConfig) -> str:
    payload = {
        "live": config.live.model_dump(mode="json"),
        "risk": config.risk.model_dump(mode="json"),
    }
    return _sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")))[:32]


def _code_version() -> str:
    try:
        from ..version import __version__

        return f"trading-agent-{__version__}"
    except Exception:  # noqa: BLE001 - version is advisory provenance only
        return "trading-agent-dev"


def _resolve_config_path(flag_value: str | None) -> Path:
    if flag_value:
        return Path(flag_value).expanduser()
    env_value = os.environ.get("TRADING_AGENT_CONFIG")
    if env_value:
        return Path(env_value).expanduser()
    return Path(__file__).resolve().parents[3] / "config" / "simulation.yaml"


def _build_backtest_settings(
    backtest: BacktestSettings | None,
    args: argparse.Namespace,
) -> BacktestSettings:
    current = backtest
    if current is None:
        if args.start is None or args.end is None:
            print(
                "error: no [backtest] section in the configuration; pass --start and --end "
                "to define the range",
                file=sys.stderr,
            )
            raise SystemExit(2)
        current = BacktestSettings(
            range_start=date.fromisoformat(args.start),
            range_end=date.fromisoformat(args.end),
        )
    updates: dict[str, Any] = {}
    if args.start:
        updates["range_start"] = date.fromisoformat(args.start)
    if args.end:
        updates["range_end"] = date.fromisoformat(args.end)
    if getattr(args, "no_synthetic", False):
        updates["include_synthetic"] = False
    if getattr(args, "out_dir", None):
        updates["output_dir"] = args.out_dir
    if updates:
        current = current.model_copy(update=updates)
    if current.range_start >= current.range_end:
        print("error: backtest --start must be before --end", file=sys.stderr)
        raise SystemExit(2)
    return current


def _run_status(args: argparse.Namespace) -> int:
    path = _resolve_config_path(args.config)
    config = load_config(path, ConfigEnvironment())
    sources = [
        f"{spec.id}{' (enabled)' if spec.enabled else ' (disabled)'}: "
        f"{', '.join(spec.symbols) or '-'}"
        for spec in config.data.registry
    ]
    print(f"config: {path} (digest {_config_digest(config)})")
    print(f"mode: {config.app.mode}")
    print(f"environment: {config.app.environment}")
    print(f"data source: {config.data.source} (registry: {len(config.data.registry)} entries)")
    for line in sources:
        print(f"  {line}")
    print(f"live enabled: {config.live.enabled}  authority: LIVE_NOT_AUTHORIZED")
    print(f"broker: {config.broker.provider} ({config.broker.robinhood_mcp_url})")
    return 0


def _run_backtest(args: argparse.Namespace) -> int:
    path = _resolve_config_path(args.config)
    config = load_config(path, ConfigEnvironment())
    backtest = _build_backtest_settings(config.backtest, args)
    tz = ZoneInfo(config.app.exchange_timezone)
    start = backtest.range_start
    end = backtest.range_end
    now = datetime.now(tz)

    cache = RealDataCache(config.data.registry_root)
    results, real_providers = build_real_providers(config, cache, start, end, now=now)
    for source_id, result in sorted(results.items()):
        cached = sum(1 for item in result.results if item.status == "cached")
        print(
            f"data {source_id}: ok={result.ok} cached={cached}/{len(result.results)} "
            f"snapshot={result.snapshot_id}"
        )
        if not result.ok:
            for item in result.results:
                detail = f" ({item.detail})" if item.detail else ""
                print(f"  {item.symbol}: {item.status}{detail}")
            print("  -> excluded from the backtest (fail-closed)")

    providers: dict[str, MarketDataProvider] = dict(real_providers)
    if backtest.include_synthetic:
        market = build_synthetic_market(config)
        providers["synthetic"] = SyntheticMarketProvider(
            market, config.app.exchange_timezone, config.data.stale_after_sessions
        )

    if not providers:
        print(
            "error: no usable data sources for the backtest (no cached/enabled registry "
            "source and synthetic disabled)",
            file=sys.stderr,
        )
        return 1

    run = run_backtest(
        config,
        providers,
        config_path=str(path),
        spec_digest=_spec_digest(config),
        config_digest=_config_digest(config),
    )

    out_dir = Path(backtest.output_dir).expanduser()
    written = write_report_package(run, out_dir / run.backtest_id)
    for line in render_markdown(run).splitlines():
        print(line)
    print(f"report: {out_dir / run.backtest_id}")
    for file_path in written:
        print(f"  {file_path.name}")
    snapshots = {
        source_id: provider.data_snapshot_id() for source_id, provider in providers.items()
    }
    print(
        f"provenance: backtest={run.backtest_id} config={path} "
        f"config_digest={run.config_digest} spec_digest={run.spec_digest} "
        f"code={run.code_version} snapshots={json.dumps(snapshots, sort_keys=True)}"
    )
    return 0


def _load_eval_protocol(value: str) -> EvalProtocol:
    """Resolve the --protocol argument: 'standard' or a YAML/JSON file."""
    if value == "standard":
        return standard_protocol()
    path = Path(value).expanduser()
    if not path.exists():
        print(f"error: protocol file not found: {path}", file=sys.stderr)
        raise SystemExit(2)
    raw = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(raw) if path.suffix in (".yaml", ".yml") else json.loads(raw)
    except (yaml.YAMLError, json.JSONDecodeError) as error:
        print(f"error: could not parse protocol file: {error}", file=sys.stderr)
        raise SystemExit(2) from error
    try:
        protocol = EvalProtocol(**data)
        protocol.validate()
    except (ConfigError, TypeError, ValueError) as error:
        print(f"error: invalid protocol file: {error}", file=sys.stderr)
        raise SystemExit(2) from error
    return protocol


def _run_eval(args: argparse.Namespace) -> int:
    path = _resolve_config_path(args.config)
    try:
        config = load_config(path, ConfigEnvironment())
    except ConfigError as error:
        print("CONFIGURATION ERROR:", file=sys.stderr)
        for violation in error.violations:
            print(f"  - {violation}", file=sys.stderr)
        return 2
    backtest = _build_backtest_settings(config.backtest, args)
    tz = ZoneInfo(config.app.exchange_timezone)
    start, end = backtest.range_start, backtest.range_end
    now = datetime.now(tz)

    cache = RealDataCache(config.data.registry_root)
    results, real_providers = build_real_providers(config, cache, start, end, now=now)
    providers: dict[str, MarketDataProvider] = dict(real_providers)
    if backtest.include_synthetic:
        market = build_synthetic_market(config)
        providers["synthetic"] = SyntheticMarketProvider(
            market, config.app.exchange_timezone, config.data.stale_after_sessions
        )
    if args.source is not None:
        providers = {source_id: p for source_id, p in providers.items() if source_id == args.source}

    wanted = args.instrument.strip().upper()
    chosen: tuple[str, str] | None = None
    for source_id, provider in sorted(providers.items()):
        for instrument in provider.instruments():
            if instrument.instrument_id.upper() == wanted or instrument.symbol.upper() == wanted:
                chosen = (source_id, instrument.instrument_id)
                break
        if chosen:
            break
    if chosen is None:
        available = ", ".join(sorted(providers)) or "none"
        print(
            f"error: instrument '{args.instrument}' not found in data sources ({available}); "
            f"fail-closed: nothing to evaluate",
            file=sys.stderr,
        )
        return 1

    source_id, instrument_id = chosen
    provider = providers[source_id]
    pairs = [
        (close.session, close.close)
        for close in provider.recent_session_closes(instrument_id, end, 10**9)
        if start <= close.session <= end
    ]
    if not pairs:
        print(
            f"error: no sessions for {instrument_id} inside {start}..{end}; "
            f"widen the range or fetch deeper history",
            file=sys.stderr,
        )
        return 1

    series = CloseSeries(pairs)
    book = BookSettings(
        initial_cash=backtest.initial_cash_usd,
        cash_yield_annual=backtest.cash_yield_annual,
        cost=backtest.cost,
        target_weight=Decimal(config.strategy.target_weight),
    )
    protocol = _load_eval_protocol(args.protocol)
    data_source = "synthetic" if isinstance(provider, SyntheticMarketProvider) else "real"
    report = evaluate_protocol(
        protocol,
        series,
        list(series.dates()),
        book=book,
        instrument_id=instrument_id,
        data_snapshot_id=provider.data_snapshot_id(),
        data_source=data_source,
    )
    out_dir = Path(args.out_dir or backtest.output_dir).expanduser()
    report = write_report(report, out_dir)
    for line in render_report_markdown(report).splitlines():
        print(line)
    print(
        f"provenance: eval={report.run_id} config={path} protocol_digest={report.protocol_digest} "
        f"code={report.code_version} snapshot={report.data_snapshot_id}"
    )
    for name, file_path in sorted(report.artifacts.items()):
        print(f"  {name}: {file_path}")
    return 0


def _data_range(args: argparse.Namespace, config: TradingConfig) -> tuple[date, date]:
    end = (
        date.fromisoformat(args.end)
        if args.end
        else datetime.now(ZoneInfo(config.app.exchange_timezone)).date()
    )
    start = (
        date.fromisoformat(args.start)
        if args.start
        else date.fromisoformat(config.backtest.range_start.isoformat())
        if config.backtest is not None
        else end
    )
    return start, end


def _run_data_status(args: argparse.Namespace) -> int:
    path = _resolve_config_path(args.config)
    config = load_config(path, ConfigEnvironment())
    cache = RealDataCache(config.data.registry_root)
    now = datetime.now(ZoneInfo(config.app.exchange_timezone))

    symbols: set[str] = set()
    for spec in config.data.registry:
        if spec.id == "synthetic":
            continue
        symbols.update(spec.symbols)

    if not symbols:
        print("no non-synthetic sources registered (registry is synthetic-only)")
        return 0

    providers: dict[str, RealMarketProvider] = {}
    for source_id in {spec.id for spec in config.data.registry if spec.id != "synthetic"}:
        items = [cache.load(source_id, symbol) for symbol in symbols]
        data = [item for item in items if item is not None and item.observations]
        if data:
            providers[source_id] = RealMarketProvider(
                source_id=source_id,
                data=data,
                exchange_timezone=config.app.exchange_timezone,
                stale_after_sessions=config.data.stale_after_sessions,
            )

    print(f"cache: {cache.root}")
    for source_id in {spec.id for spec in config.data.registry if spec.id != "synthetic"}:
        for symbol in sorted(symbols):
            item = cache.load(source_id, symbol)
            if item is None:
                print(f"  {source_id}/{symbol}: not cached")
                continue
            last = max(item.observations) if item.observations else None
            print(
                f"  {source_id}/{symbol}: {len(item.observations)} obs "
                f"last={last} digest={item.content_digest}"
            )

    if providers:
        rows = run_quality_checks(providers, config, now)
        if rows:
            print("quality:")
            for row in rows:
                print(
                    f"  {row['instrument_id']} [{row['source_id']}]: "
                    f"observed={row['observed_sessions']} expected={row['expected_sessions']} "
                    f"missing={row['missing_sessions']} staleness="
                    f"{row['sessions_since_observation']}"
                    f"sessions {'STALE' if row['stale'] else 'ok'}"
                )
    return 0


def _run_data_sync(args: argparse.Namespace) -> int:
    path = _resolve_config_path(args.config)
    config = load_config(path, ConfigEnvironment())
    cache = RealDataCache(config.data.registry_root)
    now = datetime.now(ZoneInfo(config.app.exchange_timezone))
    start, end = _data_range(args, config)

    specs = [
        spec
        for spec in config.data.registry
        if spec.id != "synthetic" and spec.enabled and spec.symbols
    ]
    if not specs:
        print("no non-synthetic sources registered (nothing to sync)")
        return 0

    exit_code = 0
    for spec in specs:
        result = fetch_source(
            spec,
            cache,
            start,
            end,
            api_key=(os.environ.get(FRED_API_KEY_ENV) or os.environ.get(spec.api_key_env or "")),
            now=now,
        )
        cached = sum(1 for item in result.results if item.status == "cached")
        bad = [item for item in result.results if item.status not in {"ok", "cached"}]
        print(
            f"{spec.id}: ok={result.ok} cached={cached}/{len(result.results)} "
            f"snapshot={result.snapshot_id}"
        )
        for item in bad:
            detail = f" ({item.detail})" if item.detail else ""
            print(f"  {item.symbol}: {item.status}{detail}")
            exit_code = 1
        if not result.ok and not bad:
            exit_code = 1
    return exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trading-agent",
        description=(
            "Robinhood local AI trading agent (development). "
            "Financial authority: LIVE_NOT_AUTHORIZED."
        ),
    )
    parser.add_argument(
        "--config",
        default=None,
        help=(
            "Path to the YAML configuration (default: $TRADING_AGENT_CONFIG "
            "or config/simulation.yaml)"
        ),
    )
    # --config must work both before and after the subcommand: the parent
    # parser uses SUPPRESS so a subcommand without the flag keeps the value
    # parsed at the top level.
    config_parent = argparse.ArgumentParser(add_help=False)
    config_parent.add_argument("--config", default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    subparsers = parser.add_subparsers(dest="command", required=True)

    learning_parser = subparsers.add_parser(
        "learning", help="research-only learning artifacts (no activation)", parents=[config_parent]
    )
    learning_sub = learning_parser.add_subparsers(dest="learning_command", required=True)
    demo_parser = learning_sub.add_parser("demo", help="deterministic synthetic learning demo")
    demo_parser.add_argument("--out-dir", default=None, help="local research artifact directory")
    demo_parser.set_defaults(func=_run_learning_demo)

    backtest_parser = subparsers.add_parser(
        "backtest", help="deterministic backtest", parents=[config_parent]
    )
    backtest_sub = backtest_parser.add_subparsers(dest="backtest_command", required=True)
    run_parser = backtest_sub.add_parser(
        "run", help="run the configured walk-forward backtest", parents=[config_parent]
    )
    run_parser.add_argument("--start", default=None, help="range start, ISO date (e.g. 2023-01-02)")
    run_parser.add_argument("--end", default=None, help="range end, ISO date (inclusive)")
    run_parser.add_argument(
        "--no-synthetic",
        action="store_true",
        help="exclude the synthetic fixture source even if the config includes it",
    )
    run_parser.add_argument(
        "--out-dir", default=None, help="report output directory (default: reports)"
    )
    run_parser.set_defaults(func=_run_backtest)

    eval_parser = subparsers.add_parser(
        "eval",
        help="M3: economic edge evaluation for a registered protocol (research only)",
        parents=[config_parent],
    )
    eval_parser.add_argument("instrument", help="symbol or instrument_id to evaluate (e.g. NVDA)")
    eval_parser.add_argument(
        "--protocol",
        default="standard",
        help="'standard' (v1.0 default) or path to a YAML/JSON protocol file",
    )
    eval_parser.add_argument(
        "--start", default=None, help="range start, ISO date (default: config backtest range)"
    )
    eval_parser.add_argument("--end", default=None, help="range end, ISO date (inclusive)")
    eval_parser.add_argument(
        "--source", default=None, help="restrict to one data source id (e.g. real or synthetic)"
    )
    eval_parser.add_argument(
        "--out-dir",
        default=None,
        help="report output directory (default: config backtest.output_dir)",
    )
    eval_parser.set_defaults(func=_run_eval)

    data_parser = subparsers.add_parser(
        "data", help="registry data sources", parents=[config_parent]
    )
    data_sub = data_parser.add_subparsers(dest="data_command", required=True)
    sync_parser = data_sub.add_parser(
        "sync",
        help="refresh enabled non-synthetic sources into the cache (fail-closed)",
        parents=[config_parent],
    )
    sync_parser.add_argument("--start", default=None, help="fetch range start, ISO date")
    sync_parser.add_argument("--end", default=None, help="fetch range end, ISO date")
    sync_parser.set_defaults(func=_run_data_sync)
    status_parser = data_sub.add_parser(
        "status",
        help="show per-symbol cache coverage and staleness (offline)",
        parents=[config_parent],
    )
    status_parser.set_defaults(func=_run_data_status)

    status_command = subparsers.add_parser(
        "status",
        help="show configuration, mode, data sources, and authority",
        parents=[config_parent],
    )
    status_command.set_defaults(func=_run_status)
    check_parser = subparsers.add_parser(
        "check-config",
        help="validate a configuration and report the live-authorization gate",
        parents=[config_parent],
    )
    check_parser.set_defaults(func=_run_check_config)
    version_parser = subparsers.add_parser(
        "version", help="print the application version", parents=[config_parent]
    )
    version_parser.set_defaults(func=_run_version)
    serve_parser = subparsers.add_parser(
        "serve",
        help="run the read-only website (M5; owner-token login, no order controls)",
        parents=[config_parent],
    )
    serve_parser.add_argument(
        "--host", default=None, help="bind host (default: web.web_host in config)"
    )
    serve_parser.add_argument(
        "--port", type=int, default=None, help="bind port (default: web.web_port in config)"
    )
    serve_parser.set_defaults(func=_run_serve)
    return parser


def _run_learning_demo(args: argparse.Namespace) -> int:
    from ..learning.demo import run_demo
    from ..learning.workflow import load_report

    config = load_config(_resolve_config_path(args.config), ConfigEnvironment())
    if config.app.mode.value != "simulation" or not config.learning.enabled:
        print(
            "error: the synthetic learning demo requires simulation and learning.enabled",
            file=sys.stderr,
        )
        return 2
    if config.learning.max_challenger_trials_per_week < 4:
        print("error: the fixed demo requires a trial allowance of at least four", file=sys.stderr)
        return 2
    root = Path(args.out_dir) if args.out_dir else config.learning.research_store_dir
    path = run_demo(root)
    report = load_report(root, path.stem)
    counts = {
        status: sum(v.status == status for v in report.dataset.outcomes)
        for status in ("MATURED", "PENDING", "INCOMPLETE")
    }
    print("SIMULATION — research only; journal updates are not weight training")
    print(f"outcomes: {counts}; trials: {len(report.trials)}; steps: {report.simulation_steps}")
    print(
        f"shadow steps: {report.shadow.simulation_steps if report.shadow else 0}; "
        f"total budget: {report.plan.protocol.max_simulation_steps}"
    )
    print(f"champion unchanged: {report.frozen_champion.digest() == report.champion_after_hash}")
    print(f"proposal: {report.proposal.status}; authorization: absent; activation: disabled")
    print(f"shadow: synthetic demonstration, paused={bool(report.alerts)}")
    print(f"artifact: {path}")
    print(f"learning page: /learning?experiment_id={path.stem}")
    print("authority: LIVE_NOT_AUTHORIZED")
    return 0


def _run_serve(args: argparse.Namespace) -> int:
    path = _resolve_config_path(args.config)
    if not path.exists():
        print(f"error: config file not found: {path}", file=sys.stderr)
        return 2
    try:
        config = load_config(path, ConfigEnvironment())
    except ConfigError as error:
        print("CONFIGURATION ERROR:", file=sys.stderr)
        for violation in error.violations:
            print(f"  - {violation}", file=sys.stderr)
        return 2
    from ..web.app import serve  # lazy: uvicorn is only required for ``serve``

    return serve(config, host=args.host, port=args.port)


def _run_version(args: argparse.Namespace) -> int:
    print(_code_version())
    return 0


def _run_check_config(args: argparse.Namespace) -> int:
    path = _resolve_config_path(args.config)
    if not path.exists():
        print(f"error: config file not found: {path}", file=sys.stderr)
        return 2
    try:
        config = load_config(path, ConfigEnvironment())
    except ConfigError as error:
        print("CONFIGURATION ERROR:", file=sys.stderr)
        for violation in error.violations:
            print(f"  - {violation}", file=sys.stderr)
        return 2

    print(f"config: {path}")
    print(f"environment: {config.app.environment}")
    print(f"mode: {config.app.mode.value.upper()}")
    print(f"live authorization: {_live_authorized(config)}")
    unmet = [
        f"{spec.id.value} ({spec.api_key_env} not set)"
        for spec in config.data.registry
        if spec.enabled and spec.api_key_env and not os.environ.get(spec.api_key_env)
    ]
    print("data sources:")
    for spec in config.data.registry:
        if not spec.enabled:
            state = "disabled"
        elif spec.api_key_env and not os.environ.get(spec.api_key_env):
            state = f"unmet ({spec.api_key_env} not set)"
        else:
            state = "enabled"
        symbols = f" symbols={len(spec.symbols)}" if spec.symbols else ""
        print(f"  {spec.id.value}: {state}{symbols}")
    print(f"data prerequisites: {len(unmet)} unmet")
    for name in unmet:
        print(f"  unmet: {name}")
    print("result: OK")
    return 0


def _live_authorized(config: TradingConfig) -> str:
    return config.authority()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except FileNotFoundError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except Exception as error:  # noqa: BLE001 - the CLI surface is one fail-closed boundary
        print(
            f"error: operation failed ({type(error).__name__}); details withheld", file=sys.stderr
        )
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
