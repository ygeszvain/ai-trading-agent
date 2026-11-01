"""Local browser QA for an existing M6 MOCK journal; not application setup or activation."""

import argparse
from pathlib import Path

import uvicorn
from fastapi.responses import RedirectResponse
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

from trading_agent.config.loading import load_config
from trading_agent.db.schema import web_auth, web_sessions
from trading_agent.supervised.fixtures import KEY
from trading_agent.supervised.journal import Journal
from trading_agent.web import app as web_module
from trading_agent.web.auth import AuthStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8028)
    args = parser.parse_args()
    if args.journal.is_symlink() or not args.journal.is_file() or args.journal.suffix != ".sqlite":
        raise SystemExit("existing fixture SQLite journal required")
    engine = create_engine(URL.create("sqlite", database=str(args.journal.resolve())))
    journal = Journal(engine)
    with journal.transaction() as conn:
        state = journal.state(conn, KEY)
        if state.domain != "M6_MOCK_ONLY" or state.account_alias != "m6-fixture":
            raise SystemExit("not a fixture journal")
    web_auth.create(engine, checkfirst=True)
    web_sessions.create(engine, checkfirst=True)
    config = load_config("config/simulation.yaml", env={})
    config.app.web_port = args.port
    web_module.create_app_engine = lambda *args, **kwargs: engine
    store = AuthStore(
        args.journal.parent / "fixture-web-auth", "fixture-m6-web-owner", "fixture-m6-web-signing"
    )
    app = web_module.build_app(config, auth_store=store)

    @app.middleware("http")
    async def fixture_landing(request, call_next):
        if request.url.path == "/":
            return RedirectResponse("/readiness", status_code=302)
        return await call_next(request)

    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
