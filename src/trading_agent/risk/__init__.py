"""Deterministic risk engine and transactional reservations (plan section 13).

Risk is code, not a model: every check is a pure function of point-in-time
state and the configured policy. The engine allows, reduces, or rejects a
decision with machine-readable reasons. Protective (risk-reducing) exits are
deliberately *not* blocked by entry-only controls (plan section 13: entry
controls and protective actions are different).
"""

from .engine import RiskEngine, RiskState

__all__ = ["RiskEngine", "RiskState"]
