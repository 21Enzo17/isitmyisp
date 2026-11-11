---
title: Features
description: Services, tunnels, the backup link, call quality, the speed test, the router over SNMP, TV mode and users.
---
# Features

Everything is set up from **Settings** in the browser and applied at once: nothing to restart, no files to edit.

## Your services

"Is it my internet, or is the bank down?" Add any HTTP(S) or TCP service and it's checked every 30 seconds. When it fails while your connection is healthy, the verdict says it's that service.

For Argentina there are ready-made checks to tick: the tax agency ARCA (Clave Fiscal, e-invoicing WSFEv1, WSAA), Rentas Jujuy, Banco Macro, Banco Nación, Galicia, Santander, Mercado Pago, Payway, plus Google Workspace, Microsoft 365, WhatsApp Web and Zoom.

Each one says exactly what it checks. Some use TCP because their HTTPS can't be checked fairly: ARCA's e-invoicing server uses a TLS setup modern clients reject, and Santander blocks automated clients.

## Opening hours

For a shop, 20 minutes without internet at 3 a.m. isn't the same as at 11 a.m. Set your hours in **Settings → Opening hours** (or in the wizard): per weekday, with up to two shifts, such as a split shift with a lunch break.

With hours set:

- **The dashboard** adds "While open: 14 min" to the last 24 hours' summary, and TV mode shows a **While open** figure.
- **The report** adds how long the business was open in the period, how much of that time had problems, and marks each incident "while open" or "while closed".
- **Held alerts** (optional): while closed, nothing reaches you. At opening time you get one summary of what happened, such as "While closed: 2 problems". A problem still going on when you open is alerted as usual.

For a shift past midnight, enter it in two parts: until 24:00, and from 00:00 the next day. Hours use the time zone of the machine running isitmyisp.

## VPN tunnels

Did the branch tunnel drop because of its configuration or because of the path? isitmyisp measures outside and inside the tunnel at once:

- **Outside** (`underlay`): the far end's public address.
- **Inside** (`overlay`): an address on the far side, reached through the tunnel.

| Through the tunnel | Outside | Verdict |
|---|---|---|
| fine | — | up |
| failing | clean | **tunnel configuration**: DPD, IKE/IPsec lifetimes and rekey, NAT-T, MTU/MSS |
| failing | losing too, your internet fine | **the far site or the path to it** |
| failing | losing too, your internet bad | **your connection** |
| failing | the far end never answers ping | can't tell (it filters ICMP) |

When configuration drops repeat at a regular interval, the report flags it: that's almost always mismatched rekey timers between both ends.

## Backup link (failover)

With a dual-WAN router, isitmyisp notices within about a minute when traffic moves to the backup link and when it comes back. It does this by watching which ISP router is first on the path. The dashboard says "on backup", and the report says from when to when the main ISP wasn't carrying the traffic.

![The dashboard while the office runs on the backup link](/docs/img/failover.png)

## Call quality

Would a call sound good right now? An estimated MOS from 1 to 5 (ITU-T G.107 E-model), from the latency, jitter and loss it already measures. If you have a phone system or SIP provider, set its address to measure against it. It's an estimate, not a real call, and the dashboard says so.

## Speed test

**Off by default, on purpose.** It fills your link for a few seconds and uses data, so it ships disabled, explains why, and asks you to accept the risks before turning it on.

![Speed test settings: what it does and why it can be a problem](/docs/img/speed-test-settings.png)

When it's on:

- It runs weekly (Sunday at 3 a.m. by default) or when you press "test now".
- It keeps to a monthly data budget (5 GB by default).
- It never runs on the backup link, during an incident or while the link is busy (above 30 % by default).
- It measures against speed.cloudflare.com, which sees your public IP.
- It also measures latency with the link full (bufferbloat) and warns when the result is limited by your Wi-Fi rather than the ISP.
- While it runs, those windows don't count towards the verdict.

## The router over SNMP

Every ISP's favourite objection is "you saturated your own link". Connect your router over SNMP (v2c, read-only) and isitmyisp reads the WAN interface usage and CPU every window. That rules out the objection, or tells you they were right. It needs your plan's speeds to know when the link is full.

## TV mode

A board for a screen on the office wall: large type, refreshes by itself, no menus or login. It opens with a link you create (and can revoke) in **Settings → TV mode**. It has two views:

- **Board** (default): the path, calls, the link, the 24-hour timeline, every destination, services, tunnels and recent incidents. Whatever is down is named at the top in red, and long lists rotate on every refresh.
- **Simple** (`?layout=simple`): just the verdict, for a shop counter.

## Users

- **Admin:** changes settings, users and alerts.
- **Viewer:** sees the dashboard, incidents and reports, and changes nothing but their own password.

Admins invite people with one-time links that expire in 48 hours, reset passwords and can disable an account, which ends its sessions at once.

## Metrics and API

| Path | What |
|---|---|
| `/metrics` | Prometheus, with a token shown in Settings |
| `/api/status` | Current state as JSON (when logged in) |
| `/healthz` | Public; only says whether it's alive |
| `/report?since=7d` | The report as HTML |
| `/report.pdf?since=7d` | The report as PDF |
