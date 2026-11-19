# Change files: a change's changelog line, in a file of its own

A change does not edit `CHANGELOG.md`. It adds 1 file here, `<yyyy-mm-dd>-<slug>.md` (slug: a-z, 0-9, -).
Line 1 is 1 heading as CHANGELOG.md writes it: `### Added`, `### Changed`, `### Deprecated`,
`### Removed`, `### Fixed` or `### Security`. Then 1 or more `- ` lines, as they will stand there.
Nothing else. A change of 2 kinds writes 2 files. Pick a slug of your own: 2 files of 2 names merge clean
(MISTAKES.md M279), 1 name in 2 branches is git's add/add conflict; keep both lines and rename 1 file.
`python3 tools/ci/changes.py check` judges the files (in `make verify` and `make verify-site`);
`show` prints what is unreleased. A release runs `fold <X.Y.Z> <date>` (RELEASING.md step 2).
A line written under `## [Unreleased]` in CHANGELOG.md stays valid; this README is not a change file.
