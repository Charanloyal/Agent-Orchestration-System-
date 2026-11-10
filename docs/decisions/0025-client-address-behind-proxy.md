# 0025: Client address for rate limits behind Render's proxy

- **Status:** Accepted
- **Date:** 2026-11-10
- **Requirements:** ADR 0016 (rate limits), ADR 0018 (production image), ADR 0021 (access
  requests); finding G3 (P1); threat model T15, T18

## Context

The login limit (`AOS_RATE_LOGIN_PER_IP_5MIN`) and the access-request limit
(`AOS_RATE_ACCESS_REQUEST_PER_IP_HOUR`) are keyed on the client address. The image started
uvicorn with `--proxy-headers --forwarded-allow-ips '*'`, which replaces the socket peer with
the **leftmost** `X-Forwarded-For` entry. The client writes that entry, so sending a new value
with each request reset both limits.

Render documents that Cloudflare fronts its services (DDoS protection) and that requests reach
the service through its proxy, but it does not publish exactly which header carries the client
address or how many proxies append to `X-Forwarded-For`. Standard proxies **append** the
address that connected to them, so the entries on the right are written by trusted proxies and
everything on the left may be forged.

## Decision

1. Uvicorn no longer interprets forwarded headers (`--no-proxy-headers`; `proxy_headers=False`
   in `app.serve`). The application alone decides what to trust.
2. A setting, `AOS_TRUSTED_PROXY_HOPS` (0–5, default 0), says how many proxies in front of the
   app append to `X-Forwarded-For`:
   - `0` (local, Docker Compose, tests): the socket peer; the header is ignored.
   - `N`: the Nth entry **from the right**. Repeated headers are joined into one list; empty
     entries are skipped; with fewer than N entries the socket peer is used.
3. The Render blueprints set `AOS_TRUSTED_PROXY_HOPS=1` on the web service, and
   `scripts/check_blueprints.py` fails CI if one does not.
4. Addresses are only hashed into rate-limit keys (SHA-256, truncated); they are never logged
   or stored raw. Uvicorn's access log stays off.

## Alternatives considered

- **Keep `--forwarded-allow-ips '*'`.** Trivial bypass of every per-address limit. Rejected.
- **Trust a single-value header such as `CF-Connecting-IP` or `True-Client-IP`.** Safe only if
  the edge always overwrites it, which Render does not document for every request path.
  Rejected until Render documents it; the hop count can be changed without code.
- **Key on the socket peer on Render.** That is Render's proxy, shared by every visitor: one
  person's failed logins would throttle everyone. Rejected.

## Consequences

- Forging the left part of `X-Forwarded-For` no longer changes the key
  (`test_rotating_a_client_supplied_forwarded_for_does_not_change_the_login_key`), different
  clients keep separate keys (`test_the_key_follows_the_address_the_trusted_proxy_appended`),
  and with hops 0 the header is ignored (`test_without_trusted_proxies_the_header_is_ignored`).
- If Render had *more* appending proxies than configured, the key would be a proxy address:
  limits would be shared by many visitors (too strict), never bypassable. If it had *fewer*,
  the key would be client-written again. The deployment check
  ([deploy-render.md](../operations/deploy-render.md), check 12) verifies both on the live
  service, and the value is changed in the Render dashboard if needed.
- Supersedes the "Proxy headers" note in ADR 0018.
