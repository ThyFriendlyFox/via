# CONTRIBUTING.md

## Ground rules

- Be respectful; assume good faith.
- Open an issue before large changes; small fixes go straight to PR.
- Feature-sized ideas go to ROADMAP.md's queue via an issue — that's the
  path to getting built.
- One logical change per PR; refactors separate from behavior changes.
- A commit names its human author. No message credits an assistant as
  author or co-author; `make verify` fails on a commit that does.

## Workflow

1. Branch from `main`: `feat/…`, `fix/…`, `docs/…`, `chore/…`.
2. Change + tests for any behavior change.
3. `make check` green before each push. `make verify`, the whole health
   gate, runs on the pull request in CI's `full` job.
4. Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`,
   `test:`, `ci:`; `!` for breaking).
5. PR against `main`; fill the template; CI's `verdict` green on the
   head commit, the branch holding `main`'s tip, and comments resolved
   before merge. Name the head in the merge, so GitHub refuses it if the
   head moved: `gh pr merge <number> --squash --match-head-commit <sha>`.
   Squash-merge; PR title becomes the
   commit message, so make it a valid Conventional Commit.
