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
| `apt_archive.sh` | On CI's install path, before install.sh: apt asks Ubuntu's own archive, not the runner's regional mirror. |

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
   run is full, and so is a document that is absent from the working tree.
7. A path whose name is not UTF-8 is judged by its rules; its line shows
   each such byte as `\xe9`.

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

The plugin holds a test's setup, call and teardown. It does not hold a
module's collection: a probe there (`import pcbnew` in a try,
`importlib.util.find_spec("pcbnew")`) decides skip marks, and the fast run
refuses it, so it costs no engine there; in the full run it runs unheld.
The watch sees `subprocess`,
`os.system`, `os.posix_spawn`, `os.posix_spawnp`, `os.execv` and
`os.execve` (and `os.execvp`, `os.execl*` and `os.spawn*`, which call
them). Behind a wrapper it skips the options and their values
(`timeout -s KILL 60`, `env -u FOO`) and reads `flock -c` and `env -S`
lines. In a shell line only a command's first word is a program:
`echo magic` starts nothing.

What the watch does not see: a process started with `python -I`, a child
whose environment drops PYTHONPATH, an engine started by a shell script
file (not a `-c` line) or by a program that is not Python, a start from
`os.fork` followed by a C library call, and a start in `tests/conftest.py`
itself, which runs before the plugin is configured. A
program under the temporary folder is a test's stand-in, not an engine.

## The workflow

`.github/workflows/ci.yml` has 4 jobs. `scope` runs `scope.py` and is the
only job that decides fast or full. `fast` runs `make verify-site` with no
toolchain. `full` gets the toolchain and runs `make verify`. `verdict` always
runs and passes only when the job the scope asked for passed: make `verdict`
the required check. The nightly run (`nightly.yml`) stays the full gate.

## Where `full` runs

`full` decides its own path in its first step, `tools/image.py decide`, and
prints 1 line: `where: image: ...` or `where: install: ...`, with the reason.

- `image`: the registry gave the image whose content tag is that of this
  commit's `Dockerfile`, `install.sh` and `requirements.txt`
  (`workcenter image` prints the tag). The job runs `make verify` in it as
  the runner's user, after `tools/image.py show` (the image's tag, commit
  and tools' versions) and `tools/image.py check` (the checkout's 3 files
  are those the image was built from; a difference fails the job).
- `install`: `sudo env REQUIRE_FREEROUTING=1 APT_UPDATE_TIMEOUT=120 APT_DOWNLOAD_TIMEOUT=570 ./install.sh`,
  then `make verify`, as before the image; the 2 bounds end a stalled
  index or download with apt's own line within the job's 30 minutes (the
  nightly run and the image build set the same 2). It is taken when the change edits 1
  of the 3 files (the install path is their test), when the registry has
  no image of the tag (the first run, a new toolchain not yet published),
  when the pull is refused or the registry does not answer, when the
  files cannot be read, and when the repository variable
  `CI_FULL_IN_IMAGE` is `0`.

The last step fails unless the decided path's verify step ran and passed.

## Ubuntu's own archive on the install path

Before install.sh, the install path (and the nightly run) runs
`sudo env APT_ARCHIVE_CI=1 bash tools/ci/apt_archive.sh /etc/apt`. The
runner's apt asks a regional mirror of Ubuntu's archive, and twice it
crawled to the download's bound of 570 s (CI runs 44402154007 and
44432768560). The script changes such a host to archive.ubuntu.com, or
ports.ubuntu.com on an arm machine, and nothing else.

1. Read its lines in the step "Ask Ubuntu's own archive". A line
   `<file>: <host> -> archive.ubuntu.com` names each file it changed.
   A line `no regional or cloud mirror ...; changed nothing` says there was none.
   A line `... a layout this script does not know; changed nothing` means
   the runner image changed its apt files: read them, then the script.
2. To turn it off without a commit: the repository variable
   `CI_APT_UBUNTU_ARCHIVE` = `0`. The step then prints 1 line that names it.
3. It refuses this machine's /etc/apt unless `APT_ARCHIVE_CI=1`: a
   person's computer keeps its mirror. Its tests run it on a folder of
   their own (`tests/test_ci_apt_archive.py`).

It does not help when archive.ubuntu.com itself is slow or down, nor with
KiCad 10's source (the PPA). The image build already asks archive.ubuntu.com.

What differs inside the image: the runner has `node`, the image does not,
so the tests that need it (6 of `tests/test_forms.py`, 1 of
`tests/test_lead.py`) skip there. A change to a file they read
(`site/api/`, `ee-agent-kit/lead/workflows/`, the 2 test files; the list
is `NODE_PATHS` in `tools/image.py`) takes the install path, where they
run. On the image path the `where:` line ends `not judged there: the
tests that need node`, with the reason.

To read a run: the line `where:` in the step "Decide where the gate runs";
on the image path, the lines `image:`, the record's JSON and `image: the
checkout's Dockerfile, install.sh, requirements.txt are those the image
was built from` before `make verify`.
