"""Bring your own speed test: run a command the user installed, and read its JSON (#115).

Some lines are only measured right by a server isitmyisp can't use on its own: the ISP's own
on-net server behind Ookla's CLI, a LibreSpeed instance in the same city, an iperf3 box at the
other office. Their tools can't ship with isitmyisp (Ookla's licence forbids it), but the user
can install one, accept its licence in their own command line, and point isitmyisp at it:

    [speedtest]
    command = ["speedtest", "-f", "json", "--accept-license", "--accept-gdpr"]

The command comes from the config file or $ISITMYISP_SPEEDTEST_COMMAND only (see config.py), and
runs as an argument list, never through a shell. It runs once per test, after the built-in engines,
with the same schedule, budget and busy-link checks. Its result joins the test as one more server,
so the plan is held against it like any other (speedtest.best).

Understood formats, detected from the output:
- Ookla CLI, ``speedtest -f json`` (bandwidth in bytes per second);
- the older Python speedtest-cli (the ``speedtest`` many distributions ship), ``--json`` (bits per second);
- librespeed-cli, ``--json`` (Mbps);
- iperf3, ``-J`` (one direction, or both with ``--bidir``);
- a plain one for scripts: ``{"download_mbps": 930, "upload_mbps": 600, "ping_ms": 2.1,
  "server": "Name", "host": "server.example", "bytes": 1500000000}`` (all optional but one rate).
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import urllib.parse
from collections.abc import Callable

from .probes.icmp import C_ENV
from .speedtest import DOWN_SECONDS, UP_SECONDS

ENGINE = "command"
MAX_OUTPUT = 4_000_000            # characters of output read: more is not a speed test result
LABELS = {"ookla": "Ookla", "speedtest-cli": "speedtest-cli", "librespeed": "LibreSpeed", "iperf3": "iperf3", "json": ""}


class ParseError(ValueError):
    pass


def _json(text: str):
    """The whole output as JSON, or else its last line that is (some tools print progress first)."""
    text = (text or "")[:MAX_OUTPUT].strip()
    if not text:
        raise ParseError("no output")
    try:
        return json.loads(text)
    except ValueError:
        pass
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line[:1] in "{[":
            try:
                return json.loads(line)
            except ValueError:
                continue
    raise ParseError("the output is not JSON")


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) and f >= 0 else None


def detect(data) -> str:
    if isinstance(data, list):
        data = data[0] if data and isinstance(data[0], dict) else {}
    if not isinstance(data, dict):
        return "unknown"
    if isinstance(data.get("download"), dict) and "bandwidth" in data["download"]:
        return "ookla"
    if "end" in data and ("start" in data or "intervals" in data):
        return "iperf3"
    if isinstance(data.get("server"), dict) and "sponsor" in data["server"]:
        return "speedtest-cli"          # before librespeed: same fields, but bits per second
    if "bytes_received" in data or "bytes_sent" in data or ("server" in data and _num(data.get("download")) is not None):
        return "librespeed"
    if "download_mbps" in data or "upload_mbps" in data:
        return "json"
    return "unknown"


def _host(value: str | None) -> str | None:
    """A host name from 'host:port', a URL or a bare name."""
    if not value:
        return None
    value = str(value)
    if "://" in value:
        return urllib.parse.urlparse(value).hostname
    if value.count(":") == 1:          # host:port (an IPv6 address has more colons)
        return value.split(":")[0] or None
    return value.strip("[]")


def _ookla(d: dict) -> dict:
    down, up = d.get("download") or {}, d.get("upload") or {}
    srv = d.get("server") or {}
    bw = lambda part: round(b * 8 / 1e6, 1) if (b := _num(part.get("bandwidth"))) is not None else None
    place = ", ".join(x for x in (srv.get("location"), srv.get("country")) if x)
    name = " ".join(x for x in (srv.get("name"), f"({place})" if place else "") if x)
    return {"down_mbps": bw(down), "up_mbps": bw(up), "ping_ms": _num((d.get("ping") or {}).get("latency")),
            "bytes": int((_num(down.get("bytes")) or 0) + (_num(up.get("bytes")) or 0)),
            "server": name or None, "host": srv.get("ip") or _host(srv.get("host")),
            "url": (d.get("result") or {}).get("url")}


def _speedtest_cli(d: dict) -> dict:
    srv = d.get("server") or {}
    rate = lambda v: round(b / 1e6, 1) if (b := _num(v)) is not None else None
    place = ", ".join(x for x in (srv.get("name"), srv.get("country")) if x)
    name = " ".join(x for x in (srv.get("sponsor"), f"({place})" if place else "") if x)
    return {"down_mbps": rate(d.get("download")), "up_mbps": rate(d.get("upload")), "ping_ms": _num(d.get("ping")),
            "bytes": int((_num(d.get("bytes_sent")) or 0) + (_num(d.get("bytes_received")) or 0)),
            "server": name or None, "host": _host(srv.get("host")), "url": d.get("share") or None}


def _librespeed(d) -> dict:
    if isinstance(d, list):
        d = d[0] if d else {}
    srv = d.get("server") or {}
    return {"down_mbps": _num(d.get("download")), "up_mbps": _num(d.get("upload")), "ping_ms": _num(d.get("ping")),
            "bytes": int((_num(d.get("bytes_sent")) or 0) + (_num(d.get("bytes_received")) or 0)),
            "server": srv.get("name") or None, "host": _host(srv.get("url")), "url": d.get("share") or None}


def _iperf3(d: dict) -> dict:
    if d.get("error"):
        raise ParseError(str(d["error"])[:200])
    end, start = d.get("end") or {}, d.get("start") or {}
    mbps = lambda part: round(b / 1e6, 1) if (b := _num((part or {}).get("bits_per_second"))) else None
    moved = lambda a, b: int(max(_num((a or {}).get("bytes")) or 0, _num((b or {}).get("bytes")) or 0))
    received, sent = end.get("sum_received"), end.get("sum_sent")
    out = {"down_mbps": None, "up_mbps": None, "ping_ms": None, "bytes": moved(received, sent), "server": None,
           "host": ((start.get("connected") or [{}])[0] or {}).get("remote_host"), "url": None}
    out["server"] = out["host"]
    if "sum_received_bidir_reverse" in end:       # --bidir: both ways at once
        out["up_mbps"] = mbps(received)
        out["down_mbps"] = mbps(end["sum_received_bidir_reverse"])
        out["bytes"] += moved(end["sum_received_bidir_reverse"], end.get("sum_sent_bidir_reverse"))
    elif (start.get("test_start") or {}).get("reverse"):
        out["down_mbps"] = mbps(received)
    else:
        out["up_mbps"] = mbps(received)
    rtts = [_num((s.get("sender") or {}).get("mean_rtt")) for s in end.get("streams") or []]
    rtts = [r for r in rtts if r]
    if rtts:                                       # microseconds, from the sender's TCP info
        out["ping_ms"] = round(min(rtts) / 1000, 1)
    return out


def _plain(d: dict) -> dict:
    return {"down_mbps": _num(d.get("download_mbps")), "up_mbps": _num(d.get("upload_mbps")),
            "ping_ms": _num(d.get("ping_ms")), "bytes": int(_num(d.get("bytes")) or 0),
            "server": (str(d["server"])[:60] if d.get("server") else None), "host": _host(d.get("host")),
            "url": None}


PARSERS = {"ookla": _ookla, "speedtest-cli": _speedtest_cli, "librespeed": _librespeed, "iperf3": _iperf3, "json": _plain}


def parse(text: str, fmt: str = "auto") -> tuple[str, dict]:
    """(format, figures) from a command's output. Raises ParseError if no rate can be read."""
    data = _json(text)
    if fmt == "auto":
        fmt = detect(data)
    if fmt not in PARSERS:
        raise ParseError("unknown output: use format = ookla | speedtest-cli | librespeed | iperf3 | json")
    if isinstance(data, list) and fmt != "librespeed":
        data = data[-1] if data and isinstance(data[-1], dict) else {}
    if not isinstance(data, (dict, list)):
        raise ParseError("unknown output")
    try:
        got = PARSERS[fmt](data)
    except (AttributeError, TypeError, IndexError) as exc:
        raise ParseError(f"unexpected {fmt} output") from exc
    if got["down_mbps"] is None and got["up_mbps"] is None:
        raise ParseError(f"no download or upload rate in the {fmt} output")
    if got["ping_ms"] is not None:
        got["ping_ms"] = round(got["ping_ms"], 1)
    return fmt, got


def _why(proc) -> str:
    """The reason a command failed, from its last words (Ookla logs JSON lines on stderr)."""
    for line in reversed(((proc.stderr or "") + "\n" + (proc.stdout or ""))[-20_000:].splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            if isinstance(msg, dict) and msg.get("message"):
                line = str(msg["message"])
        except ValueError:
            pass
        return line[:200]
    return f"exit status {proc.returncode}"


def run(command, *, mark: Callable[[str], dict] | None = None, runner=subprocess.run) -> dict:
    """Run the user's command once. The result has the shape of an iperf3 server's (see
    speedtest.run_server), engine "command", plus its round trip and the result link if any."""
    argv, fmt = list(command.argv), command.format
    label = command.name or LABELS.get(fmt, "") or os.path.basename(argv[0])
    out = {"name": label, "engine": ENGINE, "where": None, "forced": False, "asn": None, "as_name": None,
           "down_mbps": None, "up_mbps": None, "bytes": 0, "error": None, "rtt_ms": None, "url": None}
    try:
        proc = runner(argv, capture_output=True, text=True, timeout=command.timeout, env=C_ENV,
                      stdin=subprocess.DEVNULL, check=False)
    except FileNotFoundError:
        out["error"] = f"{argv[0]}: command not found (is it installed, or mounted in the container?)"
        return out
    except subprocess.TimeoutExpired:
        out["error"] = f"{argv[0]}: no result after {command.timeout} s"
        return out
    except OSError as exc:
        out["error"] = f"{argv[0]}: {exc}"
        return out
    try:
        fmt, got = parse(proc.stdout, fmt)
    except ParseError as exc:
        failed = proc.returncode or not (proc.stdout or "").strip()   # some tools exit 0 on a usage error
        why, base = str(_why(proc) if failed else exc), os.path.basename(argv[0])
        out["error"] = why if why.startswith(f"{base}:") else f"{base}: {why}"
        return out
    out.update(entry(fmt, got, name=command.name, fallback=label, mark=mark))
    return out


def entry(fmt: str, got: dict, *, name: str = "", fallback: str = "", engine: str = ENGINE,
          mark: Callable[[str], dict] | None = None) -> dict:
    """One parsed result as a server of the test (see speedtest.run_server): named after the tool
    (or `name`) and its server, its bytes, and which side of the ISP that server is on."""
    label = name or LABELS.get(fmt) or fallback or fmt
    out = {"name": f"{label} · {got['server']}"[:60] if got["server"] and got["server"] != label else label,
           "engine": engine, "where": None, "forced": False, "asn": None, "as_name": None,
           "down_mbps": got["down_mbps"], "up_mbps": got["up_mbps"], "error": None, "rtt_ms": got["ping_ms"],
           "url": got["url"] if str(got["url"] or "").startswith("https://") else None}
    # what it moved; if the tool doesn't say, what those rates move in a test as long as ours
    out["bytes"] = got["bytes"] or int(((got["down_mbps"] or 0) * DOWN_SECONDS + (got["up_mbps"] or 0) * UP_SECONDS) * 1e6 / 8)
    if got["host"] and mark:
        info = mark(got["host"]) or {}
        out.update({k: info.get(k) for k in ("asn", "as_name", "where")})
    return out
