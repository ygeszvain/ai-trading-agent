"""Research prompts (plan section 8: two prompt versions, v1/v2).

The prompt is a pure function of a sanitized, point-in-time brief: same brief,
same prompt version -> identical prompt text, so the prompt digest is stable
and every evaluation is reproducible (docs/research_layer.md).

The system prompt states the M2 research policy in full: advisory-only,
no execution authority, no market data beyond what the brief provides, and a
strict answer contract. Version v1 is free-form prose; v2 is structured JSON.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

PROMPT_VERSIONS: tuple[str, ...] = ("v1", "v2")


@dataclass(frozen=True)
class ResearchBrief:
    """Everything a research evaluation may cite, frozen at decision time.

    Only values the strategy itself could have seen at that instant: recent
    session closes (point-in-time), the latest quote with its age, the
    portfolio's published state, and the deterministic strategy's own decision
    (so the model's view can be compared against it).
    """

    instrument_id: str
    symbol: str
    asset_class: str
    is_synthetic: bool
    session_date: date
    data_snapshot_id: str
    generator_version: str
    session_closes: tuple[tuple[date, Decimal], ...]
    last_quote_price: Decimal | None
    quote_as_of: datetime | None
    quote_age_sessions: int | None
    session_volume: Decimal | None
    nav: Decimal | None
    cash: Decimal | None
    open_positions: int
    deterministic_action: str
    deterministic_weight: Decimal | None

    def age_label(self) -> str:
        if self.quote_as_of is None:
            return "no recent quote (missing)"
        if self.quote_age_sessions is not None:
            return f"{self.quote_age_sessions} session(s) old"
        return "age unknown"

    def prompt_seed(self) -> str:
        """Canonical text of the brief: same values -> same prompt digest."""
        return "|".join(
            [
                self.instrument_id,
                self.session_date.isoformat(),
                self.data_snapshot_id,
                "|".join(f"{d.isoformat()}:{c}" for d, c in self.session_closes),
                str(self.last_quote_price),
                self.quote_as_of.isoformat() if self.quote_as_of else "",
                str(self.quote_age_sessions),
                str(self.session_volume),
                str(self.nav),
                str(self.cash),
                str(self.open_positions),
                self.deterministic_action,
                str(self.deterministic_weight),
            ]
        )


_SYSTEM_TEMPLATE = (
    "You are the research layer of a deterministic trading demo (v1, local-only).\n"
    "Policy: you ADVISE. You have zero execution authority; no part of your output "
    "can place, amend, or cancel an order.\n"
    "Rules: cite only the data provided in the brief. Do not assume any data not "
    "listed. This instrument's market data is a synthetic fixture generated for "
    "offline evaluation, not live market data. Be concise and concrete.\n"
)


def build_prompt(brief: ResearchBrief, version: str) -> tuple[str, str]:
    """(system, user) prompt pair for the brief at the given prompt version."""
    if version not in PROMPT_VERSIONS:
        raise ValueError(f"unknown research prompt version: {version!r}")
    system = _SYSTEM_TEMPLATE
    lines: list[str] = []
    lines.append(
        f"Instrument: {brief.symbol} ({brief.asset_class}; synthetic fixture: {brief.is_synthetic})"
    )
    lines.append(f"Session date: {brief.session_date.isoformat()}")
    lines.append(
        f"Data snapshot: {brief.data_snapshot_id} (generator {brief.generator_version})"
    )
    lines.append("")
    lines.append("Recent session closes (oldest first):")
    for session_date, close in brief.session_closes:
        lines.append(f"  {session_date.isoformat()}: {close}")
    lines.append("")
    if brief.last_quote_price is not None:
        lines.append(
            f"Latest quote: {brief.last_quote_price} ({brief.age_label()}, point-in-time)"
        )
    else:
        lines.append("Latest quote: none (stale/missing)")
    if brief.session_volume is not None:
        lines.append(f"Session volume: {brief.session_volume}")
    if brief.nav is not None:
        lines.append(
            f"Portfolio: NAV {brief.nav}, cash {brief.cash}, open positions {brief.open_positions}"
        )
    lines.append("")
    weight = (
        f" at target weight {brief.deterministic_weight}"
        if brief.deterministic_weight is not None and brief.deterministic_weight != 0
        else ""
    )
    lines.append(
        f"The deterministic momentum strategy decided: {brief.deterministic_action}{weight}."
    )
    if version == "v1":
        lines.append(
            "\nIn 3-5 sentences, state your independent research view on this "
            "instrument for the coming session, the factors driving it, and "
            "whether you agree or disagree with the strategy's decision and why."
        )
    else:
        lines.append(
            "\nRespond with a single JSON object, no prose, matching exactly: "
            '{"view": "bullish" | "bearish" | "neutral" | "insufficient_data", '
            '"confidence": number in [0,1], '
            '"key_factors": [short strings, max 4], '
            '"risk_flags": [short strings, max 4], '
            '"summary": "one or two sentences", '
            '"agrees_with_strategy": boolean}'
        )
    return system, "\n".join(lines)
