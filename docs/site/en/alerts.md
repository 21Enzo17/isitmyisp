---
title: Alerts
description: Telegram, email or webhook messages when the internet, a service or a tunnel goes down.
---
# Alerts

A message when the internet, a service or a tunnel goes down. Each one says **whose fault it is and what to do**. Set them up in **Settings → Alerts** (or in the wizard); every channel has a button to send a test.

## When it alerts

- **Only if it lasts.** By default it alerts once a problem has lasted at least 2 minutes; you can set 0 to 240. A few seconds' blip won't wake you up.
- **Also when it's resolved**, with the total duration. This can be turned off.
- **With a link to the dashboard**, if you fill in the dashboard address. The wizard fills it in from the address you used.

## Telegram

1. Create a bot by talking to [@BotFather](https://t.me/BotFather) and copy its token (something like `123456789:AA…`).
2. Send your bot any message.
3. Get your chat id from [@userinfobot](https://t.me/userinfobot). For a group or channel, the id starts with `-100…`, or use `@channel_name`.

## Email

Any SMTP server: your domain's or your mail provider's. Fill in the server, the port (587 with STARTTLS or 465 with SSL), the username, the password, the sender and the recipients separated by commas.

With Gmail you need an [app password](https://support.google.com/accounts/answer/185833), not your account password.

## Webhook

A URL that receives a POST with the alert. Discord and Slack URLs are detected and get their own format; any other gets a JSON body with the event, title, text and incident data. Works with Home Assistant, n8n or your own system.

## Monthly report by email

Besides alerts, isitmyisp can email you **last month's report every month**, without opening the dashboard. Turn it on in **Settings → Monthly report by email**:

- Choose the day (1 to 28), the hour and the recipients. Leave them empty to use the alert email recipients.
- The message has a short summary: how many incidents and how long, whose fault they were, the worst day, how much it affected you while open (if you set your [opening hours](features.md#opening-hours)), time on the backup link, call quality and measured speed.
- The **full report** is attached, as PDF (in the Docker image) or HTML, ready to forward to your ISP.
- It uses the email server set up for alerts.
- It's sent **once a month**, even if the machine restarts. If sending fails it's retried every 15 minutes, and the error shows in Settings.
- **"Send now"** emails you last month's report to see how it arrives. That test doesn't count as the month's send.

## If an alert doesn't arrive

- Press **Send test**: the result of each channel shows at the top.
- If a real alert fails, the error stays visible in **Settings → Alerts**.
- Passwords and tokens are never shown back: leave the field empty and the stored one is kept.
