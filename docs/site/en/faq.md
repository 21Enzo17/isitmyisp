---
title: Frequently asked questions
nav: FAQ
description: Common questions and troubleshooting.
---
# Frequently asked questions

## Will it slow my connection down?

No. It sends small pings every 2 seconds to a few destinations, about 1.3 GB a month. The only thing that really uses bandwidth is the [speed test](features.md#speed-test), which is off unless you turn it on.

## Can I connect it over Wi-Fi?

You can, but you shouldn't. With the probe on Wi-Fi, a Wi-Fi problem gets mixed up with an ISP one. Wire it to the router; the dashboard tells you when it's on Wi-Fi.

## Does it work with any ISP?

Yes. It needs nothing from the ISP: it measures from your side. It identifies the ISP by its autonomous system (AS) number, also behind CGNAT or double NAT.

## Do I have to leave a computer on?

Something has to be on all the time, but it can be a Raspberry Pi, which uses about as much power as a phone charger. See the [Raspberry Pi guide](raspberry-pi.md).

## The dashboard has said "Measuring…" or "Checking…" for a while

- **Just installed:** the first windows take a minute or two.
- **All the time:** the monitor isn't running. Check its state with `docker ps` and its log with `docker logs isitmyisp`.
- **On one service:** no check of that service has completed yet. It should clear within 30 seconds.

## The router "loses" pings but the internet works

That's normal for many routers and business firewalls: they deprioritise pings addressed to themselves. isitmyisp detects it and doesn't count it as a problem. See [how the verdict works](verdict.md).

## Why is the speed test below my plan?

It can be the ISP or something on your side: other devices using the internet at that moment, or the Wi-Fi of the machine measuring. The result warns when your Wi-Fi seems to be the limit. If you connected the router over SNMP, it also shows everything the WAN carried during the test.

## Alerts don't arrive

Press **Send test** in **Settings → Alerts** and look at each channel's result. See [Alerts](alerts.md#if-an-alert-doesnt-arrive).

## I forgot my password

```bash
docker exec -it isitmyisp isitmyisp admin reset-password <user>
```

## How do I update?

Run the [installer](install.md#update) again. The data is kept.

## How do I uninstall it?

```bash
curl -fsSL https://isitmyisp.enzo-meneghini.com/install.sh | sh -s -- --uninstall
```

The measurements stay in the `isitmyisp` volume. To delete them too: `docker volume rm isitmyisp`.

## How much does it cost?

The software is free ([MIT](https://github.com/21Enzo17/isitmyisp/blob/main/LICENSE)). If you'd like it installed and looked after for you, it's available as a service.

## I found a bug or want to suggest something

Open an [issue on GitHub](https://github.com/21Enzo17/isitmyisp/issues).
