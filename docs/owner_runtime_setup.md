# Owner-run authentication setup — inactive integration only

The project can run synthetic simulation now. Live trading cannot start from the
delivered configuration. This guide prepares official OAuth/schema discovery in
a separate owner-operated runtime; it does not activate a trading strategy.
Read the [repair report](stabilization_and_auth_readiness.md) and current
[build status](build_status.md) first. No financial-account authentication has
been performed by the coding agent.

## 1. Keep the owner runtime separate

Create a separate **standard, non-admin macOS user named `ai-trading-executor`**
using the operating system's user-management controls. Log in interactively as
that user. Do not run Codex, research inference, or general-purpose agent tools
under that identity. Do not grant the coding user access to its private home or
credential directory. Separate identities have not been created or independently
validated by this implementation; the operator must verify access controls.

This is required by [AGENTS.md](../AGENTS.md): “Keep live broker credentials and
execution privileges out of the coding environment.” The CLI checks the OS
username/effective UID before opening any auth client or browser. There is no
configuration flag to waive the guard. This is a local guard, not a substitute
for deployed OS isolation or independent monitoring.

## 2. Install the reviewed source under that user

From that user's terminal, with Git and uv installed:

```sh
git clone --branch codex/offline-stabilization https://github.com/ygeszvain/ai-trading-agent.git
cd ai-trading-agent
uv sync --locked
uv run trading-agent check-config
```

Verify the reviewed commit locally before authentication. Do not copy an existing
broker token, browser session, `.env`, owner web-auth file or account database into
this checkout. The simulation settings keep live capital zero and live disabled.

## 3. Complete official browser consent privately

```sh
uv run trading-agent owner-auth login --runtime-dir "$HOME/.local/share/ai-trading-agent"
```

The private runtime directory must be outside the checkout, owned by the runtime
user, mode `0700`, with no symlink or group/public-writable ancestor. Credentials
are written exclusively to `oauth.json` mode `0600`. The command opens the
system browser and waits up to five minutes for an exact ephemeral loopback
callback. The owner completes Robinhood's official sign-in/consent and MFA in the
browser; the app never requests these values through chat or terminal prompts.
Select the existing dedicated Agentic/MCP account if the broker asks. If the flow
requires creating/funding an account or changing approvals, stop and review it
rather than treating setup as permission for those actions.

The public metadata advertises `internal`; it is **not verified read-only**.
Robinhood describes read access across accounts, so keep this credential in the
isolated runtime even though the commands here never call trading tools. Review
[Robinhood's official external-agent onboarding](https://robinhood.com/us/en/support/articles/agentic-trading-overview/)
and [trade approval limitations](https://robinhood.com/us/en/support/articles/trading-with-your-agent/).
No account linkage/funding or approval-setting change is part of these commands.

The client checks pinned metadata, issuer, state, PKCE S256, exact redirect and
resource binding. Any metadata drift or unsupported response stops the flow.
Registration and exchange have been verified only with fake transport. Actual
broker acceptance of this public-client/loopback flow remains pending.

## 4. Inspect safe status, then schema discovery

```sh
uv run trading-agent owner-auth status --runtime-dir "$HOME/.local/share/ai-trading-agent"
uv run trading-agent owner-auth discover --runtime-dir "$HOME/.local/share/ai-trading-agent"
```

Status reports presence/expiry and inactive authority without printing the token.
Discovery initializes the official MCP connection and lists tool schemas only;
it does not call a tool, enumerate accounts, request balances or place orders.
An unsupported protocol version stops for review. The complete observed schema
is stored privately as `tools-<hash>.json`. Bounded output includes its hash/count
and field types for recognized read tools, never defaults/enums/account values.
Discovery does not approve the schema for execution or verify an account binding.

Only the sanitized CLI status/schema hash/field-type summary is suitable for
review. Do not upload `oauth.json`, private tool manifests, callback URLs/codes,
headers, account numbers, auth-attempt receipts or browser screenshots. No secret
should be pasted into Codex, model context, GitHub or a support issue.

## 5. Failure, shutdown, and revocation

A private `auth-attempt.json` receipt is created before registration; failures
retain it. No automatic retry, refresh or consent overwrite is implemented. If
registration or exchange is ambiguous, preserve the private receipt and review
broker-side connected-agent state before a new attempt. Do not repeatedly delete
state and retry. A sanitized error class/message is enough for a software report.

Stop commands with Ctrl-C. This client issues no orders, so shutdown does not
cancel or liquidate anything. If access must be revoked, use the current official
Robinhood connected-agent controls/support from the owner's broker app. Exact
revocation behavior, token lifetime and broker-side effect must be observed by
the owner; no undocumented revocation endpoint or guaranteed menu is claimed.
Deleting a local credential file alone does not prove broker revocation.

## 6. What is still required before trading

The next software integration is an exact allowlisted read normalizer based on
the observed schemas, privately verified dedicated-account binding, and safe
persisted reconciliation. Actual execution transport, owner signing/activation,
separate executor and independent monitor operation, broker approval/recovery,
prospective investment evidence and the unsigned pilot fields remain unresolved.
The code still denies actual dispatch after a successful login or discovery.

The USD 500 report is in the [inactive worksheet](pilot500_owner_request.unsigned.json).
No discretionary limits beyond balance and “best algorithm” are recorded owner
preferences, not invented asset/strategy/expiry decisions. The existing limits
remain in simulation; a $500 whole-share fixture produced no trades. There is no
established best algorithm and no demonstrated investable edge.

A separate operational requirement is protected LM Studio access before private
financial evidence is used. The current loopback endpoint answered harmless
anonymous probes. Configure it through owner-reviewed [official authentication
controls](https://lmstudio.ai/docs/developer/core/authentication); this work did
not change global settings or provision model secrets.

**Current financial authority: LIVE_NOT_AUTHORIZED.**
