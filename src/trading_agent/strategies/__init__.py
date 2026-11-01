"""Deterministic strategies and baselines (build plan sections 10-11).

The strategy emits typed decisions (or explicit HOLD) and sizes orders in
Decimal. Baselines share identical capital and cost conventions so the
comparison is meaningful (plan section 11).
"""

from .baselines import CashBaseline, PassiveBaseline
from .momentum import DecisionContext, MomentumStrategy, StrategyOutput

__all__ = [
    "CashBaseline",
    "DecisionContext",
    "MomentumStrategy",
    "PassiveBaseline",
    "StrategyOutput",
]
