# CI.md — what runs in `.github/` and why

The workflow files in `.github/workflows/` are the source of truth. This
file explains them and holds the repository settings that are not files.

| File | Trigger | Does |
|---|---|---|
| `ci.yml` | push to `main`, every PR, manual | `full`: the image of this commit's toolchain when the registry gives it, else `sudo ./install.sh`; then `make verify` (tools/ci/README.md, "Where `full` runs"). |
| `nightly.yml` | 06:17 UTC daily | `sudo env REQUIRE_FREEROUTING=1 ./install.sh` then `make verify`, always by install.sh. Files 1 `ci-failure` issue on red when none is open. Catches a moved PPA, a new KiCad point release, a broken dependency. |
| `image.yml` | PR on the files the build reads, every push to `main`, `v*.*.*`, Monday 04:17 UTC, manual | Builds the image on amd64 and arm64 from install.sh, checks it with doctor and the gates as a user; pushes to `ghcr.io/<owner>/ee-workcenter` except on a PR. |
| `release.yml` | tag `v*.*.*` | Publishes the GitHub Release with generated notes (the image comes from `image.yml`). |
| `stale.yml` | Mondays | Marks issues stale after 60 days, closes after 14 more. `blocked`, `security`, `accepted` are exempt. |
| `../dependabot.yml` | weekly | pip (`requirements.txt`), GitHub Actions, Docker base image. Minor and patch updates grouped. |
| `../PULL_REQUEST_TEMPLATE.md` | every PR | What, Why, Evidence, checklist. |

## Toolchain step

CI's `full` job takes the toolchain from the image of its tag when the
registry has it, else installs with `sudo env REQUIRE_FREEROUTING=1 ./install.sh`
(tools/ci/README.md, "Where `full` runs"). The runner is `ubuntu-24.04`, so the PPA step, the Java package, and ngspice
match the cloud environment. `REQUIRE_FREEROUTING=1` makes a blocked JAR
download fail the run; a green CI proves the autoroute engine installs.

## The container image: what the owner does once

1. Merge the pull request that carries wip/image. Its `Image` workflow builds both machines' images on the pull request and pushes nothing: read that run first (lines below).
2. After the merge, `Image` runs on main and pushes (every push to main starts it).
3. Open the package: the repository's page, Packages, `ee-workcenter` (or github.com/users/ThyFriendlyFox/packages/container/package/ee-workcenter). If it shows Private: Package settings, Danger Zone, Change visibility, Public, type the name, confirm ("Configuring a package's access control and visibility", "Configuring visibility of packages for your personal account"). Public cannot be made private again (same page). Until then users and forks cannot pull it; CI on the repository's own branches can (the label links the package before its first publish), and a fork's pull request falls back to install.sh.
4. On the same page, under "Manage Actions access", the repository `via` should be listed with write (a package a workflow publishes is linked to it). If it is not: Add Repository, `via`, Write.
5. Optional: Settings, Secrets and variables, Actions, Variables: `CI_FULL_IN_IMAGE` = `0` sends every full run to install.sh (to take a bad image out of CI at once). Unset or any other value: the image when the registry gives it.

The lines to read in the first runs:

- The build step: `[install] boot: ... missing; apt install curl gnupg ca-certificates git make gcc libc6-dev` (install.sh's first step), then `workcenter ee: ok` (amd64) or `degraded, without openems` (arm64), then `image tc-... (x86_64|aarch64) at /opt/workcenters/ee/image.json` with 6 version lines (`image.py record`). A line `image.py: record refused: ...` is a failed image.
- "The gates" step: `GREEN: rc_divider` and `owners of the files written: <the runner's user>`.
- CI's `full` job: `where: image: the registry holds ...` or `where: install: ...` with its reason; on the image path `image: the checkout's Dockerfile, install.sh, requirements.txt are those the image was built from` before `make verify`. On the image's own pull request the job takes the install path (`where: install: this change edits Dockerfile, install.sh: the install path is their test`).

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
