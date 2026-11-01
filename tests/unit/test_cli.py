"""CLI smoke check behavior (Prompt 1 acceptance: minimal configuration smoke check)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from trading_agent.cli.main import main

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_check_config_valid_simulation(capsys, valid_config_dict) -> None:
    config_file = REPO_ROOT / "config" / "simulation.yaml"
    exit_code = main(["check-config", "--config", str(config_file)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "SIMULATION" in out
    assert "LIVE_NOT_AUTHORIZED" in out
    assert "result: OK" in out
    # The gate reports unmet prerequisites explicitly.
    assert "unmet" in out


def test_check_config_invalid_fails_with_clear_error(tmp_path, capsys, valid_config_dict) -> None:
    import yaml

    bad = valid_config_dict
    bad["live"]["approved_capital_usd"] = "-1"
    bad["risk"]["max_gross_nav_fraction"] = "0.9"
    bad["risk"]["min_cash_nav_fraction"] = "0.9"
    config_file = tmp_path / "bad.yaml"
    config_file.write_text(yaml.safe_dump(bad))
    exit_code = main(["check-config", "--config", str(config_file)])
    err = capsys.readouterr().err
    assert exit_code == 2
    assert "CONFIGURATION ERROR" in err
    assert "negative" in err
    assert "1.0" in err  # gross + min cash over unity reported


def test_check_config_missing_file_clear_error(tmp_path, capsys) -> None:
    exit_code = main(["check-config", "--config", str(tmp_path / "missing.yaml")])
    err = capsys.readouterr().err
    assert exit_code == 2
    assert "not found" in err


def test_cli_version() -> None:
    assert main(["version"]) == 0


def test_uv_run_entrypoint(capsys) -> None:
    """The documented owner command works from the project root."""
    result = subprocess.run(
        ["uv", "run", "trading-agent", "check-config"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "LIVE_NOT_AUTHORIZED" in result.stdout
    assert "result: OK" in result.stdout


def test_eval_writes_versioned_report(capsys, tmp_path) -> None:
    exit_code = main(
        [
            "eval",
            "TEST_A",
            "--start",
            "2025-11-03",
            "--end",
            "2026-11-30",
            "--out-dir",
            str(tmp_path),
            "--config",
            str(REPO_ROOT / "config" / "simulation.yaml"),
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Verdict:" in out
    jsons = list(tmp_path.glob("*.json"))
    assert len(jsons) == 1
    assert len(list(tmp_path.glob("*.md"))) == 1
    payload = json.loads(jsons[0].read_text())
    # Synthetic data can never earn the paper verdict (M3 gate).
    assert payload["verdict"] in {"continue_research", "reject"}
    assert payload["run"]["instrument_id"] == "TEST_A"
    assert len(payload["protocol"]["digest"]) == 32
    assert "synthetic" in next(tmp_path.glob("*.md")).read_text()
