## What

## Why
<!-- Fixes #NN / ee-agent-kit/ROADMAP.md item: <name> -->

## Evidence
<!-- The CI run whose `verdict` passed the head, gate summaries, fixture results -->

## Checklist
- [ ] `make check` passed before each push of this branch
- [ ] CI's `verdict` is green on the head commit, and the branch holds `main`'s tip (`make verify` for a `full` change, `make verify-site` for a `fast` one; with no CI, `make verify` on the machine)
- [ ] Merged with `gh pr merge <number> --merge --match-head-commit <sha>`, the head whose `verdict` was read
- [ ] Tests or fixture boards added/updated for behavior changes
- [ ] STATUS/ROADMAP updated in this PR as applicable
- [ ] The changelog line is a new file under `ee-agent-kit/changes/`, not an edit of CHANGELOG.md
- [ ] No secrets, scaffolding, or leftover diagnostics
