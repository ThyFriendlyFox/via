# site

The Via website: 1 static page that says what the workcenter is, with real
runs of its commands and its example projects. Plain HTML, 1
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
| `effects.js` | The motion, with Motion: the logo draws itself, sections rise into view, runs type out, the example's signals light their path on the board, the board leans toward the pointer and turns over. The head's script adds `motion` to `<html>` unless the reader asked for reduced motion or the page is a capture (`?shot=`); without Motion every element sits where it ends. The signal buttons and the turn-over button work without Motion. |
| `vendor/` | Motion 14.6.0 (motion.dev), its UMD build from the npm package `motion`, and its MIT license. SHA256 `5cd165acfdf8e14ca5358c3d876142e5465419ee0d100bcf195da474cf8db2bf`. |
| `logo.svg` | The Via wordmark: V, I and A as copper, a pad on each and traces between. The header, the footer, the closing section and `og.html` draw it inline. |
| `showcase/` | The examples' pictures: KiCad's 3D renders of Herald, the example the page shows (`herald-top.png`, `herald-bottom.png`) and its layers (`herald-layers.png`); a card for each example (`herald.png`, `hush.png`, `signet.png`, `rosetta-iso.png`) and Agentcast's (`agentcast.png`, from its repository's v0.5). `draw_face.py` writes Herald's board drawing into `index.html` between `face:begin` and `face:end`. |
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

## The examples' pictures

Run each from the repository's root, with KiCad 10. Herald's drawing comes
from its design file and its routed board; draw it again when either
changes:

```sh
python3 site/showcase/draw_face.py
```

Herald's renders come from `workcenter render` on the example
(`examples/fire-alarm-communicator/v0.1/README.md` names the command, and
`site/media/README.md` says how to fetch the parts' 3D bodies), cropped and
scaled with FFmpeg:

```sh
ffmpeg -i examples/fire-alarm-communicator/v0.1/docs/board-3d-top.png \
  -vf "crop=1228:780:170:100,scale=1200:762:flags=lanczos,format=rgb24" site/showcase/herald-top.png
ffmpeg -i examples/fire-alarm-communicator/v0.1/docs/board-3d-bottom.png \
  -vf "crop=1228:780:170:100,scale=1200:762:flags=lanczos,format=rgb24" site/showcase/herald-bottom.png
ffmpeg -i examples/fire-alarm-communicator/v0.1/docs/layers.png \
  -vf "scale=1200:-2:flags=lanczos,format=rgb24" site/showcase/herald-layers.png
```

Herald's, Hush's and Signet's cards are their own 3D renders, cropped to
the card's shape and scaled to 1000 x 571 with FFmpeg. Rosetta's card,
`rosetta-iso.png`, is the render its v0.2 drew for the page before Herald:

```sh
ffmpeg -i examples/ring-mouse/v0.4/docs/assembly-iso.png \
  -vf "crop=1330:760:130:105,scale=1000:571:flags=lanczos,format=rgb24" site/showcase/signet.png
ffmpeg -i examples/fire-alarm-communicator/v0.1/docs/board-3d-iso.png \
  -vf "crop=1500:857:34:127,scale=1000:571:flags=lanczos,format=rgb24" site/showcase/herald.png
ffmpeg -i examples/anc-speaker/v0.1/docs/assembly-iso.png \
  -vf "crop=1160:663:180:125,scale=1000:571:flags=lanczos,format=rgb24" site/showcase/hush.png
```

## A new example on the page

The section "Boards, not demos." (`id="built"`) holds 1 card for each
example. To add an example when it lands on `main`:

1. Crop the example's 3D render to 1.75 to 1 and scale it to 1000 x 571
   into `showcase/<name>.png`, with a command like the cards' above.
2. Add an `<a class="proj">` to the section. Its `href` is the example's
   README on GitHub. Its `<img>` states `width="1000" height="571"`, and
   its text says what the board is, then its size, layers and parts.
3. Add `showcase/<name>.png` to the file list in `build.sh`.
4. Add its FFmpeg command to the list above.
5. Run `python3 -m pytest tests/test_docs.py`. It checks each picture's
   stated size against the file, and each link of the built page.

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
