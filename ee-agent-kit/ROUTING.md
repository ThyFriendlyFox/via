# ROUTING.md — read this first

You are an AI agent pointed at this repository. This folder (`ee-agent-kit/`)
is the operating system for working on it. This file tells you which file
governs which situation. Do not improvise a process that a file below
already defines.

## Dispatch table

| You are here because… | Go to | Notes |
|---|---|---|
| First time this kit is in this repo (placeholders like `{{THIS}}` still exist anywhere in the kit) | `SETUP.md` | One-time tailoring. Do this before anything else. |
| "Push out a feature" / "do the weekly update" / a scheduled weekly trigger fired | `WEEKLY.md` | The core cycle. Requires ROADMAP.md to have a ready queue. |
| Deciding WHAT to build, or the queue is empty/stale | `ROADMAP.md` | The single source of work. Nothing gets built that isn't traceable to it. |
| Writing or changing ANY code, at any time | `AGENTS.md` | The binding contract: commands, invariants, landmines, style. Always in effect. |
| About to do something `PROCESSES.md` names (a hand route, a CI step, a route, a doc that names a tag or run, a scripted edit, a close-out) | `PROCESSES.md` | Binding checklists. Follow the steps; done means its "Done when" holds. |
| You made a mistake, redid work, or a run was red because of you | `MISTAKES.md` | Append the entry and point it at a process, same PR. No process yet → write it (`P13`). |
| On a board, and the next step is not plain | `workcenter next <project>` | The one next step: the command, why, what to read, when it is done. Exit 0 when nothing is left. |
| On a chip (a folder with `chip.json`): RTL, benches, a mask layout | `workcenter next <project>`, then `../.claude/skills/chip-design/SKILL.md` and `../.claude/skills/chip-gates/SKILL.md` | The same command names a chip's one next step. The 2 skills write the project and drive the 10 chip gates to GREEN. |
| A circuit's limit, a part that switches, a deck for another machine | `../.claude/skills/simulate/SKILL.md` | Corners (`sim/corners.json`), the frequency plan (`sim/frequency-plan.json`, `PROCESSES.md` P30), bundles (`sim --bundle`). |
| About to start a helper on part of a task | `PROCESSES.md` P31 | Budget first, the lead in its own worktree, a brief per helper. |
| A project's version landed, a branch is about to be deleted, or "what did the projects teach the workcenter?" | `PROCESSES.md` P35 | `python3 tools/harvest.py branches`, `scripts`, `mistakes`; each finding with its evidence and 6 scores into ROADMAP.md under "Later", the highest rating first. |
| Asked "where does this project stand?" | `STATUS.md` | Answer from it; update it when state changes. |
| The gate fails, or you're adding/changing checks | `VERIFICATION.md` | One command answers "is this repo healthy". |
| Cutting a release / tagging | `RELEASING.md` | Weekly cycle ends here. |
| Triage, dependency updates, stale issues, deprecations | `MAINTENANCE.md` | The between-features runbook. |
| Vulnerability report or anything secret-shaped | `SECURITY.md` | Overrides normal process. Never open a public issue for it. |
| Human contributor questions, PR conventions | `CONTRIBUTING.md` | |
| CI is missing or broken, workflows need creating | `CI.md` | Source blocks for `.github/workflows/`. |
| Understanding the codebase before a change | `docs/ARCHITECTURE.md` | Parts, data flow, boundaries. |
| Adding/changing any config option | `docs/CONFIGURATION.md` | Every knob lands in its table, same PR. |
| Adding or changing an engine (kicad-cli, ngspice, FreeRouting, kipy) | `docs/ENGINES.md` | Includes the new-engine contract: install step, doctor check, gate, 2 fixtures. |
| Judging whether a feature is worth building, or writing roadmap items | `docs/USE-CASES.md` | Every ROADMAP item traces to a use case here. |
| Writing ANY user-facing text (docs, UI copy, errors, release notes) | `docs/STYLE.md` | One voice, enforced terms table. |
| Writing YOUR OWN words — commits, PR bodies, reports, devlog entries | `TONE.md` | The agent's voice. Always in effect, like AGENTS.md. |
| Recording what happened this week (or any notable event) | `DEVLOG.md` | Append-only plain history. Every cycle writes an entry. |
| Asked for a blog post / public write-up of recent work | `skills/blog-post/SKILL.md` | Devlog in, post out. Never publishes without a go-ahead. |
| The session holds more than 1 repository, or a repository was added mid-session | `skills/attached-repos/SKILL.md` | Assign roles before the first edit. The board is the project; this repo is the workcenter and read-only. |
| Changing what a project gets from this workcenter (a tool, gate, path, requirement) | `../WORKCENTER.md` | The contract. Same commit as the change. `WORKCENTER.template.md` is the blank for new workcenters. |
| Placing parts, reviewing a schematic, layout or Gerbers, a part's derating, a footprint, a symbol, a panel | `../.claude/skills/kistack/SKILL.md` | Names the vendored kistack skill for the step (`third_party/kistack/`) and where this kit's rules win over it. |
| Requirements, a design review, an inspection (MIL-STD, DO-160), proof that a board meets its parts' ratings | `../.claude/skills/verification/SKILL.md` and `PROCESSES.md` P28 | The verification package: conditions, sourced requirements, cited nodal analysis per deck, traceability; `workcenter verify` checks it against a fresh run. |

## Precedence

1. `SECURITY.md` overrides everything for security-shaped work.
2. `AGENTS.md` is binding whenever code is touched; `PROCESSES.md` is binding whenever an action it names is taken; `TONE.md` is binding whenever the agent writes words. When any of them conflicts with intuition, it wins.
3. `ROADMAP.md` decides what gets built. If requested work isn't on it, add it to the roadmap first (or get the human to), then build it. **The roadmap is not optional — every feature flows down from it.**
4. `VERIFICATION.md`'s gate decides what ships. No green, no push.
5. Everything else is reference.

## Standing rules (apply in every instance)

- Docs move with behavior: STATUS.md, CHANGELOG.md, ROADMAP.md updates land in the same commit/PR as the change they describe.
- Commit at boundaries with evidence in the message. Never commit directly to `main`.
- Report outcomes faithfully: failing is reported as failing, with output.
- Scope is what the current roadmap item names — no side quests. Defects found on the way get fixed if they block the item, otherwise queued in ROADMAP.md.
