# Owner-operated Gmail alert verification — no trading activation

Email software and a local TLS delivery sink pass offline checks; actual Gmail
receipt and incident response remain **EXTERNAL_VALIDATION_PENDING**. This guide
is for the approved owner OS account in a private terminal, outside Codex. Do not
paste passwords, MFA codes, app passwords, tokens or private logs into chat.
[AGENTS.md](../AGENTS.md) requires keeping credentials out of the coding environment.
The runtime directory remains outside the checkout, owned by the operator, mode
0700; configuration/consent/journal files require 0600. Same-user permissions do
not constitute isolation from other processes running as that user.

## 1. Review Gmail eligibility and protected storage privately

This adapter uses pinned implicit TLS SMTP `smtp.gmail.com:465`, following
[Google's SMTP documentation](https://developers.google.com/workspace/gmail/imap/imap-smtp). It has no inbox
read access and does not use the Codex Gmail connector. The owner selected Gmail
with the same sender and recipient; private owner-review files retain the exact
address. No personal email address is included in this public guide.

Google recommends Sign in with Google. This adapter currently supports an app
password only, requiring 2-Step Verification and an eligible account; some
organization, security-key-only or Advanced Protection accounts do not offer it.
Check [Google's current app-password instructions](https://support.google.com/accounts/answer/185833)
and [Gmail client guidance](https://support.google.com/mail/answer/7126229).
The owner's eligibility has not been verified. If unavailable, stop this dependent
step and request an OAuth mail-adapter repair here; do not use a normal Gmail
password or weaken account protections. App passwords can grant broader mail
access than sending; protect and revoke this dedicated credential accordingly.

If choosing this supported method, create the dedicated app password privately
through Google. Store it in the runtime user's macOS Keychain. One owner-only
command (replace `OWNER_EMAIL` with your sender) prompts for the secret when `-w`
is last; do not put the secret in an argument, environment variable or shell
history:

```sh
/usr/bin/security add-generic-password -a OWNER_EMAIL -s ai-trading-agent.gmail-smtp -w
```

Alternatively use Keychain Access's New Password Item with that exact service and
account, following [Apple's instructions](https://support.apple.com/en-am/guide/keychain-access/kyca699a9058/mac).
Review Keychain access controls; do not grant every application access or use
`-A`. Codex must not execute credential retrieval or inspect this item. The owner
runtime retrieves it only at dispatch using the exact service/account pair,
keeps it out of the journal/message/output, and fails safely if unavailable.
No broker credential is needed for email.

## 2. Prepare and review one-message consent

From the reviewed `codex/operations-readiness` checkout, owner-run:

```sh
uv sync --locked
uv run trading-agent check-config
uv run trading-agent operations email-prepare --runtime-dir "$HOME/.local/share/ai-trading-agent"
```

This only writes disabled placeholder `email-profile.json` and
`email-consent.unsigned.json`; it sends nothing. Existing consent is preserved,
never silently overwritten. In a private editor set the exact selected sender
and identical recipient, and set profile `enabled` true **only for email testing**.
Do not add credentials to JSON. Archive the original unsigned placeholder under
a unique name, then run `email-prepare` again; it binds a new unsigned proposal to
the exact edited profile hash. Preserve file modes. Do not hand-edit the hash or
reuse consent for a changed profile.

Review the proposed one-hour UTC start/expiry, purpose OWNER_EMAIL_TEST, one
message, up to three definite-negative attempts and acknowledgment deadline.
If the interval has already expired, archive it and regenerate; do not extend
an already approved consent. After explicit review, save a copy as
`email-consent.json` mode 0600 with `approved` true. This owner-file action approves
only the exact bounded email test. It is not financial authorization. No agent
has set it true for you. Exact mail body:

```text
Operational notification; this message grants no trading authority.
Event: OWNER_EMAIL_TEST
Incident reference: <consent hash>
Observed at: <consent start UTC>
Review the protected local incident record and respond through the owner procedure.
Pause is not confirmation of cancellation or liquidation.
No account number, broker response or credential is included.
```

Subject: `[AI Trading Agent] OWNER_EMAIL_TEST`. To/From are the same privately
configured address. Stable Message-ID is derived from scope/run/incident/code;
it does not promise Gmail exactly-once behavior.

## 3. Send once and verify receipt

These commands are **owner-operated external checks**, not offline tests:

```sh
uv run trading-agent operations email-test --runtime-dir "$HOME/.local/share/ai-trading-agent"
uv run trading-agent operations email-status --runtime-dir "$HOME/.local/share/ai-trading-agent"
```

ACCEPTED means SMTP accepted the message, not inbox delivery. Check Gmail privately,
including Spam and any same-sender behavior. The command returns a safe message
hash. Record receipt only after actually seeing it, using that exact hash and a
64-character lowercase SHA-256 reference to a private owner receipt note:

```sh
uv run trading-agent operations email-ack --runtime-dir "$HOME/.local/share/ai-trading-agent" \
  --message-id MESSAGE_HASH --owner-reference PRIVATE_RECEIPT_NOTE_HASH
```

Acknowledge after receipt even if mail consent has since expired. Do not claim
an automatic inbox acknowledgment. UNKNOWN can mean Gmail accepted the message
before the connection broke. Repeating the command will not resend an ambiguous
attempt. Preserve its journal; investigate privately. `email-resolve` with the
same hash arguments records a reviewed failure without deleting it. A new fresh
acknowledged channel test must follow resolution before new-risk email health
can pass. Never delete the journal to get around deduplication or message caps.

## 4. Independent monitor preparation and limitations

A successful test does not deploy a monitor. Archive prior consent and run
`operations email-prepare-monitor --runtime-dir ...` for a disabled
`monitor-profile.json` and an unsigned, separately bounded OPERATIONAL_NOTICE
proposal. The owner must supply exact hashed account scope/run, enable the
monitor deliberately, bind the consent to that profile/run and approve delivery
separately. A test consent cannot send operational notices or cross runs. No
financial account identifier belongs in email configuration.

A future separately operated runtime must atomically publish protected
`runtime-health.json` matching `operations.monitor.Health`: domain RUNTIME_HEALTH,
exact scope/run, executor PID/generation, observed/data/reconciliation/audit UTC
times, healthy/unknown-orders/forbidden-close-exposure flags and envelope expiry.
The production publisher and deployment are **not validated here**. Never forge
healthy timestamps. Missing/invalid/stale/future evidence produces an incident.
The worker can record incidents while email is disabled/unconfigured/expired;
that does not deliver them. Different PIDs do not establish privilege isolation.

After a separate operations review, the owner can run `operations email-worker`
once or with `--continuous` in a separate process. It never starts an executor or
renews financial authority; no service/schedule is installed by setup. It rereads
mail configuration each cycle, remains quiet on unchanged results and stops with
Ctrl-C. The tested minimum is a disposable separate-process failure simulation.
Actual death/network/mail-outage/restart/expired-consent drills, acknowledgment
response, a backup escalation path and an independent stop procedure remain
pending. This machine or network losing power can also prevent email: an
independently hosted dead-man monitor is not implemented or certified.

Revoke the dedicated app password through Google's official controls when no
longer needed. Deleting local configuration alone does not revoke Google access.
Stopping the email worker, receiving mail or acknowledging an incident does not
cancel orders, liquidate holdings, resume trading or authorize activation.

**Current financial authority: LIVE_NOT_AUTHORIZED.**
