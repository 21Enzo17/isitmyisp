"""AS number lookups, offline by default.

Privacy first: by default we never send the IPs of your path to anyone.
  * Offline (default): the public iptoasn.com IPv4 dataset, downloaded once with
    `isitmyisp update-asn` (a single bulk file, no per-IP queries) and searched locally.
  * Online (opt-in, --asn-online): Team Cymru's whois service over TCP/43, which does
    receive the public IPs being looked up.
"""

from __future__ import annotations

import bisect
import gzip
import ipaddress
import re
import shutil
import socket
import urllib.request
from array import array
from pathlib import Path

from .netutil import ip_kind

IPTOASN_URL = "https://iptoasn.com/data/ip2asn-v4.tsv.gz"
CYMRU_HOST = "whois.cymru.com"


def _clean_name(name: str) -> str:
    name = re.sub(r"^AS\d+\s*-\s*", "", name.strip())  # "AS7303 - Telecom..." -> "Telecom..."
    name = re.sub(r"^[A-Z0-9_.]+(?:-[A-Z0-9_.]+)*\s+-\s+", "", name)  # "CLOUDFLARENET - Cloudflare" -> "Cloudflare"
    return re.sub(r",\s*[A-Z]{2}$", "", name)  # drop trailing ", AR"


def db_path(data_dir: Path) -> Path:
    return data_dir / "ip2asn-v4.tsv.gz"


def download(data_dir: Path, timeout: float = 60) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    target = db_path(data_dir)
    tmp = target.with_suffix(".part")
    req = urllib.request.Request(IPTOASN_URL, headers={"User-Agent": "isitmyisp"})
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(tmp, "wb") as out:
        shutil.copyfileobj(resp, out)
    tmp.replace(target)
    return target


class OfflineASN:
    """Sorted IPv4 ranges -> (ASN, name), searched with bisect. ~0.5M ranges, a few MB in memory."""

    def __init__(self, path: Path):
        self.starts = array("I")
        self.ends = array("I")
        self.asns = array("I")
        self.names: dict[int, str] = {}
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 5:
                    continue
                asn = int(parts[2])
                if asn == 0:  # "Not routed"
                    continue
                self.starts.append(int(ipaddress.IPv4Address(parts[0])))
                self.ends.append(int(ipaddress.IPv4Address(parts[1])))
                self.asns.append(asn)
                self.names.setdefault(asn, _clean_name(parts[4]))

    def get(self, ip: str) -> tuple[str, str] | None:
        try:
            n = int(ipaddress.IPv4Address(ip))
        except ValueError:
            return None
        i = bisect.bisect_right(self.starts, n) - 1
        if i >= 0 and self.starts[i] <= n <= self.ends[i]:
            asn = self.asns[i]
            return f"AS{asn}", self.names.get(asn, "")
        return None


_offline_cache: dict[Path, OfflineASN] = {}


def lookup(ips: list[str], data_dir: Path | None = None, online: bool = False,
           timeout: float = 6.0) -> dict[str, tuple[str, str]]:
    """Return {ip: (asn, as_name)} for the public IPs in `ips`."""
    public = sorted({ip for ip in ips if ip_kind(ip) == "public"})
    if not public:
        return {}
    if data_dir is not None and db_path(data_dir).exists():
        path = db_path(data_dir)
        db = _offline_cache.get(path) or _offline_cache.setdefault(path, OfflineASN(path))
        return {ip: r for ip in public if (r := db.get(ip))}
    if online:
        return _cymru(public, timeout)
    return {}


def _cymru(public: list[str], timeout: float) -> dict[str, tuple[str, str]]:
    query = "begin\nverbose\n" + "\n".join(public) + "\nend\n"
    try:
        with socket.create_connection((CYMRU_HOST, 43), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(query.encode())
            chunks = []
            while data := sock.recv(4096):
                chunks.append(data)
    except OSError:
        return {}
    result: dict[str, tuple[str, str]] = {}
    for line in b"".join(chunks).decode(errors="replace").splitlines():
        parts = [p.strip() for p in line.split("|")]
        # AS | IP | BGP Prefix | CC | Registry | Allocated | AS Name
        if len(parts) >= 7 and parts[0].isdigit():
            result[parts[1]] = (f"AS{parts[0]}", _clean_name(parts[6]))
    return result
