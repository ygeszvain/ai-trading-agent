"""Run orchestration: the trading pipeline and exchange clock (plan section 17).

The pipeline is idempotent: a deterministic run id plus database uniqueness
constraints mean a restart never duplicates economic effects. Consequential
state and its activity events commit in one transaction per session.
"""

from .clock import ExchangeClock
from .pipeline import RunResult, TradingPipeline

__all__ = ["ExchangeClock", "RunResult", "TradingPipeline"]
