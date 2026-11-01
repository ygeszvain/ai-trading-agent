"""Owner review of an existing M7 synthetic journal; never normal application startup."""

import argparse
from pathlib import Path

import uvicorn
from fastapi.responses import RedirectResponse
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

from trading_agent.autonomy.fixtures import KEY
from trading_agent.autonomy.store import Store
from trading_agent.config.loading import load_config
from trading_agent.db.schema import web_auth, web_sessions
from trading_agent.web import app as web_module
from trading_agent.web.auth import AuthStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8028)
    args = parser.parse_args()
    if args.journal.is_symlink() or not args.journal.is_file() or args.journal.suffix != ".sqlite":
        raise SystemExit("existing fixture journal required")
    engine = create_engine(URL.create("sqlite", database=str(args.journal.resolve())))
    with Store(engine).transaction() as conn:
        state = Store(engine).state(conn, KEY)
        if state.domain != "M7_MOCK_ONLY" or state.account_alias != "m7-fixture":
            raise SystemExit("not a synthetic M7 journal")
    web_auth.create(engine, checkfirst=True)
    web_sessions.create(engine, checkfirst=True)
    config = load_config("config/simulation.yaml", env={})
    config.app.web_port = args.port
    web_module.create_app_engine = lambda *a, **k: engine
    auth = AuthStore(
        args.journal.parent / "fixture-web-owner", "fixture-m7-web-owner", "fixture-m7-web-signing"
    )
    app = web_module.build_app(config, auth_store=auth)

    @app.middleware("http")
    async def fixture_landing(request, call_next):
        if request.url.path == "/":
            return RedirectResponse("/autonomy", status_code=302)
        return await call_next(request)

    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
