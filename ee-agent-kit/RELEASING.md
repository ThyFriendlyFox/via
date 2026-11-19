# RELEASING.md — cutting a release

The weekly cycle (WEEKLY.md step 7) ends here. Weekly update = **minor**
by default; **major** if breaking; out-of-band fixes = patch.
(Pre-1.0: breaking → minor, everything else → patch.)

1. A release is cut only from a commit the gate passed: CI's `verdict`
   is green on that exact commit of `main`
   (`gh run list --workflow ci.yml --commit <sha>`), or, where there is
   no CI, `make verify` printed `VERIFY GREEN` on it. Steps 2 to 4 make a
   new commit: it goes through a pull request and waits for its own
   `verdict`. The tag goes on it only when a `full` job passed on it
   (step 4), never on a `fast` verdict alone.
2. The fold: `python3 tools/ci/changes.py fold X.Y.Z YYYY-MM-DD`. It
   writes `## [X.Y.Z] - YYYY-MM-DD` into CHANGELOG.md with the lines
   under its `## [Unreleased]` and the lines of every change file in
   `ee-agent-kit/changes/`, under their headings; it leaves an empty
   `## [Unreleased]` and deletes the files it folded. It refuses a
   version that is already there. Read `git diff` before the commit.
3. Bump the version where the stack keeps it (manifest/plist/gradle/…).
4. Commit `chore: release vX.Y.Z` on a branch; push it on `make check`;
   merge its pull request when `verdict` is green on its head (AGENTS.md).
   The tag needs the whole gate on the tagged commit: a run of `ci.yml`
   on that merge commit of `main` whose `full` job passed. A release
   commit changes only documents, so `make scope` calls it `fast`, and
   the push to `main` runs the `fast` job alone. So ask for a run by
   hand, which is always `full`: `gh workflow run ci.yml --ref main`.
   Find it with
   `gh run list --workflow ci.yml --commit <sha> --event workflow_dispatch`,
   and read its jobs:
   `gh run view <id> --json jobs --jq '.jobs[] | select(.name == "full" or .name == "verdict") | .conclusion'`
   prints `success` twice. Only then put the tag `vX.Y.Z` on `<sha>` and
   push the tag. If `main` moved before the run started, the run tested
   another commit: tag that commit after its own run, or run again.
5. `release.yml` (CI.md) builds artifacts and publishes the GitHub
   Release from the tag.
6. Verify the published artifact actually installs/runs. A release
   isn't done until it's been exercised.
7. STATUS.md "Last release" gets the new tag; ROADMAP.md Shipped table
   gets the release column filled.
