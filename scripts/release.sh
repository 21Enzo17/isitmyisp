#!/bin/sh
# Cut a release from main: checks, multi-arch image on GHCR, git tag, GitHub release.
#
#   scripts/release.sh            # the version in pyproject.toml
#   scripts/release.sh --dry-run  # checks only, prints what it would publish
#
# Done by hand on purpose (CI is off, see #2). Once per machine:
#   gh auth refresh -s write:packages                       # permission to push images
#   gh auth token | docker login ghcr.io -u 21Enzo17 --password-stdin
#   docker run --privileged --rm tonistiigi/binfmt --install arm64   # build arm64 (Raspberry Pi) on amd64
#   docker buildx create --name iim --use
set -eu
cd "$(dirname "$0")/.."

IMAGE=ghcr.io/21enzo17/isitmyisp
DRY=0; [ "${1-}" = --dry-run ] && DRY=1

VERSION=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)
PKG=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' isitmyisp/__init__.py)
fail() { echo "✗ $*" >&2; exit 1; }

[ "$VERSION" = "$PKG" ] || fail "pyproject.toml says $VERSION, isitmyisp/__init__.py says $PKG"
case "$VERSION" in *dev*|*rc*|*a*|*b*) fail "$VERSION is not a release version" ;; esac
grep -q "^## \[$VERSION\]" CHANGELOG.md || fail "CHANGELOG.md has no '## [$VERSION]' section"
[ "$(git branch --show-current)" = main ] || fail "releases are cut from main"
[ -z "$(git status --porcelain)" ] || fail "the working tree has uncommitted changes"
git fetch -q origin main && [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || fail "main is not in sync with origin"
git rev-parse -q --verify "refs/tags/v$VERSION" >/dev/null && fail "tag v$VERSION already exists"

echo "→ tests"
python3 -m unittest discover -s tests -q 2>&1 | tail -1
[ -x .venv/bin/python ] && .venv/bin/python -m unittest discover -s tests -q 2>&1 | tail -1

NOTES=$(awk -v v="$VERSION" '$0 ~ "^## \\[" v "\\]" {on=1; next} /^## \[/ {on=0} /^\[.*\]: / {on=0} on' CHANGELOG.md)
echo "→ v$VERSION: $IMAGE:$VERSION and :latest (linux/amd64, linux/arm64)"
if [ "$DRY" = 1 ]; then
  printf '%s\n' "$NOTES" | head -12
  echo "(dry run: nothing published)"
  exit 0
fi

printf 'Publish v%s (image, tag, GitHub release)? [y/N] ' "$VERSION"
read -r ok; case "$ok" in [yY]*) ;; *) exit 1 ;; esac

docker buildx build --platform linux/amd64,linux/arm64 --build-arg "VERSION=$VERSION" \
  -t "$IMAGE:$VERSION" -t "$IMAGE:latest" --push .
git tag -a "v$VERSION" -m "isitmyisp $VERSION"
git push origin "v$VERSION"
printf '%s\n\nInstall: `curl -fsSL https://isitmyisp.enzo-meneghini.com/install.sh | sh`\nImage: `%s:%s`\n' \
  "$NOTES" "$IMAGE" "$VERSION" | gh release create "v$VERSION" --title "isitmyisp $VERSION" --notes-file -
echo "✓ released v$VERSION. Make the package public once: github.com/users/21Enzo17/packages/container/isitmyisp/settings"
