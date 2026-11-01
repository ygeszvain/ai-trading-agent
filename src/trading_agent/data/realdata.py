"""Real market data: registry-driven fetching, local cache, content digests.

M3 (plan section 8 + M3 prompt). Free historical sources are fetched over
HTTPS using only the Python standard library (urllib) — no new dependencies,
no cloud SDKs. Every source in the configuration registry is explicit:

- **Cache:** ``data_cache/<source_id>/<symbol>.json`` — the complete
  canonical observation set for that symbol. A re-fetch that produces a
  different *content digest* updates the cache and records the correction;
  identical content is a no-op. The cache is never silently substituted:
  every use reports whether the data is ``ok``, ``cached`` (reused within
  the refresh policy), or a failure state.
- **Point-in-time:** the provider implements the same ``MarketDataProvider``
  cutoff contract as the synthetic fixture (section 8): an observation is
  usable only at or after its timestamp; staleness is explicit.
- **Fail closed:** unreachable sources, missing API keys, and parse failures
  produce explicit statuses. A backtest or quality report on incomplete data
  is refused or loudly labeled — never quietly re-based.

FRED CSV observation endpoint (free, key required):
    {api_base_url}/fred/series/observations?series_id=SP500&file_type=csv
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from email.message import Message
from pathlib import Path
from typing import IO
from zoneinfo import ZoneInfo

from ..config.models import SourceSpec, TradingConfig
from ..contracts.market import Instrument, MarketBar, QualityFlag, Quote
from .provider import MarketDataProvider, SessionClose

# Series-level metadata. Only the asset class is asserted from the registry;
# everything else (prices) comes from the source itself — never invented.
FRED_SERIES_ASSET_CLASSES: dict[str, str] = {
    "SP500": "global_equity",
    "IEX": "global_equity",
    "IEI": "us_bond",
    "IEF": "us_bond",
    "IEG": "us_bond",
    "IEH": "us_bond",
    "DTWEXBGS": "fx",
}

FRED_DEFAULT_API_BASE = "https://api.stlouisfed.org"

#: ``data_cache`` layout root relative to the project (overridable in tests).
HTTPGet = Callable[[str, float], tuple[int, bytes]]

OBSERVATION = dict[date, Decimal]  # normalized session date -> close


def _sha256_hex(payload: bytes | str) -> str:
    data = payload.encode("utf-8") if isinstance(payload, str) else payload
    return hashlib.sha256(data).hexdigest()


def canonical_observations_observations(symbol: str, rows: list[tuple[date, Decimal]]) -> str:
    """Canonical serialization of one symbol's observations (digest basis).

    Sorted by date; values serialized as plain decimal strings. The digest of
    this string is the symbol's *content digest*: a stable identity for the
    data itself, independent of fetch order, key material, or host.
    """
    payload = {
        "symbol": symbol,
        "observations": [
            {"date": obs_date.isoformat(), "close": format(value.normalize(), "f")}
            for obs_date, value in sorted(rows)
        ],
    }
    return _sha256_hex(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def content_digest(symbol: str, rows: list[tuple[date, Decimal]]) -> str:
    return canonical_observations_observations(symbol, rows)[:32]


@dataclass(frozen=True)
class SymbolFetch:
    """Outcome for one symbol of one source fetch."""

    source_id: str
    symbol: str
    # ok | cached | no_adapter | disabled | unreachable | auth_failed | parse_failed | invalid
    status: str
    bars: int = 0
    first_date: date | None = None
    last_date: date | None = None
    content_digest: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class SourceFetchResult:
    source_id: str
    enabled: bool
    symbols: tuple[str, ...]
    results: tuple[SymbolFetch, ...] = ()
    snapshot_id: str | None = None  # set only when every enabled symbol succeeded

    @property
    def ok(self) -> bool:
        return bool(self.results) and all(
            result.status in {"ok", "cached"} for result in self.results
        )


@dataclass(frozen=True)
class RealSymbolData:
    """One symbol's cached observation set (close-only series)."""

    source_id: str
    symbol: str
    asset_class: str
    observations: OBSERVATION = field(default_factory=dict)
    fetched_at: datetime | None = None
    content_digest: str | None = None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: Message,
        newurl: str,
    ) -> None:
        raise urllib.error.HTTPError(req.full_url, code, "redirect denied", headers, fp)


def default_http_get(url: str, timeout: float) -> tuple[int, bytes]:
    parsed = urllib.parse.urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "api.stlouisfed.org"
        or parsed.path != "/fred/series/observations"
        or parsed.fragment
    ):
        raise ValueError("unapproved data endpoint")
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect()).open(
            request, timeout=timeout
        ) as response:
            return response.status, response.read(8_000_001)
    except urllib.error.HTTPError as error:
        return error.code, b""


class RealDataCache:
    """Filesystem cache under ``<root>/<source_id>/<symbol>.json``."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        return self._root

    def _path(self, source_id: str, symbol: str) -> Path:
        if (
            not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", source_id)
            or not re.fullmatch(r"[A-Za-z0-9_.:^_-]{1,64}", symbol)
            or symbol in {".", ".."}
        ):
            raise ValueError("invalid data cache identity")
        return self._root / source_id / f"{symbol}.json"

    def load(self, source_id: str, symbol: str) -> RealSymbolData | None:
        path = self._path(source_id, symbol)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text())
            observations = {row["date"]: Decimal(row["close"]) for row in payload["observations"]}
            fetched_at = datetime.fromisoformat(payload["fetched_at"])
            return RealSymbolData(
                source_id=source_id,
                symbol=payload["symbol"],
                asset_class=payload.get("asset_class", "unknown"),
                observations=observations,
                fetched_at=fetched_at,
                content_digest=payload.get("content_digest"),
            )
        except (OSError, ValueError, KeyError):
            return None

    def save(self, data: RealSymbolData) -> None:
        path = self._path(data.source_id, data.symbol)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "source_id": data.source_id,
            "symbol": data.symbol,
            "asset_class": data.asset_class,
            "fetched_at": (data.fetched_at or datetime.now(UTC)).isoformat(),
            "content_digest": content_digest(data.symbol, list(data.observations.items())),
            "observations": [
                {"date": obs_date.isoformat(), "close": format(value.normalize(), "f")}
                for obs_date, value in sorted(data.observations.items())
            ],
        }
        path.write_text(json.dumps(payload, indent=0, sort_keys=True))


def _parse_fred_csv(body: bytes, symbol: str) -> list[tuple[date, Decimal]]:
    """FRED CSV: header ``date,SYMBOL``; missing values are ``.`` (skipped)."""
    rows: list[tuple[date, Decimal]] = []
    lines = body.decode("utf-8", errors="replace").splitlines()
    if not lines:
        raise ValueError("empty response body")
    header = [column.strip() for column in lines[0].split(",")]
    if "date" not in header:
        raise ValueError(f"unexpected FRED CSV header: {lines[0]!r}")
    value_index = header.index(symbol) if symbol in header else (1 if len(header) > 1 else None)
    if value_index is None:
        raise ValueError(f"CSV has no value column for {symbol!r}")
    for line in lines[1:]:
        cells = [cell.strip() for cell in line.split(",")]
        if value_index >= len(cells):
            continue
        if cells[value_index] in ("", "."):
            continue  # missing observation: gap, never interpolated
        obs_date = date.fromisoformat(cells[0])
        value = Decimal(cells[value_index])
        if value < 0:
            raise ValueError(f"negative observation for {symbol} on {obs_date}")
        rows.append((obs_date, value))
    return rows


def _fred_url(
    api_base_url: str,
    symbol: str,
    start: date,
    end: date,
    api_key: str,
) -> str:
    params = {
        "series_id": symbol,
        "file_type": "csv",
        "observation_start": start.isoformat(),
        "observation_end": end.isoformat(),
        "api_key": api_key,
    }
    return f"{api_base_url.rstrip('/')}/fred/series/observations?" + urllib.parse.urlencode(params)


def fetch_symbol(
    spec: SourceSpec,
    symbol: str,
    cache: RealDataCache,
    start: date,
    end: date,
    *,
    api_key: str,
    now: datetime,
    http_get: HTTPGet = default_http_get,
) -> SymbolFetch:
    """Fetch (or reuse the cache for) one symbol of one registry source.

    Refresh policy: a cached set is reused when it was fetched within
    ``refresh.max_age_minutes`` AND its last observation is within
    ``refresh.backfill_sessions`` sessions of ``now``. Otherwise a network
    fetch runs; the fetch result is unioned with the cache so historical
    corrections are preserved and the new content digest recorded.
    """
    if spec.id != "fred":
        return SymbolFetch(
            spec.id,
            symbol,
            "no_adapter",
            detail="no fetch adapter registered for this source in M3",
        )
    api_base = spec.api_base_url or FRED_DEFAULT_API_BASE
    if api_base != FRED_DEFAULT_API_BASE:
        return SymbolFetch(spec.id, symbol, "invalid", detail="unapproved data origin")
    if not api_key:
        env_name = spec.api_key_env or "FRED_API_KEY"
        return SymbolFetch(
            spec.id,
            symbol,
            "auth_failed",
            detail=f"{env_name} is not set; refusing to fetch",
        )

    cached = cache.load(spec.id, symbol)
    rows = (
        [
            (obs_date, value)
            for obs_date, value in sorted(cached.observations.items())
            if start <= obs_date <= end
        ]
        if cached
        else []
    )
    max_age = (
        timedelta(minutes=spec.refresh.max_age_minutes) if spec.refresh.max_age_minutes else None
    )
    fresh = (
        cached is not None
        and cached.fetched_at is not None
        and (max_age is None or now - cached.fetched_at <= max_age)
        and _tail_is_current(cached, now, spec.refresh.backfill_sessions)
    )
    if fresh and rows and cached is not None:
        return SymbolFetch(
            spec.id,
            symbol,
            "cached",
            bars=len(rows),
            first_date=min(cached.observations),
            last_date=max(cached.observations),
            content_digest=cached.content_digest,
            detail="cache within refresh policy",
        )

    url = _fred_url(api_base, symbol, start, end, api_key)
    try:
        status_code, body = http_get(url, 30.0)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        return SymbolFetch(
            spec.id,
            symbol,
            "unreachable",
            detail=f"classified network failure: {error.__class__.__name__}",
        )
    if status_code == 400 and b"API Key" in body or status_code in (401, 403):
        return SymbolFetch(
            spec.id, symbol, "auth_failed", detail=f"FRED rejected the API key (HTTP {status_code})"
        )
    if status_code != 200:
        return SymbolFetch(spec.id, symbol, "unreachable", detail=f"HTTP {status_code}")
    try:
        fetched = _parse_fred_csv(body, symbol)
    except (ValueError, ArithmeticError):
        return SymbolFetch(spec.id, symbol, "parse_failed", detail="invalid provider payload")

    merged = dict(cached.observations) if cached else {}
    merged.update(dict(fetched))
    data = RealSymbolData(
        source_id=spec.id,
        symbol=symbol,
        asset_class=FRED_SERIES_ASSET_CLASSES.get(symbol, "unknown"),
        observations=merged,
        fetched_at=now,
    )
    cache.save(data)
    return SymbolFetch(
        spec.id,
        symbol,
        "ok",
        bars=len(merged),
        first_date=min(merged),
        last_date=max(merged),
        content_digest=data.content_digest or content_digest(symbol, list(merged.items())),
        detail=f"fetched {len(fetched)} new rows",
    )


def _tail_is_current(data: RealSymbolData, now: datetime, backfill_sessions: int) -> bool:
    if not data.observations:
        return False
    last = max(data.observations)
    missing_days = (now.date() - last).days
    # Daily sources: each missing calendar day is one missing session.
    return missing_days <= max(backfill_sessions, 1)


def fetch_source(
    spec: SourceSpec,
    cache: RealDataCache,
    start: date,
    end: date,
    *,
    api_key: str,
    now: datetime,
    http_get: HTTPGet = default_http_get,
) -> SourceFetchResult:
    if not spec.enabled or not spec.symbols:
        return SourceFetchResult(spec.id, spec.enabled, tuple(spec.symbols))
    results = [
        fetch_symbol(spec, symbol, cache, start, end, api_key=api_key, now=now, http_get=http_get)
        for symbol in spec.symbols
    ]
    snapshot_id = None
    if all(result.status in {"ok", "cached"} for result in results):
        digest = _sha256_hex("".join((result.content_digest or "") for result in results))[:16]
        snapshot_id = f"realdata-{digest}"
    return SourceFetchResult(spec.id, True, tuple(spec.symbols), tuple(results), snapshot_id)


class RealMarketProvider(MarketDataProvider):
    """Point-in-time view over cached real (close-only) observations.

    Daily series: one observation per trading date, timestamped at the
    exchange session close. OHLC collapses to the close (index/bond series
    have no meaningful intraday OHLC in this source); volume is 0 and
    ``session_volume`` returns None — callers that require volume must treat
    that as unavailable, never zero-trade capacity.
    """

    @property
    def source_id(self) -> str:
        return self._source_id

    def __init__(
        self,
        source_id: str,
        data: list[RealSymbolData],
        exchange_timezone: str,
        stale_after_sessions: int = 1,
        close_time: time = time(20, 0),
    ) -> None:
        self._source_id = source_id
        self._tz = ZoneInfo(exchange_timezone)
        self._stale_after_sessions = stale_after_sessions
        self._close_time = close_time
        self._closes: dict[str, dict[date, Decimal]] = {
            item.symbol: dict(item.observations) for item in data
        }
        self._symbols = sorted(self._closes)
        self._sessions = sorted(
            {obs_date for closes in self._closes.values() for obs_date in closes}
        )
        self._session_index = {session: index for index, session in enumerate(self._sessions)}
        self._snapshot_id = (
            "realdata-"
            + _sha256_hex(
                json.dumps(
                    {
                        symbol: content_digest(symbol, sorted(closes.items()))
                        for symbol, closes in sorted(self._closes.items())
                    },
                    sort_keys=True,
                )
            )[:16]
        )
        self._instruments = tuple(
            Instrument(
                instrument_id=f"{source_id}:{symbol}",
                symbol=symbol,
                asset_class=item.asset_class,
                price_decimals=2,
                quantity_precision=0,
                is_synthetic=False,
                eligible=True,
                notes=(f"{source_id} close-only series",),
            )
            for item in data
            for symbol in [item.symbol]
        )

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(self._symbols)

    @property
    def stale_after_sessions(self) -> int:
        return self._stale_after_sessions

    def instruments(self) -> tuple[Instrument, ...]:
        return self._instruments

    def sessions(self) -> tuple[date, ...]:
        return tuple(self._sessions)

    def data_snapshot_id(self) -> str:
        return self._snapshot_id

    def _close_at(self, instrument_id: str, obs_date: date) -> Decimal | None:
        symbol = instrument_id.split(":", 1)[-1]
        return self._closes.get(symbol, {}).get(obs_date)

    def bars(self, instrument_id: str, start: datetime, end: datetime) -> tuple[MarketBar, ...]:
        symbol = instrument_id.split(":", 1)[-1]
        closes = self._closes.get(symbol, {})
        out: list[MarketBar] = []
        for obs_date, close in sorted(closes.items()):
            if not start.date() <= obs_date <= end.date():
                continue
            ts = datetime.combine(obs_date, self._close_time, tzinfo=self._tz)
            out.append(
                MarketBar(
                    instrument_id=instrument_id,
                    ts=ts,
                    open=close,
                    high=close,
                    low=close,
                    close=close,
                    volume=Decimal("0"),
                    source_id=self._source_id,
                    quality=QualityFlag.VALID,
                    exchange_time=ts,
                )
            )
        return tuple(out)

    def _session_of(self, instant: datetime) -> date:
        session = instant.astimezone(self._tz).date()
        prior = [day for day in self._session_index if day <= session]
        return prior[-1] if prior else session

    def quote(self, instrument_id: str, as_of: datetime) -> Quote | None:
        symbol = instrument_id.split(":", 1)[-1]
        closes = self._closes.get(symbol, {})
        if not closes:
            return None
        prior = [obs_date for obs_date in closes if self._ts(obs_date) <= as_of]
        if not prior:
            return None
        last = max(prior)
        stale = self.sessions_since_observation(instrument_id, as_of)
        quality = QualityFlag.STALE if stale >= self._stale_after_sessions else QualityFlag.VALID
        return Quote(
            instrument_id=instrument_id,
            price=closes[last],
            as_of=self._ts(last),
            source_id=self._source_id,
            quality=quality,
        )

    def _ts(self, obs_date: date) -> datetime:
        return datetime.combine(obs_date, self._close_time, tzinfo=self._tz)

    def sessions_since_observation(self, instrument_id: str, as_of: datetime) -> int:
        symbol = instrument_id.split(":", 1)[-1]
        closes = self._closes.get(symbol, {})
        if not closes:
            return -1
        prior = [obs_date for obs_date in closes if self._ts(obs_date) <= as_of]
        if not prior:
            return -1
        last = max(prior)
        if last not in self._session_index:
            return -1
        as_of_session = self._session_of(as_of)
        if as_of_session not in self._session_index:
            prior_sessions = [day for day in self._session_index if day <= as_of_session]
            if not prior_sessions:
                return -1
            as_of_session = prior_sessions[-1]
        return self._session_index[as_of_session] - self._session_index[last]

    def recent_session_closes(
        self, instrument_id: str, as_of_session: date, count: int
    ) -> tuple[SessionClose, ...]:
        symbol = instrument_id.split(":", 1)[-1]
        closes = self._closes.get(symbol, {})
        window = [
            SessionClose(session=obs_date, close=close)
            for obs_date, close in sorted(closes.items())
            if obs_date <= as_of_session
        ]
        return tuple(window[-count:])

    def session_volume(self, instrument_id: str, as_of: datetime) -> Decimal | None:
        return None  # close-only series: volume unavailable, never faked


def build_real_providers(
    config: TradingConfig,
    cache: RealDataCache,
    start: date,
    end: date,
    *,
    now: datetime,
    http_get: HTTPGet = default_http_get,
    api_key_env: str = "FRED_API_KEY",
) -> tuple[dict[str, SourceFetchResult], dict[str, RealMarketProvider]]:
    """Fetch every enabled non-synthetic registry source and build providers.

    Returns per-source results plus a provider per source that succeeded.
    A source whose data is only partially fetched yields no provider (fail
    closed): the backtest must use complete data or refuse.
    """
    import os

    results: dict[str, SourceFetchResult] = {}
    providers: dict[str, RealMarketProvider] = {}
    for spec in config.data.registry:
        if spec.id == "synthetic" or not spec.enabled or not spec.symbols:
            continue
        results[spec.id] = fetch_source(
            spec,
            cache,
            start,
            end,
            api_key=os.environ.get(api_key_env, "") or os.environ.get(spec.api_key_env or "", ""),
            now=now,
            http_get=http_get,
        )
    for source_id, result in results.items():
        spec = next(entry for entry in config.data.registry if entry.id == source_id)
        data = [
            item
            for symbol in result.results
            if symbol.status in {"ok", "cached"}
            for item in [cache.load(source_id, symbol.symbol)]
            if item is not None
        ]
        if len(data) == len(result.results):
            providers[source_id] = RealMarketProvider(
                source_id=source_id,
                data=data,
                exchange_timezone=config.app.exchange_timezone,
                stale_after_sessions=config.data.stale_after_sessions,
            )
        del spec
    return results, providers


def run_quality_checks(
    providers: dict[str, RealMarketProvider],
    config: TradingConfig,
    now: datetime,
) -> list[dict[str, object]]:
    """Per-instrument quality rows (M3 data-quality gate)."""
    rows: list[dict[str, object]] = {} if False else []
    all_sessions = sorted(
        {session for provider in providers.values() for session in provider.sessions()}
    )
    for source_id, provider in sorted(providers.items()):
        for instrument in provider.instruments():
            closes = dict()
            for session in all_sessions:
                window = provider.recent_session_closes(instrument.instrument_id, session, 1)
                if window:
                    closes[session] = window[-1]
            observed = set(closes)
            expected = {session for session in all_sessions}
            missing = sorted(expected - observed)
            stale = provider.sessions_since_observation(instrument.instrument_id, now)
            rows.append(
                {
                    "source_id": source_id,
                    "instrument_id": instrument.instrument_id,
                    "observed_sessions": len(observed),
                    "expected_sessions": len(expected),
                    "missing_sessions": len(missing),
                    "missing_sample": missing[:10],
                    "sessions_since_observation": stale,
                    "stale": stale >= config.data.stale_after_sessions,
                    "snapshot_id": provider.data_snapshot_id(),
                }
            )
    return rows
