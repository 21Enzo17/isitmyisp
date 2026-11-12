---
title: Install
description: Install isitmyisp with one command, by hand with Docker, or without Docker.
---
# Install

isitmyisp runs on a Linux machine that stays on and is **wired to the router**: a Raspberry Pi, a mini PC or a server. Starting from scratch with a Pi? Follow the [Raspberry Pi guide](raspberry-pi.md).

## One command

```bash
curl -fsSL https://isitmyisp.enzo-meneghini.com/install.sh | sh
```

The installer is short, and you can [read it first](https://isitmyisp.enzo-meneghini.com/install.sh). It shows every command and asks before running it:

1. If Docker is missing, it offers to install it with the official installer (`get.docker.com`).
2. It downloads the ready-made image from Docker Hub (`21enzo03/isitmyisp`, for PCs and Raspberry Pi). Only if it can't, it builds it from the source.
3. It starts the monitor and waits until it's healthy.
4. It prints the link to create the admin account.

Then the [first-run wizard](first-steps.md) does the rest from your browser.

### Options

Pass options after `sh -s --`, for example `curl … | sh -s -- --local`.

| Option | What it does |
|---|---|
| `--local` | Dashboard on this machine only (by default it's on your LAN, behind a login) |
| `--port 9090` | Another port for the dashboard (default 8080) |
| `--lang es` / `--lang en` | Language (default: the system's) |
| `--tz Europe/Madrid` | Time zone for reports (default: the machine's) |
| `--name` / `--volume` | Another name for the container and its data volume (default `isitmyisp`), to run more than one on the same machine |
| `--version 0.1.0` | A specific version (default: the latest) |
| `--build` | Build the image from the source instead of downloading it |
| `--dry-run` | Print the commands, run nothing |
| `-y` | Don't ask (for scripts) |
| `--uninstall` | Remove the container; the measurements stay in the volume |

### Update

Run the same command again. It replaces the container and keeps the data, which lives in the Docker volume `isitmyisp`.

## By hand, with Docker

If you'd rather type the command yourself:


```bash
docker run -d --name isitmyisp --restart unless-stopped \
  --net=host --cap-add=NET_RAW \
  -e TZ=Europe/Madrid -v isitmyisp:/data \
  -v /run/systemd/resolve:/run/systemd/resolve:ro \
  21enzo03/isitmyisp:latest --lang en monitor --web 0.0.0.0:8080
```

| Part | Why |
|---|---|
| `--net=host` | To see your real router and path. Inside Docker's network, the "router" would be Docker |
| `--cap-add=NET_RAW` | Permission to ping. No privileged mode, nothing else from the host |
| `-v isitmyisp:/data` | Where measurements, incidents and settings live |
| `-v /run/systemd/resolve…` | Optional: lets it see your real DNS servers on systemd-resolved hosts |
| `TZ` | The time shown in reports |
| `--web 0.0.0.0:8080` | Dashboard on your LAN. `127.0.0.1:8080` keeps it on the machine; `off` disables it |

On first start, the log (`docker logs isitmyisp`) prints a **one-time setup token** to create the admin account, so nobody else on your network can claim the instance before you.

## Without Docker

You need Linux, `fping` (recommended) or iputils `ping`, and `mtr`. The measuring core has no Python dependencies; the web UI and PDF are extras.

```bash
pip install 'isitmyisp[web,pdf] @ git+https://github.com/21Enzo17/isitmyisp.git'
isitmyisp monitor --web 0.0.0.0:8080
```

It's also handy for a quick look from the terminal:

```bash
isitmyisp discover          # router, ISP, DNS, CGNAT, IPv6 and the path's segments
isitmyisp status -s 30      # measure 30 seconds and give a verdict
isitmyisp mtr 8.8.8.8       # mtr that tells real loss from ICMP noise
isitmyisp report --since 7d # the HTML report
```

## Try it without installing

The [demo](/en/isp/) shows the whole dashboard with a day of sample data. You can also run it on your machine, measuring nothing (with the image built or pulled):

```bash
docker run --rm -p 127.0.0.1:8090:8080 21enzo03/isitmyisp:latest \
  --lang en demo --scenario isp --bind 0.0.0.0:8080
```
