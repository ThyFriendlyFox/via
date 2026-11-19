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
mkdir -p "$out/fonts" "$out/showcase/datasheets" "$out/vendor" "$out/examples"

# What the site serves: the examples' pictures, Herald's 3D model and its datasheets' first pages,
# the agents' marks, Motion, model-viewer and the meshopt decoder with their licenses. og.html,
# media/ (the README's pictures), the scripts that draw the pictures and write the example pages,
# vercel.json and each README.md stay in the repository. api/ holds the forms' functions: Vercel
# builds them from the project's folder, not from OUT.
for file in site.css site.js effects.js example.js agents.svg favicon.svg favicon-32.png apple-touch-icon.png \
  og.png logo.svg fonts/inter-latin-wght-normal.woff2 fonts/LICENSE \
  showcase/herald-top.png showcase/herald-layers.png showcase/herald-schematic.png showcase/herald.glb \
  showcase/agentcast.png \
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
ex=$(cksum <"$here/example.js" | cut -d ' ' -f 1)
# X and Discord keep a shared link's picture by its address, for days: the Open Graph image is named
# with its checksum too, so a new picture is fetched anew.
og=$(cksum <"$here/og.png" | cut -d ' ' -f 1)
# An example's page names them from its folder, as ../site.css.
up='\(\(\.\./\)*\)'
version="s|href=\"${up}site.css\"|href=\"\1site.css?v=$css\"|; s|src=\"${up}site.js\"|src=\"\1site.js?v=$js\"|"
version="$version; s|src=\"${up}effects.js\"|src=\"\1effects.js?v=$fx\"|; s|src=\"${up}example.js\"|src=\"\1example.js?v=$ex\"|"
version="$version; s|/og.png\"|/og.png?v=$og\"|g"

# Each example's page and the files it shows, as site/examples.py writes them.
for folder in "$here"/examples/*/; do
  [ -d "$folder" ] || continue
  name=$(basename -- "$folder")
  mkdir -p "$out/examples/$name"
  cp "$folder"* "$out/examples/$name/"
done

# The blog's pages, as site/blog.py writes them, and any picture a post names from its folder.
mkdir -p "$out/blog"
for file in "$here"/blog/*; do
  case "$file" in
    *.html | */feed.xml) ;;
    *) [ -f "$file" ] && cp "$file" "$out/blog/" ;;
  esac
done
# The feed's addresses are whole, so it is served only from a build for an address.
if [ -n "$origin" ] && [ -f "$here/blog/feed.xml" ]; then
  sed "s|%ORIGIN%|$origin|g" "$here/blog/feed.xml" >"$out/blog/feed.xml"
fi

for path in "$here/index.html" "$here/404.html" "$here/examples.html" "$here"/examples/*.html "$here/blog.html" "$here"/blog/*.html \
  "$here/feedback.html" "$here/guide.html"; do
  [ -f "$path" ] || continue
  page=${path#"$here"/}
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
