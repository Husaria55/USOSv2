#!/usr/bin/env bash
# Kompiluje obie prezentacje. Przy pierwszym uruchomieniu pobiera tectonic
# do .tools/bin (bez sudo); pakiety LaTeX-a tectonic dociąga sam i trzyma w cache.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
tectonic="$root/.tools/bin/tectonic"
version="0.17.0"

if [ ! -x "$tectonic" ]; then
  mkdir -p "$root/.tools/bin"
  curl -sL "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%40$version/tectonic-$version-x86_64-unknown-linux-musl.tar.gz" \
    | tar xz -C "$root/.tools/bin"
fi

cd "$root/prezentacja"
for f in "${@:-prezentacja.tex prezentacja_krotka.tex}"; do
  for tex in $f; do
    "$tectonic" "$tex"
  done
done
