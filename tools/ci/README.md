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
| `changes.py` | A change's changelog line in a file of its own under `ee-agent-kit/changes/`: `check` (in the kit checks), `show`, and `fold <X.Y.Z> <date>` for a release. |
| `nightly_issue.py` | The nightly run's last step: reads the night's outcome, the gate's log and the open `ci-failure` issues, and prints what to do (open, comment, close or nothing) with the text. |

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
2. Run `make verify-site` for every answer. It ends with
   `VERIFY-SITE GREEN in <n>s`. Any other end is red: read the step above it.
   It is the only local run that hides KiCad's libraries, and CI's `fast`
   job runs it on every change. A change whose answer is `fast` may be
   pushed straight to `main`.
3. If the answer is `full`, run `make check` and push to a work branch,
   never to `main`. CI's `full` job runs `make verify` on the pull
   request (or on a run by hand, `gh workflow run ci.yml --ref <branch>`);
   merge only when its `verdict` is green on the head commit. Where
   there is no CI, run `make verify` on the machine. It ends with
   `VERIFY GREEN` (`ee-agent-kit/CI.md`, "Where the health gate runs").

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
toolchain, on every change: for a full change it runs beside `full`. `full`
gets the toolchain and runs `make verify`. `verdict` always runs and passes
only when `fast` passed and, for a full change, `full` passed too: make
`verdict` the required check. The nightly run (`nightly.yml`) stays the full
gate.

`fast` runs on full changes because only its runner lacks KiCad. A test that
loads KiCad's symbol or footprint libraries without a skip mark passes in
`full` and fails in `fast`. Before, `fast` ran only on fast changes, so such a
test reached main through a full pull request and turned the next fast push
red (CI runs 44455634601 and 44462711649).

## A test that needs KiCad's libraries

A test that loads a symbol or footprint from KiCad's libraries
(`tools/kicadgen.py` reads `KICAD_SYMBOL_DIR` and `KICAD_FOOTPRINT_DIR`,
default `/usr/share/kicad/symbols` and `/usr/share/kicad/footprints`) carries
the skip its file already has, `needs_libs`:
`pytest.mark.skipif(not LIBS.is_file(), reason="KiCad symbol libraries are not installed")`
with `LIBS = kicadgen.SYMBOL_DIR / "Device.kicad_sym"`. A test that starts
`workcenter design` on a fixture board loads them too. It carries
`needs_libs` even when it already skips where kicad-cli is absent: the fast
gate on a machine with KiCad has kicad-cli and hides the libraries only.

`make verify-site` sets both variables to empty folders of its own, so it
finds such a test on a machine that has KiCad. To run 1 file that way:

```
KICAD_SYMBOL_DIR=/nonexistent KICAD_FOOTPRINT_DIR=/nonexistent WORKCENTER_NO_ENGINES=1 \
  python -m pytest tests/<file> -p no:cacheprovider -q -m "not engine"
```

## A changelog line in a file of its own

A change does not edit `ee-agent-kit/CHANGELOG.md`. It adds 1 file,
`ee-agent-kit/changes/<yyyy-mm-dd>-<slug>.md`: line 1 is 1 of Keep a
Changelog's headings (`### Added`, `### Changed`, `### Deprecated`,
`### Removed`, `### Fixed`, `### Security`), then 1 or more `- ` lines as
they will stand in CHANGELOG.md. 2 changes then write 2 files, and 2 files
of 2 names merge clean. On 2026-11-19 `main` moved under an open pull
request 5 times, and each time the pull request conflicted in CHANGELOG.md
alone (M279). Pick a slug of your own: 1 name in 2 branches is git's
add/add conflict, as for any file; keep both lines and rename 1 file.
Each `- ` line stands once: `check` refuses a line that CHANGELOG.md,
another change file or the same file already holds, and a line that ends
in white space.

1. `python3 tools/ci/changes.py check`: every change file is well formed.
   A fault is 1 line, `<file>:<line>: <why>`, and the exit is 1. The kit
   checks of `make verify` and `make verify-site` run it.
2. `python3 tools/ci/changes.py show`: what `## [Unreleased]` holds today.
   Under each heading, the change files' lines come first, newest first by
   the date in the name, then CHANGELOG.md's own Unreleased lines.
3. `python3 tools/ci/changes.py fold <X.Y.Z> <YYYY-MM-DD>`: the release
   step (`ee-agent-kit/RELEASING.md` step 2). It writes the release's
   section with both places' lines, leaves an empty `## [Unreleased]` and
   deletes the folded files. A second run changes nothing. A version that
   is already there, with lines still unreleased, is refused.

A line written straight under `## [Unreleased]` stays valid: every action
reads both places, and so does the roadmap pointer test in
`tests/test_docs.py`. The script is Python's standard library only.

## The nightly's `ci-failure` issue

The nightly run's last step runs on a passed and a failed night. It lists
the open issues labelled `ci-failure` and asks `nightly_issue.py` what to do.

1. A failed night with no open issue opens one.
2. A failed night with an open issue adds 1 comment to it.
3. A passed night closes each open issue, with 1 comment that names its run.
4. A passed night with no open issue does nothing.

With 2 or more open, the oldest (lowest number) is spoken to: it holds the
history. On a failed night each other one is closed as its duplicate, so 1
stays open and the next failure is seen. The text holds the run's address,
the step that failed, the gate's `FAILED`, `why:` and `TESTS RED` lines,
bounded to 20000 characters, inside a code fence. A text over the bound is
cut, and the fence open at the cut is closed with its own backticks. A gate
that stopped before its tests gives its step and the last 40 lines of its
log. The step is named only from a step line of `verify/verify.sh`
(`== 1/4 lint`), in backticks; any other `== ` line stays in the fence. A night
that stopped at install has no log and says so. The script is Python's
standard library only: on that night there is no venv, and the runner's
`python3` runs it. Its tests run the step's own script under node with a
stand-in GitHub (`tests/test_ci_nightly_issue.py`).

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

Neither path builds the image. `.github/workflows/image.yml` builds it on
amd64 and arm64, on every pull request that touches the toolchain's files
and on every push to main. It runs the gates on a fixture in it as the
runner's user, checks that they wrote `build/gates.json`, and checks that
every file they wrote is that user's. The real build test of
`tests/test_image.py` runs only when asked by name:
`WORKCENTER_TEST_IMAGE_BUILD=1 python3 -m pytest tests/test_image.py::test_the_image_builds_and_runs_the_gates_as_the_calling_user`,
on a machine where `docker info` answers. Nothing sets the variable for
`make verify` or `make check`. On the install path the build took about
669 s of the file's 674.6 s, and made its shard the longest, 991 s
(job 135422229691).

## The hosts of Ubuntu's archive on the install path

Before install.sh, the install path (and the nightly run) runs
`sudo env APT_ARCHIVE_CI=1 bash tools/ci/apt_archive.sh /etc/apt`. On
2026-11-19 each of 2 hosts was the slow one once: the runner's regional
mirror crawled to the download's bound of 570 s (CI runs 44402154007 and
44432768560), and at 07:14 UTC archive.ubuntu.com did not deliver the
index within 120 s in 3 tries (run 44477966021). So apt keeps more than
1 host and asks the fastest first:

- The mirror list (`/etc/apt/apt-mirrors.txt`, which the runner's
  `ubuntu.sources` names) keeps the runner's mirror, archive.ubuntu.com and
  security.ubuntu.com. A source line that names a regional mirror itself
  (us-east-2.ec2.archive.ubuntu.com, us.archive.ubuntu.com, the same under
  ports.ubuntu.com) names the list instead, and the list gets the mirror
  and Ubuntu's own host (archive.ubuntu.com or ports.ubuntu.com) beside it.
- A probe asks every host of the list for the first 1 MiB of
  `dists/<suite>/main/binary-<arch>/Packages.gz`, side by side, 3 s each,
  ended at 4 s: at most 5 s in all, of the 8 s the `full` job's limit
  leaves beside install.sh's worst case. The list's priorities follow bytes a
  second. A host that does not answer goes last and stays. With no answer
  at all the priorities stay as the runner wrote them; hosts of 1
  priority, or of none, apt asks in random order, and the line says so.
- `/etc/apt/apt.conf.d/80apt-archive-ci` sets apt's http and https
  timeout to 15 s and `Acquire::Retries` to 0: a file whose host sends
  nothing for 15 s goes to the next host of the list at once. A host that
  accepts the connection and then sends nothing costs 2 timeouts, 30 s
  (apt 2.8.3's `methods/basehttp.cc`). apt fetches the files of 1 host one
  after another (`apt-pkg/acquire.cc`: 1 queue per host), and the
  runner's `apt-get update` puts 4 InRelease files on the first host: a
  silent first host costs 60 s (connections refused or dropped) to 120 s
  (accepted, then silent). The latter is all of CI's 120 s for 1 try of
  the update. With apt's defaults (30 s, 3 retries) it would be 988 s.
- The list's tags follow a tab, as apt reads them (`methods/mirror.cc`).
  A line with a blank before its first tab is a layout the script does
  not know: it changes nothing.

1. Read its lines in the step "Rank the hosts of Ubuntu's archive". A
   line `probe <host>: <n> bytes in <s> s, <r> bytes/s` or
   `probe <host>: no answer (...); it goes last` per host, then
   `apt-mirrors.txt: apt asks <first>, then ...: the fastest first`, or
   `no host answered the probe; apt asks in the runner's order: ...`
   (`... by the runner's priorities: <a> and <b> in random order, ...`
   when priorities tie or are missing).
   A line `<file>: <host> -> mirror+file:/etc/apt/apt-mirrors.txt` names a
   source file it pointed at the list, and `added ...` the hosts the list
   gained. A line `no regional or cloud mirror ...; changed nothing` says
   no source uses a mirror list or names a regional mirror.
   A line `... a layout this script does not know; changed nothing` means
   the runner image changed its apt files: read them, then the script.
2. To turn it off without a commit: the repository variable
   `CI_APT_UBUNTU_ARCHIVE` = `0`. The step then prints 1 line that names it.
3. It refuses this machine's /etc/apt unless `APT_ARCHIVE_CI=1`: a
   person's computer keeps its mirror. Its tests run it on a folder of
   their own, with a stand-in for the probe (`tests/test_ci_apt_archive.py`).

What it does not cover:

- A host that keeps sending a trickle never goes silent for 15 s, so apt
  does not leave it. The probe ranks it last only if it is slow at the
  step's start.
- install.sh's download passes its own `Acquire::http::Timeout=60` and
  `Acquire::Retries=3` on apt's command line, which win over the file: in
  the download a silent host is left after 4 tries of 60 s.
- KiCad 10's source (the PPA) has 1 host. `Acquire::Retries` holds for
  every source, so in `apt-get update` the PPA gets 1 try of 15 s, not 4
  of 30 s, and nothing to fall back to; install.sh tries the update again
  as a whole.
- A first host that accepts connections and then sends nothing can take
  all 120 s of 1 try of the update. The probe puts a host that is silent
  at the step's start last, so this needs a host that goes silent after
  the probe.
- An arm runner's `ports.ubuntu.com`, named alone with no list, stays 1
  host: the script knows no second host for it.
- The image build: apt runs inside the container with Ubuntu's default
  sources, and this step does not run there.

The image holds node, from Ubuntu 24.04's own `nodejs` (18.19.1), which
the Dockerfile installs after install.sh: the tests that run it
(`tests/test_forms.py`, `tests/test_lead.py`, `tests/test_ci_nightly_issue.py`) run inside the image as on
the runner, so a change to what they read takes the image path like any
other. install.sh does not install node: a board needs none.
`image.py record` refuses an image without it, and `image.py show`
names its version.

To read a run: the line `where:` in the step "Decide where the gate runs";
on the image path, the lines `image:`, the record's JSON and `image: the
checkout's Dockerfile, install.sh, requirements.txt are those the image
was built from` before `make verify`.
