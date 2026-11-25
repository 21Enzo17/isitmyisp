# Changelog

Versions follow [semantic versioning](https://semver.org). Each release has a Docker image
(`21enzo03/isitmyisp:<version>` on Docker Hub, amd64 and arm64) and a git tag `v<version>`.

## [Unreleased]

### Fixed
- **A Cloudflare error no longer hides the other engines.** When Cloudflare refused the test (for
  example HTTP 429) but M-Lab, iperf3 or your own command measured, the whole test showed as failed:
  the dashboard printed only the error, and `/metrics`, the peak-hour comparison and the TV board left
  it out. Now the test counts with what did measure, and Cloudflare's row in the table says why it
  has no figure.

## [0.7.0] - 2026-11-25

### Added
- **More in `/metrics`**: jitter, call quality (MOS), time spent in incidents (for availability),
  route changes, the latest speed test (with bufferbloat), the router's link over SNMP and the
  check-up grade. The speed is the test's best figure, as on the dashboard, with each engine's own
  (Cloudflare, M-Lab, your own command, another machine, iperf3) and the peak-hour test against the
  usual one. Nothing is exported as a zero when it isn't set up.
- **Grafana dashboard** in `contrib/grafana`, ready to import, with the scrape config and optional
  alert rules.
- **M-Lab as a second speed test engine** (#115): the nearest Measurement Lab NDT7 server (the open
  platform behind Google's speed test), picked by round trip among the ones M-Lab offers. Off by
  default with its own consent: M-Lab publishes every test, with your public IP, as open data. On a
  1000 Mbps fibre where Cloudflare topped out at 490, M-Lab Buenos Aires measured 930.
- **Your own speed test engine** (#115): set `[speedtest] command` in the config file (or
  `ISITMYISP_SPEEDTEST_COMMAND`) to run a tool you installed, such as Ookla's CLI (`speedtest -f json`),
  the Python speedtest-cli (`--json`), librespeed-cli (`--json`), iperf3 (`-J`) or a script printing
  `{"download_mbps": …, "upload_mbps": …}`. The output format is detected. It runs after the built-in
  engines, on the same schedule and budget, and its result joins the comparison with the plan.
  isitmyisp ships none of these tools and accepts no licence for you. The command can't be set from
  the web UI, so an admin page or a forged form can't make it run anything.
- **Speed test results from another machine** (#115): `POST /api/speedtest` takes the JSON output of
  any tool the own engine reads (`speedtest -f json | curl -H "Authorization: Bearer …" --data-binary @- …`),
  so the PC on the cable can measure and isitmyisp shows it with the rest. Off until an admin makes a
  token in Settings → Connection (its own token, not the Prometheus one; new token and off buttons).
  Pushed tests use none of the budget, and are rate limited.

- **Peak-hour speed test** (#115): an optional second scheduled test at the hour everyone is online
  (21:00 by default), on the same days as the usual one. The dashboard compares the two ("at peak
  hour: 450 Mbps, 50% of the usual test's 900") and says when the line slows down in the evening.
  On the same engines that is the ISP's congestion, whatever the engine's own ceiling. It doubles
  the tests, so each gets half the budget, and it keeps the usual guards (busy link, incident, backup).

### Changed
- **Docs**: the speed test page says what each engine measures and what it shares (Cloudflare,
  M-Lab, your own command, another machine, iperf3), and the privacy table lists M-Lab and the own command.
- **The plan is compared with each test's best figure**, from whichever engine or server gave it
  (Cloudflare, M-Lab, your iperf3 servers), on the dashboard, the report and the monthly summary. A
  server can only measure less than your line, never more, so a slow far server no longer reads as
  your ISP falling short. The dashboard says which server the figure came from.
- The TV board's speed meters show that best figure too, as the dashboard does.
- **Cloudflare's speed test fills a fast line better** (#115): 6 streams instead of 4, 50 MB download
  and 20 MB upload requests (fewer TCP slow starts), and the figure is the 90th percentile of the
  half-second rates after the warm-up, as speed.cloudflare.com reports it, not the mean, which Wi-Fi
  stalls pull down. The upload is now counted as it goes, not per request. When Cloudflare
  rate-limits your IP (HTTP 429) the test says so and ends at once instead of waiting out the clock.

### Fixed
- **No more blind spot every 15 minutes**: the periodic re-discovery ran with the probes stopped, so
  about 40 s of every 15 minutes (~5% of the time) went unmeasured and the status strip looked dashed.
  It now runs beside the probes, and the session is only rebuilt when something it measures changed.
- **"Healthy" next to 22% loss, explained**: when a window is healthy but ping lost packets, the
  chart tooltip and the data table now say why: only ping lost (TCP connections to the same
  destinations were fine), or too little loss to be a fault.
- **Chart page**: the data table no longer sits flush against the chart card.

## [0.6.2] - 2026-11-20

### Changed
- **Dashboard order**: where the problem is and what to do (with the button for your ISP's report)
  now come right after the verdict and the numbers. On a phone they were near the bottom (#107).
- **When the monitor stops reporting** the pill says "No new data" and the numbers and the 24 h chart
  are dimmed, with a line saying when they were last measured. "No outages for" stops growing while
  nothing is measured (#107).
- **One "Check-up" in the menu** with two tabs, "Whole network" and "From this device"; the old
  addresses (`/doctor`, `/check`) still work (#107).
- **Red means the ISP only where it says so**: the verdict, the charts and their legend keep the ISP's
  red; errors, badges, bad changes and down tunnels use their own (#107).
- **Incidents on a phone** are cards instead of a table that scrolled sideways, and the report's mtr
  tables scroll inside their own box on screen and print whole (#107, #108, #110).
- **Clearer texts**: service failures say the cause in words ("connection dropped"), dates in
  sentences read one way ("at 11:34" today, "Thu 19 Nov, 17:02" another day), Check-up hides counts of
  zero and grades only the whole-network checks, repeated failures of the same service, device or
  tunnel fold into one row in Incidents (×N, time added up), and the availability change is in
  percentage points with a real minus sign (#106).
- The availability sparkline follows the number: green only at 99.5 % or more, amber from 98 %, red
  below (#108).

### Fixed
- The dashboard no longer shows a change of "+0 ms" (or "+0.0 pp") under latency and availability:
  a change that rounds to zero is left out (#104).
- **Bad inputs no longer give an error 500**: plan speeds that aren't numbers, `/chart?from=nan`, a
  huge `?k` and `/check?id=` out of range (#105).
- Validation and delivery errors show in the page's language, and a rejected form keeps what you
  typed (#105).
- **Custom report period**: a bad date shows a message, reversed dates are put in order, "until"
  includes that day, and a future or empty period says so. Without a PDF engine the PDF links are
  hidden and the page explains how to print (#105).
- "Only some destinations failed" isn't an outage: it no longer resets "no outages since" nor counts
  as one in the report's summary (#105).
- With sign-in off, `/tv` shows the board directly, and the account menu says "Viewer", not "Admin"
  (#105, #108).
- `?lang=` wins over the saved language everywhere, and the language links keep the page's other
  settings (range, tab) (#105, #108).
- Pages that don't exist (404) or can't be opened that way (405) show a styled page with a way back
  (#108).

## [0.6.1] - 2026-11-20

### Added
- **Static public IP**: if you pay for a fixed IP, set it in Settings → Your connection and you get an
  alert when your connection goes out with another one; it closes when yours is back. Empty (the
  default) means nothing is checked: on most connections the IP changes now and then and that's normal.
  When set, api.ipify.org is asked every 10 minutes.

### Fixed
- **Path changes were too noisy**: load balancing inside the ISP or a CDN (two paths that alternate
  and cost nothing) was shown as a stream of changes, marked "unstable", put on the chart and on the
  TV. Now a path that alternates without effect is learned as one path, and only changes that made
  something worse (slower, losing packets, or no longer getting there) are shown open, marked on the
  chart and shown on the TV; the rest stay folded under "no effect".

## [0.6.0] - 2026-11-19

### Added
- **Path changes**: every 10 minutes isitmyisp traces the path to each internet destination, tunnel
  and service, and notices when your ISP moves your traffic to another one. A change that makes things
  clearly slower opens an incident and alerts ("Your ISP changed the path: slower now") with the
  latency before and after; it closes when the path goes back or the latency recovers. When any
  incident opens, the path is traced right away and the alert, the incidents page and the report say
  where it stops, or that the ISP changed it just before. The dashboard lists the last 7 days' changes
  with before and after, the chart marks them and the report has a section for them (#97).
- **Unstable tunnels**: every drop inside a tunnel counts, even one too short to be an outage. Three
  or more without a quiet hour between them make the tunnel *unstable*: one incident and one alert,
  with the likely cause (lifetimes or rekey when they repeat on a timer, the tunnel's configuration, the
  far site or your connection) and a path change just before, if there was one. It closes after an hour
  without drops. The tunnels page shows the last 24 hours' drops hour by hour; the dashboard and the TV
  board show the tunnel in amber as "Unstable" instead of "Up"; the report has a section for it (#99).

### Changed
- **TV board**: a path change that is still making things worse goes on top only when nothing worse is
  going on; during an outage it is one line at the foot of the latest events. The simple (counter) view
  doesn't show it. What's down or unstable stays put while long lists rotate (#97, #99).

### Fixed
- **`mtr` with no report**: for a name that doesn't resolve, `mtr` exits 0 and prints nothing, which
  killed the thread that stores an incident's path (a traceback in the log, no evidence). It is now a
  plain "no path" like any other `mtr` error.

## [0.5.2] - 2026-11-17

### Fixed
- **Zombie `mtr` processes in Docker**: every path re-discovery (every 15 min) left one `<defunct>`
  process behind, because `mtr` exits without waiting for its helper and the orphan landed on
  isitmyisp as PID 1. isitmyisp now reaps them, and the image runs under `tini` (#94).

### Changed
- The installer and the manual `docker run` cap the container log at 3 files of 10 MB.

## [0.5.1] - 2026-11-17

### Security
- **Open redirect in `?next=`**: `/theme?next=/%09/evil.example` (no login needed) sent the browser
  to another site, because browsers drop tabs and newlines from a URL; a newline gave a 500. The theme
  switch and the login now accept only a path on this site (#91).

### Added
- FAQ entries on how the verdict is reached, the container's permissions, the installer and how the
  project is written with AI (#92).

## [0.5.0] - 2026-11-17

### Added
- **The TV board shows more at a glance**: the doctor's network grade (in place of the 24 h
  availability once the doctor has run), 30 days of internet and ISP availability, the last speed
  test against your plan with where the bottleneck is, and call quality. Each block shows only when
  it has data; `?layout=simple` is unchanged (#84).

### Changed
- **Settings in four tabs** (Monitoring, Your connection, Alerts, Access), still without JS. The
  contracted plan has its own card, and switched-off features fold away until you open them (#85).

### Fixed
- A day with measured windows could show as "before monitoring" in the 30-day strip when the first
  window ended just past midnight (#87).
- Without the web extra, the web tests used to skip themselves and a broken install still passed;
  they now fail unless `ISITMYISP_CORE_ONLY=1` says the core-only run is on purpose (#83).

## [0.4.0] - 2026-11-16

### Added
- **Loops and broadcast storms on your LAN** get a verdict of their own: duplicate replies, broadcast
  well above normal, or the router's MAC moving. With the router over SNMP, its broadcast and
  multicast counters too. A `loop` demo scenario (#64).
- **`isitmyisp doctor`**, a check-up of how your network is set up even when nothing is down: CGNAT,
  double NAT, IPv6, DNS speed and hijacking, MTU, router reboots, loops, link speed, NIC errors and
  Wi-Fi. Green, yellow or red with what to do, and an A–F grade next to the list. It also runs once a
  day, has its own dashboard page and goes in the report (#65).
- **Check from this device** (`/check`): measure from a PC or phone in about 15 seconds, crossed with
  what the probe saw in the same minutes. The page loads `/static/check.js`, allowed by its CSP only
  there, with `connect-src https:` to reach the internet destinations (#66).
- **Speed inside and outside the ISP**: up to three iperf3 servers of your own, marked inside or
  outside your ISP by ASN (or by hand), next to Cloudflare. The dashboard and the report say whether
  the bottleneck is your access or the ISP's exit (#68).

### Fixed
- The speed test confirmation said "about 15 seconds" even with iperf3 servers, each of which adds
  about as much.
- Docs and README brought in line with the code: the speed test's incident and busy-link guards
  apply only to scheduled tests, the "Measurement" settings card, BBVA in the presets, and every new
  outgoing connection listed in Privacy (#75).
- The dashboard grid no longer squashes the link, calls and services cards between 761 and 1100 px
  wide (#77).

### Changed
- The sidebar's bottom: the "System active" box is now one quiet status line, and the account,
  language and version live in a menu (#78).

## [0.3.0] - 2026-11-12

### Added
- **The chart, enlarged** (`/chart`, "Enlarge" on the dashboard): drag across it to zoom into that
  stretch and double-click to zoom out, like in Grafana; a range picker with quick ranges (the last
  15 minutes to the last 30 days) and an exact from/to; earlier, later, zoom in and out. Up to 90
  minutes every column is one 30-second window with its exact loss, and a table lists them. The
  dashboard's "Last 24 hours" button opens the same picker.
- **Each monitored destination** (your router, the ISP's first hop, each internet destination, DNS)
  opens its own enlarged chart.
- The dashboard tooltip shows each column's **peak** loss next to its average: a few seconds at 40 %
  no longer look like 0.3 %.
- The public demo has every zoom of its day, and dragging there jumps to the closest one.

### Changed
- "Without outages" shows the last 24 hours as a strip (green, and the colour of whoever was at fault
  in each outage) instead of a line of accumulated healthy hours, which said little and could run
  over a long figure.
- The UI still works with no JavaScript, but it's no longer script-free: the enlarged chart loads
  `/static/chart.js` (drag-to-zoom), allowed by its CSP only on that page and never inline.

## [0.2.3] - 2026-11-12

### Fixed
- With Tailscale's MagicDNS on the machine, the DNS server measured was Tailscale's local forwarder
  (100.100.100.100), not your network's. It's now skipped like systemd-resolved's stub. A resolver on
  the same machine (AdGuard Home, Pi-hole on 127.0.0.1) is measured if it answers. When nothing else
  is found, the router is measured only if it answers DNS: many business routers and firewalls don't,
  and measuring one blamed "your DNS" all the time.

### Added
- **Settings → General → DNS servers:** choose which DNS servers to measure (up to 3, private
  addresses and 127.0.0.1 allowed, for AdGuard Home or Pi-hole). Empty means automatic, and the
  field shows what was found.

## [0.2.2] - 2026-11-12

### Fixed
- `isitmyisp status` crashed (`AttributeError: no attribute 'db'`): it read `--db` without declaring
  it. A test now checks that every command only reads arguments its parser declares.

### Changed
- Removed the old TV board's stylesheet rules (unused since the redesign; nothing looks different).
- `scripts/dockerhub-readme.sh` puts the README on the Docker Hub page; `docs/brand/social-preview.png`
  is the card for links to the repository.

## [0.2.1] - 2026-11-12

Fixes found before announcing it: the verdict missed intermittent outages, and the demo was cut off
on common laptop screens.

### Fixed
- A connection that drops and comes back (bad, good, bad, good…) never opened an incident, so it got
  no alert and no line in the ISP report: it only showed as separate short blips. Three bad windows
  within five minutes now open an **intermittent** incident, which says how many times it dropped
  on the dashboard, the TV board, alerts and the report (and the ISP message), and closes after three
  clean minutes. An outage whose ISP first hop looks affected only in some windows is no longer split
  into separate "backbone" and "access network" incidents, nor kept from opening.
- After a restart, what's normal for each destination's latency was learned again from scratch (and a
  slow spell going on at that moment could be learned as normal). It's now loaded from the last day's
  healthy windows.
- On a 1366 or 1440 px laptop the dashboard's 24-hour card was too narrow and its data table spilled
  over the next card. The chart now takes the whole row below 1800 px, cards stack below 1100 px, and
  the table scrolls inside its card.
- The report shown in the web app had no way back: it now has "Back to the dashboard" and, outside the
  demo, "Download PDF" (neither is printed nor in the files that get attached or saved).

### Added
- The public demo has TV mode (the board and the simple view) and an intermittent outage in its day.
- Docs: TV mode, devices and opening hours with screenshots; how it differs from Uptime Kuma,
  SmokePing and PingPlotter; backing up and moving to another machine; when the monitor doesn't
  start or doesn't see the network; what it doesn't do (IPv4 verdict, small latency rises, Linux only).
- A README in Spanish, and a shorter README in English.

## [0.2.0] - 2026-11-12

Ready to sell: what a small business sees in the first meeting, and the image published for amd64 and
arm64 so nobody has to build it.

### Added
- Opening hours (#34): per weekday with up to two shifts. The dashboard, the TV board and the report
  count the downtime that happened while the business was open, each incident in the report says
  whether it was in or out of hours, and alerts can be held while closed with one summary at
  opening time. A step in the first-run wizard; the public demo has a shop's hours.
- Monthly report by email (#36): on a chosen day and hour, last month's evidence report goes out with a
  plain-language summary in the message and the report attached (PDF in the Docker image, HTML
  otherwise). Uses the alerts' SMTP server, sent once per month across restarts, retried on failure,
  with a "send now" preview.
- Devices on your network (#10): card terminals, printers, camera recorders, phone systems, access
  points, checked by ping or a TCP port every 30 s. When one stops answering while the router still
  does, the dashboard, TV board, alerts and report say it's the device, not the internet. Private
  addresses are accepted only for these. The demo has three, and its card terminal drops once.
- TV mode at the short address /tv: the TV shows a code, an admin types it in Settings, and the screen
  stays paired with its own device cookie (codes expire in 10 minutes and work once; screens can be
  unpaired one by one). The direct secret link remains as an alternative.
- A light/dark button that works without JavaScript, and a documentation site at /docs (es/en).

### Changed
- The TV board follows the new design: the verdict and three figures on top, the last 24 hours beside
  the latest events, then the destinations as tiles and your services, devices and tunnels. It fits
  any screen from 720p to 1440p without scrolling, shows only events that fit whole, and no longer
  relies on CSS that older TV browsers lack.
- A new design for the dashboard and every page: a sidebar, the verdict beside three figures with
  sparklines and change against the day before, and cards of equal height for the chart, destinations
  and events.
- The evidence report reads in two parts: a summary for the owner first (worked fine, outages, problems
  while open, speed against the plan, comparison with the period before, the outages that hit most,
  devices and services in one line each, and what to do), then the technical annex for the ISP, which
  opens with the ready message. It follows the new design, in HTML and PDF.

### Fixed
- Old closed incidents and their mtr captures are now deleted after about 13 months, as documented.
- The docs builder used an f-string form that needs Python 3.12; it now runs on 3.10 and 3.11 too.
- Stylesheet URLs carry a fingerprint, so a new design is never stuck in a browser cache.

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

[0.7.0]: https://github.com/21Enzo17/isitmyisp/releases/tag/v0.7.0
[0.6.2]: https://github.com/21Enzo17/isitmyisp/releases/tag/v0.6.2
[0.6.1]: https://github.com/21Enzo17/isitmyisp/releases/tag/v0.6.1
[0.6.0]: https://github.com/21Enzo17/isitmyisp/releases/tag/v0.6.0
[0.5.2]: https://github.com/21Enzo17/isitmyisp/releases/tag/v0.5.2
[0.5.1]: https://github.com/21Enzo17/isitmyisp/releases/tag/v0.5.1
[0.5.0]: https://github.com/21Enzo17/isitmyisp/releases/tag/v0.5.0
[0.4.0]: https://github.com/21Enzo17/isitmyisp/releases/tag/v0.4.0
[0.3.0]: https://github.com/21Enzo17/isitmyisp/releases/tag/v0.3.0
[0.2.0]: https://github.com/21Enzo17/isitmyisp/releases/tag/v0.2.0
[0.1.0]: https://github.com/21Enzo17/isitmyisp/releases/tag/v0.1.0
