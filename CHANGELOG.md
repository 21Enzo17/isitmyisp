# Changelog

Versions follow [semantic versioning](https://semver.org). Each release has a Docker image
(`ghcr.io/21enzo17/isitmyisp:<version>`, amd64 and arm64) and a git tag `v<version>`.

## [Unreleased]

### Changed
- The evidence report reads in two parts: a summary for the owner first (worked fine, outages, problems
  while open, speed against the plan, comparison with the period before, the outages that hit most,
  devices and services in one line each, and what to do), then the technical annex for the ISP, which
  opens with the ready message. Call quality lists the five longest stretches, not all of them.
- The evidence report (HTML and PDF) follows the new design: the dashboard's palette, the new mark,
  the verdict with its colour dot, rounded figure tiles, drawn icons for what the evidence rules
  out, and a neutral note for demo data. Tints are resolved in Python, so the PDF engine needs no
  newer CSS. Screenshots regenerated.

### Added
- Devices on your network (#10): card terminals, printers, camera recorders, phone systems, access
  points, checked by ping or a TCP port every 30 s. When one stops answering while the router still
  does, the dashboard, TV board, alerts and report say it's the device, not the internet. Private
  addresses are accepted only for these. The demo has three, and its card terminal drops once.
- Monthly report by email (#36): on a chosen day and hour, last month's evidence report goes out with a
  plain-language summary in the message and the report attached (PDF in the Docker image, HTML
  otherwise). Uses the alerts' SMTP server, sent once per month across restarts, retried on failure,
  with a "send now" preview.
- Opening hours (#34): per weekday with up to two shifts. The dashboard, the TV board and the report
  count the downtime that happened while the business was open, each incident in the report says
  whether it was in or out of hours, and alerts can be held while closed with one summary at
  opening time. A step in the first-run wizard; the public demo has a shop's hours.

## [0.1.0] - 2026-11-11

The first release: everything needed to tell whether a problem is the Wi-Fi, the router or the ISP,
and to prove it.

### Measuring and verdicts
- Continuous ICMP + TCP probing of the router, the ISP's first hop and several internet anchors, with
  a classifier that needs ICMP and TCP to agree (Wilson intervals, 2-of-2 hysteresis).
- "What we ruled out / what we didn't": router link usage over SNMP to rule out a link full of your own traffic.
- Failover detection: knows when the office runs on the backup link, and for how long.
- Call quality: estimated MOS (ITU-T G.107 E-model) from what is already measured.
- Speed test against the contracted plan, **off by default**, with a monthly data budget.
- Tunnel mode (IPsec, L2TP, WireGuard…): a tunnel problem told apart from an internet one.
- Your services (HTTP/TCP), with ready-made checks for Argentina (ARCA, Rentas Jujuy, banks, payments).

### Evidence
- Incidents with mtr captures, and an HTML/PDF report for the ISP with the evidence and its limits.

### Web
- Dashboard with the path (your network → your ISP → internet), 24 h timeline and per-target history. No JavaScript, strict CSP.
- Local accounts with roles (admin / viewer), invitations, alerts by Telegram, email and webhooks.
- TV mode: a board for a screen on the wall, with rotation and visible alarms.
- First-run wizard: your plan, your services and alerts in a few minutes.
- Demo mode on synthetic data, also published as a static site.

### Install
- One-line installer (`install.sh`) that shows every Docker command before running it, and a Raspberry Pi guide.

[0.1.0]: https://github.com/21Enzo17/isitmyisp/releases/tag/v0.1.0
