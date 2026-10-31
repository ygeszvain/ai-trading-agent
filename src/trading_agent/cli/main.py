"""trading-agent CLI.

Commands (M0):
  check-config   Load, validate, and report a configuration with its live
                 activation-gate result. Exits 0 when valid, 2 when the
                 configuration is invalid, 3 on unexpected failure.
  capabilities   Report broker provider capabilities from code.
  version        Print the application version.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .. import FINANCIAL_AUTHORITY, __version__
from ..config.loading import ConfigEnvironment, load_config
from ..config.models import TradingConfig
from ..exceptions import ConfigError
from ..execution.factory import build_broker_adapter
from ..gates.live_activation import evaluate_live_activation

EXIT_OK = 0
EXIT_CONFIG_INVALID = 2
EXIT_UNEXPECTED = 3


def _probe_llm(config: TradingConfig) -> None:
    """Read-only probe of the configured local LM Studio endpoint.

    Only a model-list GET is issued (no inference, no mutations, no cloud).
    Unreachable or unexpected responses are reported, never fatal.
    """
    url = config.llm.base_url.rstrip("/") + "/models"
    print(f"llm: {config.llm.base_url} (probe: {url})")
    request = urllib.request.Request(url, method="GET")
    if config.llm.auth_token is not None:
        request.add_header("Authorization", f"Bearer {config.llm.auth_token.get_secret_value()}")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            payload: dict[str, Any] = json.loads(response.read().decode("utf-8"))
        model_ids = [
            entry.get("id") for entry in payload.get("data", []) if isinstance(entry, dict)
        ]
        configured = config.llm.model_id
        state = "reachable"
        loaded = ", ".join(str(model) for model in model_ids) if model_ids else "(none)"
        detail = f"{len(model_ids)} model(s) loaded: {loaded}"
        if configured is not None and configured not in model_ids:
            detail += f"; configured model_id {configured!r} NOT found in loaded models"
        print(f"llm probe: {state} — {detail}")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        kind = error.__class__.__name__
        print(f"llm probe: UNREACHABLE or invalid response — {kind} (non-fatal in M0)")


def _run_check_config(args: argparse.Namespace, env: ConfigEnvironment) -> int:
    try:
        config = load_config(args.config, env=env)
    except ConfigError as error:
        print(error.format(), file=sys.stderr)
        return EXIT_CONFIG_INVALID
    print(f"trading-agent v{__version__} (M0)")
    print(f"config file: {Path(args.config) if args.config else '(resolved default)'}")
    summary = config.sanitized_summary()
    print(
        "mode: "
        f"{summary['app']['mode'].upper()}  environment={summary['app']['environment']}  "
        f"web={summary['app']['web_host']}:{summary['app']['web_port']}"
    )
    llm = summary["llm"]
    print(
        "llm: "
        f"provider={llm['provider']}  base_url={llm['base_url']}  "
        f"model_id={llm['model_id']}  cloud_fallback={llm['allow_cloud_fallback']}"
    )
    broker = build_broker_adapter(config)
    capabilities = broker.capabilities()
    print(
        f"broker: provider={capabilities.provider}  connected={capabilities.connected}  "
        f"reads={capabilities.reads_enabled}  execution={capabilities.execution_enabled}"
    )
    for note in capabilities.notes:
        print(f"  note: {note}")
    decision = evaluate_live_activation(config, broker)
    print(f"live activation gate: {decision.summary()}")
    for check in decision.unmet:
        print(f"  unmet: {check.name} — {check.detail}")
    if args.probe_llm:
        _probe_llm(config)
    print(f"financial authority: {decision.authority}")
    print("result: OK")
    return EXIT_OK


def _run_capabilities(args: argparse.Namespace, env: ConfigEnvironment) -> int:
    try:
        config = load_config(args.config, env=env)
    except ConfigError as error:
        print(error.format(), file=sys.stderr)
        return EXIT_CONFIG_INVALID
    broker = build_broker_adapter(config)
    decision = evaluate_live_activation(config, broker)
    print(
        json.dumps(
            {"capabilities": vars(broker.capabilities()), "authority": decision.authority}, indent=2
        )
    )
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trading-agent",
        description="Single-owner local trading application (M0 foundation; LIVE_NOT_AUTHORIZED)",
    )
    parser.add_argument("--version", action="version", version=f"trading-agent {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check-config", help="load, validate, and report a configuration")
    check.add_argument("--config", default=None, help="path to the YAML configuration file")
    check.add_argument(
        "--probe-llm",
        action="store_true",
        help="issue a read-only model-list GET to the configured local LM Studio endpoint",
    )

    caps = subparsers.add_parser("capabilities", help="print sanitized broker capabilities")
    caps.add_argument("--config", default=None)

    subparsers.add_parser("version", help="print the version and exit")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    env = ConfigEnvironment()
    try:
        if args.command == "version":
            print(f"trading-agent {__version__} (authority: {FINANCIAL_AUTHORITY})")
            return EXIT_OK
        if args.command == "check-config":
            return _run_check_config(args, env)
        if args.command == "capabilities":
            return _run_capabilities(args, env)
        parser.error(f"unknown command {args.command!r}")
        return EXIT_UNEXPECTED
    except ConfigError as error:
        print(error.format(), file=sys.stderr)
        return EXIT_CONFIG_INVALID
    except Exception as error:  # noqa: BLE001 — classify unexpected failures at the CLI edge
        print(f"UNEXPECTED ERROR: {error.__class__.__name__}: {error}", file=sys.stderr)
        return EXIT_UNEXPECTED


if __name__ == "__main__":
    raise SystemExit(main())
