"""Minimal SNMP v2c client (GET / GETNEXT) and WAN link usage, standard library only.

Why: the first objection any ISP raises is "you saturated your own link". Reading the WAN
interface counters from the customer's router (MikroTik, Fortinet, UniFi, pfSense... all speak
SNMP) lets the report say "your link was at 23% of the contracted speed: it wasn't your traffic".

Only what we need is implemented: BER for INTEGER, OCTET STRING, NULL, OID, Counter32/64,
Gauge32, TimeTicks, and the v2c exception values. Read-only; the router needs a read-only
community restricted to the probe's address.
"""

from __future__ import annotations

import random
import socket
import time
from dataclasses import dataclass

OID_SYS_DESCR = "1.3.6.1.2.1.1.1.0"
OID_SYS_UPTIME = "1.3.6.1.2.1.1.3.0"
OID_IF_NAME = "1.3.6.1.2.1.31.1.1.1.1"
OID_IF_HC_IN = "1.3.6.1.2.1.31.1.1.1.6"
OID_IF_HC_OUT = "1.3.6.1.2.1.31.1.1.1.10"
OID_IF_HIGH_SPEED = "1.3.6.1.2.1.31.1.1.1.15"
OID_HR_PROCESSOR_LOAD = "1.3.6.1.2.1.25.3.3.1.2"

NO_SUCH = {0x80: "noSuchObject", 0x81: "noSuchInstance", 0x82: "endOfMibView"}


class SnmpError(RuntimeError):
    pass


# ------------------------------------------------------------------ BER encoding

def _len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    out = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(out)]) + out


def _tlv(tag: int, value: bytes) -> bytes:
    return bytes([tag]) + _len(len(value)) + value


def _int(n: int) -> bytes:
    size = max(1, (n.bit_length() + 8) // 8)
    return _tlv(0x02, n.to_bytes(size, "big", signed=True))


def _oid(oid: str) -> bytes:
    parts = [int(p) for p in oid.strip(".").split(".")]
    if len(parts) < 2:
        raise SnmpError(f"bad OID {oid!r}")
    body = bytearray([parts[0] * 40 + parts[1]])
    for p in parts[2:]:
        chunk = [p & 0x7F]
        p >>= 7
        while p:
            chunk.append(0x80 | (p & 0x7F))
            p >>= 7
        body += bytes(reversed(chunk))
    return _tlv(0x06, bytes(body))


def encode_request(community: str, oids: list[str], request_id: int, pdu_tag: int = 0xA0) -> bytes:
    varbinds = b"".join(_tlv(0x30, _oid(o) + _tlv(0x05, b"")) for o in oids)
    pdu = _tlv(pdu_tag, _int(request_id) + _int(0) + _int(0) + _tlv(0x30, varbinds))
    return _tlv(0x30, _int(1) + _tlv(0x04, community.encode()) + pdu)  # version 1 = v2c


# ------------------------------------------------------------------ BER decoding

def _read(data: bytes, i: int) -> tuple[int, bytes, int]:
    tag = data[i]
    n = data[i + 1]
    i += 2
    if n & 0x80:
        k = n & 0x7F
        n = int.from_bytes(data[i:i + k], "big")
        i += k
    return tag, data[i:i + n], i + n


def _decode_oid(b: bytes) -> str:
    parts = [b[0] // 40, b[0] % 40]
    v = 0
    for byte in b[1:]:
        v = (v << 7) | (byte & 0x7F)
        if not byte & 0x80:
            parts.append(v)
            v = 0
    return ".".join(map(str, parts))


def _decode_value(tag: int, b: bytes):
    if tag == 0x02:
        return int.from_bytes(b, "big", signed=True)
    if tag in (0x41, 0x42, 0x43, 0x46):  # Counter32, Gauge32, TimeTicks, Counter64
        return int.from_bytes(b, "big", signed=False)
    if tag == 0x04:
        return b.decode(errors="replace")
    if tag == 0x06:
        return _decode_oid(b)
    if tag == 0x40:
        return ".".join(str(x) for x in b)
    if tag == 0x05:
        return None
    if tag in NO_SUCH:
        return NO_SUCH[tag]
    return b


def decode_response(data: bytes) -> tuple[int, int, list[tuple[str, object]]]:
    """Returns (request_id, error_status, [(oid, value)])."""
    try:
        _, msg, _ = _read(data, 0)
        _, _, i = _read(msg, 0)            # version
        _, _, i = _read(msg, i)            # community
        tag, pdu, _ = _read(msg, i)
        if tag != 0xA2:
            raise SnmpError(f"unexpected PDU type 0x{tag:02x}")
        _, rid, j = _read(pdu, 0)
        _, err, j = _read(pdu, j)
        _, _, j = _read(pdu, j)            # error index
        _, vbl, _ = _read(pdu, j)
        out, k = [], 0
        while k < len(vbl):
            _, vb, k = _read(vbl, k)
            _, oid_b, m = _read(vb, 0)
            vtag, val, _ = _read(vb, m)
            out.append((_decode_oid(oid_b), _decode_value(vtag, val)))
        return int.from_bytes(rid, "big", signed=True), int.from_bytes(err, "big"), out
    except (IndexError, ValueError) as exc:
        raise SnmpError("malformed SNMP response") from exc


# ------------------------------------------------------------------ client

class SnmpClient:
    def __init__(self, host: str, community: str = "public", port: int = 161, timeout: float = 2.0, retries: int = 1):
        self.host, self.community, self.port = host, community, port
        self.timeout, self.retries = timeout, retries

    def _request(self, oids: list[str], pdu_tag: int) -> list[tuple[str, object]]:
        rid = random.randint(1, 2**31 - 1)
        packet = encode_request(self.community, oids, rid, pdu_tag)
        last: Exception | None = None
        for _ in range(self.retries + 1):
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.settimeout(self.timeout)
                try:
                    s.sendto(packet, (self.host, self.port))
                    while True:
                        data, _ = s.recvfrom(65535)
                        got_id, err, varbinds = decode_response(data)
                        if got_id != rid:
                            continue
                        if err:
                            raise SnmpError(f"SNMP error status {err}")
                        return varbinds
                except socket.timeout as exc:
                    last = exc
                except OSError as exc:
                    raise SnmpError(f"cannot reach {self.host}:{self.port}: {exc}") from exc
        raise SnmpError(f"no answer from {self.host}:{self.port} (wrong community, ACL or SNMP disabled?)") from last

    def get(self, oids: list[str]) -> dict[str, object]:
        return dict(self._request(oids, 0xA0))

    def walk(self, base: str, limit: int = 256) -> list[tuple[str, object]]:
        out, oid = [], base
        for _ in range(limit):
            (next_oid, value), = self._request([oid], 0xA1)
            if not next_oid.startswith(base + ".") or value in NO_SUCH.values():
                break
            out.append((next_oid, value))
            oid = next_oid
        return out


# ------------------------------------------------------------------ link usage

@dataclass
class LinkUsage:
    down_mbps: float
    up_mbps: float
    down_pct: float | None   # of the contracted speed (None if not configured)
    up_pct: float | None
    cpu_pct: float | None    # router CPU, if exposed (HOST-RESOURCES-MIB)

    @property
    def peak_pct(self) -> float | None:
        vals = [v for v in (self.down_pct, self.up_pct) if v is not None]
        return max(vals) if vals else None


def interfaces(client: SnmpClient) -> list[tuple[int, str]]:
    return [(int(oid.rsplit(".", 1)[1]), str(name)) for oid, name in client.walk(OID_IF_NAME)]


class LinkMonitor:
    """Reads the WAN interface counters each window and turns deltas into Mbps and % of contract.

    Download = octets IN on the WAN interface, upload = octets OUT.
    """

    def __init__(self, client: SnmpClient, interface: str, down_contract_mbps: float = 0, up_contract_mbps: float = 0):
        self.client = client
        self.interface = interface
        self.down_c, self.up_c = down_contract_mbps, up_contract_mbps
        self.if_index: int | None = None
        self._last: tuple[float, int, int, int] | None = None  # (time, uptime, in, out)
        self.error: str | None = None

    def _resolve(self) -> int:
        if self.if_index is None:
            for idx, name in interfaces(self.client):
                if name == self.interface:
                    self.if_index = idx
                    break
            else:
                raise SnmpError(f"interface {self.interface!r} not found on the router")
        return self.if_index

    def sample(self, now: float | None = None) -> LinkUsage | None:
        """None on the first call (no delta yet) or on errors (stored in .error)."""
        now = now or time.time()
        try:
            idx = self._resolve()
            vals = self.client.get([OID_SYS_UPTIME, f"{OID_IF_HC_IN}.{idx}", f"{OID_IF_HC_OUT}.{idx}"])
            uptime, rx, tx = (vals.get(OID_SYS_UPTIME), vals.get(f"{OID_IF_HC_IN}.{idx}"),
                              vals.get(f"{OID_IF_HC_OUT}.{idx}"))
            if not all(isinstance(v, int) for v in (uptime, rx, tx)):
                raise SnmpError("router does not expose 64-bit interface counters (IF-MIB ifHC*)")
            cpu = self._cpu()
        except SnmpError as exc:
            self.error = str(exc)
            return None
        self.error = None
        prev, self._last = self._last, (now, uptime, rx, tx)
        if prev is None or uptime < prev[1] or rx < prev[2] or tx < prev[3]:  # first sample, reboot or reset
            return None
        dt = now - prev[0]
        if dt <= 0:
            return None
        down = (rx - prev[2]) * 8 / dt / 1e6
        up = (tx - prev[3]) * 8 / dt / 1e6
        return LinkUsage(round(down, 2), round(up, 2),
                         round(100 * down / self.down_c, 1) if self.down_c else None,
                         round(100 * up / self.up_c, 1) if self.up_c else None, cpu)

    def counters(self) -> tuple[int, int] | None:
        """Raw WAN octet counters (in, out), for an average over an arbitrary span (the speed test)."""
        try:
            idx = self._resolve()
            vals = self.client.get([f"{OID_IF_HC_IN}.{idx}", f"{OID_IF_HC_OUT}.{idx}"])
            rx, tx = vals.get(f"{OID_IF_HC_IN}.{idx}"), vals.get(f"{OID_IF_HC_OUT}.{idx}")
        except SnmpError:
            return None
        return (rx, tx) if isinstance(rx, int) and isinstance(tx, int) else None

    def _cpu(self) -> float | None:
        try:
            loads = [v for _, v in self.client.walk(OID_HR_PROCESSOR_LOAD, limit=64) if isinstance(v, int)]
        except SnmpError:
            return None
        return round(sum(loads) / len(loads), 1) if loads else None
