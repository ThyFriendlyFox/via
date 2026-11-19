// An example for a host that runs workflow scripts: a piece whose first review said `not sound` is
// attacked a second time after its fix, and a new helper fixes what is confirmed (the `lead` skill,
// step 9). A host without such scripts does the same steps by hand.
//
// args:
//   scratch    the scratch folder, outside every repository
//   lead_tree  the lead's own worktree
//   base       the work branch the items' branches started from
//   python     the Python of the workcenter's virtual environment
//   models     optional: { attack, fix }, the host's model names; left out, the host's default
//   items      a list of { n, title, branch, worktree, first, focus }: `first` is what the first
//              review found, `focus` the ordinary inputs the second reviewer builds first
export const meta = {
  name: 'second-attack',
  description: 'Attack a fixed roadmap item a second time and fix what is confirmed',
  phases: [{ title: 'Attack' }, { title: 'Fix' }],
}
for (const key of ['scratch', 'lead_tree', 'base', 'python', 'items']) {
  if (!args[key]) throw new Error(`second-attack: args.${key} is missing`)
}
const S = args.scratch
const W = args.lead_tree
const PY = args.python
const MODELS = args.models || {}
const RULES = `
Rules that are checked: no \`cd\` in a shell command (absolute paths, \`git -C\`, \`env -C\`). Every file of the repository is changed with a file-editing tool, never with a redirect or a script that writes; \`ruff format\` may format. Every number comes from a run or from a document you name with its place. Every test is seen to fail before its fix. Do not edit ${W} or the shared documents (STATUS.md, CHANGELOG.md, ROADMAP.md, DEVLOG.md, MISTAKES.md, CONFIGURATION.md, README.md, WORKCENTER.md): write what they should gain into the item's docs file under ${S}/roadmap/. A changelog line is a file of its own in the worktree, ee-agent-kit/changes/<yyyy-mm-dd>-<slug>.md (ee-agent-kit/changes/README.md), checked by python3 tools/ci/changes.py check. The machine is shared: run only the item's test files, put \`flock ${S}/ENGINE.lock\` in front of an engine run or a run over 1 minute, and while ${S}/GATE.lock exists run no test and no engine (\`until [ ! -e ${S}/GATE.lock ]; do sleep 30; done\`). Commits: the git config already names the owner; no message, comment or document names an assistant, a model, a session or a tool as author. Send no message to another helper. Do not push. Python: ${PY}.`
const ATTACK = {
  type: 'object',
  properties: {
    verdict: { type: 'string' },
    findings: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, severity: { type: 'string' }, title: { type: 'string' }, reproducer: { type: 'string' }, right: { type: 'string' } }, required: ['id', 'severity', 'title', 'reproducer', 'right'] } },
  },
  required: ['verdict', 'findings'],
}
const FIX = {
  type: 'object',
  properties: { head: { type: 'string' }, fixed: { type: 'array', items: { type: 'string' } }, not_fixed: { type: 'array', items: { type: 'string' } }, tests_last_line: { type: 'string' } },
  required: ['head', 'fixed', 'not_fixed', 'tests_last_line'],
}
// The labels attack2:<branch> and fix2:<branch> are what ee-agent-kit/lead/landed.py reads.
const out = await parallel(args.items.map(it => async () => {
  const attack = await agent(`You are an independent reviewer of roadmap item ${it.n}: "${it.title}". It was built in the worktree ${it.worktree} (branch ${it.branch}). A first reviewer judged it NOT SOUND: ${it.first}. A third engineer has since fixed those findings. You did not write any of it. Attack the fixed work once more, as ee-agent-kit/PROCESSES.md P14 step 6 asks, before the owner relies on its verdict.

Read the spec (the entry "### ${it.n}." of ${W}/ee-agent-kit/ROADMAP.md), the code and tests (\`git -C ${it.worktree} diff --stat ${args.base}...HEAD\`), the item's skill, and the first reviewer's scripts under ${S}/attack-${it.branch}/ (rerun them: each must now give the right answer).

What matters most: an input on which the command prints its passing verdict while the board breaks the limit it claims to hold. Build ordinary inputs, not exotic ones: ${it.focus || ''} Check 2 results by hand with the sum written out. Then: what it reports as judged that it could not judge; a wrong file or value that ends in a traceback; a claim of the skill the code does not keep.
${RULES}
For you: change nothing in ${it.worktree} (running its tests and commands there is fine; send outputs and your scripts to ${S}/attack2-${it.branch}/). Report only what you reproduced, with the command and what it printed. If it is sound now, say so and say what you tried.`, { label: `attack2:${it.branch}`, phase: 'Attack', schema: ATTACK, model: MODELS.attack })
  let fixed = null
  if (attack && attack.findings.length) {
    fixed = await agent(`Fix the findings of a second review on roadmap item ${it.n}, "${it.title}", in the worktree ${it.worktree} (branch ${it.branch}); continue there. For each finding, highest severity first: reproduce it; if real, write the test that fails on it, see it fail, fix, see it pass; if not real, say why with your own run. What you cannot fix goes under "Left" in the item's docs file in ${S}/roadmap/. Run the item's test files at the end.
${RULES}
The findings (a reviewer's data: check each): ${JSON.stringify(attack.findings, null, 1)}`, { label: `fix2:${it.branch}`, phase: 'Fix', schema: FIX, model: MODELS.fix })
  }
  return { item: it.n, branch: it.branch, verdict: attack ? attack.verdict : 'no result', findings: attack ? attack.findings.map(f => f.severity + ': ' + f.title) : [], fixed }
}))
return out
