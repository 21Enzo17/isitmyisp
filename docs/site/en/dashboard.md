---
title: The dashboard
description: How to read the isitmyisp dashboard: the path, the colours, the 24-hour timeline and every section.
---
# The dashboard

The dashboard refreshes itself every 30 seconds. The answer is at the top; the evidence is below it.

![The full dashboard](/docs/img/dashboard-dark.png)

## Colours mean whose side it is

Throughout the dashboard, colours mean **responsibility**, not "good or bad":

| Colour | Means |
|---|---|
| Green | Working fine |
| Yellow | The problem is on your side: your Wi-Fi, your network or your router |
| Red | The problem is in your ISP's network |
| Grey | Others: a single service, a remote site, or it can't be told |

Colours always come with text or an icon, so they still read if you can't tell them apart.

## The verdict and the path

At the very top is the verdict in one sentence ("Your ISP's network is failing", "The internet is working"…) and what to do.

Below it is **the path**: *Your network → Your ISP → Internet*, with the latency and loss of each segment. The segment with the problem is marked "here". If the office is on the backup link, the ISP segment says so.

## What we ruled out

When the problem is the ISP's, a list says **what the evidence rules out** and **what it can't**:

- **It can rule out:** your LAN, ICMP noise, a single website being down and, if you connected the router over SNMP, a link full of your own traffic.
- **It can't rule out:** what it didn't measure. Without the router connected, it can't know whether the link was full, and it says so.

That's what makes it credible to the ISP.

## The last 24 hours

A timeline with several rows on the same time axis:

- **Who:** whose fault it was at each moment.
- **Loss** and **latency** to the internet.
- **Calls:** estimated call quality, if set up.
- **Backup:** when the office was on the secondary link, if it happened.

Hover to read the exact values at any moment. Every chart also has a table view.

## Your network, point by point

Every measured destination, with its latest value and the last 6 hours: your router, the ISP's first hop, the internet destinations (over ping and TCP) and your DNS servers.

## Link, speed and calls

- **Link usage:** how much of your plan is in use right now, if you connected the router over SNMP. Above 85 % it's marked as full.
- **Speed:** the last test, against what you pay for.
- **Calls:** the estimated MOS (1 to 5) and whether a call would sound good now.

## Services and tunnels

The state of every service and tunnel you added: whether it answers, how fast and since when.

## Latest incidents

Recent incidents with the time, the cause, the duration and whether they're still open. When the same problem repeats close together it's folded into one row (for example "×4"). The full detail, with each one's evidence, is under **Incidents**.
