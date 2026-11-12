---
title: The dashboard
description: How to read the isitmyisp dashboard: the status, the figures, the path, the last 24 hours and every card.
---
# The dashboard

The dashboard refreshes itself every 30 seconds. The answer is at the top; the evidence is below it.

![The dashboard during a problem in the ISP's network](/docs/img/incident.png)

## Colours mean whose side it is

Throughout the dashboard, colours mean **responsibility**, not "good or bad":

| Colour | Means |
|---|---|
| Green | Working fine |
| Orange | The problem is on your side: your Wi-Fi, your network or your router |
| Red | The problem is in your ISP's network |
| Grey | Others: a single service, a remote site, or it can't be told |

Colours always come with text or an icon, so they still read if you can't tell them apart.

## At the top: the status and the theme

- **The status pill** sums it all up in a couple of words: "Connection stable", "Your ISP is failing", "Problem on your side"…
- **The moon or sun button** switches between light and dark mode and remembers it in that browser. Until you press it, the dashboard follows your system's setting.

## The verdict and the three figures

On the left is the verdict in one sentence ("Your ISP's network is failing", "The internet is working"), with a large icon in the colour of whoever is responsible. Beside it are three figures, each with a small chart of the last 24 hours:

- **Availability, 24 h:** how much of the measured time the connection worked. The arrow compares it with the 24 hours before.
- **Without outages:** how long since the last problem with your connection. While one is going on, the card turns into **"Problem going on for"** and shows its duration in red.
- **Latency to the internet:** the median time the internet destinations take to answer. When it went down compared with the day before, the arrow is green.

## Last 24 hours

A timeline with several rows on the same time axis:

- **Who:** whose fault it was at each moment.
- **Loss** and **latency** to the internet.
- **Calls:** estimated call quality, if set up.
- **Backup:** when the office was on the secondary link, if it happened.

Hover to read the exact values at any moment. Below it there's a table view with the same data.

## Monitored destinations

Every measured destination, with its current latency and a small chart of the last 6 hours: your router, the ISP's first hop, the internet destinations and your DNS servers. The coloured dot says how it's doing. When a destination loses packets, the percentage shows in red under its latency.

## Latest events

Recent incidents, newest first, with how long ago they started and how long they lasted ("2 h ago (5 min)"). When the same problem repeats close together it's folded into one line (for example "×4"). "See all" leads to **Incidents**, with each one's full evidence.

## Where the problem is

**The path**: *Your network → Your ISP → Internet*, with the latency and loss of each segment. The point with the problem is marked "The evidence points here". If the office is on the backup link, the ISP segment says so.

Below the path:

- **What to do**, depending on who is responsible.
- **The active incident**, if there is one, with its evidence, **what the evidence rules out** (your LAN, ICMP noise, a single website being down and, if you connected the router over SNMP, a link full of your own traffic) and what it can't.
- **The day's summary** and the buttons for the **report for your ISP** (HTML or PDF).
- **Brief drops**: problems shorter than a minute, too short to become an incident.

## Your link, calls, services and tunnels

- **Your link (from your router):** how much of your plan is in use right now, if you connected the router over SNMP. Above 85 % it's marked as full. Below it, the latest **speed test** against what you pay for.
- **Call quality:** the estimated MOS (1 to 5) and whether a call would sound good now.
- **Services, devices and tunnels:** whether each one answers, how fast and since when. [Devices on your network](features.md#devices-on-your-network) (card terminal, printer, cameras…) show their kind and address.
