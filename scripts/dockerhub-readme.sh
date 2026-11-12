#!/bin/sh
# Put the README on the Docker Hub page (short description + full description), from this machine.
#
#     scripts/dockerhub-readme.sh
#
# Asks for a Docker Hub personal access token (hub.docker.com → Account settings → Personal access
# tokens, "Read & Write" is enough). It's read from the terminal, never stored and never printed.
# Relative links and images in the README point at GitHub, since Docker Hub can't resolve them.
set -eu

IMAGE=${IMAGE:-21enzo03/isitmyisp}
USER_HUB=${DOCKERHUB_USER:-${IMAGE%%/*}}
REPO_RAW="https://raw.githubusercontent.com/21Enzo17/isitmyisp/main"
REPO_WEB="https://github.com/21Enzo17/isitmyisp/blob/main"
SHORT="Is it your Wi-Fi, your router or your ISP? Self-hosted connection monitor with evidence reports."
cd "$(dirname "$0")/.."

printf 'Docker Hub token for %s: ' "$USER_HUB" > /dev/tty
stty -echo < /dev/tty; read -r TOKEN < /dev/tty; stty echo < /dev/tty; printf '\n' > /dev/tty
[ -n "$TOKEN" ] || { echo "no token" >&2; exit 1; }

TOKEN="$TOKEN" USER_HUB="$USER_HUB" IMAGE="$IMAGE" SHORT="$SHORT" REPO_RAW="$REPO_RAW" REPO_WEB="$REPO_WEB" \
python3 - <<'EOF'
import json, os, re, urllib.request

readme = open("README.md", encoding="utf-8").read()
raw, web = os.environ["REPO_RAW"], os.environ["REPO_WEB"]

def absolute(m):
    attr, url = m.group(1), m.group(2)
    if re.match(r"^(https?:|#|mailto:)", url):
        return m.group(0)
    is_img = attr in ("src", "srcset", "img")
    return m.group(0).replace(url, f"{raw if is_img else web}/{url}")

readme = re.sub(r'(src|srcset|href)="([^"]+)"', absolute, readme)                       # HTML
readme = re.sub(r'!\[[^\]]*\]\(([^)]+)\)', lambda m: m.group(0) if m.group(1).startswith("http")
                else m.group(0).replace(m.group(1), f"{raw}/{m.group(1)}"), readme)         # markdown images
readme = re.sub(r'(?<!!)\[([^\]]+)\]\((?!https?:|#|mailto:)([^)]+)\)', lambda m: f"[{m.group(1)}]({web}/{m.group(2)})", readme)

def call(url, data, token=None, method="POST"):
    req = urllib.request.Request(url, data=json.dumps(data).encode(), method=method,
                                 headers={"Content-Type": "application/json",
                                          **({"Authorization": f"Bearer {token}"} if token else {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

jwt = call("https://hub.docker.com/v2/users/login", {"username": os.environ["USER_HUB"],
                                                     "password": os.environ["TOKEN"]})["token"]
out = call(f"https://hub.docker.com/v2/repositories/{os.environ['IMAGE']}/",
           {"description": os.environ["SHORT"][:100], "full_description": readme}, jwt, "PATCH")
print(f"✓ Docker Hub updated: {out.get('description')!r}, README {len(out.get('full_description') or '')} characters")
EOF
