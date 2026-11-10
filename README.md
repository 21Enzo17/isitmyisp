# isitmyisp

**Is it your Wi-Fi, your router or your ISP?**
A self-hosted connection monitor, built by someone who worked in an ISP's NOC. It finds *where* the problem is and builds the evidence your ISP needs to escalate your ticket.

> 🚧 Early development: monitoring, incidents, the evidence report (HTML/PDF), the dashboard, Prometheus metrics and tunnel mode all work. Not yet battle-tested on many networks.

## Why another monitor?
Most tools either run speedtests, which measure the thing that rarely breaks and eat your data cap, or plot pings without telling you what they mean. isitmyisp reads the network the way a NOC engineer does:

- **It separates real loss from ICMP noise.** Routers often deprioritize replies to themselves, so `mtr` shows "loss" on a middle hop while traffic through it is fine. isitmyisp only counts loss that persists to the destination.
- **It doesn't trust ICMP alone.** For each destination it also times TCP handshakes to port 443, and it times real DNS queries to your resolvers. ICMP loss with clean TCP is deprioritization, not a problem.
- **It doesn't cry wolf.** "1 packet lost out of 50" is not 2% loss, it's noise. Loss only counts when it's statistically significant (95% Wilson interval), latency is judged against each target's own baseline, and incidents need consecutive bad windows to open.
- **It blames the right segment,** using address types and AS numbers, not hop positions: your home (including a second router if you have double NAT), your ISP's access network, your ISP's backbone, or a single remote destination.
- **It detects CGNAT, double NAT and IPv6** and explains what that means for you.
- **Tunnel mode:** did your IPsec/L2TP/WireGuard tunnel drop because of its configuration or because of the path? It measures outside and inside the tunnel at the same time, and spots drops that repeat on a schedule (the fingerprint of mismatched rekey lifetimes).

```
$ isitmyisp discover
   1. [home]   192.168.1.1        0.0%     1.6 ms  ok
   2. [ISP]    181.89.4.100       0.0%     4.2 ms  ok  AS7303 Telecom Argentina S.A.
   3. [ISP]    181.96.60.162      0.0%    29.6 ms  ok  AS7303 Telecom Argentina S.A.
   4. [ISP]    ???              100.0%     0.0 ms  no reply
   5. [ISP]    181.89.51.39      40.0%    28.9 ms  ignored (ICMP deprioritized)  AS7303 Telecom Argentina S.A.
   6. [ISP]    181.13.127.246     0.0%    34.1 ms  ok  AS7303 Telecom Argentina S.A.
   7. [beyond] 1.1.1.1            0.0%    29.2 ms  ok  AS13335 Cloudflare, Inc.

  Destination reached with 0.0% loss: the path is fine. Loss on intermediate hops is ICMP handling, not real loss.
```

## Quick start (Docker, recommended)
```bash
docker build -t isitmyisp .
docker run --rm --net=host --cap-add=NET_RAW -v isitmyisp:/data isitmyisp update-asn   # once, optional
docker run --rm --net=host --cap-add=NET_RAW -v isitmyisp:/data \
  -v /run/systemd/resolve:/run/systemd/resolve:ro isitmyisp status

# keep it running, then build the report for your ISP
docker run -d --name isitmyisp --restart unless-stopped --net=host --cap-add=NET_RAW \
  -e TZ=America/Argentina/Buenos_Aires -v isitmyisp:/data \
  -v /run/systemd/resolve:/run/systemd/resolve:ro isitmyisp monitor
docker exec isitmyisp isitmyisp report --since 7d -o /data/report.html
```
Set `TZ` to your time zone so the report shows local times. While `monitor` runs, the web UI is on **http://127.0.0.1:8080** (local only by default; `--web 0.0.0.0:8080` exposes it on your LAN, `--web off` disables it). On first start the logs print a **one-time setup token**: open the link, create your admin account, and configure everything from the browser.

The image is ~330 MB, mostly because of the PDF engine (WeasyPrint + Pango).
`--net=host` is required to see your real gateway and path. The `/run/systemd/resolve` mount is optional: it lets the container see your real DNS servers on systemd-resolved hosts. Without it, your router is assumed to be your resolver.

## Without Docker
Needs Linux, `fping` (recommended) or iputils `ping`, and `mtr`. No root. The measuring core has no Python dependencies; the web UI and PDF are extras.
```bash
pip install -e .            # CLI only
pip install -e '.[web,pdf]' # + web UI and PDF
isitmyisp discover          # gateway, ISP, DNS, CGNAT, IPv6, path segments
isitmyisp status -s 30      # measure 30 s and get a verdict
isitmyisp mtr 8.8.8.8       # mtr with real loss vs ICMP noise
isitmyisp monitor           # measure continuously, open/close incidents, capture mtr evidence
isitmyisp report --since 7d # self-contained HTML evidence report
isitmyisp report --pdf      # PDF (pip install 'isitmyisp[pdf]')
isitmyisp web               # dashboard + /metrics from an existing database
isitmyisp --lang es status  # Spanish output
```

## Privacy: every external connection, listed
isitmyisp is meant to run on your network for months. By default it **never sends your data or your path's IPs to any third party.**

| Connection | When | What it sends | Default |
|---|---|---|---|
| ICMP to your gateway, your ISP's first hop, 1.1.1.1, 8.8.8.8, 9.9.9.9 | always | ICMP echo (64 bytes) | on |
| TCP handshake to 1.1.1.1, 8.8.8.8, 9.9.9.9 port 443 | always | SYN, then closes (no data, no TLS) | on |
| DNS queries to your own resolvers | always | A queries for www.google.com, www.cloudflare.com, www.wikipedia.org | on |
| `mtr` to 1.1.1.1 | on discovery and incidents | ICMP probes | on |
| iptoasn.com | only when you run `update-asn` | one HTTPS download of the public dataset (no per-IP queries) | manual |
| Team Cymru whois | only with `--asn-online` | the public IPs of your path | **off** |
| api.ipify.org | only with `--public-ip` | an HTTPS request (reveals your public IP to them) | **off** |

Bandwidth: about 1.3 GB/month at the default `monitor` settings (one ping every 2 s to 5–6 targets).

## Web UI and security
Dashboard, incidents, tunnels, reports and **settings** (anchors, intervals, language, tunnels, access) are all in the browser and applied live: no restart, no config files to edit. Everything works without JavaScript.

Authentication is built on audited libraries, not hand-rolled crypto:

| | |
|---|---|
| **Accounts** | Flask-Login sessions, **Argon2id** password hashes (argon2-cffi), login rate limit (Flask-Limiter) |
| **First admin** | Created with a one-time setup token printed in the logs, so nobody on your LAN can claim the instance first |
| **CSRF** | Token on every form (Flask-WTF) plus a same-origin `Origin` check |
| **Headers** | Strict CSP (no scripts at all), `X-Frame-Options: DENY`, `HttpOnly` + `SameSite` cookies (`ISITMYISP_SECURE_COOKIES=1` behind HTTPS) |
| **Server** | Waitress (production WSGI), untrusted `X-Forwarded-*` headers stripped |

Three authentication modes, chosen in Settings → Access:
- **local** (default): accounts with passwords.
- **proxy**: trust a user header (`Remote-User`) from **Authelia, Authentik, oauth2-proxy or Tailscale**, only from the proxy addresses you list. You get SSO, 2FA and passkeys from your proxy. The UI refuses to switch to this mode unless your current request really comes through the proxy, so you can't lock yourself out.
- **none**: only allowed while the UI listens on localhost, and settings become read-only.

Locked out anyway? Recover from the console:
```bash
docker exec -it isitmyisp isitmyisp admin auth-mode local
docker exec -it isitmyisp isitmyisp admin reset-password <user>
docker exec -it isitmyisp isitmyisp admin setup-token
```
Prometheus scrapes `/metrics` with a bearer token shown in Settings (`authorization: { credentials: <token> }`). `/healthz` is public and only returns `{"ok": true|false}`.

## Dashboard, metrics and API
| Path | What |
|---|---|
| `/` | Current verdict, active incident, last 24 h timeline, tunnels, targets. Refreshes every 30 s, no JavaScript |
| `/report?since=7d&lang=es` | Evidence report (HTML) |
| `/report.pdf?since=7d` | Evidence report (PDF) |
| `/metrics` | Prometheus: `isitmyisp_loss_ratio`, `isitmyisp_rtt_median_ms`, `isitmyisp_verdict`, `isitmyisp_incident_active`, `isitmyisp_incidents_total` |
| `/api/status` | Current state as JSON (login or proxy auth) |
| `/healthz` | Public liveness check, no details |

## Tunnel mode
Add tunnels in **Settings → Tunnels**. If you prefer configuration as code, a `config.toml` in the data directory (`/data` in Docker) or `--config` takes precedence, and the UI shows those tunnels read-only:
```toml
[[tunnel]]
name = "branch-office"
underlay = "203.0.113.10"   # the far end's PUBLIC address (outside the tunnel)
overlay = "10.10.0.1"       # an address on the far side reached THROUGH the tunnel
type = "ipsec-l2tp"         # ipsec-l2tp | ipsec | wireguard | openvpn | other
```
| Through the tunnel | Outside the tunnel | Verdict |
|---|---|---|
| fine | — | up |
| failing | clean | **tunnel configuration**: DPD, IKE/IPsec lifetimes and rekey, NAT-T, MTU/MSS |
| failing | losing too, your internet fine | **the far site or the path to it** |
| failing | losing too, your internet bad | **your connection** |
| failing | the far end never answers ping | can't tell (it filters ICMP) |

If configuration drops repeat at a regular interval, the report says so: that's almost always mismatched lifetimes or rekey timers between both ends.

## The evidence report
`isitmyisp report` writes one self-contained HTML file: no JavaScript and no external assets. It has two readers in mind:
- **You:** a plain-language summary ("3 incidents, 1 h 6 min in total; 2 were inside your ISP's network"), a timeline and where each problem was.
- **Your ISP's support and NOC:** a ready-to-paste message listing only the incidents inside their network, with the hop and AS where loss starts, plus every mtr capture and the methodology.

To try it without waiting for real problems, generate a clearly synthetic dataset: `python3 scripts/demo_data.py /tmp/demo.db && isitmyisp report --db /tmp/demo.db --since 1d`.

## How the verdict works
1. **Home:** loss or abnormal latency to any of your own routers means the problem is on your side. If you're on Wi-Fi, you'll be told so.
2. **Every destination affected:** the problem is in your ISP. If its first hop is also affected, it's the access network; otherwise it's the backbone or its upstream.
3. **Only some destinations:** it's not your ISP.
4. **Everything fine except DNS:** your resolver.

ICMP and TCP must agree before blaming anyone, and nothing is blamed on a handful of lost packets.

## Roadmap
- [x] Probes (fping/ping, TCP 443, DNS), discovery (gateway, ISP first hop, DNS, CGNAT, double NAT, IPv6, offline ASN), CLI verdicts (EN/ES)
- [x] Statistical significance, per-target baselines, hysteresis, re-discovery when the route changes
- [x] Incidents with hysteresis and automatic mtr capture stored as evidence
- [x] HTML evidence report (EN/ES): plain-language summary, timeline, incidents, message for your ISP, mtr appendix, methodology
- [x] Tunnel mode: path vs configuration, periodic drop (rekey) detection
- [x] Dashboard, Prometheus `/metrics`, `/api/status`, PDF export
- [x] CI workflow: tests on Python 3.10–3.13, multi-arch image (amd64/arm64) to GHCR
- [x] Web UI with settings applied live, local/proxy/none authentication, console recovery
- [ ] MTU/MSS probing through tunnels, alerts (Telegram/Discord), Wi-Fi signal (`iw`)

## License
MIT
