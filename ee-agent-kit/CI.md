# CI.md — what runs in `.github/` and why

The workflow files in `.github/workflows/` are the source of truth. This
file explains them and holds the repository settings that are not files.

| File | Trigger | Does |
|---|---|---|
| `ci.yml` | push to `main`, every PR, manual | `fast` on every change: no toolchain, `make verify-site` (KiCad's libraries hidden, no engine started). `full`: the image of this commit's toolchain when the registry gives it, else `tools/ci/apt_archive.sh` (apt asks Ubuntu's own archive, not the runner's regional mirror), then `sudo env REQUIRE_FREEROUTING=1 APT_UPDATE_TIMEOUT=120 APT_DOWNLOAD_TIMEOUT=570 ./install.sh`; then `make verify` (tools/ci/README.md, "Where `full` runs"). `verdict` passes when `fast` passed and, for a change `tools/ci/scope.py` calls full, `full` too. |
| `nightly.yml` | 06:17 UTC daily | `tools/ci/apt_archive.sh`, then `sudo env REQUIRE_FREEROUTING=1 APT_UPDATE_TIMEOUT=120 APT_DOWNLOAD_TIMEOUT=570 ./install.sh` then `make verify`, always by install.sh. Keeps 1 `ci-failure` issue in step with the nights (`tools/ci/nightly_issue.py`): a failed night opens it or adds 1 comment with the run and the gate's `why:` lines; a passed night closes it with 1 comment naming the run; a second open one is closed as a duplicate of the oldest (tools/ci/README.md, "The nightly's `ci-failure` issue"). Catches a moved PPA, a new KiCad point release, a broken dependency. |
| `image.yml` | PR on the files the build reads, every push to `main`, `v*.*.*`, Monday 04:17 UTC, manual | Builds the image on amd64 and arm64 from install.sh, with CI's 2 bounds of its apt step as build arguments, checks it with doctor and the gates as a user; pushes to `ghcr.io/<owner>/via` except on a PR. |
| `release.yml` | tag `v*.*.*` | Publishes the GitHub Release with generated notes (the image comes from `image.yml`). |
| `stale.yml` | Mondays | Marks issues stale after 60 days, closes after 14 more. `blocked`, `security`, `accepted` are exempt. |
| `../dependabot.yml` | weekly | pip (`requirements.txt`), GitHub Actions, Docker base image. Minor and patch updates grouped. |
| `../PULL_REQUEST_TEMPLATE.md` | every PR | What, Why, Evidence, checklist; the changelog line is a new file under `ee-agent-kit/changes/`. |

## Toolchain step

CI's `full` job takes the toolchain from the image of its tag when the
registry has it, else installs with `sudo env REQUIRE_FREEROUTING=1 APT_UPDATE_TIMEOUT=120 APT_DOWNLOAD_TIMEOUT=570 ./install.sh`
(tools/ci/README.md, "Where `full` runs").

The 2 bounds end a stalled index or download with apt's own line within the `full` job's 30 minutes: 88 s for the key + 3 x 120 + 2 x 20 + 570 = 1058 s of the 1066 s the newest passing run left (job 134941364976). The nightly run (45 minutes) and the image build (60 minutes) set the same 2; `test_the_worst_case_of_the_apt_step_fits_the_jobs_limit` reads each workflow's own limit. A person's computer has no total bound. The download's 570 s cover all its passes and the waits between them (APT_DOWNLOAD_TRIES, default 5; APT_DOWNLOAD_WAIT, default 20 s), so the sum stays 1058 s. CI and the image build set neither variable and run on the script's defaults; `test_ci_and_the_image_build_leave_the_passes_and_the_wait_to_the_script` holds the 3 workflows and the Dockerfile to that.

The runner is `ubuntu-24.04`, so the PPA step, the Java package, and ngspice
match the cloud environment. `REQUIRE_FREEROUTING=1` makes a blocked JAR
download fail the run; a green CI proves the autoroute engine installs.

Before install.sh, the install path and the nightly run turn apt from the runner's regional mirror to Ubuntu's own archive: `sudo env APT_ARCHIVE_CI=1 bash tools/ci/apt_archive.sh /etc/apt`. Twice the mirror us-east-2.ec2.archive.ubuntu.com crawled and the download hit its bound of 570 s (CI runs 44402154007 and 44432768560), while the image builds of the same hours asked archive.ubuntu.com and were fast (`Image` run 44432768632 built both machines between 00:54 and 00:59 UTC on 2026-11-19). The script changes only a regional or cloud host of archive.ubuntu.com or ports.ubuntu.com; a layout it does not know, it names and leaves. Setting the repository variable `CI_APT_UBUNTU_ARCHIVE` to `0` turns it off (tools/ci/README.md, "Ubuntu's own archive on the install path"). Its first run on a runner, CI run 44444183056 (2026-11-19), passed, and the install step then took 1 min 29 s, where the 3 runs before it on the regional mirror ran 9 min 43 s or more and stopped at the download's bound.

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
6. Optional: under the same Variables, `CI_APT_UBUNTU_ARCHIVE` = `0` leaves the runner's apt mirror as it is on the install path and the nightly run (to take the archive step out at once). Unset or any other value: apt asks Ubuntu's own archive.
7. Optional: the old package `ee-workcenter` holds the images pushed before the first release. Nothing writes to it any more, and the owner may delete it (its Package settings, Danger Zone, Delete this package).

Done on 2026-11-18: steps 1 and 2. Pull request 92's `Image` run (44396387137) built both machines' images and pushed nothing; `build (amd64)` stopped on its first run on a 503 of the KiCad 10 source and passed on its 1 re-run. It was merged as 1fb707c, and the `Image` run on main (44402154037) built both images, pushed them, and its `publish` job passed at 21:36 UTC. Those images went to the old package, `ee-workcenter`. Step 3 for `via` waits for its first push. CI run 44409635104 took the image path first: the install step was skipped and `make verify` ran inside the image, 3732 of 3811 tests passed and 1 failed, a test of the gates step that read the machine's user list, fixed since.

A user's commands for the image of a release: the README, "Run the workcenter from its container".

The lines to read in the first runs:

- The build step: `[install] boot: ... missing; apt install curl gnupg ca-certificates git make gcc libc6-dev` (install.sh's first step), then `workcenter ee: ok` (amd64) or `degraded, without openems` (arm64), then `image tc-... (x86_64|aarch64) at /opt/workcenters/ee/image.json` with 6 version lines (`image.py record`). A line `image.py: record refused: ...` is a failed image.
- "The gates" step: `GREEN: rc_divider` and `owners of the files written: <the runner's user>`. A user id with no name prints its number from `id -un`, which then ends with 1, and the step stops.
- CI's `full` job: `where: image: the registry holds ...` or `where: install: ...` with its reason; on the image path `image: the checkout's Dockerfile, install.sh, requirements.txt are those the image was built from` before `make verify`. On the image's own pull request the job takes the install path (`where: install: this change edits Dockerfile, install.sh: the install path is their test`). On the image path the shards' logs go with the container: a failed test's report follows its `FAILED` line under `why:`, and a shard that ended with no report prints the end of its output.

## What CI still needs from a third party

CI's `full` job still needs Launchpad's host on every run that takes the install path. The owner chose the container image to end that: the `full` job runs in the image of its toolchain's content tag when the registry has it, and needs no third party then (`tools/image.py decide`). What stays open: a pull request that changes `Dockerfile`, `install.sh` or `requirements.txt` takes the install path, as its test, and needs Launchpad's host; and every push to main runs install.sh again inside the image build, so an outage of KiCad 10's package source turns that `Image` run red and leaves `main`'s image stale. Building the toolchain layer from install.sh and requirements.txt alone, kept between builds by the registry's cache, would let a push that changes neither run without a third party; it is not built.

The install path also needs Ubuntu's archive. It asks archive.ubuntu.com (ports.ubuntu.com on an arm machine), not the runner's regional mirror, since the mirror crawled to the download's bound in CI runs 44402154007 and 44432768560. A slow or absent archive.ubuntu.com still turns the install path red; the image path does not use the runner's apt.

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
