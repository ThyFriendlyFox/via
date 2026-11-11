# EE Workcenter

This repository is a workcenter: tools, skills, and gates for turning a
KiCad 10 project into fabrication outputs that passed every check.

Read in this order:

1. `ee-agent-kit/ROUTING.md` decides which file governs the situation.
2. `ee-agent-kit/AGENTS.md` is binding whenever code here is touched.
3. `WORKCENTER.md` is the contract projects get from this workcenter.
4. `ee-agent-kit/PROCESSES.md` is binding before any action it names;
   every mistake lands in `ee-agent-kit/MISTAKES.md` with its process, in
   the same PR.

On a board, `workcenter next <project>` names the one next step: what to
do, the command, why, what to read, and when the step is done. Follow it
until it says nothing is left.

A skill is a procedure at `.claude/skills/<name>/SKILL.md`. A host that
loads skills offers each by name; any other reader opens the file.

A commit names the repository's owner as its author and its committer, as
`git log -1 origin/main` names them. No message carries a `Co-Authored-By`
line for an assistant, a session line, or a tool's name as an author.
`make verify` fails on a commit that does.

Session with more than 1 repository: run the `attached-repos` skill before
the first edit. This repository is read-only during a board task unless the
task is about the workcenter itself.
