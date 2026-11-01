"""Seeded synthetic market generator.

Determinism contract: ``build_synthetic_market(config)`` is a pure function
of the configuration (seed, start session, session count, universe, missing
and named scenarios) and ``FIXTURE_MODEL_VERSION`` (the generator's shape).
The same inputs always produce the same market, and no network access is
involved. Changing the model (wick shape, liquidity profile, regime cadence)
bumps ``FIXTURE_MODEL_VERSION`` so derived snapshot/run identities change
with it (a stale database row can never masquerade as the same run).

Model (documented in docs/fill_simulation.md):
- Three observation ticks per session: 09:30, 10:00 (decision point), 16:00,
  in the exchange timezone (America/New_York), stored as UTC instants.
- Per-tick lognormal-noise returns around a regime drift; regimes change
  every 16 sessions so momentum clusters exist for the strategy to find.
- TEST_A trends upward, TEST_B is noisy/mean-reverting (and carries the
  configured 2-session data gap), TEST_C trends downward.
- Wick shape: ``0.4 x |open-close| + 0.5 bps of price``. The relative floor
  (not an absolute dollar amount) keeps quiet bars quiet: a limit order
  placed 5 bps across the touch still needs the market to actually move to
  cross it, instead of every bar filling every aggressive limit.
- Liquidity profile: thin per-bar volume on purpose. The venue caps each
  bar at 0.1% of its volume, so normal order sizes produce multi-bar
  (partial) fill liveness in the demo instead of one instant fill.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from zoneinfo import ZoneInfo

from ..config.models import TradingConfig
from ..contracts.market import Instrument, MarketBar, QualityFlag

# Bump whenever the generator's *shape* changes (not data parameters that
# come from configuration). Part of the snapshot identity.
FIXTURE_MODEL_VERSION = "v2"

# Minimal US equity market holiday set for 2026 (exchange calendar, plan
# section 17: use exchange calendars, never fixed UTC offsets).
_US_HOLIDAYS_2026: frozenset[date] = frozenset(
    {
        date(2026, 1, 1),  # New Year's Day
        date(2026, 1, 19),  # MLK Day
        date(2026, 2, 16),  # Washington's Birthday
        date(2026, 4, 3),  # Good Friday
        date(2026, 5, 25),  # Memorial Day
        date(2026, 6, 19),  # Juneteenth
        date(2026, 7, 3),  # Independence Day (observed; Jul 4 is a Saturday)
        date(2026, 9, 7),  # Labor Day
        date(2026, 11, 26),  # Thanksgiving
        date(2026, 12, 25),  # Christmas
    }
)

_TICK_TIMES: tuple[time, ...] = (time(9, 30), time(10, 0), time(16, 0))

# Thin-liquidity engineering profile (see module docstring). base_volume is
# the expected per-bar volume; realized volume is lognormal around it.
_INSTRUMENT_PROFILES: dict[str, dict[str, Decimal | float | int]] = {
    "TEST_A": {  # persistent uptrend with momentum regimes (~100 USD)
        "initial_price": Decimal("100.00"),
        "drift_per_tick": 0.0016,
        "tick_sigma": 0.006,
        "base_volume": 12_000,
    },
    "TEST_B": {  # noisy, mean-reverting (~50 USD); carries the data gap
        "initial_price": Decimal("50.00"),
        "drift_per_tick": 0.0001,
        "tick_sigma": 0.014,
        "base_volume": 6_000,
    },
    "TEST_C": {  # persistent downtrend (~75 USD)
        "initial_price": Decimal("75.00"),
        "drift_per_tick": -0.0014,
        "tick_sigma": 0.009,
        "base_volume": 10_000,
    },
}

_FALLBACK_PROFILE: dict[str, Decimal | float | int] = {
    "initial_price": Decimal("25.00"),
    "drift_per_tick": 0.0,
    "tick_sigma": 0.01,
    "base_volume": 8_000,
}


def business_sessions(start: date, count: int) -> list[date]:
    """The next ``count`` open sessions on or after ``start`` (weekdays minus holidays)."""
    sessions: list[date] = []
    day = start
    while len(sessions) < count:
        if day.weekday() < 5 and day not in _US_HOLIDAYS_2026:
            sessions.append(day)
        day += timedelta(days=1)
    return sessions


@dataclass(frozen=True)
class SyntheticMarket:
    """The fully generated fixture market for one run configuration."""

    seed: int
    sessions: tuple[date, ...]
    instruments: dict[str, Instrument]
    bars: dict[str, tuple[MarketBar, ...]]  # per instrument, chronological
    data_snapshot_id: str


def _data_snapshot_id(config: TradingConfig) -> str:
    basis = json.dumps(
        {
            "model": FIXTURE_MODEL_VERSION,
            "seed": config.data.fixture_seed,
            "start": config.data.start_session.isoformat(),
            "sessions": config.data.sessions,
            "universe": list(config.paper.synthetic_fixture_universe),
            "missing": [dict(m) for m in config.data.missing_scenarios],
            "scenarios": sorted(config.data.scenarios),
        },
        sort_keys=True,
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]


def build_synthetic_market(config: TradingConfig) -> SyntheticMarket:
    """Generate the deterministic fixture market for the given configuration."""
    seed = config.data.fixture_seed
    rng = random.Random(seed)
    ex_tz = ZoneInfo(config.app.exchange_timezone)
    sessions = business_sessions(config.data.start_session, config.data.sessions)

    missing = {
        str(scenario.get("instrument")): (
            date.fromisoformat(str(scenario["from"])),
            date.fromisoformat(str(scenario["to"])),
        )
        for scenario in config.data.missing_scenarios
    }

    instruments: dict[str, Instrument] = {}
    bars: dict[str, tuple[MarketBar, ...]] = {}

    for instrument_id in config.paper.synthetic_fixture_universe:
        profile = _INSTRUMENT_PROFILES.get(instrument_id)
        if profile is None:
            profile = dict(_FALLBACK_PROFILE)
            notes: tuple[str, ...] = (
                "instrument not in the default profile; deterministic fallback parameters",
            )
        else:
            notes = ()

        price = Decimal(str(profile["initial_price"]))
        drift = float(profile["drift_per_tick"])  # feature-space float (plan section 6)
        sigma = float(profile["tick_sigma"])
        base_volume = int(profile["base_volume"])
        quantum = Decimal(1).scaleb(-2)

        instruments[instrument_id] = Instrument(
            instrument_id=instrument_id,
            symbol=instrument_id,
            asset_class="synthetic-equity",
            price_decimals=2,
            quantity_precision=0,
            is_synthetic=True,
            eligible=True,
            notes=notes,
        )

        gap = missing.get(instrument_id)
        regime_factor = 1.0
        rows: list[MarketBar] = []

        for session_index, session in enumerate(sessions):
            if gap is not None and gap[0] <= session <= gap[1]:
                continue  # explicit missing-data scenario: no observations at all
            # Regime turns on a 16-session cadence (never on the first session).
            if session_index > 0 and session_index % 16 == 0:
                regime_factor = float(rng.choice([1.0, 2.5, -1.0, 0.5]))
            for tick_index, tick_time in enumerate(_TICK_TIMES):
                local = datetime.combine(session, tick_time).replace(tzinfo=ex_tz)
                ts = local.astimezone(UTC)
                if tick_index == 0:
                    # Overnight gap: the session open moves from the prior close.
                    price = price * Decimal(
                        str(round(math.exp(drift * 0.5 + sigma * 0.8 * rng.gauss(0, 1)), 6))
                    )
                move = math.exp(drift * regime_factor / 3 + sigma * 0.6 * rng.gauss(0, 1))
                open_price = price
                price = price * Decimal(str(round(move, 6)))
                open_r = open_price.quantize(quantum, rounding=ROUND_HALF_EVEN)
                close_r = price.quantize(quantum, rounding=ROUND_HALF_EVEN)
                wick_widen = abs(open_r - close_r) * Decimal("0.4") + max(
                    open_r, close_r
                ) * Decimal("0.0005")
                high_r = max(open_r, close_r) + wick_widen
                low_r = min(open_r, close_r) - wick_widen
                if low_r <= 0:
                    low_r = close_r * Decimal("0.9")
                volume = Decimal(str(max(1000, int(base_volume * math.exp(0.5 * rng.gauss(0, 1))))))
                rows.append(
                    MarketBar(
                        instrument_id=instrument_id,
                        ts=ts,
                        open=open_r,
                        high=high_r,
                        low=low_r.quantize(quantum, rounding=ROUND_HALF_EVEN),
                        close=close_r,
                        volume=volume,
                        source_id="synthetic-fixture",
                        quality=QualityFlag.VALID,
                        exchange_time=local,
                    )
                )
        bars[instrument_id] = tuple(rows)

    return SyntheticMarket(
        seed=seed,
        sessions=tuple(sessions),
        instruments=instruments,
        bars=bars,
        data_snapshot_id=_data_snapshot_id(config),
    )
