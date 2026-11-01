"""Broker gateway lifecycle: the persistent shadow loop (build plan section 17).

The gateway hosts a background loop that performs broker ``account_snapshot``
cycles at a configured interval. In this build that is continuous, read-only
observation of the owner's Robinhood account via the official MCP (plan
section 14). The paper research engine keeps using the simulator; the shadow
gateway runs independently against the real account and only observes.

Properties:
  * Runs on a daemon thread; each cycle rebuilds its own DB session and
    broker adapter, so a failing broker session or a closed app window can
    never corrupt app state or kill the process.
  * Every cycle's result is handed to ``on_cycle`` and persisted by the
    adapter (``broker_snapshots``); the web dashboard reads that history.
  * Unexpected exceptions are audited as gateway events, remembered as
    ``last_error``, and the loop continues.
  * ``stop()`` is idempotent and prompt (1-second interruptible sleep).
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Literal

from sqlalchemy.orm import Session

from ..contracts.broker import AccountSnapshot
from .broker_interface import BrokerAdapter

log = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]
AdapterFactory = Callable[..., BrokerAdapter]
CycleCallback = Callable[[AccountSnapshot | None, str | None], None]


class ShadowMonitor:
    """Drives repeated shadow cycles: (session, adapter, close) per tick."""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        adapter_factory: AdapterFactory,
        poll_seconds: float = 30.0,
        on_cycle: CycleCallback | None = None,
        shadow_provider: Literal["simulator", "robinhood"] = "robinhood",
    ) -> None:
        if poll_seconds < 5.0:
            raise ValueError("poll_seconds must be >= 5 (broker rate limits)")
        self._session_factory = session_factory
        self._adapter_factory = adapter_factory
        self._poll_seconds = poll_seconds
        self._on_cycle = on_cycle
        self._shadow_provider = shadow_provider
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._last_error: str | None = None
        self._cycles = 0

    # ------------------------------------------------------------- state

    @property
    def shadow_provider(self) -> str:
        return self._shadow_provider

    @property
    def running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def cycle_count(self) -> int:
        return self._cycles

    # ---------------------------------------------------------- lifecycle

    def start(self) -> bool:
        """Start the loop. Idempotent; returns True if newly started."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, name="broker-shadow-loop", daemon=True
            )
            self._thread.start()
            return True

    def stop(self, timeout: float = 10.0) -> None:
        """Signal the loop to stop and wait for it to exit."""
        with self._lock:
            if self._thread is None:
                return
            self._stop.set()
            thread = self._thread
            self._thread = None
        thread.join(timeout=timeout)

    # ---------------------------------------------------------------- loop

    def _run(self) -> None:
        while not self._stop.is_set():
            snapshot = None
            error = None
            session: Session | None = None
            adapter: BrokerAdapter | None = None
            try:
                session = self._session_factory()
                adapter = self._adapter_factory(session=session)
                snapshot = adapter.account_snapshot()
                session.commit()
                error = None
                self._cycles += 1
            except Exception as exc:  # noqa: BLE001 - the loop must survive
                error = f"{type(exc).__name__}: {exc}"
                if session is not None:
                    try:
                        session.rollback()
                    except Exception:  # noqa: BLE001
                        pass
                if adapter is not None:
                    try:
                        adapter.log_cycle_error(error)  # type: ignore[attr-defined]
                        session.commit()
                    except Exception:  # noqa: BLE001 - audit is best-effort
                        pass
                log.warning("shadow cycle failed: %s", error)
            finally:
                if adapter is not None:
                    try:
                        adapter.close()
                    except Exception:  # noqa: BLE001
                        pass
                if session is not None:
                    try:
                        session.close()
                    except Exception:  # noqa: BLE001
                        pass
            self._last_error = error
            if self._on_cycle is not None:
                try:
                    self._on_cycle(snapshot, error)
                except Exception:  # noqa: BLE001 - observers must not kill loop
                    log.exception("shadow on_cycle observer failed")
            self._stop.wait(self._poll_seconds)
