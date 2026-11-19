# CI.md — what runs in `.github/` and why

The workflow files in `.github/workflows/` are the source of truth. This
file explains them and holds the repository settings that are not files.

| File | Trigger | Does |
|---|---|---|
| `ci.yml` | push to `main`, every PR, manual (`gh workflow run ci.yml --ref <branch>`: always `full`, the gate of a branch with no pull request) | `fast` on every change: no toolchain, `make verify-site` (KiCad's libraries hidden, no engine started). `full`: the image of this commit's toolchain when the registry gives it, else `tools/ci/apt_archive.sh` (apt keeps the runner's mirror and Ubuntu's own archive, asks the fastest first, and in the index update sends a file to the next host after 15 s of silence), then `sudo env REQUIRE_FREEROUTING=1 APT_UPDATE_TIMEOUT=120 APT_DOWNLOAD_TIMEOUT=570 ./install.sh`; then `make verify` (tools/ci/README.md, "Where `full` runs"). `verdict` passes when `fast` passed and, for a change `tools/ci/scope.py` calls full, `full` too. |
| `nightly.yml` | 06:17 UTC daily | `tools/ci/apt_archive.sh`, then `sudo env REQUIRE_FREEROUTING=1 APT_UPDATE_TIMEOUT=120 APT_DOWNLOAD_TIMEOUT=570 ./install.sh` then `make verify`, always by install.sh. Keeps 1 `ci-failure` issue in step with the nights (`tools/ci/nightly_issue.py`): a failed night opens it or adds 1 comment with the run and the gate's `why:` lines; a passed night closes it with 1 comment naming the run; a second open one is closed as a duplicate of the oldest (tools/ci/README.md, "The nightly's `ci-failure` issue"). Catches a moved PPA, a new KiCad point release, a broken dependency. |
| `image.yml` | PR on the files the build reads, every push to `main`, `v*.*.*`, Monday 04:17 UTC, manual | Builds the image on amd64 and arm64 from install.sh, with CI's 2 bounds of its apt step as build arguments, checks it with doctor (its `requirements` row included: the venv holds the pins of the requirements.txt in the tag) and the gates on a fixture as the runner's user (they must write build/gates.json, and every file they write must be that user's); pushes to `ghcr.io/<owner>/via` except on a PR. |
| `board-gates.yml` | `workflow_call` from a board repository | `workcenter gates` on each project folder the caller names, 1 job each; the gates table in the job's summary; red on RED and SKIPPED. In the image of Via's toolchain where the runner can pull it, else `tools/ci/apt_archive.sh` then `install.sh` with CI's 2 apt bounds (`.claude/skills/board-ci/SKILL.md`). |
| `board-fixture.yml` | PR and push to `main` on the 2 board workflows, the fixture, `tools/`, `install.sh`, `requirements.txt` or `Dockerfile`; manual | Calls `board-gates.yml` on `tests/boards/pass-rc-divider` with `strict: true`, Via at the run's own commit. |
| `release.yml` | tag `v*.*.*` | Publishes the GitHub Release with generated notes (the image comes from `image.yml`). |
| `stale.yml` | Mondays | Marks issues stale after 60 days, closes after 14 more. `blocked`, `security`, `accepted` are exempt. |
| `../dependabot.yml` | weekly | pip (`requirements.txt`), GitHub Actions, Docker base image. Minor and patch updates grouped. |
| `../PULL_REQUEST_TEMPLATE.md` | every PR | What, Why, Evidence, checklist; the changelog line is a new file under `ee-agent-kit/changes/`. |

## Where the health gate runs

`main` takes no commit that its gate did not pass on that exact commit. The gate is `make verify` for a change `make scope` calls `full`, and `make verify-site` for one it calls `fast`. The full gate runs on GitHub, in the `full` job of `ci.yml`. It is the
same `make verify` as on a machine. The owner chose this on 2026-11-19.

| The change | Before its push | On GitHub | What may merge |
|---|---|---|---|
| Any change, pushed to a work branch with a pull request | `make check TESTS="<the test files of what it touches>"` | The push starts `ci.yml`. The `scope` job picks `fast` or `full`. `fast` runs on every change; `verdict` is green only when `fast` passed and, for a `full` change, `full` too. | The head commit, when `verdict` is green on it and the branch holds `main`'s tip. |
| A work branch with no pull request yet | `make check TESTS="..."` | A run by hand: `gh workflow run ci.yml --ref <branch>` (`workflow_dispatch`). It is always `full`. | Nothing merges without a pull request. A green `verdict` lets others start work from that commit. |
| A change `make scope` calls `fast`, pushed straight to `main` | `make verify-site` | The push to `main` runs `ci.yml`; its `fast` job runs `make verify-site` again. | It is on `main` already. |
| A release | The release commit goes through a pull request like any change. | Its `verdict` on `main`. | The tag goes only on a commit whose `full` job passed. A release commit is `fast`, so ask for a run by hand on `main`: `gh workflow run ci.yml --ref main` (RELEASING.md step 4). |
| Any change, where there is no CI (a fork without Actions, an offline machine) | `make verify`, alone on the machine (`ee-agent-kit/lead/gate-and-push.sh` pushes only on `VERIFY GREEN`) | Nothing. | The commit that printed `VERIFY GREEN`. |

`make check` is `make lint`, then the gate's kit checks (`make kit`, `verify/verify.sh kit`: the 2 copies of every kit skill, each skill's frontmatter, CLAUDE.md = AGENTS.md, every mistake's process and every process's Done when; 0.6 s to 0.75 s here), then pytest on the kit's own tests and the files in `TESTS`: the commits' authors (`tests/test_docs.py`), the 2 copies of the lead's skills (`tests/test_lead_skills.py`), and this rule's documents and kit checks (`tests/test_gate_rule.py`). Engine starts are refused and the tests marked `engine` are left out, as in `make verify-site`. It takes no lock, so it does not need the machine alone. With no `TESTS` it took 8.2 s to 14.5 s here, 3 runs on 4 processors with helpers at work (load average 5.2 to 6.5), on 2026-11-19.

When CI itself cannot run for a cause outside the change, the gate is `make verify` on the machine on the exact commit, by the same rule as a machine with no CI. On 2026-11-19 at 07:14 UTC a package host was down: `apt-get update` did not end within 120 s on the runner, 3 tries, and the job stopped before any test.

The rules that follow from it:

- A work branch may hold a commit the gate has not passed yet. The pull
  request shows it: its checks are pending or red. Nobody merges it,
  releases from it, or starts other work from it until `verdict` is
  green on that commit.
- A red `verdict` is answered with a new commit. Pushed history is not
  rewritten. A red gate is fixed, not left (AGENTS.md).
- A pull request's run tests its head merged with `main` as it was when
  the run started. Merge `main` into the branch first, so the tree CI
  tested is the tree that lands. If `main` moves before the merge, merge
  it in again and wait for the new `verdict`.
- Merge with `gh pr merge <number> --merge --match-head-commit <sha>`.
  GitHub then refuses the merge if the head is no longer the commit
  whose `verdict` you read.
- The gate's lock and the helpers' rules for it (PROCESSES.md P31 steps
  11 to 14) are for a gate on a machine. A landing that CI gates needs
  neither.
- `verdict` can be made a required check of `main` in the repository's
  settings (Branches). GitHub then refuses a merge without it. It is a
  setting, not a file; this document does not say whether it is on.

Why, from the runs of 2026-11-19. On the machine, the gate needs the
machine alone. The gate push24 waited 50 min 31 s for quiet and was
ended by its 1-hour limit (MISTAKES.md M273). The gate push28 ran
`make verify` in 906 s (its tests 889 s), from 05:26:16 UTC; the gate
before it, push27, had made its lock at 05:06:51 (M274, M278). While a
gate waits or runs, no helper may start a test. CI's `full` job ran the
same `make verify` on the same commit, 9beca5b, in 14 min 58 s (run
44466890200, 05:41:46 to 05:56:44 UTC, on the install path), while the
machine went on working. Inside the image, the `full` job of run
44428908528 took 12 min 42 s. Before this change each landing ran the
whole suite 2 times: on the machine, then on the pull request.

## Toolchain step

CI's `full` job takes the toolchain from the image of its tag when the
registry has it, else installs with `sudo env REQUIRE_FREEROUTING=1 APT_UPDATE_TIMEOUT=120 APT_DOWNLOAD_TIMEOUT=570 ./install.sh`
(tools/ci/README.md, "Where `full` runs").

The 2 bounds end a stalled index or download with apt's own line within the `full` job's 30 minutes: 88 s for the key + 3 x 120 + 2 x 20 + 570 = 1058 s of the 1066 s the newest passing run left (job 134941364976). The nightly run (45 minutes) and the image build (60 minutes) set the same 2; `test_the_worst_case_of_the_apt_step_fits_the_jobs_limit` reads each workflow's own limit. A person's computer has no total bound. The download's 570 s cover all its passes and the waits between them (APT_DOWNLOAD_TRIES, default 5; APT_DOWNLOAD_WAIT, default 20 s), so the sum stays 1058 s. CI and the image build set neither variable and run on the script's defaults; `test_ci_and_the_image_build_leave_the_passes_and_the_wait_to_the_script` holds the 3 workflows and the Dockerfile to that.

CI's `full` job does not build the image. The build test of `tests/test_image.py` ran a whole `docker build` and the gates in it wherever `docker info` answered, which on CI's install path took about 669 s of the file's 674.6 s and made its shard the longest, 991 s against 785, 579 and 385 s (job 135422229691); main's push run 44496113605 was cancelled at the job's 30 minutes. The test now runs only when `WORKCENTER_TEST_IMAGE_BUILD=1`, which nothing sets; `image.yml` builds the image on every pull request that touches the toolchain's files and on every push to main, and checks there all that the test checked (tools/ci/README.md, "Where `full` runs").

The `full` job keeps `timeout-minutes: 30` for now. Its worst case still rests on 670 s for `make verify` and 28 s for the steps after apt (job 134941364976, `test_the_worst_case_of_the_apt_step_fits_the_jobs_limit` in `tests/test_install_apt.py`): 1058 s for the apt step of the 1066 s those leave. A run with the build in measured 1003 s and 185 s for them (job 135422229691), which leaves less than 1058 s. The first passing install-path run without the build, job 135593285528 (2026-11-19), measured them: `make verify` 725 s (`tests: 721 s on the wall clock`), and 406 s from the java step's line to `make verify`, 385 s of which is the openEMS step's own apt download (1 stall of 282.8 s). That download has no bound of its own, and the worst-case arithmetic does not count it. The test still holds 670 s and 28 s: its figures change in a landing of their own, and then the limit is raised to fit or the apt bounds are cut. On that job's split the build out would leave the 785 s shard the longest, about 206 s less; the new `tests/test_image.py` row of `verify/shards.csv` reshuffles the shards, so that is an estimate.

The runner is `ubuntu-24.04`, so the PPA step, the Java package, and ngspice
match the cloud environment. `REQUIRE_FREEROUTING=1` makes a blocked JAR
download fail the run; a green CI proves the autoroute engine installs.

The runner keeps its own Java first on PATH (17.0.21 in CI run 44444183056, after apt had set up openjdk-21-jre-headless 21.0.13.1), and its own JDKs under /usr/lib/jvm. install.sh records the JVM it installed in `/opt/workcenters/ee/java.path`, and Via runs that one whatever PATH holds. FreeRouting 1.9.0 draws a window, so that JVM needs `lib/libawt_xawt.so`: the apt step installs openjdk-21-jre when the 21's own JVM lacks it (in CI run 44515796762 a JDK of the runner's own had the library, the headless 21 was recorded, and 13 routing tests failed). With `REQUIRE_FREEROUTING=1` the install ends red when the java it leaves is older than 21 or cannot draw. The lines to read: `[install] apt: install openjdk-21-jre (the JVM of the 21 under /usr/lib/jvm has no lib/libawt_xawt.so, which FreeRouting needs)` in the apt step, then `[install] java: /usr/lib/jvm/java-21-openjdk-amd64/bin/java (...), Java 21: Via runs it`, then after `[install] done in`: `ok       java         21.0.13.1 at /usr/lib/jvm/java-21-openjdk-amd64/bin/java, recorded by install.sh in /opt/workcenters/ee/java.path`, with nothing after the path.

`make verify` holds the engine lock for the whole gate, so its tests' commands never wait on it. `tests/conftest.py` still names a file for a waiting run's 2 lines (`WORKCENTER_LOCK_LOG`), so a test that compares stderr reads the same lines in CI and on a machine where another session holds the lock.

Before install.sh, the install path and the nightly run rank the hosts of Ubuntu's archive: `sudo env APT_ARCHIVE_CI=1 bash tools/ci/apt_archive.sh /etc/apt`. On 2026-11-19 each of 2 hosts was the slow one once. At 03:00 UTC the mirror us-east-2.ec2.archive.ubuntu.com crawled and the download hit its bound of 570 s, 3 runs (CI runs 44402154007 and 44432768560 had done the same). The answer then turned the mirror into archive.ubuntu.com; its first run on a runner, CI run 44444183056, passed, and the install step took 1 min 29 s. At 07:14 UTC run 44477966021 (job 135403130537) turned azure.archive.ubuntu.com into archive.ubuntu.com, and `apt-get update` did not end within 120 s in 3 tries. So the step now keeps every host: the mirror list (`/etc/apt/apt-mirrors.txt`) keeps the runner's mirror, archive.ubuntu.com and security.ubuntu.com, and a source that names a regional mirror itself is pointed at the list, with Ubuntu's own host added beside it. A probe asks each host for the first 1 MiB of `dists/<suite>/main/binary-<arch>/Packages.gz`, side by side, 3 s each and ended at 4 s: at most 5 s, of the 8 s the `full` job's limit leaves beside install.sh's worst case. The list's priorities follow bytes a second; a host that does not answer goes last and stays; with no answer the list stays. `/etc/apt/apt.conf.d/80apt-archive-ci` sets apt's http and https timeout to 15 s and `Acquire::Retries` to 0, so in `apt-get update` a file whose host is silent for 15 s goes to the next host of the list at once (in the download, install.sh's own `Acquire::Retries=3` and 60 s on apt's command line take their place: job 135500622487 spent its whole 570 s on 1 pass from a host the probe had ranked first) (apt-transport-mirror(1); apt 2.8.3's `apt-pkg/acquire-worker.cc`). apt fetches 1 host's files in turn (`apt-pkg/acquire.cc`), the update puts 4 InRelease files on the first host, and a host that accepts and then says nothing costs 2 timeouts (`methods/basehttp.cc`). So a silent first host costs the update 60 s to 120 s; with apt's defaults (30 s, 3 retries) it would cost 508 s to 988 s. 120 s is all of 1 try of the update: a host that goes silent after the probe can still fail that try. The setting holds for every source: KiCad 10's PPA gets 1 try per update. The step prints 1 line per host with what it measured, and the order it chose. Setting the repository variable `CI_APT_UBUNTU_ARCHIVE` to `0` turns it off (tools/ci/README.md, "The hosts of Ubuntu's archive on the install path").

## The fast job on every change

`fast` runs on every pull request and push, beside `full`. Its runner has no KiCad. A test that loads KiCad's symbol or footprint libraries without a skip passes in `full` and fails in `fast`; when `fast` ran only for fast changes, 7 such tests reached main through full pull requests and turned every site-only push red (CI runs 44455634601 and 44462711649). `verdict` asks `fast` for every change and `full` too for a full one. `make verify-site` sets `KICAD_SYMBOL_DIR` and `KICAD_FOOTPRINT_DIR` to empty folders, so it fails such a test on a machine with KiCad (tools/ci/README.md, "A test that needs KiCad's libraries"). Run it before every push: it also fails a test that skips on kicad-cli but loads the libraries, which the CI runner skips.

## The nightly's ci-failure issue

The nightly run's last step runs on a passed and a failed night, not on a cancelled one. It lists the open issues labelled `ci-failure`, calls `tools/ci/nightly_issue.py` with the night's outcome, the gate's log (`build/nightly-verify.log`, written by the Verify step through `tee`) and each step's outcome, and does what it prints. Issue 63 of nightly run 44031336712 (2026-11-17) stayed open after run 44251400298 passed and was closed by hand; the step now closes such an issue on the next passed night. To read a night: the step's lines `nightly-issue: open ...`, `comment on #N`, `close #N as completed` or `as not_planned`, or `nothing to do`. Not yet run on GitHub. A night that hits the job's time limit counts as cancelled: the step is skipped, and an open issue stays as it is.

## The changelog in files of their own

A change writes its changelog line into `ee-agent-kit/changes/<yyyy-mm-dd>-<slug>.md`, not into CHANGELOG.md (tools/ci/README.md, "A changelog line in a file of its own"). The kit checks of `ci.yml`'s fast and full jobs run `python3 tools/ci/changes.py check`; a fault is 1 line, `<file>:<line>: <why>`. On 2026-11-19 an open pull request conflicted in CHANGELOG.md each time `main` moved, and GitHub runs no checks on a pull request that conflicts (M279). A release folds the files with `fold` (RELEASING.md step 2).

## The container image: what the owner does once

1. Merge the pull request that carries wip/image. Its `Image` workflow builds both machines' images on the pull request and pushes nothing: read that run first (lines below).
2. After the merge, `Image` runs on main and pushes (every push to main starts it).
3. Open the package: the repository's page, Packages, `via` (or github.com/users/ThyFriendlyFox/packages/container/package/via). The package `via` is made by the first push to it: the release's tag, or the next push to main. Check that it is public, as the old package was. If it shows Private: Package settings, Danger Zone, Change visibility, Public, type the name, confirm ("Configuring a package's access control and visibility", "Configuring visibility of packages for your personal account"). Public cannot be made private again (same page). Until then users and forks cannot pull it; CI on the repository's own branches can (the label links the package before its first publish), and a fork's pull request falls back to install.sh.
4. On the same page, under "Manage Actions access", the repository `via` should be listed with write (a package a workflow publishes is linked to it). If it is not: Add Repository, `via`, Write.
5. Optional: Settings, Secrets and variables, Actions, Variables: `CI_FULL_IN_IMAGE` = `0` sends every full run to install.sh (to take a bad image out of CI at once). Unset or any other value: the image when the registry gives it.
6. Optional: under the same Variables, `CI_APT_UBUNTU_ARCHIVE` = `0` leaves the runner's apt mirror as it is on the install path and the nightly run (to take the archive step out at once). Unset or any other value: apt keeps the runner's mirror and Ubuntu's own archive and asks the fastest first.
7. Optional: the old package `ee-workcenter` holds the images pushed before the first release. Nothing writes to it any more, and the owner may delete it (its Package settings, Danger Zone, Delete this package).

Done on 2026-11-18: steps 1 and 2. Pull request 92's `Image` run (44396387137) built both machines' images and pushed nothing; `build (amd64)` stopped on its first run on a 503 of the KiCad 10 source and passed on its 1 re-run. It was merged as 1fb707c, and the `Image` run on main (44402154037) built both images, pushed them, and its `publish` job passed at 21:36 UTC. Those images went to the old package, `ee-workcenter`. Step 3 for `via` waits for its first push. CI run 44409635104 took the image path first: the install step was skipped and `make verify` ran inside the image, 3732 of 3811 tests passed and 1 failed, a test of the gates step that read the machine's user list, fixed since.

A user's commands for the image of a release: the README, "Run Via from its container".

The lines to read in the first runs:

- The build step: `[install] boot: ... missing; apt install curl gnupg ca-certificates git make gcc libc6-dev` (install.sh's first step), then `workcenter ee: ok` (amd64) or `degraded, without openems` (arm64), then `Setting up nodejs (18.19.1+dfsg-6ubuntu5) ...` (the Dockerfile's install of node, after install.sh), then `image tc-... (x86_64|aarch64) at /opt/workcenters/ee/image.json` with 7 version lines, the last `  node         18.19.1` (`image.py record`). `image.py: record refused: node: not ok in the image` is an image without node. The first doctor in the log is install.sh's own last step, which runs before node is installed: its `node` row reads `absent`, and that is expected. The doctor after `Setting up nodejs` is the Dockerfile's, and its `node` row reads `ok` with `18.19.1`. A line `image.py: record refused: ...` is a failed image.
- "The gates" step: `GREEN: rc_divider` and `owners of the files written: <the runner's user>`. A user id with no name prints its number from `id -un`, which then ends with 1, and the step stops.
- CI's `full` job: `where: image: the registry holds ...` or `where: install: ...` with its reason; on the image path `image: the checkout's Dockerfile, install.sh, requirements.txt are those the image was built from` before `make verify`. On the image's own pull request the job takes the install path (`where: install: this change edits Dockerfile, install.sh: the install path is their test`). On the image path the shards' logs go with the container: a failed test's report follows its `FAILED` line under `why:`, and a shard that ended with no report prints the end of its output.

## Board repositories: `board-gates.yml`

A board repository calls `ThyFriendlyFox/via/.github/workflows/board-gates.yml@main` from 1 workflow of its own; the `board-ci` skill holds the caller. The job pulls `ghcr.io/<owner>/via:<content tag of the toolchain files at workcenter-ref>` with the caller's token. The image path is the normal path: the package is public, and on 2026-11-19 the registry gave its tag list and the manifest of `tc-ad6cb1705e532dcc`, `main`'s content tag, to a pull with no login. When the registry holds no image of that toolchain, or the caller sets `use-image: false`, the job takes the install path: `tools/ci/apt_archive.sh`, then `sudo env APT_UPDATE_TIMEOUT=120 APT_DOWNLOAD_TIMEOUT=570 ./install.sh`, for the same reason as `full`'s install path. `REQUIRE_FREEROUTING` is not set: the 4 gates route nothing. A GREEN with ERC, DRC or EXPORT at skip ends the job red, 1 line per gate: that project had no schematic or no board to judge.

The steps are held by `tests/test_board_gates_workflow.py` with stand-ins. Only a run in a board repository shows that GitHub resolves the `uses:` line and the matrix from the `projects` input, that the caller's `permissions` reach the called job, what docker's line is for a refused pull, how GitHub renders the summary, and the install path's time on a board repository's runner. Of the image path it shows: that `docker run` with `--user` set to the runner's user and group writes the board's `build/` and the report; that `image.py check` passes on Via's checkout inside the image; and that the gates run where `HOME` is not that user's home. `image.yml`'s step "The gates on a fixture, as the runner's user" runs `workcenter gates .` in the image with the same `--user`.

## What CI still needs from a third party

CI's `full` job still needs Launchpad's host on every run that takes the install path. The owner chose the container image to end that: the `full` job runs in the image of its toolchain's content tag when the registry has it, and needs no third party then (`tools/image.py decide`). What stays open: a pull request that changes `Dockerfile`, `install.sh` or `requirements.txt` takes the install path, as its test, and needs Launchpad's host; and every push to main runs install.sh again inside the image build, so an outage of KiCad 10's package source turns that `Image` run red and leaves `main`'s image stale. Building the toolchain layer from install.sh and requirements.txt alone, kept between builds by the registry's cache, would let a push that changes neither run without a third party; it is not built.

The install path also needs Ubuntu's archive. It keeps the runner's mirror, archive.ubuntu.com and security.ubuntu.com (ports.ubuntu.com on an arm machine with a regional mirror) and asks the fastest first, since each was the slow one once on 2026-11-19 (CI runs 44402154007 and 44432768560, then 44477966021). Every host slow or down at once still turns the install path red, and so does a host that trickles without a silence of 15 s, or a first host that accepts and goes silent after the probe; KiCad 10's source has 1 host. The image path does not use the runner's apt.

The image holds node (Ubuntu 24.04's `nodejs`, 18.19.1), so a change to the forms' functions, the lead's workflow scripts, the nightly's issue step or their tests takes the image path like any other change. Before, such a change took the install path for node alone, and on 2026-11-19 a push of website work stopped there at the download's bound on both attempts (CI run 44432768560). The image's own pull request still takes the install path: it edits the Dockerfile.

## The website (Vercel project settings)

- The Vercel project `via`, linked to this repository, Root Directory
  `site`, production branch `main`, production at <https://via.computer>. `site/vercel.json` holds the build command,
  the output folder and the headers. The project has 1 other setting: the
  private Blob store `via-forms` is connected to it, and gives the forms'
  functions in `site/api/` the variable `BLOB_READ_WRITE_TOKEN` in
  production, preview and development (`site/README.md`, "The forms").
- Every push to `main` deploys production. Every other branch gets a
  preview. The project's setting that skips a deployment when a push
  leaves the Root Directory unchanged is on. `make verify` runs the same `site/build.sh` in
  `tests/test_docs.py`, so a build that fails on Vercel fails here first.

## Social preview (repo Settings)

- Settings, General, Social preview: upload `site/og.png`. GitHub has no
  file or API for this image.

## Branch protection on `main` (repo Settings)

- Require the `verify` check; require PRs; require up-to-date branches;
  squash-merge only; auto-delete head branches.
