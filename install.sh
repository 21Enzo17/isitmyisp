#!/bin/sh
# isitmyisp installer: runs the monitor in Docker with the documented flags, and nothing else.
#
#   curl -fsSL https://isitmyisp.enzo-meneghini.com/install.sh | sh
#
# It shows every command before running it and asks first. Run it again to update: the data lives in
# a Docker volume and is kept. Read it before piping it into a shell; it's short on purpose.
#
# Options:
#   -y, --yes           don't ask (for scripts)
#   --local             dashboard only on this machine (default: reachable from your LAN, port 8080)
#   --port N            dashboard port (default 8080)
#   --lang es|en        interface language (default: from $LANG)
#   --tz ZONE           time zone for reports (default: this machine's)
#   --version X         image version (default: latest release)
#   --build             build the image from the source instead of downloading it
#   --name / --volume   container and volume names (default isitmyisp)
#   --dry-run           print the commands, run nothing
#   --uninstall         remove the container (the data volume is kept; it says how to delete it)
set -eu

REPO="https://github.com/21Enzo17/isitmyisp.git"
IMAGE_REPO="docker.io/21enzo03/isitmyisp"
NAME=isitmyisp VOLUME=isitmyisp PORT=8080 LAN=1 YES=0 DRY=0 BUILD=0 UNINSTALL=0 VERSION=latest
LANG_UI="" TZ_UI=""

case "${LANG:-}" in es*) ES=1 ;; *) ES=0 ;; esac
say() { if [ "$ES" = 1 ]; then printf '%s\n' "$2"; else printf '%s\n' "$1"; fi; }
die() { say "✗ $1" "✗ $2" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    -y|--yes) YES=1 ;;
    --local) LAN=0 ;;
    --lan) LAN=1 ;;
    --port) PORT="$2"; shift ;;
    --lang) LANG_UI="$2"; shift ;;
    --tz) TZ_UI="$2"; shift ;;
    --version) VERSION="$2"; shift ;;
    --build) BUILD=1 ;;
    --name) NAME="$2"; shift ;;
    --volume) VOLUME="$2"; shift ;;
    --dry-run) DRY=1 ;;
    --uninstall) UNINSTALL=1 ;;
    -h|--help) sed -n '2,21p' "$0" 2>/dev/null | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown option: $1" "opción desconocida: $1" ;;
  esac
  shift
done

case "$PORT" in ''|*[!0-9]*) die "--port must be a number" "--port tiene que ser un número" ;; esac
[ -n "$LANG_UI" ] || { [ "$ES" = 1 ] && LANG_UI=es || LANG_UI=en; }
case "$LANG_UI" in es) ES=1 ;; en) ES=0 ;; *) die "--lang must be es or en" "--lang tiene que ser es o en" ;; esac

# Answers come from the terminal even when the script itself arrives through a pipe.
ask() {
  [ "$YES" = 1 ] && return 0
  [ "$DRY" = 1 ] && return 0
  # /dev/tty can exist and still fail to open (no controlling terminal: cron, CI, ssh without -t),
  # so try opening it (in a subshell: a failed redirection can end the script) instead of trusting -r
  if (: < /dev/tty) 2>/dev/null; then
    printf '%s ' "$1" > /dev/tty
    read -r answer < /dev/tty || answer=n
  else
    die "no terminal to ask on: run again with -y to accept" "no hay terminal para preguntar: volvé a correrlo con -y para aceptar"
  fi
  case "$answer" in ''|[yYsS]*) return 0 ;; *) return 1 ;; esac
}

# docker, with sudo when this user can't reach the daemon; show() prints a command, dk_run() also runs it
dk() { if [ -n "$SUDO" ]; then sudo docker "$@"; else docker "$@"; fi; }
show() { printf '  $ %sdocker %s\n' "${SUDO:+sudo }" "$*"; }
dk_run() { show "$@"; [ "$DRY" = 1 ] || dk "$@"; }

[ "$(uname -s)" = Linux ] || die "isitmyisp measures from a Linux machine (a Raspberry Pi, a mini PC, a server)." \
                                 "isitmyisp mide desde una máquina Linux (una Raspberry Pi, una mini PC, un servidor)."

SUDO=""
docker_ok() { docker info >/dev/null 2>&1; }

# ------------------------------------------------------------------ Docker
if ! command -v docker >/dev/null 2>&1; then
  say "Docker is not installed. The official installer (get.docker.com) supports Raspberry Pi OS, Debian and Ubuntu:" \
      "Docker no está instalado. El instalador oficial (get.docker.com) sirve para Raspberry Pi OS, Debian y Ubuntu:"
  printf '  $ curl -fsSL https://get.docker.com | sudo sh\n'
  if ask "$(say 'Install Docker now? [Y/n]' '¿Instalar Docker ahora? [S/n]')"; then
    [ "$DRY" = 1 ] || { curl -fsSL https://get.docker.com | sudo sh; }
  else
    die "Docker is needed. Install it and run this again." "Hace falta Docker. Instalalo y volvé a correr esto."
  fi
fi
if [ "$DRY" = 0 ] && ! docker_ok; then
  if command -v sudo >/dev/null 2>&1 && sudo docker info >/dev/null 2>&1; then
    SUDO="sudo"
    say "(using sudo for docker: add yourself to the docker group to avoid it)" \
        "(uso sudo para docker: sumate al grupo docker para no necesitarlo)"
  else
    die "Docker is installed but not running (try: sudo systemctl start docker)." \
        "Docker está instalado pero no corre (probá: sudo systemctl start docker)."
  fi
fi

# ------------------------------------------------------------------ uninstall
if [ "$UNINSTALL" = 1 ]; then
  say "This removes the container \"$NAME\". The measurements stay in the volume \"$VOLUME\"." \
      "Esto borra el contenedor \"$NAME\". Las mediciones quedan en el volumen \"$VOLUME\"."
  ask "$(say 'Continue? [Y/n]' '¿Seguir? [S/n]')" || exit 1
  dk_run rm -f "$NAME"
  say "To delete the data too (it can't be undone):  docker volume rm $VOLUME" \
      "Para borrar también los datos (no se puede deshacer):  docker volume rm $VOLUME"
  exit 0
fi

# ------------------------------------------------------------------ settings
if [ -z "$TZ_UI" ]; then
  TZ_UI=$(timedatectl show -p Timezone --value 2>/dev/null || true)
  [ -n "$TZ_UI" ] || TZ_UI=$(cat /etc/timezone 2>/dev/null || true)
  [ -n "$TZ_UI" ] || TZ_UI=$(readlink /etc/localtime 2>/dev/null | sed 's|.*/zoneinfo/||' || true)
  [ -n "$TZ_UI" ] || TZ_UI=UTC
fi
if [ "$LAN" = 1 ]; then BIND="0.0.0.0:$PORT"; else BIND="127.0.0.1:$PORT"; fi
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
[ -n "$IP" ] || IP=127.0.0.1
[ "$LAN" = 1 ] || IP=127.0.0.1

if [ "$BUILD" = 1 ]; then
  IMAGE="isitmyisp:local"
else
  IMAGE="$IMAGE_REPO:$VERSION"
fi

# the one container, always started the same way (used to show it and to run it)
start() {
  set -- run -d --name "$NAME" --restart unless-stopped --net=host --cap-add=NET_RAW \
    -e "TZ=$TZ_UI" -e "ISITMYISP_HEALTH_URL=http://127.0.0.1:$PORT/healthz" -v "$VOLUME:/data"
  [ -d /run/systemd/resolve ] && set -- "$@" -v /run/systemd/resolve:/run/systemd/resolve:ro
  set -- "$@" "$IMAGE" --lang "$LANG_UI" monitor --web "$BIND"
  show "$@"
  [ "${SHOW_ONLY:-0}" = 1 ] || [ "$DRY" = 1 ] || dk "$@" >/dev/null
}
SRC="$REPO"; [ "$VERSION" = latest ] || SRC="$REPO#v${VERSION#v}"

say "" ""
say "isitmyisp will run like this:" "isitmyisp va a correr así:"
say "  - network: the host's (--net=host), to see your real router and path" \
    "  - red: la del equipo (--net=host), para ver tu router y tu camino reales"
say "  - ping permission (NET_RAW); nothing else from the host, no privileged mode" \
    "  - permiso para hacer ping (NET_RAW); nada más del equipo, sin modo privilegiado"
say "  - data in the Docker volume \"$VOLUME\" (kept on updates)" \
    "  - datos en el volumen de Docker \"$VOLUME\" (se conservan al actualizar)"
if [ "$LAN" = 1 ]; then
  say "  - dashboard on your LAN: http://$IP:$PORT (login required; --local to keep it on this machine)" \
      "  - panel en tu red local: http://$IP:$PORT (con usuario y contraseña; --local para dejarlo solo en este equipo)"
else
  say "  - dashboard only on this machine: http://127.0.0.1:$PORT" \
      "  - panel solo en este equipo: http://127.0.0.1:$PORT"
fi
say "  - time zone $TZ_UI, language $LANG_UI" "  - zona horaria $TZ_UI, idioma $LANG_UI"
say "" ""
if [ "$BUILD" = 1 ]; then show build -t "$IMAGE" "$SRC"; else show pull "$IMAGE"; fi
dk inspect "$NAME" >/dev/null 2>&1 && show rm -f "$NAME"
SHOW_ONLY=1 start
say "" ""
ask "$(say 'Go ahead? [Y/n]' '¿Avanzo? [S/n]')" || exit 1

# ------------------------------------------------------------------ image
if [ "$BUILD" = 0 ] && ! dk_run pull "$IMAGE"; then
  say "No published image for this machine yet: building it from the source (a few minutes on a Raspberry Pi)." \
      "Todavía no hay imagen publicada para este equipo: la construyo desde el código (unos minutos en una Raspberry Pi)."
  BUILD=1 IMAGE="isitmyisp:local"
fi
[ "$BUILD" = 1 ] && dk_run build -t "$IMAGE" "$SRC"

# ------------------------------------------------------------------ (re)start
if dk inspect "$NAME" >/dev/null 2>&1; then show rm -f "$NAME"; [ "$DRY" = 1 ] || dk rm -f "$NAME" >/dev/null; fi
start
[ "$DRY" = 1 ] && exit 0

say "Starting (up to 2 minutes)…" "Arrancando (hasta 2 minutos)…"
i=0
until [ "$(dk inspect -f '{{.State.Health.Status}}' "$NAME" 2>/dev/null)" = healthy ]; do
  i=$((i + 1))
  if [ $i -gt 60 ] || [ "$(dk inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null)" != true ]; then
    dk logs --tail 30 "$NAME" >&2 || true
    die "it didn't start; the last lines of its log are above." "no arrancó; arriba están las últimas líneas de su registro."
  fi
  sleep 2
done

TOKEN=$(dk logs "$NAME" 2>&1 | sed -n 's/.*setup?token=\([A-Za-z0-9_-]*\).*/\1/p' | tail -1)
say "" ""
say "✓ isitmyisp is measuring." "✓ isitmyisp está midiendo."
if [ -n "$TOKEN" ]; then
  say "Open this link to create the admin account and finish the setup (valid 24 h):" \
      "Abrí este link para crear la cuenta de administrador y terminar la configuración (vale 24 h):"
  say "  http://$IP:$PORT/setup?token=$TOKEN" "  http://$IP:$PORT/setup?token=$TOKEN"
else
  say "Dashboard: http://$IP:$PORT" "Panel: http://$IP:$PORT"
fi
say "Update later: run this installer again. Logs: docker logs -f $NAME" \
    "Para actualizar: volvé a correr este instalador. Registro: docker logs -f $NAME"
