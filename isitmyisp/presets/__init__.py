"""Ready-made service checks ("is it my internet, or is ARCA down?"), one JSON file per region.

The files are data, meant to be edited by people who know the region: each entry says what exactly is
checked and why (some use TCP because the service's HTTPS can't be checked fairly, see the notes).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).parent


@dataclass(frozen=True)
class Preset:
    id: str
    group: str
    name: str
    kind: str      # http | tcp
    target: str
    what: dict     # {lang: explanation}


@lru_cache(maxsize=None)
def load(region: str = "ar") -> tuple[Preset, ...]:
    path = HERE / f"services_{region}.json"
    if not path.exists():
        return ()
    doc = json.loads(path.read_text(encoding="utf-8"))
    return tuple(Preset(p["id"], p["group"], p["name"], p["kind"], p["target"], p.get("what", {}))
                 for p in doc["presets"])


def grouped(region: str = "ar") -> list[tuple[str, list[Preset]]]:
    out: dict[str, list[Preset]] = {}
    for p in load(region):
        out.setdefault(p.group, []).append(p)
    return list(out.items())
