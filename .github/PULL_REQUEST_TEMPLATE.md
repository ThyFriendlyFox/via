## What

## Why
<!-- Fixes #NN / ee-agent-kit/ROADMAP.md item: <name> -->

## Evidence
<!-- The CI run whose `verdict` passed the head, gate summaries, fixture results -->

## Checklist
- [ ] `make check` passed before each push of this branch
- [ ] CI's `verdict` is green on the head commit before the merge (`make verify` in the `full` job; with no CI, `make verify` on the machine)
- [ ] Tests or fixture boards added/updated for behavior changes
- [ ] STATUS/ROADMAP updated in this PR as applicable
- [ ] The changelog line is a new file under `ee-agent-kit/changes/`, not an edit of CHANGELOG.md
- [ ] No secrets, scaffolding, or leftover diagnostics
