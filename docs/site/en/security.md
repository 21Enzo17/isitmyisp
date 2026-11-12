---
title: Security
description: Accounts, access modes, security headers and how to recover access.
---
# Security

The dashboard holds your network's settings and the evidence of your incidents, so it's protected accordingly. Authentication is built on audited libraries, not hand-rolled crypto.

| | |
|---|---|
| **Accounts** | Flask-Login sessions, **Argon2id** password hashes and a login rate limit |
| **First admin** | Created with a one-time token printed in the log, so nobody on your network can claim the instance before you |
| **CSRF** | A token on every form plus a same-origin check |
| **Headers** | Strict CSP (no inline code, and scripts only on the enlarged chart), `X-Frame-Options: DENY`, `HttpOnly` and `SameSite` cookies |
| **Server** | Waitress, a production WSGI server; `X-Forwarded-*` headers that don't come from a trusted proxy are ignored |

The dashboard works with **no JavaScript**: the charts' hover is pure CSS, and zooming and moving through time are plain links. The one script is optional, `/static/chart.js` on the enlarged chart, for dragging across it to zoom like in Grafana; it builds a link and nothing else. Every other page's security policy forbids every script, and none allows inline code.

## Access modes

Chosen in **Settings → Access**:

- **Local** (default): password accounts, either admin or viewer. See [Users](features.md#users).
- **Proxy:** trusts a user header (`Remote-User`) set by **Authelia, Authentik, oauth2-proxy or Tailscale**, only from the proxy addresses you list. You get SSO, two-factor and passkeys. The dashboard won't switch to this mode unless your own request is coming through the proxy, so you can't lock yourself out.
- **None:** only allowed while the dashboard listens on localhost, and settings become read-only.

## Reaching it from outside your network

Don't publish port 8080 to the internet. To reach it from outside, use a VPN (WireGuard, Tailscale) or a proxy with HTTPS and authentication. Behind HTTPS, add `-e ISITMYISP_SECURE_COOKIES=1` so cookies only travel encrypted.

## Locked out

From the machine's console:

```bash
docker exec -it isitmyisp isitmyisp admin reset-password <user>
docker exec -it isitmyisp isitmyisp admin auth-mode local
docker exec -it isitmyisp isitmyisp admin setup-token
```

## Reporting a security problem

If you find a vulnerability, please don't open a public issue: contact the author privately through [GitHub](https://github.com/21Enzo17).
