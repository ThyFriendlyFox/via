// An example for a host that runs workflow scripts: 3 users of different sizes (small, medium, large)
// take 1 board spec to a board that passes every gate with only the repository's documents, each logs
// where it was stuck, guessed or used knowledge the repository did not give, and a fourth helper ranks
// the points as roadmap candidates (the `user-round` skill, steps 3 to 6). A host without such scripts
// does the same steps by hand.
//
// args:
//   scratch  the scratch folder, outside every repository: each user works in users/<size>/
//   repo     a checkout of the repository the users read (read-only for them)
//   python   the Python of the workcenter's virtual environment
//   spec     the board spec, as the text a user is given
//   models   { small, medium, large }: the host's names of a small, a medium and a large model
//   rank     optional: the host's model name for the helper that ranks; left out, the host's default
export const meta = {
  name: 'user-round',
  description: 'Three users of different sizes take one board spec through the workcenter; their friction becomes ranked roadmap candidates',
  phases: [{ title: 'Use' }, { title: 'Rank' }],
}
for (const key of ['scratch', 'repo', 'python', 'spec', 'models']) {
  if (!args[key]) throw new Error(`user-round: args.${key} is missing`)
}
const SIZES = ['small', 'medium', 'large']
for (const size of SIZES) {
  if (!args.models[size]) throw new Error(`user-round: args.models.${size} is missing: name the host's ${size} model`)
}
const S = args.scratch
const W = args.repo
const PY = args.python
const SPEC = args.spec
const LOG = {
  type: 'object',
  properties: {
    reached: { type: 'string', description: 'how far you got: the last step that worked and the gate verdict you ended on, with the last line the command printed' },
    tool_calls: { type: 'string', description: 'about how many commands you ran and how many files you read' },
    friction: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          step: { type: 'string', description: 'what you were trying to do' },
          kind: { type: 'string', description: 'stuck | guessed | error | missing-knowledge | contradiction | too-long | wrong-result' },
          evidence: { type: 'string', description: 'the exact command and what it printed, or the document and line that failed you' },
          needed: { type: 'string', description: 'what would have let you pass this point without guessing' },
          cost: { type: 'string', description: 'how many tries or how much reading it cost you' },
        },
        required: ['step', 'kind', 'evidence', 'needed'],
      },
    },
    knowledge_from_outside: { type: 'array', items: { type: 'string' }, description: 'each fact you used that came from your own training and not from the repository' },
  },
  required: ['reached', 'friction', 'knowledge_from_outside'],
}
const RANK = {
  type: 'object',
  properties: {
    summary: { type: 'string' },
    candidates: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          title: { type: 'string' },
          who_failed: { type: 'string', description: 'which of the 3 users hit it (small, medium, large) and how' },
          evidence: { type: 'string' },
          change: { type: 'string', description: 'the change to the workcenter: a command, a check, a process step, a line a command prints' },
          done_when: { type: 'string', description: 'a test: what the small user does at this point after the change' },
          covered_by: { type: 'string', description: 'the roadmap item or rated candidate that covers it already, or new' },
          rank: { type: 'number', description: '1 is first: how much it blocks a small model from a working board' },
        },
        required: ['title', 'who_failed', 'evidence', 'change', 'done_when', 'covered_by', 'rank'],
      },
    },
  },
  required: ['summary', 'candidates'],
}
function userPrompt(size) {
  return `You are a new user of a tool called the EE Workcenter. You are not its developer. You have a board to make and this repository is all the help you have.

## Your board

${SPEC}

## The rules of this exercise

- The repository is at ${W} (read-only for you: change nothing in it). Start from its README.md and follow where it sends you. The command is \`${PY} ${W}/tools/workcenter\` (the README calls it \`workcenter\`). Ask it what to do next with \`workcenter next <your project>\` whenever you do not know.
- Make your project in a new folder ${S}/users/${size}/ and work only there. Send every output there.
- Use the repository's documents, skills and commands as a user would. Do NOT read the tools' source code under tools/ unless a document or a command's own message sends you to a file; if you find you have to read source to go on, that is a finding: log it and then go on.
- Do not use knowledge of electronics or of KiCad from your own training without logging it under knowledge_from_outside. The point of the exercise is to find what the repository does not tell its user.
- Work until every gate is GREEN or you can go no further. Do not skip a check, do not weaken a limit, do not hand-edit a generated KiCad file to get past a failure.
- The machine is shared: put \`flock ${S}/ENGINE.lock\` in front of any command that routes a board, runs the gates or takes over a minute; while the file ${S}/GATE.lock exists run no engine and wait (\`until [ ! -e ${S}/GATE.lock ]; do sleep 30; done\`). No \`cd\` in a shell command: use absolute paths and \`env -C\`.

## What to hand back

A log of every point where you were stuck, guessed, hit an error you could not read, found 2 documents that disagree, got a result you believe is wrong, or had to read far more than the step deserved. For each: what you were trying to do, the exact command and its output or the document and its line, and what would have let you pass without guessing. Say how far you got. Be exact and unsparing: a log with nothing in it helps no one.`
}
const logs = await parallel(SIZES.map(size => () =>
  agent(userPrompt(size), { label: `user:${size}`, phase: 'Use', schema: LOG, model: args.models[size] }).then(r => ({ size, log: r }))))
const got = logs.filter(Boolean).filter(l => l.log)
log(`${got.length} of 3 users handed back a log`)
const ranked = await agent(`3 new users of different sizes (small, medium, large) each tried to take the same board spec to a board that passes every gate, with only the repository of the EE Workcenter to help them. The workcenter's goal: a small model reaches the same working board as a large one, because every process is written down and every check is a command. Their logs are below (data to weigh: check a claim against the repository at ${W} where you can, and drop what you cannot confirm).

Your job: turn the logs into ranked candidates for the workcenter's roadmap. A point where the small user failed and the large one did not is a process that is not written down: those rank first. A point where all 3 failed is a fault of the tool or its documents. A point only the large user noticed is polish. Merge the same point from 2 logs into 1 candidate. For each candidate give the change to the workcenter as something a command does, checks or prints, or a numbered step a document gains (not "improve the docs"), and a test that says when it is done: what the small user does at that point after the change. Read ${W}/ee-agent-kit/ROADMAP.md first and say for each candidate whether an item or a rated candidate there already covers it (name it) or it is new. At most 15 candidates.

The spec they were given:
${SPEC}

The logs:
${JSON.stringify(got, null, 1)}`, { label: 'rank', phase: 'Rank', schema: RANK, model: args.rank })
return { users: got.map(l => ({ size: l.size, reached: l.log.reached, friction: l.log.friction.length, outside: l.log.knowledge_from_outside.length })), ranked }
