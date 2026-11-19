# RELEASING.md — cutting a release

The weekly cycle (WEEKLY.md step 7) ends here. Weekly update = **minor**
by default; **major** if breaking; out-of-band fixes = patch.
(Pre-1.0: breaking → minor, everything else → patch.)

1. A release is cut only from a commit the gate passed: CI's `verdict`
   is green on that exact commit of `main`
   (`gh run list --workflow ci.yml --commit <sha>`), or, where there is
   no CI, `make verify` printed `VERIFY GREEN` on it. Steps 2 to 4 make a
   new commit: it goes through a pull request and waits for its own
   `verdict`, and the tag goes on it only then.
2. The fold: `python3 tools/ci/changes.py fold X.Y.Z YYYY-MM-DD`. It
   writes `## [X.Y.Z] - YYYY-MM-DD` into CHANGELOG.md with the lines
   under its `## [Unreleased]` and the lines of every change file in
   `ee-agent-kit/changes/`, under their headings; it leaves an empty
   `## [Unreleased]` and deletes the files it folded. It refuses a
   version that is already there. Read `git diff` before the commit.
3. Bump the version where the stack keeps it (manifest/plist/gradle/…).
4. Commit `chore: release vX.Y.Z` on a branch; push it on `make check`;
   merge its pull request when `verdict` is green on its head. Put the
   tag `vX.Y.Z` on that merge commit of `main` once its own `verdict`
   is green, and push the tag.
5. `release.yml` (CI.md) builds artifacts and publishes the GitHub
   Release from the tag.
6. Verify the published artifact actually installs/runs. A release
   isn't done until it's been exercised.
7. STATUS.md "Last release" gets the new tag; ROADMAP.md Shipped table
   gets the release column filled.
