# site

The Via website: a home page that says what the workcenter is, with real
runs of its commands and drawings of what each gate catches, and a page for
each example project, written from the example's own files. Plain HTML, 1
stylesheet, 3 small scripts and Motion. No framework and no install step.
Vercel deploys it.

The look follows the apparatus site
(<https://github.com/reagent-systems/apparatus>): paper and ink, 1 steel-blue
accent, Inter at weights 400 and 500, no borders. The drawings and the agents'
strip follow the text-to-cad site (<https://www.texttocad.dev>): ink on
dotted paper, a file's name under each drawing, blue for a dimension or a
bound and red for what a check caught. The commands use the system's
monospace face, so the first load carries 1 font file.

## Commands

Run each from the repository's root.

```sh
python3 -m http.server 8000 --directory site    # the site at http://localhost:8000
python3 site/examples.py                         # the example pages, from the examples' files
python3 site/examples.py --check                 # exit 1 when a page is not what the script writes
python3 site/examples.py --pictures              # also the examples' 3D pictures (numpy, Pillow)
sh site/build.sh out https://example.org         # the files a host serves, in out/
```

`site/build.sh OUT [ORIGIN]` copies what the site serves into `OUT`. `ORIGIN`
is the address the site is served at. The canonical links, the Open Graph
tags and the 404 page's base need an absolute address, and the script
writes it into them. Without `ORIGIN` it leaves those lines out, so no
deploy ships a made-up address. The script refuses a folder that is not
empty.

## What is where

| Path | Holds |
|---|---|
| `index.html` | The home page: the hero, the agents, the gates, the examples, design as code, how a run goes, run it. `%ORIGIN%` marks each line that needs the site's address. `?theme=dark` and `?theme=light` ask for a theme; `?shot=diagram` shows the diagram alone, for a capture. |
| `examples.html`, `examples/<name>.html` | The list of examples, and 1 page for each. `examples.py` writes them; do not edit them by hand. |
| `examples/<name>/` | What an example's page shows: `board.svg`, the board drawn from its file for the explorer; `spin.webp`, the turntable's 36 views side by side; `top.png`, `bottom.png` and `iso.png`, KiCad's renders with the backdrop taken out. |
| `examples.py` | Writes the example pages. "The example pages" below says what it reads. |
| `404.html` | The page a host serves for an unknown path. |
| `site.css` | The look: the colour tokens for light and dark, the type scale, every component. `media/hero.html` takes its cards from it. |
| `site.js` | The theme button, the copy button, and the agents' strip: it drifts sideways, rests under a pointer, a finger or the focus, and a mouse, a swipe or the arrow keys move it. |
| `effects.js` | The motion, with Motion: the wordmark is built as a board is (sketched, its corners set, its copper laid, its traces run), drawings draw themselves, sections rise into view, runs type out, the example's knob turns. The head's script adds `motion` to `<html>` unless the reader asked for reduced motion or the page is a capture (`?shot=`); without Motion every element sits where it ends. The knob works without Motion. |
| `example.js` | An example page's turntable, which a drag or the arrow keys turn, and its board explorer: layers on and off, zoom and pan, a net followed, a part named. |
| `agents.svg` | The marks of the 21 agents in the strip, 1 symbol each, drawn in the text colour. "What is not ours" names where each comes from. |
| `vendor/` | Motion 14.6.0 (motion.dev), its UMD build from the npm package `motion`, and its MIT license. SHA256 `5cd165acfdf8e14ca5358c3d876142e5465419ee0d100bcf195da474cf8db2bf`. |
| `logo.svg` | The Via wordmark: V, I and A as copper, a pad on each and traces between. Every page's header and footer, the hero, the closing section, `og.html` and `media/hero.html` draw it inline. |
| `showcase/` | The home page's cards: `rosetta-iso.png` (also the root README's picture), `agentcast.png` (from its repository's v0.5) and `fixture.png` (a view of the first fixture board), each with KiCad's backdrop taken out by `key.py`. `rosetta-knob.html` is the part of Rosetta's page with the knob; `draw_face.py` writes its board drawing between `face:begin` and `face:end`. |
| `favicon.svg` | The icon: the wordmark of `logo.svg`, centred in a square. It follows the system's colour scheme. |
| `favicon-32.png`, `apple-touch-icon.png` | The icon as PNG, for a browser that takes no SVG icon and for a phone's home screen. |
| `og.html` | The page the image below is a capture of. |
| `og.png` | The Open Graph image, 1280 x 640. Also the image for the repository's social preview. |
| `media/` | The pictures of the root `README.md`, with the page its first picture is a capture of. `media/README.md` shows each and the command that draws it. The site serves 2 of them, `schematic.png` and `board.png`: its design section shows them. |
| `fonts/` | Inter, the latin file, with its license. |
| `build.sh` | Makes the folder a host serves. |
| `vercel.json` | The Vercel project's build command, output folder and headers. |

## The runs on the pages

Each run on a page is what the command printed in a checkout of this
repository. `tests/test_docs.py` runs each command again and compares: only
the seconds and the checkout's folder may differ. When a gate's output
changes, the test names the line, and the page gets the new text.

## The drawings of the gates

Each drawing on the home page shows a board in the repository that a gate
stopped, and names it under the drawing. A value it marks, such as 0.4216 V
or 15.9 kHz, is a number in that board's files, in `tests/boards/README.md`,
or in a run the page shows, to the places the drawing gives:
`tests/test_docs.py` holds each one to its source. An axis's tick is marked
`tick` and is not held.

## The example pages

An example is a folder `examples/<name>/<version>/` that holds a README.md;
its newest version is the one shown. `examples.py` reads:

- From the README: the title (`# Rosetta v0.1: a universal game controller`
  gives the name, the version and the line under the name), the first
  paragraph, the table under "What is hard about it" and the list under
  "What is open".
- From `TIMELINE.md`, when there is one: each `## <date> · <stage> · <title>`
  entry, in order, with its paragraphs. A paragraph that starts with
  `Evidence:` is set small. A fenced `workcenter gates` run is shown as it
  stands, and its last line is the verdict on the page.
- From the board (`*.kicad_pcb`): the size of its outline, its copper
  layers, its parts, tracks and vias, and the drawing the explorer shows.
- `showcase/<name>-knob.html`, when there is one: a part of the page
  written for that example.

To add an example: put its version folder under `examples/`, with its
README, its TIMELINE.md and its pictures in `docs/` (`workcenter render`
writes them), then run `python3 site/examples.py --pictures`, and link its
card from `index.html`. A host serves the page at `/examples/<name>`;
its files sit beside it in `examples/<name>/`, so a link from it reads the
same with the `.html` and without.

## The example's pictures

Run each from the repository's root, with KiCad 10 and the parts' 3D bodies
(`site/media/README.md` says how to fetch them). The knob's drawing comes
from the design file and the routed board; draw it again when either
changes, then write the pages again:

```sh
python3 site/showcase/draw_face.py
python3 site/examples.py
```

The renders come from `workcenter render` on the example, in its `docs/`.
`python3 site/examples.py --pictures` takes KiCad's backdrop out of them,
crops and scales them, and lays the turntable's frames side by side. The
home page's cards are keyed the same way, 1 picture at a time:

```sh
python3 site/showcase/key.py site/media/board-spin.gif site/showcase/fixture.png --frame 3
```

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
| The GitHub mark in the pages | Primer Octicons | MIT, © GitHub, Inc. |
| `vendor/motion-14.6.0.js` | Motion 14.6.0, the npm package `motion` | MIT, © Motion B.V., in `vendor/MOTION-LICENSE.md` |
| `agents.svg`: 18 marks | Lobe Icons, the npm package `@lobehub/icons-static-svg` 1.102.0: Claude Code, Codex, Cursor, Gemini, Grok, GitHub Copilot, Windsurf, Cline, AMP, Antigravity, OpenClaw, Goose, Kilo, Kiro CLI, Hermes (Nous Research's mark), OpenCode, Roo, Trae | MIT, © LobeHub |
| `agents.svg`: Zed | Simple Icons, the npm package `simple-icons` 16.37.0 | CC0 1.0 |
| `agents.svg`: VS Code | Codicons, the npm package `@vscode/codicons` 0.0.46-24 | CC BY 4.0, © Microsoft Corporation |
| `agents.svg`: Droid | text-to-cad, `apps/docs/public/agents/droid.svg` (<https://github.com/earthtojake/text-to-cad>) | MIT, © Thompson Labs LLC |

Each agent's mark is its maker's trademark. The strip names the agents Via
works with; no maker endorses Via.
