# tools/ci: what a change needs, fast or full

A change that touches only what no engine reads gets the fast gate: no
toolchain, no engine. Any other change gets the full health gate. CI and a
developer's machine ask the same script. The fast gate's time on this
workcenter's shared machine is in `ee-agent-kit/STATUS.md`; it is not yet
the minute the roadmap asks for.

| File | What it does |
|---|---|
| `scope.py` | Reads a change and prints `fast` or `full`, with 1 line per path saying why. |
| `engine_marker.py` | The pytest plugin behind the `engine` marker. `tests/conftest.py` loads it. |
| `guard/engine_watch.py` | Writes a line for each engine a Python process starts; refuses it in the fast run. |
| `guard/sitecustomize.py` | Loads the watch in every Python process that has `guard/` on PYTHONPATH. |

## The rules of `scope.py`

1. A path under `site/` is fast.
2. A `.md` file is fast, unless it is under `tests/`, `examples/`,
   `templates/`, `third_party/` or `.claude/`: a command reads the files there.
3. Any other path is full. A path no rule names is full.
4. A document (`.md`, `.html`) is full when a run it shows changed: a
   `$ workcenter ...` line or a line printed under it, or a line of the
   README's quick start. `tests/test_docs.py` runs those with the engines.
   It reads them with `scope.runs_in`, `scope.document_text` and
   `scope.quick_start`, the same functions.
5. No base, or a base git cannot read: full.
6. A list of paths (`--paths`) carries no text: a document that shows a
   run is full.

## Before a push

1. Run `make scope`. It compares the working tree with
   `git merge-base origin/main HEAD` (set `SCOPE_BASE=<ref>` for another base).
   - A line `fast  <path>: <why>`: this path needs no engine.
   - A line `full  <path>: <why>`: this path needs the full gate.
   - The last line is the answer: `fast` or `full`.
2. If the answer is `fast`, run `make verify-site`. It ends with
   `VERIFY-SITE GREEN in <n>s`. Any other end is red: read the step above it.
3. If the answer is `full`, run `make verify`. It ends with `VERIFY GREEN`.

## A test that starts an engine

A test that starts kicad-cli, ngspice, Java (FreeRouting), openEMS, a chip
engine (`tools/chipflow.py` `ENGINES`) or imports `pcbnew` carries
`@pytest.mark.engine`. A board fixture's gates start kicad-cli.

1. Run the test file: `python -m pytest tests/<file> -p no:cacheprovider -q`.
2. A failure `<test> started <engine> and has no engine marker
   (tools/ci/engine_marker.py)`: put `@pytest.mark.engine` on that test.
3. The fast run (`make verify-site`) leaves the marked tests out
   (`-m "not engine"`) and sets `WORKCENTER_NO_ENGINES=1`: an engine start
   raises `FileNotFoundError`, which the commands read as an absent engine.

What the watch does not see: a process started with `python -I`, a child
whose environment drops PYTHONPATH, and an engine started by a shell script
file (not a `-c` line). A program under the temporary folder is a test's
stand-in, not an engine.

## The workflow

`.github/workflows/ci.yml` has 4 jobs. `scope` runs `scope.py` and is the
only job that decides. `fast` runs `make verify-site` with no toolchain.
`full` installs the toolchain and runs `make verify`. `verdict` always runs
and passes only when the job the scope asked for passed: make `verdict` the
required check. The nightly run (`nightly.yml`) stays the full gate.
