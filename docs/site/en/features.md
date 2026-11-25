---
title: Features
description: Services, tunnels, the backup link, call quality, the speed test, the router over SNMP, TV mode and users.
---
# Features

Everything is set up from **Settings** in the browser and applied at once: nothing to restart, no files to edit.

## Your services

"Is it my internet, or is the bank down?" Add any HTTP(S) or TCP service and it's checked every 30 seconds. When it fails while your connection is healthy, the verdict says it's that service.

For Argentina there are ready-made checks to tick: the tax agency ARCA (Clave Fiscal, e-invoicing WSFEv1, WSAA), Rentas Jujuy, Banco Macro, Banco Nación, Galicia, Santander, BBVA Argentina, Mercado Pago, Payway, plus Google Workspace, Microsoft 365, WhatsApp Web and Zoom.

Each one says exactly what it checks. Some use TCP because their HTTPS can't be checked fairly: ARCA's e-invoicing server uses a TLS setup modern clients reject, and Santander blocks automated clients.

## Devices on your network

"Did the card terminal drop, or the internet?" Add the devices on your network in **Settings → Monitoring → Devices on your network**: the card terminal, the fiscal printer, the camera recorder, the phone system, the Wi-Fi access points.

- Each one is checked every 30 seconds **by ping** or, when the device doesn't answer ping, **by connecting to a port** it listens on: printers 9100, cameras 554 (RTSP) or 80, phone systems 5060.
- If it stops answering **3 times in a row while your router still answers**, the dashboard, the alerts and the report say **it's that device**, not your internet or your ISP: check that it's on, its cable or its Wi-Fi.
- If what fails is your own network (the router doesn't answer), the device isn't blamed.
- They show in the **Services, devices and tunnels** card of the dashboard and on the TV board.
- Here, and only here, private addresses (192.168…, 10…, 172.16…) or local names (`printer.local`) are accepted. Internet addresses go in **Your services**.

![Settings → Monitoring → Devices on your network, with a card terminal, a fiscal printer and the camera recorder](/docs/img/devices-settings.png)

## Opening hours

For a shop, 20 minutes without internet at 3 a.m. isn't the same as at 11 a.m. Set your hours in **Settings → Alerts → Opening hours** (or in the wizard): per weekday, with up to two shifts, such as a split shift with a lunch break.

With hours set:

- **The dashboard** adds "While open: 14 min" to the last 24 hours' summary, and TV mode shows a **While open** figure.
- **The report** adds how long the business was open in the period, how much of that time had problems, and marks each incident "while open" or "while closed".
- **Held alerts** (optional): while closed, nothing reaches you. At opening time you get one summary of what happened, such as "While closed: 2 problems". A problem still going on when you open is alerted as usual.

![Settings → Alerts → Opening hours: two shifts Monday to Friday and Saturday morning](/docs/img/hours-settings.png)

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

### Unstable tunnels

A tunnel can never go "fully" down and still cut calls and transfers: 30-second drops too short to be an outage, or outages that come back every hour or two. isitmyisp counts every drop inside the tunnel, even one that lasts a single measurement:

- **With 3 drops or more and no quiet hour between them**, the tunnel is **unstable**: one incident (not one per drop) and one alert, with the likely cause. It closes after an hour without drops, at the last drop.
- **The likely cause** comes from the same table as above, looking at all the drops together: repeating on a timer with a clean path, **lifetimes or rekey** ("every 2 h"); no pattern with a clean path, **the tunnel's configuration**; the path losing too, **the far site** or **your connection**; a far end that never answers ping, can't tell. If your ISP changed the path to the far site just before, it says so too.
- The tunnels page shows the last 24 hours' drops hour by hour, how many were too short to count as an outage and what to check. On the dashboard and the TV board the tunnel shows in amber, "Unstable", instead of "Up". The report has an "Instability inside the tunnels" section.

## Backup link (failover)

With a dual-WAN router, isitmyisp notices within about a minute when traffic moves to the backup link and when it comes back. It does this by watching which ISP router is first on the path. The dashboard says "on backup", and the report says from when to when the main ISP wasn't carrying the traffic.

![The dashboard while the office runs on the backup link](/docs/img/failover.png)

## Static public IP

If you pay for a fixed public IP, put it in Settings → Your connection. Every 10 minutes isitmyisp asks api.ipify.org for your public IP, and when it isn't yours two times in a row it opens an incident and alerts, with the IP you have now; it closes by itself when yours is back. Left empty (the default), nothing is asked and nothing is said: on most connections the IP changes now and then and that's normal.

## Path changes

Your ISP can move your traffic to another path without you noticing: a different exit, another carrier, a longer way round. Every 10 minutes isitmyisp traces the path (3 rounds of `mtr`) to each internet destination, each tunnel's far end and each of your services, and notices when the ISP changes it. A hop that doesn't answer, or load balancing between routers of the same network, is not a change; a new path needs two traces in a row.

- **When the new path is clearly slower**, it opens an incident and alerts: "Your ISP changed the path: slower now", with the latency before and after (at least +15 ms and +25 %, or 1 point more loss, 15 minutes after the change). It closes when the path goes back or the latency recovers.
- **When any incident opens**, it traces right away what that incident depends on and says what the path shows: the usual path and where it stops (inside your ISP or past it), or that the ISP changed it a few minutes before. That line goes in the alert, on the incidents page and in the report.
- The dashboard lists the changes of the last 7 days with the path before and after, and the report has a "Path changes" section. Only the ones that made something worse (slower, losing packets, or no longer getting there) are shown open and marked on the chart; the rest stay folded under "no effect". A path that goes back and forth without costing anything is load balancing: after the first time it is learned as one path and isn't counted as a change again. Going back and forth is marked unstable only when it hurts.

Paths are compared by network (/24) and organisation, so it needs no ASN database to work, but with one (Settings → Your connection) it names each network.

## Call quality

Would a call sound good right now? An estimated MOS from 1 to 5 (ITU-T G.107 E-model), from the latency, jitter and loss it already measures. If you have a phone system or SIP provider, set its address to measure against it. It's an estimate, not a real call, and the dashboard says so.

## Speed test

**Off by default, on purpose.** It fills your link for a few seconds and uses data, so it ships disabled, explains why, and asks you to accept the risks before turning it on.

![Speed test settings: what it does and why it can be a problem](/docs/img/speed-test-settings.png)

When it's on:

- It runs weekly (Sunday at 3 a.m. by default), daily at the hour you pick, or only when you press "test now". Optionally also at [peak hour](#peak-hour).
- It keeps to a monthly data budget (5 GB by default).
- It never runs on the backup link or over the budget.
- A scheduled test also waits out an incident and a busy link (above 30 % by default). "Test now" runs anyway: you asked for it.
- It measures against speed.cloudflare.com, which sees your public IP, and against any other [engine](#engines) you turn on.
- Your plan is compared with the **best figure** of each test, from whichever engine gave it. A server can only measure less than your line, never more, so a slow far server is never read as your ISP falling short.
- It also measures latency with the link full (bufferbloat) and warns when the result is limited by your Wi-Fi rather than the ISP.
- While it runs, those windows don't count towards the verdict.

### Engines

Each engine measures the path to its own server, so each one tells you something different. Every engine you turn on runs in the same test, one after the other, and the budget is split between them.

| Engine | What it measures | What it shares | Default |
|---|---|---|---|
| **Cloudflare** | Towards the internet: the path to Cloudflare's nearest server. On some ISPs Cloudflare itself is the ceiling (its server, or its peering with that ISP). | Cloudflare sees your public IP. | on, with the test |
| **M-Lab** | The nearest [Measurement Lab](https://www.measurementlab.net/) NDT7 server, the open platform behind Google's speed test, with servers in many more cities. | **M-Lab publishes every test as open data, with your public IP.** It needs its own consent. | **off** |
| **Your own command** | Whatever your tool measures, for example your ISP's own server through Ookla's CLI. | What that tool shares. | **off** |
| **Another machine** | A test run elsewhere, for example on a PC on the cable, sent to isitmyisp. | Nothing more from here. | **off** |
| **Your iperf3 servers** | Inside or outside your ISP: see [below](#inside-and-outside-your-isp). | Each server sees your public IP. | **off** |

Cloudflare's figure is the 90th percentile of the half-second rates after a one-second warm-up, with six streams, as speed.cloudflare.com reports it. If Cloudflare is rate-limiting your IP (HTTP 429), the result says so.

#### M-Lab

Turn it on in **Settings → Your connection → Speed test against your plan**, and tick the second box: M-Lab publishes each test, with your public IP, as open data for research. On a 1000 Mbps fibre where Cloudflare topped out at 490, M-Lab Buenos Aires measured 930.

#### Your own engine

isitmyisp can run a speed test tool you installed and read its JSON. It ships none of them and accepts no licence for you: Ookla's, for example, allows only personal use, so you accept it in your own command. The command is set only in the config file (or the `ISITMYISP_SPEEDTEST_COMMAND` variable), never from the web UI, so an admin page or a forged form can't make it run anything.

```toml
[speedtest]
command = ["speedtest", "-f", "json", "--accept-license", "--accept-gdpr"]
name = "Ookla"         # optional, how it's shown
format = "auto"        # auto | ookla | speedtest-cli | librespeed | iperf3 | json
timeout = 120          # seconds
```

It understands Ookla's CLI (`speedtest -f json`), the Python speedtest-cli (`--json`), librespeed-cli (`--json`), iperf3 (`-J`) and a plain format for your scripts: `{"download_mbps": 930, "upload_mbps": 600, "ping_ms": 2.1, "server": "Name"}`. It runs as an argument list, never through a shell, after the built-in engines, with the same schedule and guards. Its data can't be capped, so it's counted against the budget afterwards. With Docker, mount the tool into the container.

#### From another machine

The machine running isitmyisp is not always the one to measure with: a Raspberry Pi on Wi-Fi, or a CPU that can't keep up with 1 Gbps. Any other machine can send its results. In **Settings → Your connection → Results from another machine**, make a token. Then, from that machine (for example, a cron job on a PC on the cable):

```sh
speedtest -f json | curl -H "Authorization: Bearer <token>" --data-binary @- \
  "http://<isitmyisp>:8080/api/speedtest?name=PC"
```

It takes any format the own engine reads (`?format=` if it can't tell), and `?wireless=1` if that machine is on Wi-Fi. A pushed result shows up even if this machine's own test is off, uses none of the budget, and is limited to 6 a minute. The token is not the Prometheus one; you can make a new one or turn it off at any time.

### Peak hour

Tick **Also test at peak hour** (21:00 by default) for a second test, on the same days, at the hour everyone is online. The dashboard compares it with the usual one: "At peak hour: 450 Mbps, 50% of the usual test's 900 Mbps". Below 80 % it says the line slows down in the evening. On the same engines, that is the ISP's congestion, whatever the engine's own ceiling. It doubles the tests, so each one gets half the budget, and it skips when your own link is busy, like any scheduled test.

### Inside and outside your ISP

Cloudflare alone can't tell a slow access from a slow exit. In **Settings → Your connection → Speed test against your plan** you can add up to three [iperf3](https://iperf.fr/) servers of your own: a VPS, another branch, or a server inside your ISP's network. One per line, as `host[:port]` (5201 by default).

Each server is marked **inside** or **outside** your ISP by its autonomous system (ASN), against your ISP's. An address in the ISP's CGNAT space counts as inside. A LAN or VPN address can't be told apart, so write `inside` or `outside` after it (`10.8.0.1 outside`). Marking by ASN needs the ASN data (**Settings → Your connection → Main ISP and backup link**) or `--asn-online`.

With one server on each side, the dashboard and the report compare the best download of each:

| Result | What it means |
|---|---|
| **The ISP's exit** | Outside is under 60 % of inside, for example 300 Mbps up to the ISP and 40 to the rest of the internet. The bottleneck is its peering or transit, not your access. |
| **The access** | Inside and outside are alike, but even inside the ISP you get under 60 % of your plan. The limit is your access link. |
| **No bottleneck at the exit** | Inside and outside are alike. |

The guards still hold: the data cap per test is shared between the engines and your servers, it doesn't run on the backup link, and a scheduled test still waits out an incident. It needs the `iperf3` program on the machine (the Docker image ships it), and each server sees your public IP.

## The router over SNMP

Every ISP's favourite objection is "you saturated your own link". Connect your router over SNMP (v2c, read-only) and isitmyisp reads the WAN interface usage and CPU every window. That rules out the objection, or tells you they were right. It needs your plan's speeds (**Settings → Your connection → Your contracted plan**) to know when the link is full.

It also reads the broadcast and multicast each router interface receives: a storm on the LAN (a loop between switches) shows up there, next to the CPU. See [loops and broadcast storms](/docs/en/verdict/#loops-and-broadcast-storms).

## TV mode

A board for a screen on the office wall: large type, refreshes by itself, no menus or login. See it in the [demo](/en/isp/tv/).

![The TV board during a problem in the ISP's network](/docs/img/tv.png)

**To put it on a TV**, without typing anything long with the remote:

1. On the TV, open the dashboard's address followed by **/tv**, for example `192.168.1.50:8080/tv`.
2. The TV shows a short code, like **C4R-HN9**.
3. From your phone or computer, in **Settings → Access → TV mode**, type that code and name the screen ("Counter TV").
4. Within a few seconds the TV shows the board, and stays paired: after a power cut or a restart it comes back to the board on its own.

![What the TV shows before it's paired: a short code and the steps](/docs/img/tv-code.png)

![Settings → Access → TV mode: where the code is typed](/docs/img/tv-settings.png)

For the TV to reach the dashboard, the dashboard has to be reachable from your network, which is what the installer does by default. If you installed it with `--local`, run it again without that option (see [Install](install.md)); your data is kept.

The code expires after 10 minutes and works once. **Settings → Access → TV mode** lists the paired screens and can unpair any of them. If you'd rather paste a link, there's also a secret, revocable **direct link**.

It has two views:

- **Board** (default): the verdict and three figures (the [network check](/docs/en/doctor/) grade with its first problem, or 24-hour availability until the check has run; time without outages or with problems; latency), availability over the last 30 days day by day, the last 24 hours beside the latest events and call quality, the latest speed test against your plan (when it is on), every measured destination and your services, devices and tunnels. Each block shows only when it has data. Whatever is down is named at the top in red, destinations losing packets are marked in red, and long lists rotate on every refresh (what's down or unstable stays put). A [path change](#path-changes) that's still making things worse goes on top in one line when nothing worse is going on; during an outage it moves to the foot of the latest events. It fits any screen from 720p to 4K with no scrollbars.
- **Simple** (`?layout=simple`): just the verdict, for a shop counter. [See it in the demo](/en/isp/tv/simple/).

![The simple TV view](/docs/img/tv-simple.png)

## Users

- **Admin:** changes settings, users and alerts.
- **Viewer:** sees the dashboard, incidents and reports, and changes nothing but their own password.

Admins invite people with one-time links that expire in 48 hours, reset passwords and can disable an account, which ends its sessions at once.

## Metrics and API

| Path | What |
|---|---|
| `/metrics` | Prometheus, with a token shown in **Settings → Access**. What it exports, a ready-made Grafana dashboard and alert rules are in [`contrib/grafana`](https://github.com/21Enzo17/isitmyisp/tree/main/contrib/grafana) |
| `POST /api/speedtest` | A speed test result from [another machine](#from-another-machine), with its own token |
| `/api/status` | Current state as JSON (when logged in) |
| `/healthz` | Public; only says whether it's alive |
| `/report?since=7d` | The report as HTML |
| `/report.pdf?since=7d` | The report as PDF |
