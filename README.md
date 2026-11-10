# isitmyisp

**Is it your Wi-Fi, your router or your ISP?**
A self-hosted connection monitor, built by someone who worked in an ISP's NOC. It finds *where* the problem is and builds the evidence your ISP needs to escalate your ticket.

> 🚧 Early development. The CLI works; dashboard, PDF reports, tunnel mode and published images are coming.

## Why another monitor?
Most tools either run speedtests, which measure the thing that rarely breaks and eat your data cap, or plot pings without telling you what they mean. isitmyisp reads the network the way a NOC engineer does:

- **It separates real loss from ICMP noise.** Routers often deprioritize replies to themselves, so `mtr` shows "loss" on a middle hop while traffic through it is fine. isitmyisp only counts loss that persists to the destination.
- **It doesn't trust ICMP alone.** For each destination it also times TCP handshakes to port 443, and it times real DNS queries to your resolvers. ICMP loss with clean TCP is deprioritization, not a problem.
- **It doesn't cry wolf.** "1 packet lost out of 50" is not 2% loss, it's noise. Loss only counts when it's statistically significant (95% Wilson interval), latency is judged against each target's own baseline, and incidents need consecutive bad windows to open.
- **It blames the right segment,** using address types and AS numbers, not hop positions: your home (including a second router if you have double NAT), your ISP's access network, your ISP's backbone, or a single remote destination.
- **It detects CGNAT, double NAT and IPv6** and explains what that means for you.

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
```
`--net=host` is required to see your real gateway and path. The `/run/systemd/resolve` mount is optional: it lets the container see your real DNS servers on systemd-resolved hosts. Without it, your router is assumed to be your resolver.

## Without Docker
Needs Linux, `fping` (recommended) or iputils `ping`, and `mtr`. No root and no Python dependencies.
```bash
pip install -e .
isitmyisp discover          # gateway, ISP, DNS, CGNAT, IPv6, path segments
isitmyisp status -s 30      # measure 30 s and get a verdict
isitmyisp mtr 8.8.8.8       # mtr with real loss vs ICMP noise
isitmyisp monitor           # measure continuously, store in SQLite
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

## How the verdict works
1. **Home:** loss or abnormal latency to any of your own routers means the problem is on your side. If you're on Wi-Fi, you'll be told so.
2. **Every destination affected:** the problem is in your ISP. If its first hop is also affected, it's the access network; otherwise it's the backbone or its upstream.
3. **Only some destinations:** it's not your ISP.
4. **Everything fine except DNS:** your resolver.

ICMP and TCP must agree before blaming anyone, and nothing is blamed on a handful of lost packets.

## Roadmap
- [x] Probes (fping/ping, TCP 443, DNS), discovery (gateway, ISP first hop, DNS, CGNAT, double NAT, IPv6, offline ASN), CLI verdicts (EN/ES)
- [x] Statistical significance, per-target baselines, hysteresis, re-discovery when the route changes
- [ ] Incident detection with automatic MTR capture stored as evidence
- [ ] Web dashboard and HTML/PDF evidence report (EN/ES)
- [ ] **Tunnel mode:** did your IPsec/L2TP/WireGuard tunnel drop because of your config or because of loss on the path?
- [ ] Prometheus `/metrics`, multi-arch images (amd64/arm64), alerts (Telegram/Discord)

## License
MIT
