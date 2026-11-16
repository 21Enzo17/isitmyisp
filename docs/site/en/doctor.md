---
title: The network check-up
nav: The check-up
description: Eleven checks of your network (CGNAT, double NAT, IPv6, DNS, MTU, loops, your network card) with what to do for each.
---
# The network check-up

The verdict tells you what is failing right now. The check-up looks at how your network is set up even when everything works: things that don't take internet down but later explain a problem. It takes about 15 seconds.

Each check comes out **green** (fine), **yellow** (worth a look) or **red** (wrong), with one sentence and what to do. If something couldn't be measured, it says so instead of calling it fine.

## How to run it

- **On its own**: the monitor runs it once a day.
- **In the dashboard**: in **Check-up**, with the **Check now** button. The monitor picks it up on its next round.
- **In the terminal**:

```bash
isitmyisp doctor            # 15 seconds, the result on screen
isitmyisp doctor -s 30      # watch the local network for 30 seconds
isitmyisp doctor --json     # for scripts
isitmyisp doctor --save     # also store it, for the dashboard and the report
```

It exits with code 1 if any check is red, so it works in a script.

## What it checks

**Whole network** (true for any device at your home or office):

| Check | Yellow or red when |
|---|---|
| CGNAT | Your ISP puts you behind a shared IP (100.64.x.x). You can't open ports or run an inbound VPN. |
| Double NAT | There are two routers in a row (say, the ISP's and yours). It can break games, calls and VPNs. |
| IPv6 | Your router announces IPv6 but it doesn't reach the internet: some apps stall or fail. |
| DNS speed | Your DNS servers take 150 ms or more (yellow, 400 ms red), or one doesn't answer. |
| DNS interception | A query to an address that doesn't exist gets an answer: someone (the router or the ISP) answers in place of your DNS. |
| Packet size (MTU) | Large packets are dropped silently. A smaller MTU that is signalled (1492 on PPPoE) is fine. |
| Router restarts | The router restarted in the last 24 hours (read over SNMP, if you set it up). |
| Loops and storms | Duplicate replies, unusual broadcast or a router MAC that keeps changing (see [loops](verdict.md#loops-and-broadcast-storms)). |

**This machine only** (the one running isitmyisp):

| Check | Yellow or red when |
|---|---|
| Link speed | The card negotiates half duplex, or less than your plan (for example 100 Mb/s with a 300 Mb/s plan). |
| Card errors | The card's error counters grew while measuring: cable, connector or port. |
| Wi-Fi or cable | isitmyisp measures over Wi-Fi, so your Wi-Fi problems mix with everything else. A cable is better. |

## The grade

Next to the list there is a grade from A to F: each yellow adds 1 and each red 2. No points is an A; 1 is a B; up to 3 a C; up to 5 a D; more, an F. It's a summary. What matters is the list and what to do on each line.

## In the report

The [report for your ISP](report.md) includes the last check-up of the period as **Checked on the customer side**. Support can see you already looked at your network before filing the claim.
