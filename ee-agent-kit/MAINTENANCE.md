# MAINTENANCE.md — the between-features runbook

## Cadence

| Task | When | How |
|---|---|---|
| Issue/PR triage | Weekly, start of cycle | Label, ask for repro, close-with-reason or queue on ROADMAP.md |
| Dependency updates | Weekly (automated) | Merge green Dependabot PRs; batch minors |
| A pull request from a bot or a host's integration | When it arrives | Merge it only with its `verdict` check green on its head commit. It edits files by hand that a script of the repository writes: Vercel's analytics pull request changed 7 generated pages, was merged red on 2026-11-16, and `main` failed 4 tests until the generator was given its lines |
| Harvest of the projects' findings | When a project's version lands, and before a branch is deleted | `PROCESSES.md` P35: `python3 tools/harvest.py branches`, `scripts` and `mistakes`; findings go to the table under "Later" in ROADMAP.md with their scores, and `python3 tools/harvest.py later` holds it |
| Security advisories | Immediately | SECURITY.md |
| Stale sweep | Automated | `stale.yml` (CI.md) |
| Health check | Per PR + nightly | `make verify` in CI |

## Triage labels

`bug` · `enhancement` · `docs` · `good first issue` · `help wanted` ·
`needs-repro` · `blocked` · `wontfix` · `security` · `ci-failure`

## Issue lifecycle

new → labeled → (needs-repro?) → accepted (queued on ROADMAP.md if it's
feature-shaped) → in progress → closed by PR or closed-with-reason.
Never close silently; one sentence of why is the minimum.

## Deprecation policy

Deprecate in release N with a warning; remove no earlier than N+2.
Every deprecation gets a changelog line under `### Deprecated`, in a
change file of its own under `ee-agent-kit/changes/` (its README says the form).

## Bus factor

Maintainers: <!-- handles -->. If unmaintained, the intent is:
<!-- archive with notice / hand to org / bless a fork -->.
