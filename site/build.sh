#!/bin/sh
# site/build.sh OUT [ORIGIN]
#
# Copies the files the site serves into OUT. ORIGIN is the address the site
# is served at, for example https://example.org or https://owner.github.io/via.
# The canonical link, the Open Graph tags and the 404 page's base need an
# absolute address. Without ORIGIN those lines are left out, so no deploy
# ships a made-up address.
set -eu

usage="usage: site/build.sh OUT [ORIGIN]"
out=${1:?$usage}
given=${2:-}
origin=${given%/}

case "$origin" in
  "") ;;
  *[!A-Za-z0-9.:/_~-]*)
    echo "site/build.sh: ORIGIN holds a character an address does not need: $given" >&2
    exit 2
    ;;
  http://?* | https://?*) ;;
  *)
    echo "site/build.sh: ORIGIN starts with http:// or https://, then a host. It is: $given" >&2
    exit 2
    ;;
esac

if [ -e "$out" ] && [ -n "$(ls -A "$out" 2>/dev/null)" ]; then
  echo "site/build.sh: $out is not empty. Name a new folder, or empty this one first." >&2
  exit 2
fi

here=$(dirname -- "$0")
mkdir -p "$out/fonts" "$out/media" "$out/showcase" "$out/vendor" "$out/examples"

# What the site serves: of media/, the 2 pictures the page shows; the cards' pictures; the agents'
# marks; Motion and its license. og.html, the README's other pictures, the scripts that draw the
# pictures and write the example pages, vercel.json and each README.md stay in the repository.
for file in site.css site.js effects.js example.js agents.svg favicon.svg favicon-32.png apple-touch-icon.png \
  og.png logo.svg fonts/inter-latin-wght-normal.woff2 fonts/LICENSE media/schematic.png media/board.png \
  showcase/agentcast.png showcase/fixture.png vendor/motion-14.6.0.js vendor/MOTION-LICENSE.md; do
  cp "$here/$file" "$out/$file"
done

# Each example's page and the files it shows, as site/examples.py writes them.
for folder in "$here"/examples/*/; do
  [ -d "$folder" ] || continue
  name=$(basename -- "$folder")
  mkdir -p "$out/examples/$name"
  cp "$folder"* "$out/examples/$name/"
done

for path in "$here/index.html" "$here/404.html" "$here/examples.html" "$here"/examples/*.html; do
  [ -f "$path" ] || continue
  page=${path#"$here"/}
  if [ -n "$origin" ]; then
    sed "s|%ORIGIN%|$origin|g" "$here/$page" >"$out/$page"
  else
    sed '/%ORIGIN%/d' "$here/$page" >"$out/$page"
  fi
done

if [ -n "$origin" ]; then
  echo "site/build.sh: the site for $origin is in $out"
else
  echo "site/build.sh: the site is in $out, with no canonical link and no Open Graph image: no ORIGIN was given"
fi
