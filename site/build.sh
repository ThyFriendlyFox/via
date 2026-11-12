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
mkdir -p "$out/fonts" "$out/showcase/datasheets" "$out/vendor"

# What the site serves: the examples' pictures, Herald's 3D model and its datasheets' first pages,
# Motion, model-viewer and the meshopt decoder with their licenses. og.html, media/ (the README's
# pictures), the scripts that draw, vercel.json and each README.md stay in the repository.
for file in site.css site.js effects.js favicon.svg favicon-32.png apple-touch-icon.png og.png logo.svg \
  fonts/inter-latin-wght-normal.woff2 fonts/LICENSE \
  showcase/herald-top.png showcase/herald-layers.png showcase/herald.png showcase/herald-schematic.png \
  showcase/herald.glb \
  showcase/hush.png showcase/signet.png showcase/rosetta-iso.png showcase/wyvern-iso.png showcase/agentcast.png \
  vendor/motion-14.6.0.js vendor/MOTION-LICENSE.md vendor/model-viewer-4.4.0.min.js vendor/MODEL-VIEWER-LICENSE \
  vendor/meshopt_decoder-1.2.0.js vendor/MESHOPTIMIZER-LICENSE.md; do
  cp "$here/$file" "$out/$file"
done
cp "$here"/showcase/datasheets/*.png "$out/showcase/datasheets/"

# A host may keep a stylesheet or a script for hours while it asks again for each page: the custom
# domain keeps them 4 hours. Each page names them with their checksum, so a new page never runs with
# the last build's stylesheet.
css=$(cksum <"$here/site.css" | cut -d ' ' -f 1)
js=$(cksum <"$here/site.js" | cut -d ' ' -f 1)
fx=$(cksum <"$here/effects.js" | cut -d ' ' -f 1)
version="s|href=\"site.css\"|href=\"site.css?v=$css\"|; s|src=\"site.js\"|src=\"site.js?v=$js\"|; s|src=\"effects.js\"|src=\"effects.js?v=$fx\"|"

for page in index.html 404.html; do
  if [ -n "$origin" ]; then
    sed "s|%ORIGIN%|$origin|g; $version" "$here/$page" >"$out/$page"
  else
    sed "/%ORIGIN%/d; $version" "$here/$page" >"$out/$page"
  fi
done

if [ -n "$origin" ]; then
  echo "site/build.sh: the site for $origin is in $out"
else
  echo "site/build.sh: the site is in $out, with no canonical link and no Open Graph image: no ORIGIN was given"
fi
