---
title: How the verdict works
nav: The verdict
description: What isitmyisp measures, how it tells real loss from noise and how it decides whose fault it is.
---
# How the verdict works

This page is for technicians. It explains what is measured and why the verdict never blames anyone without evidence.

## What it measures

In 30-second windows, with one ping every 2 seconds:

- **Your router** (or routers, if there's more than one).
- **The ISP's first hop**: the first router outside your network.
- **Several internet destinations** (1.1.1.1, 8.8.8.8 and 9.9.9.9 by default), over ICMP and TCP (a handshake to port 443, no data).
- **Your DNS servers**, with real queries.
- Your services, tunnels and the router over SNMP, if you set them up.

From that it identifies the path's segments: your network, the ISP's access network, its backbone and what lies beyond. It uses address types and autonomous system (AS) numbers, not hop positions.

## Real loss or ICMP noise

Routers deprioritise pings addressed to themselves, so `mtr` shows "loss" on a middle hop while traffic through it is perfectly fine. isitmyisp only counts loss that **persists to the destination**, and requires **ICMP and TCP to agree**.

## It doesn't cry wolf

- **Statistical significance.** One packet lost out of 50 isn't "2 % loss". Loss must be significant by a 95 % Wilson interval, with at least 2 packets lost.
- **Its own baseline.** Latency is judged against what's normal for each destination, not a fixed number.
- **Hysteresis.** An incident opens after 2 bad windows in a row and closes after 2 good ones.

## Whose fault it is

1. **Your network:** loss or abnormal latency to your own router **that also shows up on the internet**. If only the router "loses" pings while the internet works through it, the router filters ICMP (common on business firewalls) and nobody is blamed.
2. **Your ISP:** every destination affected. If its first hop is affected too, it's the access network; otherwise it's the backbone or its upstream.
3. **Others:** only some destinations affected. It isn't your ISP.
4. **DNS:** everything works except name resolution. It's your DNS server.

When a service you added fails while the internet is healthy, the verdict is "that service". When the office is on the backup link, it says so.

## Evidence for every incident

When an incident opens, an `mtr` capture towards the affected destination is taken and stored with it. If the path changes, it's rediscovered. Incident evidence is kept about 13 months, per-destination measurements 35 days.

## What the evidence rules out

Every ISP incident lists what the evidence rules out (your LAN, ICMP noise, a single site, a full link) and what it can't. Without router data over SNMP, a full link stays as "can't rule out". Better to say so than to over-claim.
