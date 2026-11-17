---
title: Check from this device
nav: From this device
description: Measure from your PC or phone and compare it with the probe in the same minutes: is it that device's Wi-Fi, the device itself or the network?
---
# Check from this device

The probe measures from a single place: the machine running isitmyisp. If the probe is fine but your phone isn't, the problem is between that phone and the router, and the probe alone can't see it. This check measures from the device in your hand and compares it with what the probe saw in the same minutes.

## How to run it

Open the dashboard from the device you want to test (the PC, the phone, the laptop) and go to **This device**. Tap **Start** and wait about 15 seconds without closing the page.

The browser measures:

- **To the probe**: 20 small requests for latency, jitter and loss inside your network, and a download and an upload for the speed on your local network.
- **To the internet**: HTTPS requests to the internet destinations (**Settings → Monitoring → Measurement → Internet destinations**), to see how long they take to answer. Nothing is read from those sites, only the time.

It needs JavaScript, on this page only. The rest of the dashboard still works without it.

## What it tells you

| Result | What it means |
|---|---|
| **The network is fine** | Fine from this device and from the probe. If an app still fails, it's that app or that service. |
| **Between this device and the router** | The probe was fine, but to this device there was loss, delay or low speed. It's the Wi-Fi, a cable or a switch port. Not the ISP. |
| **This device** | The local network is fine and the probe reaches the internet, but this device doesn't. Check for a VPN, a firewall or antivirus, a proxy or a browser extension. |
| **The probe saw it too** | The problem is shared: the dashboard's verdict applies (the router or the ISP). |
| **No probe data** | The monitor wasn't measuring, so there is nothing to compare with. |

The local network counts as bad at 10 % loss or more, a 100 ms median or more, 50 ms jitter or more, or under 5 Mb/s down or up. Towards the internet, at 20 % or more failed requests.

The speed it measures is the local network's (device to probe), not your internet speed. If the probe is a Raspberry Pi or on Wi-Fi, the probe itself may be the limit.

A destination that never answers HTTPS while the others do (some IPs serve no web) doesn't count as loss: it's left out. The same if the probe couldn't reach it either.

## What is stored

Each result is stored with the time, the system and browser ("Android · Chrome") and what was measured. The device's IP is not stored: only a short fingerprint to count how many different devices checked. **This device** shows the last 30 days.

## In the report

The [report for your ISP](report.md) adds the period's checks as **Tested from N devices**. Support sees the problem repeats on several devices, or that you already ruled out the Wi-Fi.
