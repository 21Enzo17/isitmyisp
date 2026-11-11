---
title: isitmyisp · Docs
nav: What it is
description: isitmyisp tells you whether an internet problem is your Wi-Fi, your router or your ISP, and builds the evidence to claim.
---
# Is it your Wi-Fi, your router or your ISP?

isitmyisp is a connection monitor that runs on your network and measures it all the time. When something fails, it tells you **where** the problem is, says it in plain words and builds the evidence your ISP needs so they don't answer "restart the modem".

<div class="cards" markdown>
<div markdown>
### Install it
One command on a Raspberry Pi or any Linux machine. [Install](install.md)
</div>
<div markdown>
### Try it first
The whole UI on sample data, in your browser. [Live demo](/en/isp/)
</div>
<div markdown>
### Read the dashboard
What every colour, number and verdict means. [The dashboard](dashboard.md)
</div>
<div markdown>
### Claim to your ISP
The evidence report and how to use it. [The report](report.md)
</div>
</div>

![The dashboard during a problem in the ISP's network: the path from your network to the internet, with the ISP marked](/docs/img/incident.png)

## Who it's for

- **Small offices and shops**, where the internet is the till, the card terminal, the phones and the invoicing. One small box (a Raspberry Pi is enough) tells you whose fault each outage was and gives you the report to claim.
- **IT providers** who look after those offices: a verdict you can show the client, the backup link and call quality at a glance, and a report the ISP can't wave away.
- **Homes** tired of "restart the modem" who want proof.

## What it answers

**Whose fault is it?** The dashboard shows the path *Your network → Your ISP → Internet* and marks the segment where the problem is. It doesn't panic over a few lost pings: to blame anyone, the failure must be statistically significant, sustained, and seen over both ICMP and TCP. [How it decides](verdict.md)

**What did we rule out?** For every ISP problem, the report lists what the evidence rules out (your LAN, a single website, a link full of your own downloads) and what it can't. It never claims more than it can prove.

**Is the office running as it should?** It notices when you switch to the backup link, estimates whether a call would sound good, checks the services your business depends on and watches VPN tunnels to your branches. [Features](features.md)

**Who tells me?** Alerts by Telegram, email or webhook, only when a problem lasts, saying whose fault it is and what to do. [Alerts](alerts.md)

## What it doesn't do

- **It doesn't send your data anywhere.** No cloud, no telemetry: everything stays on your machine. Every external connection is [listed](privacy.md).
- **It isn't a server monitor.** "Your services" exists to tell "my internet" from "the service", not to compete with tools like Uptime Kuma.
- **It doesn't guess.** When the evidence isn't enough, the verdict says so.

isitmyisp is free software ([MIT licence](https://github.com/21Enzo17/isitmyisp/blob/main/LICENSE)), built by someone who worked in an ISP's NOC.
