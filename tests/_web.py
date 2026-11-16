"""Whether the web tests can run.

Without Flask they fail, so a missing web extra never passes as a quiet "OK". To test the core
alone on purpose (what release.sh does first), set ISITMYISP_CORE_ONLY=1 and they are skipped.
"""

import os

try:
    import flask  # noqa: F401
    HAVE_WEB = True
except ImportError:
    if os.environ.get("ISITMYISP_CORE_ONLY") != "1":
        raise ImportError("Flask is not installed: install the web extra (pip install -e '.[web]'), "
                          "or set ISITMYISP_CORE_ONLY=1 to skip the web tests on purpose") from None
    HAVE_WEB = False
