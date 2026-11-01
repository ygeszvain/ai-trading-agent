"""Versioned evaluation protocol (plan section 15, M4 research / prompt 6).

A protocol is the pre-registered contract for an evaluation: hypothesis,
label horizons, chronological split plan (train/validation/test plus a
final holdout), parameter grid and trial budget, objective, benchmarks,
risk constraints, promotion criteria, stress suite, and cost model.

The protocol is hash-pinned at registration. Changing the objective or
promotion criteria after results exist requires a NEW protocol version;
silently editing a registered protocol raises ``ProtocolIntegrityError``.
This enforces the plan's rule that selection criteria are fixed before
selection, so the walk-forward results cannot be moved to match a story.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from ..exceptions import TradingAgentError

PROTOCOL_VERSION = "eval-v1"


class ProtocolIntegrityError(TradingAgentError):
    """A registered protocol was modified after the fact (goalpost moving)."""


class SplitSettings(BaseModel):
    """Chronological walk-forward split plan, in business sessions.

    ``embargo_days`` must be >= the maximum label horizon: labels computed
    near a boundary that would look into the next window are purged from
    the training window, and the embargo gap is left unlabelled between
    windows, so no training label can reference data from the window being
    selected or tested on.
    """

    model_config = ConfigDict(extra="forbid")

    train_days: int = Field(default=504, ge=20)  # ~24 months of business sessions
    validation_days: int = Field(default=126, ge=5)  # ~6 months
    test_days: int = Field(default=126, ge=5)  # ~6 months
    advance_days: int = Field(default=126, ge=5)
    embargo_days: int = Field(default=252, ge=1)
    holdout_days: int = Field(default=126, ge=5)  # final holdout, evaluated once only
    warmup_days: int = Field(default=63, ge=5)  # history required before the first fold


class LabelHorizon(BaseModel):
    """A prediction horizon used to label training windows (in sessions)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    days: int = Field(default=21, ge=1, le=2520)


class ParameterGrid(BaseModel):
    """Cartesian candidate space for the momentum rule (fitted per fold)."""

    model_config = ConfigDict(extra="forbid")

    lookback: list[int] = Field(default_factory=lambda: [10, 21, 42, 63])
    entry: list[Decimal] = Field(
        default_factory=lambda: [Decimal("0.02"), Decimal("0.05"), Decimal("0.10")]
    )
    exit: list[Decimal] = Field(
        default_factory=lambda: [Decimal("0.00"), Decimal("0.03"), Decimal("0.08")]
    )
    weight: list[Decimal] = Field(default_factory=lambda: [Decimal("1.0")])
    max_trials: int = Field(default=24, ge=1, le=4096)

    @field_validator("entry", "exit", "weight", mode="before")
    @classmethod
    def _validate_levels(cls, value: Any, info: ValidationInfo) -> list[Decimal]:
        items = list(value) if isinstance(value, (list, tuple)) else [value]
        if not items:
            raise ValueError(f"grid.{info.field_name} must be non-empty")
        return [max(Decimal("0"), min(Decimal("1"), Decimal(str(item)))) for item in items]

    def combos(self) -> list[dict[str, Any]]:
        combos: list[dict[str, Any]] = []
        for lookback in self.lookback:
            for entry in self.entry:
                for exit_ in self.exit:
                    for weight in self.weight:
                        combos.append(
                            {
                                "lookback": int(lookback),
                                "entry": str(entry),
                                "exit": str(exit_),
                                "weight": str(weight),
                            }
                        )
                        if len(combos) >= self.max_trials:
                            return combos
        return combos


class ObjectiveSettings(BaseModel):
    """Selection objective — fixed before any trial runs (plan section 15)."""

    model_config = ConfigDict(extra="forbid")

    spec: Literal["net_excess_sharpe", "net_excess_return"] = "net_excess_sharpe"
    reference: Literal["cash", "passive"] = "passive"


class BenchmarkSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cash: bool = True
    passive: bool = True
    exposure_matched: bool = True
    llm_ablation: bool = False  # opt-in; historical results are exploratory


class ExecutionCostModel(BaseModel):
    """Conservative per-fill cost assumptions (bps of notional, labelled)."""

    model_config = ConfigDict(extra="forbid")

    fee_bps: Decimal = Decimal("4.18")  # Robinhood-style trading fee
    spread_bps: Decimal = Decimal("10")  # half-spread cost per side
    slippage_bps: Decimal = Decimal("15")  # baseline impact
    volume_participation_cap: Decimal = Decimal("0.10")  # max % of session volume per order
    impact_bps_per_participation: Decimal = Decimal("200")  # slope: bps per full participation
    latency_sessions: int = Field(default=1, ge=1)  # close signal -> next session
    limit_band_bps: Decimal = Decimal("50")  # entry limit distance from signal close
    pending_max_sessions: int = Field(default=5, ge=0)  # then the remainder is cancelled


class RiskConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_drawdown: Decimal = Decimal("0.50")
    max_exposure: Decimal = Decimal("1.0")


class PromotionCriteria(BaseModel):
    """Prescribed pass conditions for the CONTINUE_RESEARCH / PAPER_TEST /
    REJECT decision (plan section 15). All are checked on the selected
    variant's out-of-sample test folds and the single final holdout."""

    model_config = ConfigDict(extra="forbid")

    min_net_excess_annual: Decimal = Decimal("0.02")
    max_drawdown_accept: Decimal = Decimal("0.30")
    min_positive_fold_ratio: Decimal = Decimal("0.60")
    confidence_interval_must_exclude_zero: bool = True
    min_test_sessions: int = Field(default=30, ge=5)
    requires_real_data: bool = True  # synthetic results can never promote


class StressSuite(BaseModel):
    """All-stress-tests list (plan section 15): every stress must run."""

    model_config = ConfigDict(extra="forbid")

    costs_2x: bool = True
    costs_3x: bool = True
    parameter_neighbors: bool = True
    delayed_signals: bool = True
    missing_data: bool = True
    overnight_gaps: bool = True
    low_liquidity: bool = True
    best_subperiod_removed: bool = True


class OperatingCostModel(BaseModel):
    """Product-level operating costs, every assumption labelled."""

    model_config = ConfigDict(extra="forbid")

    data_cost_usd_per_session: Decimal = Decimal("0")  # FRED: free public API
    compute_usd_per_session: Decimal = Decimal("0.01")  # local hardware energy estimate
    model_inference_usd_per_call: Decimal = Decimal("0.01")  # local model energy estimate
    model_calls_per_session: int = Field(default=0, ge=0)  # >0 when the LLM variant runs


class EvaluationProtocol(BaseModel):
    """The complete, hash-pinned contract for one evaluation."""

    model_config = ConfigDict(extra="forbid")

    protocol_version: str = PROTOCOL_VERSION
    hypothesis: str = (
        "A point-in-time momentum rule (long when the trailing return "
        "exceeds a threshold; exit on reversal), executed conservatively at "
        "the next session, produces positive net excess over a passive "
        "benchmark after all trading and operating costs."
    )
    labels: list[LabelHorizon] = Field(
        default_factory=lambda: [
            LabelHorizon(name="1d", days=1),
            LabelHorizon(name="5d", days=5),
            LabelHorizon(name="21d", days=21),
            LabelHorizon(name="63d", days=63),
            LabelHorizon(name="252d", days=252),
        ]
    )
    splits: SplitSettings = Field(default_factory=SplitSettings)
    grid: ParameterGrid = Field(default_factory=ParameterGrid)
    objective: ObjectiveSettings = Field(default_factory=ObjectiveSettings)
    benchmarks: BenchmarkSet = Field(default_factory=BenchmarkSet)
    execution: ExecutionCostModel = Field(default_factory=ExecutionCostModel)
    risk: RiskConstraints = Field(default_factory=RiskConstraints)
    promotion: PromotionCriteria = Field(default_factory=PromotionCriteria)
    stress: StressSuite = Field(default_factory=StressSuite)
    operating: OperatingCostModel = Field(default_factory=OperatingCostModel)

    def _canonical(self) -> dict[str, Any]:
        data = self.model_dump(mode="json", exclude={"protocol_version"})
        return data

    def digest(self) -> str:
        payload = json.dumps(self._canonical(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def register_protocol(store_root: str | Path, protocol: EvaluationProtocol) -> str:
    """Persist the protocol under its version; enforce immutability.

    Returns the protocol id. Re-registering the same version with different
    content raises ``ProtocolIntegrityError`` — the goalposts cannot move.
    """
    root = Path(store_root) / "protocols"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{protocol.protocol_version}.json"
    record = {
        "protocol_version": protocol.protocol_version,
        "digest": protocol.digest(),
        "registered_on": date.today().isoformat(),
        "protocol": protocol.model_dump(mode="json"),
    }
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing.get("digest") != protocol.digest():
            raise ProtocolIntegrityError(
                f"protocol {protocol.protocol_version!r} is already registered with "
                f"digest {existing.get('digest')}; content changed after registration. "
                "Register a new protocol version instead of editing this one."
            )
        return protocol.protocol_version
    path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    return protocol.protocol_version


def load_protocol(store_root: str | Path, protocol_version: str) -> EvaluationProtocol:
    path = Path(store_root) / "protocols" / f"{protocol_version}.json"
    if not path.exists():
        raise TradingAgentError(f"protocol {protocol_version!r} is not registered in {path}")
    record = json.loads(path.read_text(encoding="utf-8"))
    protocol = EvaluationProtocol.model_validate(record["protocol"])
    if protocol.digest() != record["digest"]:
        raise ProtocolIntegrityError(
            f"registered protocol {protocol_version!r} does not match its stored digest; "
            "the protocol file was modified after registration"
        )
    return protocol
