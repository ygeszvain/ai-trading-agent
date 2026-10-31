# Capability matrix — M0 environment and integration constraints

Recorded 2026-10-31 by read-only inspection of the target machine and public
documentation. Three classes are kept strictly separate:

- **Fact** — observed on this host at inspection time (versions, running
  services, ports). Facts drift; re-verify before relying on them.
- **Assumption** — a documented engineering choice pending measurement or
  owner confirmation.
- **PENDING (owner-run)** — requires the owner to perform an action Codex is
  not permitted to do; dependent work is blocked until performed.

## 1. Hardware and OS (facts)

| Item | Observed |
| --- | --- |
| Machine | Apple Mac Studio (M5 Ultra), hostname `mac-studio.lan` |
| CPU | Apple M5 Ultra, 36 cores |
| Memory | 96 GiB |
| GPU | Apple M5 Ultra, 80 cores, Metal 4 |
| OS | macOS 27.0 (build 26A425), arm64 |
| Display | Studio Display 5120×2880 |
| Disk (Data volume) | 1.8 TiB total, ~946 GiB available |

## 2. Installed tooling (facts, 2026-10-31)

| Tool | Version / state | Note |
| --- | --- | --- |
| Python (Homebrew default `python3`) | 3.15.2 | Newer release; not the project pin |
| Python 3.13 (Homebrew) | 3.13.2 | **Project pin** (`.python-version`) |
| Python 3.12 (Homebrew) | 3.12.9 | Available |
| Python (system `/usr/bin`) | 3.9.6 | Not used by the project |
| Python (Anaconda) | 3.12.7 | Not used by the project |
| `uv` | 0.13.6 (Homebrew) | Installed during M0 (required by Prompt 1) |
| git | 2.54.0 (Apple Git) | Local repository, no remote configured |
| Node.js (Homebrew node@20) | 20.19.4 | Present; no website build tooling in M0 |
| Docker | 29.7.2 | Running |
| PostgreSQL client (Homebrew) | psql 14.13 | Used to verify the container DB |
| Homebrew PostgreSQL | postgresql@13 (stopped), postgresql@14 (LaunchAgent present, not the trading agent's instance) | Unrelated to this project; recorded to avoid confusion |
| LM Studio (app) | 0.4.21+2 | `/Applications/LM Studio.app`; `lms` CLI present |
| Codex CLI | 0.166.0-alpha.5.1 | Bundled with ChatGPT.app; used for development |

## 3. Local model runtime (facts observed at inspection)

| Item | Observed |
| --- | --- |
| LM Studio server | Running, listening on 127.0.0.1:1234 (process "Bionic") |
| `GET /v1/models` | HTTP 200; models loaded: `phonon-40m-multilingual`, `qwen/qwen3.8-27b`, `qwen3-14b-mlx`, `text-embedding-nomic-embed-text-v1.5` (list changes as the owner loads models) |
| `POST /v1/chat/completions` (invalid payload probe) | HTTP 400 — route exists; no inference executed |
| `GET /v1/responses` (probe) | HTTP 200 — route exists |
| Authentication | Not verified; plan section 9 requires enabling supported API authentication before handling financial data |
| Ollama | Not installed on this host |

**Assumption:** the chat-completions and responses endpoints fully support
the features M2 will use (schema-constrained output, tool use). Route
existence is not functional proof; M2 runs explicit capability tests per
plan section 9 before any model-dependent workflow is enabled.

## 4. Network and ports (facts)

| Port | State at inspection |
| --- | --- |
| 1234 | LM Studio (loopback) |
| 5432 | Docker container `fda-postgres` (postgres:17) — the **dissertation** database; bound 0.0.0.0 (see security observation below); **never targeted by the trading agent** |
| 5433 | Free at inspection; now bound by `trading-agent-postgres` (127.0.0.1 only) |
| 8000 | Free at inspection; reserved for the future website |

## 5. Broker (Robinhood) — PENDING owner-run verification

Public documentation (plan section 2, sources [S1]–[S3], reviewed 2026-10-26)
states: official external-agent MCP endpoint `https://agent.robinhood.com/mcp/trading`;
external agents can read across Robinhood accounts while trading is restricted
to the dedicated account; approvals default on for built-in agents and off for
external MCP accounts (still rolling out); Agent Loops are "coming soon".

**None of this has been verified for this project.** All of the following are
PENDING and block only the dependent work (M4/Prompt 7 onward):

| Pending item | Owner action | Blocks |
| --- | --- | --- |
| Owner broker authorization | Complete the official onboarding/OAuth flow in a separately operated runtime | M4 gateway, shadow mode, all live work |
| Authenticated capability discovery | Run after authorization; record sanitized capability matrix and tool-schema digest | `broker_capabilities_verified` gate check |
| Actual trade-approval behavior | Inspect and record the account's setting | Supervised-live design (M6) |
| Account alias and dedicated account | Owner creates/assigns | All live modes |
| Fractional/order-type compatibility at the requested USD 1,000 scale | Verify through official capabilities | Pilot package (M6/M7) |

M0 ships `robinhood` as an explicitly unavailable adapter; no MCP client
library is installed. Unknown tools remain denied until classified (plan
section 14).

## 6. Data sources (facts)

- No data providers are configured. `config/source_registry.yaml` is empty.
- Paid data budget: USD 0/month; no subscriptions, purchases, or bulk
  downloads are authorized (plan section 8).
- PENDING: owner decision on any provider, budget, and entitlements (plan
  section 24).

## 7. Pilot request (plan section 24 — status table)

Requested initial allocation USD 1,000 (owner-stated, 2026-10-28): recorded.
Active runtime-approved live capital: **USD 0**. Current financial authority:
**LIVE_NOT_AUTHORIZED**. All pilot fields (account, limits, dates, mode,
overnight policy, funding) remain pending owner action; no money moved.

## 8. Security observation (outside this repository's scope)

`fda-postgres` (dissertation work) listens on `0.0.0.0:5432`, i.e. it is
reachable beyond loopback on this host. This does not affect the trading
agent (which uses 127.0.0.1:5433) but is worth the owner's attention for the
dissertation project. No change was made to that container.
