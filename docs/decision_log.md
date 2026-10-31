# Decision log

Each entry records what was decided in M0, why, and how to reverse it.
Decisions that merely restate the plan are included when they constrain
later milestones. Status: all entries below are **accepted for M0** and are
the working baseline for Prompt 2 (M1).

| ID | Decision | Rationale | Reversibility |
| --- | --- | --- | --- |
| D1 | Pin Python `>=3.13,<3.14`; `.python-version` = 3.13 (Homebrew 3.13.2) | 3.13 is a supported release (EOL Oct 2029) with mature library support; 3.15.2 is too new for a financial-critical baseline; 3.12 is available but 3.13 is the modern supported pin | Change the pin + `uv sync`; low cost |
| D2 | `uv` 0.13.6 (Homebrew) as the environment manager; `uv.lock` committed | Prompt 1 requires uv + lockfile; Homebrew bottle, no heavy download | Remove uv; lockfile regenerates |
| D3 | Typed config = Pydantic v2 models + PyYAML, with a small manual environment overlay | The plan names the plan section 9 env var names exactly; a manual overlay is explicit, testable, and avoids an extra dependency (pydantic-settings not needed) | Swap loader; models stay |
| D4 | FastAPI + uvicorn locked in M0 even though the first app code lands in M1 | Plan section 6 prescribes the stack; pinning now keeps M1 resolution stable | Remove from `pyproject.toml` in M1 if measured need differs |
| D5 | PostgreSQL 17 via `docker compose`, bound 127.0.0.1:5433, named volume, trust auth | Host port 5432 is occupied by the dissertation `fda-postgres`; loopback-only disposable DB matches plan section 6; the `postgres:17` image is already cached (no download) | `docker compose down` (+`-v`); migrate to a different port/instance |
| D6 | Decimal for all money/quantity/limit values; floats accepted only at the config boundary and converted via shortest string | Plan section 6: explicit precision/rounding; no binary-float money | Global search-replace; large blast radius (avoid) |
| D7 | v1-scope switches are config errors when on: cloud fallback, paid subscriptions (without budget), deferred asset classes, emergency liquidation, live auto-promotion / live change classes | Plan sections 3, 8, 12, 13: these are fail-closed by design; a warning would let a bad value reach runtime | Loosen specific rules in later milestones with a new decision entry |
| D8 | Synthetic `TEST_*` universe and live allowlist must be disjoint; `TEST_*` IDs never enter the live allowlist | Plan section 22: synthetic identifiers must never resolve to live instruments | Tightening only; loosening requires an owner decision |
| D9 | Broker interface in M0: adapters raise classified `BrokerError`s; no MCP client dependency | Prompt 1: "unavailable implementation explicitly rejects execution; never fabricated success"; the client library arrives with M4 against verified schemas | Add the MCP client in M4 (new decision) |
| D10 | Live-activation gate: twelve deterministic prerequisites, all must pass, re-evaluated per mutation | Plan section 17: "a single environment variable must not be sufficient" | The gate only gains checks over time; removing checks requires a decision entry |
| D11 | Website stays FastAPI + server-rendered templates + minimal JS + locally bundled assets | Plan section 18 and the website spec mandate preserving this design absent measured need | SPA/framework swap requires a documented measured-justification entry |
| D12 | Website binds loopback only; `web_host` validated at config load | Plan section 18 / website spec: no public hosting, tunnels, or LAN access | Change requires an owner decision + security review |
| D13 | Documentation split: `architecture.md` (app), `website.md` (site contract), `capability_matrix.md` (facts/assumptions/pending), `decision_log.md` (this file), `build_status.md` (ledger) | Prompt 1 requires the four docs; the website contract is large enough to stand alone for review | Merge/split freely; content travels |
| D14 | Work happens on the local `codex/main` branch; local commits only — no remote, no push, no merge in M0 | Repository has no remote; Prompt 1 prohibits push/merge/deploy | Owner may add a remote later (separate decision) |
| D15 | LM Studio endpoint existence was probed read-only (model list, invalid-payload 4xx); no inference executed, no settings changed | Prompt 1 boundary: no global LM Studio settings changes; M2 performs the functional capability tests | n/a (observation) |
