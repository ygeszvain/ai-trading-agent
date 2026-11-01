# Security policy

This is experimental research software. No release is certified for live trading,
real account data, public hosting, or unattended financial operation. The current
financial authority is LIVE_NOT_AUTHORIZED; approved live capital is zero.

## Report a vulnerability

Use the repository's private GitHub vulnerability reporting flow if the
[security reporting page](https://github.com/ygeszvain/ai-trading-agent/security/advisories/new)
offers it. Private reporting availability depends on repository settings. If it
is unavailable, open a minimal issue asking the maintainer for a private channel;
do not include exploit instructions, credentials, account data, or sensitive logs.
No private email address or response-time guarantee is published.

Include affected commit, impact, and a reproduction using fictional inputs in the
private report. Never demonstrate a vulnerability by placing or canceling a real
order, accessing another account, moving money, or exposing a service.

## Local handling

- Keep `.env`, `.data`, datasets, databases, reports, backups, and owner-auth files
  out of Git. Inspect staged changes before committing.
- Keep broker authorization out of coding and research environments. The model
  must not receive financial write tools or authority to change policy.
- Bind the website and disposable database to loopback. The supplied database
  uses development trust authentication and must contain synthetic data only.
- Treat source documents and model output as untrusted text. Preserve unknown,
  stale, and unreconciled state rather than representing it as verified.
- If a credential leaks, revoke or rotate it through its provider. Deleting a
  file or rewriting Git history alone does not revoke a credential.

The publication check is a bounded source/history review, not a full security
audit. See [publication status](docs/publication_status.md) for checks and gaps.
