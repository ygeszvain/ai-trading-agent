"""Application error types.

All errors are classified and safe to display: none of them carry secrets,
raw account numbers, or unredacted provider payloads.
"""


class TradingAgentError(Exception):
    """Base class for all trading-agent errors."""


class ConfigError(TradingAgentError):
    """The configuration is invalid; startup must fail clearly.

    Carries every detected violation so the owner can fix them in one pass
    instead of discovering them one at a time.
    """

    def __init__(self, violations: list[str]) -> None:
        self.violations = list(violations)
        summary = "configuration is invalid: " + "; ".join(self.violations)
        super().__init__(summary)

    def format(self) -> str:
        lines = ["CONFIGURATION ERROR — startup blocked:"]
        lines.extend(f"  - {violation}" for violation in self.violations)
        return "\n".join(lines)
