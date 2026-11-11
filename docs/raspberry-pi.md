# isitmyisp on a Raspberry Pi

From a new Pi to the setup page in about 15 minutes. [Español](raspberry-pi.es.md)

## What you need

- **Raspberry Pi 4 or 5** (2 GB is enough). A Pi 3 works, but it's slow at PDFs.
- **The official power supply**. With a weak one, the Pi reboots on its own and those reboots get recorded as if they were outages.
- **A microSD card of 16 GB or more**, ideally "high endurance", because the database writes every 30 seconds. To measure for months, a USB SSD is better.
- **A network cable straight to the router.** The probe has to measure the connection, not its own Wi-Fi. If it's on Wi-Fi the dashboard says so, and it's harder to tell a Wi-Fi problem from an ISP one.

## 1. Flash the system (5 min)

With [Raspberry Pi Imager](https://www.raspberrypi.com/software/):

1. Device: your model. OS: **Raspberry Pi OS Lite (64-bit)** (under "Raspberry Pi OS (other)").
2. In **Edit settings**:
   - Hostname: `isitmyisp`.
   - Username and password: you choose them.
   - Time zone: yours. It's the time the reports will show.
   - Wi-Fi: leave it empty if you'll use a cable.
   - **Services** tab: enable SSH.
3. Write the card.

## 2. Power on and log in (2 min)

Insert the card, plug in the network cable and the power supply. A minute later, from your computer:

```bash
ssh your-user@isitmyisp.local
```

If `isitmyisp.local` doesn't answer, find the Pi's IP in the router's list of devices.

## 3. Install (5 to 10 min)

```bash
curl -fsSL https://isitmyisp.enzo-meneghini.com/install.sh | sh
```

Before doing anything, the installer shows every command and asks you. This is what it does:

- If Docker is missing, it installs it with the official installer (`get.docker.com`).
- It downloads the image. While there's no published image for your version, it builds it on the Pi, which takes a few minutes more.
- It starts the monitor: the host's network, permission to ping, data in a Docker volume and the dashboard on port 8080 of your LAN.

If you'd rather read it first, open the link in a browser: it's short, plain text.

## 4. Set it up from the browser (3 min)

When it's done, the installer prints a link like this one:

```
http://192.168.1.50:8080/setup?token=…
```

Open it from any computer on the network. There you create the admin account, and the wizard asks for:

- the speeds you pay for;
- the services you use;
- where you want alerts to reach you.

Everything can be skipped and finished later.

**Reserve the Pi's IP in the router** (the "static DHCP" or "reservation" option), so the dashboard's address doesn't change.

## Afterwards

| To… | Do this |
|---|---|
| Update | Run the installer again. The data is kept. |
| See the log | `docker logs -f isitmyisp` |
| Get a report | From the dashboard, under **Reports**, or `docker exec isitmyisp isitmyisp report --since 7d -o /data/report.html` |
| Uninstall | `curl -fsSL https://isitmyisp.enzo-meneghini.com/install.sh \| sh -s -- --uninstall` (the data stays in the volume) |
| Keep the dashboard on the Pi only | Install with `sh -s -- --local` |
| Forgot the password | `docker exec -it isitmyisp isitmyisp admin reset-password <user>` |
