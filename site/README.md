# site

The Via website: 1 static page that says what the workcenter is, with real
runs of its commands and its example project, Rosetta. Plain HTML, 1
stylesheet, 2 small scripts and Motion. No framework and no install step.
Vercel deploys it.

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
| `index.html` | The page: the sections in order. `%ORIGIN%` marks each line that needs the site's address. `?theme=dark` and `?theme=light` ask for a theme; `?shot=diagram` shows the diagram alone, for a capture. |
| `404.html` | The page a host serves for an unknown path. |
| `site.css` | The look: the colour tokens for light and dark, the type scale, every component. `media/hero.html` takes its cards from it. |
| `site.js` | The theme button and the copy button. |
| `effects.js` | The motion, with Motion: the logo draws itself, sections rise into view, runs type out, the example's knob turns, the board leans toward the pointer and turns over. The head's script adds `motion` to `<html>` unless the reader asked for reduced motion or the page is a capture (`?shot=`); without Motion every element sits where it ends. The knob and the turn-over button work without Motion. |
| `vendor/` | Motion 14.6.0 (motion.dev), its UMD build from the npm package `motion`, and its MIT license. SHA256 `5cd165acfdf8e14ca5358c3d876142e5465419ee0d100bcf195da474cf8db2bf`. |
| `logo.svg` | The Via wordmark: V, I and A as copper, a pad on each and traces between. The header, the footer, the closing section and `og.html` draw it inline. |
| `showcase/` | The example's pictures: KiCad's 3D renders of Rosetta (`rosetta-top.png`, `rosetta-bottom.png`, `rosetta-iso.png`), its layers (`rosetta-layers.png`), and Agentcast's (`agentcast.png`, from its repository's v0.5). `draw_face.py` writes the board drawing into `index.html` between `face:begin` and `face:end`. |
| `favicon.svg` | The icon: the wordmark of `logo.svg`, centred in a square. It follows the system's colour scheme. |
| `favicon-32.png`, `apple-touch-icon.png` | The icon as PNG, for a browser that takes no SVG icon and for a phone's home screen. |
| `og.html` | The page the image below is a capture of. |
| `og.png` | The Open Graph image, 1280 x 640. Also the image for the repository's social preview. |
| `media/` | The pictures of the root `README.md`, with the page its first picture is a capture of. `media/README.md` shows each and the command that draws it. The site serves 2 of them, `schematic.png` and `board.png`: its board section shows them. |
| `fonts/` | Inter, the latin file, with its license. |
| `build.sh` | Makes the folder a host serves. |
| `vercel.json` | The Vercel project's build command, output folder and headers. |

## The runs on the page

Each run on the page is what the command printed in a checkout of this
repository. `tests/test_docs.py` runs each command again and compares: only
the seconds and the checkout's folder may differ. When a gate's output
changes, the test names the line, and the page gets the new text.

## The example's pictures

Run each from the repository's root, with KiCad 10 and the parts' 3D bodies
(`site/media/README.md` says how to fetch them). The drawing comes from the
design file and the routed board; draw it again when either changes:

```sh
python3 site/showcase/draw_face.py
```

The renders come from `workcenter render` on the example, cropped and
scaled with FFmpeg; `examples/universal-controller/v0.1/README.md` shows
them and names the commands.

## The images

Chromium draws the Open Graph image, so the type is Inter itself:

```sh
chromium --headless --hide-scrollbars --force-device-scale-factor=1 --window-size=1280,640 \
  --virtual-time-budget=4000 --screenshot=site/og.png "file://$PWD/site/og.html"
```

Draw it again when `og.html`, the wordmark or the run in it changes.

`favicon.svg` holds the paths of `logo.svg`. Copy them again when the
wordmark changes. librsvg draws the 2 PNG icons from `favicon.svg`:

```sh
rsvg-convert -w 32 -h 32 site/favicon.svg -o site/favicon-32.png
rsvg-convert -w 148 -h 148 --page-width 180 --page-height 180 --left 16 --top 16 -b '#fbfaf7' \
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
| `vendor/motion-14.6.0.js` | Motion 14.6.0, the npm package `motion` | MIT, © Motion B.V., in `vendor/MOTION-LICENSE.md` |
