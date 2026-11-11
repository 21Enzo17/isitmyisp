---
title: Privacy
description: Every external connection isitmyisp makes, when, and what it sends. No cloud, no telemetry.
---
# Privacy

isitmyisp is meant to run on your network for months. By default it **never sends your data or your path's IPs to any third party**. No cloud, no external accounts, no telemetry: everything stays on the machine it runs on.

## Every external connection

| Connection | When | What it sends | Default |
|---|---|---|---|
| ICMP to your router, the ISP's first hop, 1.1.1.1, 8.8.8.8 and 9.9.9.9 | always | ping (64 bytes) | on |
| One TTL-limited ping towards 1.1.1.1 | once per window | a ping that expires at the ISP's first router (detects the backup link) | on |
| TCP to 1.1.1.1, 8.8.8.8 and 9.9.9.9, port 443 | always | SYN, then closes (no data, no TLS) | on |
| DNS queries to your own resolvers | always | A queries for www.google.com, www.cloudflare.com and www.wikipedia.org | on |
| `mtr` to 1.1.1.1 | on path discovery and incidents | ICMP probes | on |
| iptoasn.com | only when you press the button in Settings or run `update-asn` | one HTTPS download of the public dataset (no per-IP queries) | manual |
| Team Cymru whois | only with `--asn-online` | the public IPs of your path | **off** |
| api.ipify.org | only with `--public-ip` | one HTTPS request (reveals your public IP to them) | **off** |
| Your services | only the ones you add | an HTTP GET (or TCP connect) every 30 s | **off** |
| speed.cloudflare.com | only if you turn on the speed test | ~15 s of downloads and uploads; Cloudflare sees your public IP | **off** |
| Your router over SNMP | only if you connect it | reads of the WAN counters and CPU | **off** |
| Telegram, your SMTP server or your webhook | only if you enable alerts | the alert text | **off** |

**Data use:** about 1.3 GB a month at the default settings.

## What it keeps, and for how long

- Per-destination measurements: **35 days**, enough for a monthly report.
- Per-window verdicts, incidents and their evidence: **about 13 months**.
- Older data is deleted automatically every hour.
- Everything lives in the Docker volume `isitmyisp` (or `~/.local/share/isitmyisp` without Docker). Delete it and nothing is left anywhere.

## The demo

The [public demo](/en/isp/) is static pages generated from made-up data. It measures nothing, has no accounts and stores nothing you do.
