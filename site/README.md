# site

The Via website: a home page that says what Via does for the person
reading it, shown on its example projects and on real runs of its
commands, and a page for each example project, written from the example's
own files. Plain HTML, 1 stylesheet, 3 small scripts, Motion, and
model-viewer for the 3D board, loaded only as the reader nears it. No
framework and no install step. Vercel deploys it. Its words follow the
website section of `ee-agent-kit/docs/STYLE.md`: plain headlines that say
what the reader gets, no slogans, and an example project, not a fixture
board, as the thing it shows.

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
| `index.html` | The home page: the hero (the wordmark built as a board is, the owner's headline, the install line and the agents' strip), Herald, the boards, the checks, design as code, the architecture and getting started. `%ORIGIN%` marks each line that needs the site's address. `?theme=dark` and `?theme=light` ask for a theme; `?shot=diagram` shows the diagram alone, for a capture. |
| `examples.html`, `examples/<name>.html` | The list of examples, and 1 page for each. `examples.py` writes them; do not edit them by hand. |
| `examples/<name>/` | What an example's page shows: `board.svg`, the board drawn from its file for the explorer; `spin.webp`, the turntable's views side by side; `top.png`, `bottom.png` and `iso.png`, KiCad's renders with the backdrop taken out; `card.png`, the picture on its card (the assembly where there is one); `pictures.json`, the render each came from and the turntable's frames. |
| `examples.py` | Writes the example pages. "The example pages" below says what it reads. |
| `404.html` | The page a host serves for an unknown path. |
| `site.css` | The look: the colour tokens for light and dark, the type scale, every component. `media/hero.html` takes its cards from it. |
| `site.js` | The theme button, the copy button, and the agents' strip: it drifts sideways, rests under a pointer, a finger or the focus, and a mouse, a swipe or the arrow keys move it. |
| `effects.js` | The motion, with Motion: the hero's wordmark is built as a board is (sketched, its corners set, its copper laid, its traces run), the gates' drawings draw themselves, the logo draws itself, sections rise into view, runs type out, the example's copper sweeps in a layer at a time, and the board leans toward the pointer. Its parts' labels come in 1 every 3 seconds while the board is on screen, a group at a time, each with a leader from its part: a diagonal, then a level run to the label. A click on a part shows its group's labels at once. The head's script adds `motion` to `<html>` unless the reader asked for reduced motion or the page is a capture (`?shot=`); without Motion every element sits where it ends, and the labels still come in. It also loads the 3D board: when the renders' section comes within 600 px of the screen, it loads model-viewer and the meshopt decoder, then `showcase/herald.glb`, and shows the model over its picture once it has drawn. Until then, and if any of it fails, the picture stays. |
| `example.js` | An example page's turntable, which a drag or the arrow keys turn, and its board explorer: layers on and off, zoom and pan, a net followed, a part named. |
| `agents.svg` | The marks of the 21 agents in the strip, 1 symbol each, drawn in the text colour. "What is not ours" names where each comes from. |
| `vendor/` | Motion 14.6.0 (motion.dev), its UMD build from the npm package `motion`, with its MIT license, SHA256 `5cd165acfdf8e14ca5358c3d876142e5465419ee0d100bcf195da474cf8db2bf`. model-viewer 4.4.0 (modelviewer.dev), `dist/model-viewer-umd.min.js` from the npm package `@google/model-viewer`, with its Apache-2.0 license, SHA256 `d785423b1d046ea84a9f59ef6cf15f3077603e1bf938b01ced9b0240691884a2`. The meshopt decoder 1.2.0, `meshopt_decoder.cjs` from the npm package `meshoptimizer`, with its MIT license, SHA256 `fedf06f101ff2ba59d66335578230b7e8f5fac5057dee084be64c67444ac6c12`. |
| `logo.svg` | The Via wordmark: V, I and A as copper, a pad on each and traces between. Every page's header and footer, the hero, the closing section, `og.html` and `media/hero.html` draw it inline. |
| `showcase/` | The examples' pictures: Herald, the example the page shows, as a 3D model (`herald.glb`, 0.6 MB) with KiCad's render of its top as the model's picture until it loads (`herald-top.png`), its layers (`herald-layers.png`) and its supervised inputs from its schematic (`herald-schematic.png`); `herald.png`, the picture `og.html` shows; `rosetta-iso.png` and `wyvern-iso.png`, which the root README shows; and Agentcast's card (`agentcast.png`, from its repository's v0.5, its backdrop taken out by `key.py`). The other cards show `examples/<name>/card.png`. `draw_face.py` writes Herald's board drawing into `index.html` between `face:begin` and `face:end`, with the label of each part as JSON (`#herald-parts`). `datasheets.py` draws the first page of each part's datasheet into `datasheets/`, 160 px wide, for its label. `make_glb.mjs` writes `herald.glb`. |
| `favicon.svg` | The icon: the wordmark of `logo.svg`, centred in a square. It follows the system's colour scheme. |
| `favicon-32.png`, `apple-touch-icon.png` | The icon as PNG, for a browser that takes no SVG icon and for a phone's home screen. |
| `og.html` | The page the image below is a capture of. |
| `og.png` | The Open Graph image, 1280 x 640. Also the image for the repository's social preview. |
| `media/` | The pictures of the root `README.md`, with the page its first picture is a capture of. `media/README.md` shows each and the command that draws it. The site serves none of them: they show a fixture board, and the site shows Herald. |
| `fonts/` | Inter, the latin file, with its license. |
| `build.sh` | Makes the folder a host serves. It names `site.css`, `site.js` and `effects.js` with their checksum (`site.css?v=...`): the custom domain's cache keeps them 4 hours and asks again for each page, so a page and its stylesheet always come from 1 build. |
| `vercel.json` | The Vercel project's build command, output folder and headers. |

## The runs on the pages

Each run on a page is what the command printed in a checkout of this
repository. `tests/test_docs.py` runs each command again and compares: only
the seconds and the checkout's folder may differ. When a gate's output
changes, the test names the line, and the page gets the new text.

## The drawings of the checks

Each drawing on the home page shows a check catching a fault in a test
circuit from this repository, or in an example's first version, and names
its file under the drawing. A value it marks, such as 0.4216 V
or 15.9 kHz, is a number in that board's files, in `tests/boards/README.md`,
or in a run the page shows, to the places the drawing gives:
`tests/test_docs.py` holds each one to its source. An axis's tick is marked
`tick` and is not held.

## The example pages

An example is a folder `examples/<name>/` whose version folders hold a
README.md each; the newest version is the one shown. `examples.py` reads:

- From the newest README: the title (`# Herald v0.1: a fire alarm
  communicator` and `# Hush — board prototype v0.1` both give the name and
  the version; the line under the name is the title's words after its
  colon, else the introduction's first sentence), the first paragraph, the
  table under "What is hard about it" and the list under "What is open" or
  "Open items", 8 items at most.
- How it was built, oldest first: for each version, its `TIMELINE.md`'s
  `## <date> · <stage> · <title>` entries, else the newest README's "What
  changed in <version>: <title>" section, its first 2 paragraphs. A
  paragraph that starts with `Evidence:` is set small, and a fenced
  `workcenter gates` run is shown as it stands.
- The checks: the verdict and the 4 gates of that run in the newest
  version's `TIMELINE.md`, else of its `docs/gates.md`; a report on several
  boards gives each board's verdict.
- From the board (`*.kicad_pcb` in the version folder): the size of its
  outline, its copper layers, its parts, tracks and vias, and the drawing
  the explorer shows. An example of several boards in folders of their own
  has no explorer.

To add an example: put its version folder under `examples/`, with its
README and its pictures in `docs/` (`workcenter render` writes them), and
a `TIMELINE.md` if its README has no "What changed" sections. Run
`python3 -B site/examples.py --pictures`, then add its card to the home
page (below). A host serves the page at `/examples/<name>`; its files sit
beside it in `examples/<name>/`, so a link from it reads the same with the
`.html` and without.

## The examples' pictures

Run each from the repository's root, with KiCad 10. Herald's drawing comes
from its design file and its routed board, and its parts' labels from the
design file, KiCad's library, its README and the report of its gates. Run
the gates first, then draw it again when any of them changes:

```sh
workcenter gates examples/fire-alarm-communicator/v0.1
python3 site/showcase/draw_face.py
python3 site/examples.py
```

The renders come from `workcenter render` on the example, in its `docs/`.
`python3 -B site/examples.py --pictures` takes KiCad's backdrop out of
them, crops and scales them, and lays the turntable's frames side by side.
An assembly's render (Signet round a finger) also has the backdrop that its
boards enclose taken out (`--holes`); a board's render does not, since a
metal lid mirrors the backdrop. Agentcast's card was keyed the same way,
once, from the render in its own repository (v0.5):

```sh
python3 site/showcase/key.py agentcast-render.png site/showcase/agentcast.png
```

A label shows the first page of its part's datasheet when that page is in
`showcase/datasheets/`, named by the first 12 hex digits of the SHA1 of
the datasheet's address. `datasheets.py` fetches each PDF the labels link
and draws its first page with Poppler's `pdftoppm`. It names on stderr each
it could not fetch: a maker that refuses a script, or an address that is
not a PDF. Draw the board once more after it, so the labels name the pages:

```sh
python3 site/showcase/datasheets.py
python3 site/showcase/draw_face.py
```

The 3D board is KiCad's VRML export of the routed board, turned into a GLB
by three.js in Chromium and compressed with gltf-transform. `make_glb.mjs`
runs the 3 steps and writes `showcase/herald.glb`, byte for byte the same
from the same board and bodies. It takes a folder of node modules with
three.js and gltf-transform, and KiCad's 3D bodies (`site/media/README.md`
says how to fetch them):

```sh
npm install --prefix /tmp/glb three@0.186.1 @gltf-transform/cli@4.5.1
KICAD10_3DMODEL_DIR=/tmp/kicad-packages3D node site/showcase/make_glb.mjs /tmp/glb/node_modules
```

The design-as-code section shows Herald's supervised inputs. KiCad exports
the schematic as SVG, librsvg draws it 8000 px wide, and FFmpeg crops the
inputs' block:

```sh
kicad-cli sch export svg examples/fire-alarm-communicator/v0.1/herald.kicad_sch -o /tmp/sch --exclude-drawing-sheet
rsvg-convert -w 8000 -b white /tmp/sch/herald.svg -o /tmp/sch/full.png
ffmpeg -i /tmp/sch/full.png -vf "crop=1600:1159:2920:3277" site/showcase/herald-schematic.png
```

Herald's renders come from `workcenter render` on the example
(`examples/fire-alarm-communicator/v0.1/README.md` names the command, and
`site/media/README.md` says how to fetch the parts' 3D bodies), cropped and
scaled with FFmpeg:

```sh
ffmpeg -i examples/fire-alarm-communicator/v0.1/docs/board-3d-top.png \
  -vf "crop=1228:780:170:100,scale=1200:762:flags=lanczos,format=rgb24" site/showcase/herald-top.png
ffmpeg -i examples/fire-alarm-communicator/v0.1/docs/layers.png \
  -vf "scale=1200:-2:flags=lanczos,format=rgb24" site/showcase/herald-layers.png
```

`og.html` shows Herald's 3D render, cropped and scaled with FFmpeg:

```sh
ffmpeg -i examples/fire-alarm-communicator/v0.1/docs/board-3d-iso.png \
  -vf "crop=1500:857:34:127,scale=1000:571:flags=lanczos,format=rgb24" site/showcase/herald.png
```

## A new example on the page

The section "More boards designed with Via" (`id="built"`) holds a card for
each finished example. To add one when it lands on `main`:

1. Write its page and pictures: `python3 -B site/examples.py --pictures`.
2. Add an `<a class="proj">` to the section. Its `href` is the example's
   page, `examples/<name>.html`. Its `<img>` is `examples/<name>/card.png`
   with the size the file has, and its text says what the board is, then
   its size, layers and parts.
3. Run `python3 -m pytest tests/test_docs.py`. It checks each picture's
   stated size against the file, each page against what `examples.py`
   writes, and each link of the built pages.

## The images

Chromium draws the Open Graph image, so the type is Inter itself:

```sh
chromium --headless --hide-scrollbars --force-device-scale-factor=1 --window-size=1280,640 \
  --virtual-time-budget=4000 --screenshot=site/og.png "file://$PWD/site/og.html"
```

It holds the wordmark, the page's headline and Herald's card picture (`showcase/herald.png`).
Draw it again when `og.html`, the wordmark, the headline or the picture changes.

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
| `vendor/model-viewer-4.4.0.min.js` | model-viewer 4.4.0, the npm package `@google/model-viewer`, which bundles three.js | Apache-2.0, © Google LLC, in `vendor/MODEL-VIEWER-LICENSE` |
| `vendor/meshopt_decoder-1.2.0.js` | The meshopt decoder of meshoptimizer 1.2.0, the npm package `meshoptimizer` | MIT, © Arseny Kapoulkine, in `vendor/MESHOPTIMIZER-LICENSE.md` |
| The parts' bodies in `showcase/herald.glb` | KiCad's 3D library, and Herald's own bodies in its `models/` | CC-BY-SA 4.0 with KiCad's exception for a design's output, for KiCad's library |
| `showcase/datasheets/*.png` | The first page of each part's datasheet, from its maker, linked from its label | © each maker; shown small, beside a link to the maker's PDF |
| `agents.svg`: 18 marks | Lobe Icons, the npm package `@lobehub/icons-static-svg` 1.102.0: Claude Code, Codex, Cursor, Gemini, Grok, GitHub Copilot, Windsurf, Cline, AMP, Antigravity, OpenClaw, Goose, Kilo, Kiro CLI, Hermes (Nous Research's mark), OpenCode, Roo, Trae | MIT, © LobeHub |
| `agents.svg`: Zed | Simple Icons, the npm package `simple-icons` 16.37.0 | CC0 1.0 |
| `agents.svg`: VS Code | Codicons, the npm package `@vscode/codicons` 0.0.46-24 | CC BY 4.0, © Microsoft Corporation |
| `agents.svg`: Droid | text-to-cad, `apps/docs/public/agents/droid.svg` (<https://github.com/earthtojake/text-to-cad>) | MIT, © Thompson Labs LLC |

Each agent's mark is its maker's trademark. The strip names the agents Via
works with; no maker endorses Via.
