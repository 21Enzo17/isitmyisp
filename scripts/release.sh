#!/bin/sh
# Cut a release from main, from this machine: checks, the multi-arch image on Docker Hub, the git tag,
# and (when GitHub allows it) a GitHub release.
#
#   scripts/release.sh            # the version in pyproject.toml
#   scripts/release.sh --dry-run  # checks only, prints what it would publish
#   scripts/release.sh --yes      # no question before publishing (from a script, or with no terminal)
#
# Done by hand on purpose (CI is off, see #2). Once per machine:
#   docker login                                                     # your Docker Hub account
#   docker run --privileged --rm tonistiigi/binfmt --install arm64   # build arm64 (Raspberry Pi) on amd64
#   docker buildx create --name iim --use
set -eu
cd "$(dirname "$0")/.."

IMAGE=${IMAGE:-docker.io/21enzo03/isitmyisp}   # the one place the image name lives (install.sh reads the same)
DRY=0; YES=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY=1 ;;
    --yes|-y) YES=1 ;;
    *) echo "✗ unknown option: $arg (use --dry-run or --yes)" >&2; exit 2 ;;
  esac
done

VERSION=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)
PKG=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' isitmyisp/__init__.py)
fail() { echo "✗ $*" >&2; exit 1; }

# The question before publishing needs a terminal. Without one (a script, a background job) say so now,
# not after the tests, when "read" would get nothing and the release would silently not happen.
[ "$DRY" = 1 ] || [ "$YES" = 1 ] || [ -t 0 ] || fail "no terminal to ask before publishing: run it with --yes, or --dry-run to check"

[ "$VERSION" = "$PKG" ] || fail "pyproject.toml says $VERSION, isitmyisp/__init__.py says $PKG"
case "$VERSION" in *dev*|*rc*|*a*|*b*) fail "$VERSION is not a release version" ;; esac
grep -q "^## \[$VERSION\]" CHANGELOG.md || fail "CHANGELOG.md has no '## [$VERSION]' section"
[ "$(git branch --show-current)" = main ] || fail "releases are cut from main"
[ -z "$(git status --porcelain)" ] || fail "the working tree has uncommitted changes"
git fetch -q origin main && [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || fail "main is not in sync with origin"
git rev-parse -q --verify "refs/tags/v$VERSION" >/dev/null && fail "tag v$VERSION already exists"

# Two runs, and either one failing stops the release. unittest's own exit code decides: the output goes
# to a file, never through a pipe, whose status would be the last command's.
[ -x .venv/bin/python ] || fail "no .venv: the web tests need it (python3 -m venv .venv && .venv/bin/pip install -e '.[web]')"
LOG=$(mktemp); trap 'rm -f "$LOG"' EXIT
run_tests() {   # label, python, extra env
  if env $3 "$2" -m unittest discover -s tests -t . -q >"$LOG" 2>&1; then
    echo "  $1: $(grep -E '^(OK|Ran)' "$LOG" | tr '\n' ' ')"
  else
    cat "$LOG" >&2; fail "tests failed ($1)"
  fi
}
echo "→ tests"
run_tests "core only, without the web extra" python3 ISITMYISP_CORE_ONLY=1
run_tests "with the web extra" .venv/bin/python ""

NOTES=$(awk -v v="$VERSION" '$0 ~ "^## \\[" v "\\]" {on=1; next} /^## \[/ {on=0} /^\[.*\]: / {on=0} on' CHANGELOG.md)
echo "→ v$VERSION: $IMAGE:$VERSION and :latest (linux/amd64, linux/arm64)"
if [ "$DRY" = 1 ]; then
  printf '%s\n' "$NOTES" | head -12
  echo "(dry run: nothing published)"
  exit 0
fi

if [ "$YES" = 0 ]; then
  printf 'Publish v%s (image on Docker Hub, git tag)? [y/N] ' "$VERSION"
  read -r ok || ok=
  case "$ok" in [yY]*) ;; *) fail "not published (answered '${ok}')" ;; esac
fi
docker buildx inspect iim >/dev/null 2>&1 || docker buildx create --name iim --use >/dev/null
docker buildx use iim

docker buildx build --platform linux/amd64,linux/arm64 --build-arg "VERSION=$VERSION" \
  -t "$IMAGE:$VERSION" -t "$IMAGE:latest" --push .
git tag -a "v$VERSION" -m "isitmyisp $VERSION"
git push origin "v$VERSION"
printf '%s\n\nInstall: `curl -fsSL https://isitmyisp.enzo-meneghini.com/install.sh | sh`\nImage: `%s:%s`\n' \
  "$NOTES" "$IMAGE" "$VERSION" | gh release create "v$VERSION" --title "isitmyisp $VERSION" --notes-file - \
  || echo "(GitHub didn't take the release; the image and the tag are published, that's what matters)"
echo "✓ released v$VERSION: $IMAGE:$VERSION"
