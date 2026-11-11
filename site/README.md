# site

The Via website: 1 static page that says what the workcenter is, with real
runs of its commands. Plain HTML, 1 stylesheet and 1 small script. No
framework and no install step. Vercel deploys it.

The look follows the apparatus site
(<https://github.com/reagent-systems/apparatus>): paper and ink, 1 ink-blue
accent, Inter at weights 400 and 500, no borders. The commands use the
system's monospace face, so the first load carries 1 font file.

## Commands

Run each from the repository's root.

```sh
python3 -m http.server 8000 --directory site    # the page at http://localhost:8000
sh site/build.sh out https://example.org        # the files a host serves, in out/
```

`site/build.sh OUT [ORIGIN]` copies what the site serves into `OUT`. `ORIGIN`
is the address the site is served at. The canonical link, the Open Graph
tags and the 404 page's base need an absolute address, and the script
writes it into them. Without `ORIGIN` it leaves those lines out, so no
deploy ships a made-up address. The script refuses a folder that is not
empty.

## What is where

| Path | Holds |
|---|---|
| `index.html` | The page: the sections in order. `%ORIGIN%` marks each line that needs the site's address. |
| `404.html` | The page a host serves for an unknown path. |
| `site.css` | The look: the colour tokens for light and dark, the type scale, every component. |
| `site.js` | The theme button and the copy button. |
| `favicon.svg` | The mark. It follows the system's colour scheme. |
| `favicon-32.png`, `apple-touch-icon.png` | The mark as PNG, for a browser that takes no SVG icon and for a phone's home screen. |
| `og.html` | The page the 2 images below are captures of. `og.html?dark` is the dark twin. |
| `og.png` | The Open Graph image, 1280 x 640. Also the image for the repository's social preview. |
| `og-dark.png` | The same in the dark theme, for the top of the root `README.md`. |
| `fonts/` | Inter, the latin file, with its license. |
| `build.sh` | Makes the folder a host serves. |
| `vercel.json` | The Vercel project's build command, output folder and headers. |

## The runs on the page

Each run on the page is what the command printed in a checkout of this
repository. `tests/test_docs.py` runs each command again and compares: only
the seconds and the checkout's folder may differ. When a gate's output
changes, the test names the line, and the page gets the new text.

## The images

Chromium draws them, so the type is Inter itself:

```sh
chromium --headless --hide-scrollbars --force-device-scale-factor=1 --window-size=1280,640 \
  --virtual-time-budget=4000 --screenshot=site/og.png "file://$PWD/site/og.html"
chromium --headless --hide-scrollbars --force-device-scale-factor=1 --window-size=1280,640 \
  --virtual-time-budget=4000 --screenshot=site/og-dark.png "file://$PWD/site/og.html?dark"
```

Draw both again when `og.html`, the mark or the run in it changes.

librsvg draws the 2 PNG icons from `favicon.svg`:

```sh
rsvg-convert -w 32 -h 32 site/favicon.svg -o site/favicon-32.png
rsvg-convert -w 112 -h 112 --page-width 180 --page-height 180 --left 34 --top 34 -b '#fbfaf7' \
  site/favicon.svg -o site/apple-touch-icon.png
```

GitHub shows a repository's social preview from an image its owner uploads:
Settings, General, Social preview. `og.png` is that image.

## Deploys

The Vercel project is `via`, and production is <https://via-kappa-five.vercel.app>. Its Root
Directory is `site`. `vercel.json` runs `build.sh` with the project's
production address and serves `dist/`. A push to `main` deploys
production, and a push to any other branch a preview. The project skips
a push that leaves `site/` unchanged.

Vercel makes a new project's first deployment its production deployment,
whatever branch it comes from. That is how this site went live from a
branch on 2026-11-11.

Any static host can serve the folder `build.sh` writes. For GitHub Pages,
give it the Pages address: `sh site/build.sh out https://<owner>.github.io/via`.

## What is not ours

| File | From | License |
|---|---|---|
| `fonts/inter-latin-wght-normal.woff2` | Inter, the latin subset of the variable font, from the npm package `@fontsource-variable/inter` 5.3.0 | SIL Open Font License 1.1, in `fonts/LICENSE` |
| The GitHub mark in `index.html` | Primer Octicons | MIT, © GitHub, Inc. |
