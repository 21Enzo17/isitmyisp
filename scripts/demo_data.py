"""Write a SYNTHETIC database (see isitmyisp/demo.py). Never publish a report built from it as evidence.

    python3 scripts/demo_data.py /tmp/demo.db
    isitmyisp report --db /tmp/demo.db --since 1d -o demo.html

To show the product, `isitmyisp demo` does this and serves the UI on it, live.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from isitmyisp.demo import build  # noqa: E402


def main(path: str, hours: float = 24.0, seed: int = 7, lang: str = "en") -> None:
    build(path, hours=hours, seed=seed, lang=lang).store.close()
    print(f"synthetic demo data written to {path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "demo.db")
