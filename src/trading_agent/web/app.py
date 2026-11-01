"""FastAPI application for the local website (docs/website.md).

Rules enforced in this module:

- The app binds only to the configured loopback host and rejects every
  request whose Host header does not match it (403, all paths).
- Every path except ``/static`` and the login form requires a valid signed
  owner session; unauthenticated API calls get 401, unauthenticated page
  requests redirect to the login form.
- ``web_auth`` / ``web_sessions`` rows are written only on login and logout;
  every other request is strictly read-only.
- No route invokes model inference or a broker operation, and no route
  exposes live order controls.
"""

from __future__ import annotations

import hmac
import sys
from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.responses import Response

from ..config.models import TradingConfig
from ..db.engine import create_app_engine, open_session
from ..db.migrate import run_migrations
from ..security.loopback import is_loopback_url
from . import auth as auth_module
from .auth import SESSION_COOKIE, AuthStore, expected_origin, host_matches
from .queries import (
    get_activity,
    get_cash_ledger,
    get_equity_curve,
    get_health,
    get_instrument,
    get_order_detail,
    get_overview,
    get_positions,
    get_prices,
    list_runs,
)

_PUBLIC_PREFIXES = ("/static/",)


def _base_context(config: TradingConfig) -> dict[str, str]:
    return {
        "mode": config.app.mode.value.upper(),
        "authority": config.authority(),
        "web_url": expected_origin(config),
        "label": config.app.mode.value.upper(),
    }


def build_app(config: TradingConfig, *, auth_store: AuthStore | None = None) -> FastAPI:
    """Construct the website app bound to the given configuration."""
    store = auth_store if auth_store is not None else auth_module.load_store()
    engine = create_app_engine(config, pool="null")

    app = FastAPI(title="trading-agent", docs_url=None, redoc_url=None)
    app.state.config = config
    app.state.auth = store
    app.state.engine = engine

    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
    app.mount(
        "/static",
        StaticFiles(directory=str(Path(__file__).parent / "static")),
        name="static",
    )
    base_ctx = _base_context(config)

    def require_auth(request: Request) -> None:
        """Fail closed: the middleware is the real gate; this is a second check."""
        if not getattr(request.state, "authenticated", False):
            raise HTTPException(status_code=401, detail="unauthenticated")

    def verify(store_obj: AuthStore, request: Request) -> bool:
        return auth_module.verify_session(store_obj, request.cookies.get(SESSION_COOKIE))

    @app.middleware("http")
    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not host_matches(config, request.headers.get("host")):
            return JSONResponse(status_code=403, content={"error": "host mismatch"})
        origin = request.headers.get("origin")
        if origin is not None and origin != expected_origin(config):
            return JSONResponse(status_code=403, content={"error": "origin mismatch"})
        path = request.url.path
        public = path == "/auth/login" or path.startswith("/static/")
        request.state.authenticated = False
        try:
            cookie = request.cookies.get(SESSION_COOKIE)
            if cookie and verify(store, request):
                with open_session(engine) as session:
                    request.state.authenticated = auth_module.session_registered(session, cookie)
            if not public and not request.state.authenticated:
                if path.startswith("/api/"):
                    return JSONResponse(status_code=401, content={"error": "unauthenticated"})
                return RedirectResponse(url="/auth/login", status_code=302)
            response = await call_next(request)
        except SQLAlchemyError:
            response = JSONResponse(
                status_code=503, content={"error": "local database unavailable"}
            )
        except ValueError:
            response = JSONResponse(
                status_code=503, content={"error": "persisted evidence unavailable"}
            )
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        return response

    def db_session(request: Request) -> Iterator[Session]:
        """Per-request session; every handler in this app is read-only."""
        session = open_session(engine)
        try:
            if engine.dialect.name == "postgresql":
                session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
                session.execute(text("SET TRANSACTION READ ONLY"))
            elif engine.dialect.name == "sqlite":
                # SQLite's legacy driver does not BEGIN for SELECT. Pin this read snapshot.
                session.connection().exec_driver_sql("BEGIN")
            yield session
        finally:
            session.close()

    SessionDep = Depends(db_session)

    # ------------------------------------------------------------- auth

    @app.get("/auth/login", response_class=HTMLResponse)
    async def login_page(request: Request) -> Response:
        if getattr(request.state, "authenticated", False):
            return RedirectResponse(url="/", status_code=302)
        return templates.TemplateResponse(
            request=request, name="login.html", context={**base_ctx, "error": None}
        )

    @app.post("/auth/login")
    async def login_submit(request: Request) -> Response:
        origin = request.headers.get("origin")
        if origin != expected_origin(config):
            return JSONResponse(status_code=403, content={"error": "origin mismatch"})
        form = await request.form()
        token = str(form.get("token", ""))
        if not token or not hmac.compare_digest(
            token.encode("utf-8"), store.owner_token.encode("utf-8")
        ):
            return templates.TemplateResponse(
                request=request,
                name="login.html",
                context={**base_ctx, "error": "invalid owner token"},
                status_code=403,
            )
        cookie = auth_module.issue_session(store)
        stamp = datetime.now(UTC)
        session = open_session(engine)
        try:
            auth_module.record_login(session, store, cookie, stamp)
            session.commit()
        finally:
            session.close()
        response = RedirectResponse(url="/", status_code=302)
        response.set_cookie(
            SESSION_COOKIE,
            cookie,
            httponly=True,
            samesite="strict",
            path="/",
            max_age=int(auth_module.SESSION_TTL.total_seconds()),
        )
        return response

    @app.post("/auth/logout")
    async def logout(request: Request) -> Response:
        require_auth(request)
        if request.headers.get("origin") != expected_origin(config):
            raise HTTPException(status_code=403, detail="origin mismatch")
        cookie = request.cookies.get(SESSION_COOKIE)
        session = open_session(engine)
        try:
            auth_module.record_logout(session, cookie)
            session.commit()
        finally:
            session.close()
        response = RedirectResponse(url="/auth/login", status_code=302)
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    # ------------------------------------------------------------- pages

    @app.get("/", response_class=HTMLResponse)
    async def page_overview(request: Request) -> Response:
        return templates.TemplateResponse(request=request, name="overview.html", context=base_ctx)

    @app.get("/activity", response_class=HTMLResponse)
    async def page_activity(request: Request) -> Response:
        return templates.TemplateResponse(request=request, name="activity.html", context=base_ctx)

    @app.get("/orders", response_class=HTMLResponse)
    async def page_orders(request: Request) -> Response:
        return templates.TemplateResponse(request=request, name="orders.html", context=base_ctx)

    @app.get("/orders/{order_id}", response_class=HTMLResponse)
    async def page_order_detail(request: Request, order_id: str) -> Response:
        return templates.TemplateResponse(
            request=request, name="order_detail.html", context={**base_ctx, "order_id": order_id}
        )

    @app.get("/portfolio", response_class=HTMLResponse)
    async def page_portfolio(request: Request) -> Response:
        return templates.TemplateResponse(request=request, name="portfolio.html", context=base_ctx)

    @app.get("/instruments/{instrument_id}", response_class=HTMLResponse)
    async def page_instrument_detail(request: Request, instrument_id: str) -> Response:
        return templates.TemplateResponse(
            request=request,
            name="instrument_detail.html",
            context={**base_ctx, "instrument_id": instrument_id},
        )

    @app.get("/learning", response_class=HTMLResponse)
    async def page_learning(request: Request, experiment_id: str | None = None) -> Response:
        from ..learning.labels import LearningError
        from ..learning.workflow import load_report

        require_auth(request)
        report = None
        error = None
        if experiment_id is not None:
            try:
                report = load_report(config.learning.research_store_dir, experiment_id)
            except (LearningError, OSError, ValueError):
                raise HTTPException(
                    status_code=404, detail="research artifact unavailable"
                ) from None
            scope = report.dataset.scope
            if (
                scope.mode != config.app.mode.value
                or scope.mode != "simulation"
                or scope.account_alias != "research-fixture"
            ):
                raise HTTPException(
                    status_code=404, detail="research artifact outside active scope"
                )
        else:
            error = (
                "No experiment selected. Run trading-agent learning demo "
                "and open its learning-page link."
            )
        return templates.TemplateResponse(
            request=request,
            name="learning.html",
            context={
                **base_ctx,
                "report": report,
                "error": error,
                "experiment_id": experiment_id,
                "actions": {r.decision_id: r.intent.action for r in report.dataset.records}
                if report
                else {},
            },
        )

    def readiness_view(
        session: Session, run_id: str | None, intent_id: str | None
    ) -> dict[str, Any]:
        from ..supervised.view import project

        return project(
            session.connection(), config, now=datetime.now(UTC), run_id=run_id, intent_id=intent_id
        )

    @app.get("/readiness", response_class=HTMLResponse)
    async def page_readiness(
        request: Request,
        session: Session = SessionDep,
        run_id: str | None = None,
        intent_id: str | None = None,
    ) -> Response:
        require_auth(request)
        view = readiness_view(session, run_id, intent_id)
        return templates.TemplateResponse(
            request=request, name="readiness.html", context={**base_ctx, "view": view}
        )

    @app.get("/api/v1/readiness")
    async def api_readiness(
        request: Request,
        session: Session = SessionDep,
        run_id: str | None = None,
        intent_id: str | None = None,
    ) -> dict[str, Any]:
        require_auth(request)
        return readiness_view(session, run_id, intent_id)

    @app.post("/api/v1/readiness/{action}")
    async def denied_live_control(request: Request, action: str) -> Response:
        require_auth(request)
        raise HTTPException(
            status_code=403, detail="LIVE_NOT_AUTHORIZED: actual live controls unavailable"
        )

    @app.get("/autonomy", response_class=HTMLResponse)
    async def page_autonomy(
        request: Request, session: Session = SessionDep, run_id: str | None = None
    ) -> Response:
        from ..autonomy.view import project

        require_auth(request)
        try:
            view = project(session.connection(), config, now=datetime.now(UTC), run_id=run_id)
        except ValueError as error:
            raise HTTPException(
                status_code=503, detail="Synthetic evidence integrity failure"
            ) from error
        return templates.TemplateResponse(
            request=request, name="autonomy.html", context={**base_ctx, "view": view}
        )

    @app.get("/api/v1/autonomy")
    async def api_autonomy(
        request: Request, session: Session = SessionDep, run_id: str | None = None
    ) -> dict[str, Any]:
        from ..autonomy.view import project

        require_auth(request)
        try:
            return project(session.connection(), config, now=datetime.now(UTC), run_id=run_id)
        except ValueError as error:
            raise HTTPException(
                status_code=503, detail="Synthetic evidence integrity failure"
            ) from error

    @app.post("/api/v1/autonomy/{action}")
    async def denied_autonomy_control(request: Request, action: str) -> Response:
        require_auth(request)
        raise HTTPException(status_code=403, detail="LIVE_NOT_AUTHORIZED: controls unavailable")

    # --------------------------------------------------------------- api

    @app.get("/api/v1/health")
    async def api_health(
        request: Request, session: Session = SessionDep, run_id: str | None = None
    ) -> dict[str, Any]:
        require_auth(request)
        return get_health(session, config, run_id)

    @app.get("/api/v1/runs")
    async def api_runs(request: Request, session: Session = SessionDep) -> dict[str, Any]:
        require_auth(request)
        return list_runs(session, config)

    @app.get("/api/v1/overview")
    async def api_overview(
        request: Request, session: Session = SessionDep, run_id: str | None = None
    ) -> dict[str, Any]:
        require_auth(request)
        return get_overview(session, config, run_id)

    @app.get("/api/v1/equity-curve")
    async def api_equity_curve(
        request: Request, session: Session = SessionDep, run_id: str | None = None
    ) -> dict[str, Any]:
        require_auth(request)
        return get_equity_curve(session, config, run_id)

    @app.get("/api/v1/activity")
    async def api_activity(
        request: Request,
        session: Session = SessionDep,
        run_id: str | None = None,
        cursor: int | None = Query(default=None, ge=0),
        limit: int = Query(default=20, ge=1, le=100),
    ) -> dict[str, Any]:
        require_auth(request)
        return get_activity(session, config, run_id, cursor=cursor, limit=limit)

    @app.get("/api/v1/orders")
    async def api_orders(
        request: Request,
        session: Session = SessionDep,
        run_id: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        require_auth(request)
        return _orders(session, config, run_id, status)

    @app.get("/api/v1/orders/{order_id}")
    async def api_order_detail(
        request: Request,
        order_id: str,
        session: Session = SessionDep,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        require_auth(request)
        return get_order_detail(session, config, run_id, order_id)

    @app.get("/api/v1/fills")
    async def api_fills(
        request: Request,
        session: Session = SessionDep,
        run_id: str | None = None,
        order_id: str | None = None,
    ) -> dict[str, Any]:
        require_auth(request)
        return _fills(session, config, run_id, order_id)

    @app.get("/api/v1/positions")
    async def api_positions(
        request: Request, session: Session = SessionDep, run_id: str | None = None
    ) -> dict[str, Any]:
        require_auth(request)
        return get_positions(session, config, run_id)

    @app.get("/api/v1/instruments/{instrument_id}")
    async def api_instrument(
        request: Request,
        instrument_id: str,
        session: Session = SessionDep,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        require_auth(request)
        return get_instrument(session, config, run_id, instrument_id)

    @app.get("/api/v1/prices/{instrument_id}")
    async def api_prices(
        request: Request,
        instrument_id: str,
        session: Session = SessionDep,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        require_auth(request)
        return get_prices(session, config, run_id, instrument_id)

    @app.get("/api/v1/cash-ledger")
    async def api_cash_ledger(
        request: Request, session: Session = SessionDep, run_id: str | None = None
    ) -> dict[str, Any]:
        require_auth(request)
        return get_cash_ledger(session, config, run_id)

    @app.get("/api/v1/bootstrap")
    async def api_bootstrap(
        request: Request, session: Session = SessionDep, run_id: str | None = None
    ) -> dict[str, Any]:
        from .review import bootstrap

        require_auth(request)
        try:
            return bootstrap(session, config, run_id, store.session_secret)
        except ValueError as error:
            raise HTTPException(status_code=404, detail="scoped snapshot unavailable") from error

    @app.get("/api/v1/events")
    async def api_events(
        request: Request, run_id: str, cursor: str, session: Session = SessionDep
    ) -> Response:
        from .review import notifications

        require_auth(request)
        try:
            return JSONResponse(
                notifications(session, config, run_id, cursor, store.session_secret)
            )
        except ValueError:
            return JSONResponse(status_code=409, content={"resnapshot_required": True})

    @app.get("/api/v1/stream")
    async def api_stream(
        request: Request, run_id: str, cursor: str, session: Session = SessionDep
    ) -> Response:
        import json

        from .review import notifications

        require_auth(request)
        try:
            page = notifications(
                session,
                config,
                run_id,
                request.headers.get("Last-Event-ID") or cursor,
                store.session_secret,
            )
        except ValueError:
            return JSONResponse(status_code=409, content={"resnapshot_required": True})
        body = (
            "retry: 5000\nid: "
            + page["cursor"]
            + "\nevent: committed\ndata: "
            + json.dumps(page)
            + "\n\n"
        )
        return Response(body, media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})

    @app.get("/api/v1/exports/activity.csv")
    async def api_export(
        request: Request, run_id: str, cursor: str | None = None, session: Session = SessionDep
    ) -> Response:
        from .review import export_activity

        require_auth(request)
        try:
            body, next_cursor, more = export_activity(
                session, config, run_id, cursor, store.session_secret
            )
        except ValueError as error:
            raise HTTPException(
                status_code=403, detail="export scope or cursor unavailable"
            ) from error
        return Response(
            body,
            media_type="text/csv",
            headers={
                "Content-Disposition": 'attachment; filename="activity.csv"',
                "X-Next-Cursor": next_cursor,
                "X-Has-More": str(more).lower(),
            },
        )

    @app.get("/api/v1/review/{section}")
    async def api_review(
        request: Request, section: str, session: Session = SessionDep, run_id: str | None = None
    ) -> dict[str, Any]:
        from .review import review

        require_auth(request)
        try:
            return review(session, config, run_id, section)
        except ValueError as error:
            raise HTTPException(status_code=404, detail="review section unavailable") from error

    @app.get("/{section}", response_class=HTMLResponse)
    async def page_review(
        request: Request, section: str, session: Session = SessionDep, run_id: str | None = None
    ) -> Response:
        from .review import review

        require_auth(request)
        try:
            view = review(session, config, run_id, section)
        except ValueError as error:
            raise HTTPException(status_code=404, detail="review section unavailable") from error
        return templates.TemplateResponse(
            request=request, name="review.html", context={**base_ctx, "view": view}
        )

    return app


def _orders(
    session: Session, config: TradingConfig, run_id: str | None, status: str | None
) -> dict[str, Any]:
    from .queries import get_orders

    return get_orders(session, config, run_id, status)


def _fills(
    session: Session, config: TradingConfig, run_id: str | None, order_id: str | None
) -> dict[str, Any]:
    from .queries import get_fills

    return get_fills(session, config, run_id, order_id)


def serve(config: TradingConfig, host: str | None = None, port: int | None = None) -> None:
    """Run the website: bootstrap owner auth, migrate, and serve on loopback."""
    path, created = auth_module.ensure_bootstrap()
    store = auth_module.load_store(path)
    if created:
        print(f"owner token created at {path} (chmod 600)")
        print("Retrieve your owner token locally from the protected file; do not share it.")
    else:
        print(f"owner token exists at {path} (delete the file to re-bootstrap)")
    if host is not None or port is not None:
        config = config.model_copy(deep=True)
        config.app = config.app.model_copy(
            update={
                "web_host": host if host is not None else config.app.web_host,
                "web_port": port if port is not None else config.app.web_port,
            }
        )
    print(f"authority: {config.authority()}  mode: {config.app.mode.value.upper()}")
    print("serving SIMULATION data only; no live order controls exist.")
    try:
        head = run_migrations(config)
        print(f"database migrations current (head: {head})")
    except Exception as error:
        print(f"ERROR: {error}")
        raise SystemExit(2) from error
    url = expected_origin(config)
    print(f"website: {url}  (owner login at {url}/auth/login)")
    app = build_app(config, auth_store=store)
    if not is_loopback_url(expected_origin(config)):
        print(
            f"ERROR: refusing to bind {config.app.web_host} (non-loopback)",
            file=sys.stderr,
        )
        raise SystemExit(1)
    uvicorn.run(app, host=config.app.web_host, port=config.app.web_port, log_level="warning")
