"""Small helpers to classify IP addresses."""

from __future__ import annotations

import ipaddress

CGNAT_V4 = ipaddress.ip_network("100.64.0.0/10")


def ip_kind(ip: str) -> str:
    """Return 'cgnat', 'private', 'public' or 'unknown' for an address string."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return "unknown"
    if addr.version == 4 and addr in CGNAT_V4:
        return "cgnat"
    if addr.is_private or addr.is_link_local or addr.is_loopback:
        return "private"
    if addr.is_global:
        return "public"
    return "unknown"


def is_ipv6(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).version == 6
    except ValueError:
        return False
