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
| A board is GREEN and is to become compact, correct and good to look at, or "iterate on it" | `../.claude/skills/board-loop/SKILL.md` | 1 prompt run again and again; a reviewer who has not seen the earlier rounds names the 3 worst problems. The project's `LOOP.md` (from `templates/project/LOOP.md`) holds the prompt, the checklist and the log. |
| A circuit's limit, a part that switches, a deck for another machine | `../.claude/skills/simulate/SKILL.md` | Corners (`sim/corners.json`), the frequency plan (`sim/frequency-plan.json`, `PROCESSES.md` P30), bundles (`sim --bundle`). |
| About to start a helper on part of a task | `PROCESSES.md` P31 | Budget first, the lead in its own worktree, a brief per helper. |
| A project's version landed, a branch is about to be deleted, or "what did the projects teach the workcenter?" | `PROCESSES.md` P35 | `python3 tools/harvest.py branches`, `scripts`, `mistakes`; each finding with its evidence and 6 scores as a row of the table under "Later" in ROADMAP.md, the highest rating first; `python3 tools/harvest.py later` holds the table. |
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
| A schematic's parts against their ratings before layout: a pin's voltage limits, a part's derating, a regulator's load, the parts a datasheet asks for | `../.claude/skills/ratings/SKILL.md` | `workcenter ratings`: each part's facts from its datasheet with the page of every number, the nets the board cannot say, a rule pack that names its standard. |
| A board goes to a fab or an assembler; a panel; a plan of measurements for a built board | `../.claude/skills/fabrication/SKILL.md` | EXPORT's placement file, assembly pages, IPC-2581 and panel, each read back; `workcenter measure`. |
| Starting a piece of work on a branch, or several agents work at once and a maintainer follows them on the project board | `../.claude/skills/now/SKILL.md` and `PROCESSES.md` P36 | `workcenter now`: 1 work card per piece of work in 1 issue's body, its `**Status:**` line in the board's own word, rewritten at each landing, block and gate; the workflow Board moves the card. |
| You are leading helpers on roadmap items: briefs, worktrees, reviews, what has finished | `skills/lead/SKILL.md` | Build, an attack by a second helper, a fix by a third; a second attack for `not sound`; `python3 lead/landed.py` says what finished. The budget is `PROCESSES.md` P31's. |
| Finished work is to go onto the work branch, or the work branch onto the default branch | `skills/land/SKILL.md` | Each piece's own commits in a straight line, its docs file applied, the gate alone on a second tree (`lead/gate-and-push.sh`); the default branch only at the owner's word, by a merge commit. |
| Is the roadmap still pointed at its goal? Run a user round | `skills/user-round/SKILL.md` | 3 users of different sizes on 1 board spec; where the small fails and the large does not is a process not written down; ranked candidates, each with a test. |
| A fast pair on a board (USB 2.0, USB 3.x): its width, gap, length, skew or reference plane | `../.claude/skills/highspeed/SKILL.md` | `workcenter highspeed`: `interfaces.json` names each pair; every limit from the interface's document, the width from the cross-section solver. |
| A routed board's voltage drop, current density or temperature; a heat map | `../.claude/skills/copper/SKILL.md` | `workcenter copper`: each power net on its own copper and in its barrels, and the board's steady temperature, against `copper.json`'s limits, with a picture of each. |
| A fast interface or an antenna on a routed board: a track's impedance, loss or crosstalk | `../.claude/skills/fields/SKILL.md` | `workcenter fields`: openEMS on the nets `fields.json` names, each limit with its source. |
| Comparing routers, or the order a board routes in | `../.claude/skills/autoroute/SKILL.md` | `workcenter bench` and `design --route --order`; a router becomes a board's default only by the benchmark. |
| A routed board's gaps, track widths or vias against a standard (ECSS-Q-ST-70-12C), or against a fab's limits | `../.claude/skills/board-rules/SKILL.md` | `board-rules.json` names the pack; volts and amps from `ratings.json`; every failure names its clause and page. |
| A rule cites a standard or a datasheet; a document's revision changed; a tool or a test cites a document; `make verify` fails in `tests/test_references.py` or `tests/test_references_code.py` | `../.claude/skills/references/SKILL.md` | `workcenter references`: the index of the documents the rules cite, each fetched once under the workcenter's name and held by its SHA256. |
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
