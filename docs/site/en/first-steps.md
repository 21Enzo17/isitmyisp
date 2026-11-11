---
title: First steps
description: Create the admin account and make isitmyisp useful from day one with the wizard.
---
# First steps

It has been measuring since it started. What's left is telling it three things about your business, so the verdict is useful from day one. The wizard asks for them in a few minutes.

## 1. Create the admin account

Open the link the installer printed (`http://<machine-ip>:8080/setup?token=…`) from any computer on the network. Choose a username and a password of at least 10 characters.

> Lost the link? The token is in the log: `docker logs isitmyisp`. After 24 hours, get a new one with `docker exec isitmyisp isitmyisp admin setup-token`.

## 2. The wizard

After creating the account, **Get started** opens. Every step can be skipped, and everything can be changed later in **Settings**, which also has a button to reopen the wizard.

### Your plan

At the top is what it already found: your router, your ISP with its autonomous system number (AS), whether you're behind CGNAT and whether the probe is on Wi-Fi. Below, it asks for the **speeds you pay for**, which are on the bill or the contract.

With those speeds, isitmyisp can tell a link full of your own downloads from a failing ISP. It also uses them to compare the [speed test](features.md#speed-test), which is off unless you turn it on.

### Your services

A list of ready-made checks to tick: in Argentina, the tax agency (ARCA), banks and payment providers; everywhere, Google Workspace, Microsoft 365, WhatsApp Web and Zoom. Each one says exactly what it checks.

When one fails while the internet works, the dashboard says it's that service and not your connection. Your own systems (an ERP, a branch server) are added from Settings.

### Alerts

Telegram or a webhook (Discord, Slack, Home Assistant…), with a button to **send a test**. The dashboard address included in messages is filled in for you. Email is set up in Settings. More in [Alerts](alerts.md).

### Done

A summary of what's set and what's pending, with links to the optional parts: tunnels, the router over SNMP, the speed test, TV mode and users.

## 3. Reserve the machine's IP

In your router, reserve the address of the machine running isitmyisp. The option is usually called "static DHCP", "reservation" or "fixed IP". That way the dashboard's link doesn't change.

## And now

Leave it measuring. After a few hours it has a baseline of your connection; after a few days, a history you can show your ISP. Meanwhile:

- Learn to read [the dashboard](dashboard.md).
- Add someone with read-only access in **Settings → Users**.
- Put the [TV mode](features.md#tv-mode) on a screen in the office.
