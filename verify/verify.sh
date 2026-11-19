#!/usr/bin/env bash
# verify/verify.sh — one command answers "is this repo healthy".
# Runs the same steps locally and in CI, in this order, the steps with no engine first:
#   1 lint  2 kit checks (no placeholders, every skill has frontmatter, manifest copied)
#   3 doctor (toolchain present)  4 tests on fixture boards, in shards side by side
# A step that cannot run fails loudly; nothing passes silently. The last lines say each step's time.
set -euo pipefail
cd "$(dirname "$0")/.."

# `verify.sh site` is the fast gate (make verify-site): for every change, and beside the full gate
# for a change tools/ci/scope.py calls full. It hides KiCad's libraries.
# It starts no engine: the tests marked `engine` are left out, and any other test that starts one
# is refused (WORKCENTER_NO_ENGINES=1) and fails (tools/ci/engine_marker.py).
# `verify.sh kit` runs the kit checks alone (make kit, inside make check): it reads a few files,
# takes no lock and leaves no gate record.
mode=${1:-full}
case "$mode" in
  full | site | kit) ;;
  *) echo "usage: verify/verify.sh [site|kit]"; exit 2 ;;
esac

# The gate runs alone: it waits its turn on the machine's engine lock and holds it to its end. The
# commands its tests start are its children and do not wait for it (tools/enginelock.py). The fast
# gate (`verify.sh site`) takes it too, as `make verify-site`: it starts no engine, but its tests
# fill the machine's processors for minutes.
if [[ "$mode" != kit ]] && ! python3 tools/enginelock.py held; then
  exec python3 tools/enginelock.py hold --what "make verify${1:+-$1}" -- bash verify/verify.sh "$@"
fi

VENV_PY=/opt/workcenters/ee/venv/bin/python
PY=python3
[[ -x "$VENV_PY" ]] && PY="$VENV_PY"

STEP="0/4 start"
# step "<name>" starts a step and notes the time the one before took; step "" ends the last one.
current=""
mark=$SECONDS
timings=()
step() {
  [[ -n "$current" ]] && timings+=("$(printf '%5d s  %s' $((SECONDS - mark)) "$current")")
  current="$*"
  mark=$SECONDS
  [[ -n "$current" ]] && STEP="$current" && printf '\n== %s\n' "$current"
  return 0
}

kit_checks() {
# Kit placeholders may remain only in SETUP.md, whose table documents them.
if grep -rnE '\{\{(PROJECT_NAME|REPO_SLUG|DEFAULT_BRANCH|BUILD_CMD|TEST_CMD|LINT_CMD|VERIFY_CMD|MIN_RUNTIME|SECURITY_EMAIL|PKG_ECOSYSTEM)\}\}' \
     ee-agent-kit docs 2>/dev/null | grep -v '^ee-agent-kit/SETUP.md:'; then
  echo "unfilled kit placeholders found"; exit 1
fi
for skill in .claude/skills/*/SKILL.md ee-agent-kit/skills/*/SKILL.md; do
  head -1 "$skill" | grep -q '^---$' || { echo "$skill: missing frontmatter"; exit 1; }
  grep -q '^name:' "$skill" || { echo "$skill: missing name"; exit 1; }
  grep -q '^description:' "$skill" || { echo "$skill: missing description"; exit 1; }
done
for kit_skill in ee-agent-kit/skills/*/; do
  name=$(basename "$kit_skill")
  diff -q "$kit_skill/SKILL.md" ".claude/skills/$name/SKILL.md" >/dev/null \
    || { echo "ee-agent-kit/skills/$name drifted from .claude/skills/$name"; exit 1; }
done
[[ -f WORKCENTER.md ]] || { echo "WORKCENTER.md missing at repo root"; exit 1; }
# One text for every agent host: CLAUDE.md for those that read it, AGENTS.md for the rest.
cmp -s CLAUDE.md AGENTS.md || { echo "CLAUDE.md and AGENTS.md at the root differ"; exit 1; }
# Every mistake names a process that exists; every process says when it is done.
grep -oE '^Process: P[0-9]+' ee-agent-kit/MISTAKES.md | awk '{print $2}' | sort -u | while read -r p; do
  grep -qE "^## $p " ee-agent-kit/PROCESSES.md || { echo "MISTAKES.md names $p; PROCESSES.md has no '## $p'"; exit 1; }
done || exit 1
awk '/^## M[0-9]+ /{if (h != "" && !p) {print h ": no Process line"; bad = 1}; h = $0; p = 0}
     /^Process: P[0-9]+$/{p = 1}
     END{if (h != "" && !p) {print h ": no Process line"; bad = 1}; exit bad}' ee-agent-kit/MISTAKES.md || exit 1
awk '/^## P[0-9]+ /{if (h != "" && !d) {print h ": no Done when line"; bad = 1}; h = $0; d = 0}
     /^Done when:/{d = 1}
     END{if (h != "" && !d) {print h ": no Done when line"; bad = 1}; exit bad}' ee-agent-kit/PROCESSES.md || exit 1
# A change's changelog line is a file of its own under ee-agent-kit/changes/ (M279); each is well formed.
python3 tools/ci/changes.py check || exit 1
echo "kit checks ok"
}

if [[ "$mode" == kit ]]; then
  kit_checks
  exit 0
fi

# The fast gate leaves no gate record: build/verify.json speaks for the whole `make verify` only.
if [[ "$mode" == site ]]; then
  step "1/4 shellcheck site/build.sh"
  shellcheck site/build.sh
  step "2/4 site build"
  built=$(mktemp -d)
  trap 'rm -rf "$built"' EXIT
  sh site/build.sh "$built/site"
  echo "site built: $(find "$built/site" -type f | wc -l) files"
  step "3/4 tests that start no engine"
  # The fast job's runner has no KiCad: its symbol and footprint folders (tools/kicadgen.py) are empty
  # folders here too, so a test that loads a library without saying so fails on any machine (P12).
  nokicad="$built/no-kicad"
  mkdir -p "$nokicad/symbols" "$nokicad/footprints"
  # `-p testshards` ends the run with its `not judged:` lines: each test a mark skipped on this machine,
  # by reason, and each that skipped inside the test; the whole list is not-judged.txt in pytest's base
  # folder (pytest-of-<user>), which CI's kept logs copy. A test `-m "not engine"` leaves out is not named.
  PYTHONPATH="verify${PYTHONPATH:+:$PYTHONPATH}" KICAD_SYMBOL_DIR="$nokicad/symbols" KICAD_FOOTPRINT_DIR="$nokicad/footprints" WORKCENTER_NO_ENGINES=1 "$PY" -m pytest -q -p testshards -p no:cacheprovider -m "not engine" tests
  step "4/4 kit checks"
  kit_checks
  printf '\nVERIFY-SITE GREEN in %ss\n' "$SECONDS"
  exit 0
fi

# For `workcenter now`: the commit the gate tests and whether the tree differs from it, noted before
# step 1; on exit the trap writes them with the verdict and the step to build/verify.json, ignored by git.
GATE_HEAD=$(git rev-parse HEAD 2>/dev/null || true)
GATE_DIRTY=no
[[ -z "$(git status --porcelain 2>/dev/null || true)" ]] || GATE_DIRTY=yes
trap 'python3 tools/now.py record "$?" "$STEP" --head "$GATE_HEAD" --dirty "$GATE_DIRTY" >/dev/null \
  || echo "no gate record written" >&2' EXIT

step "1/4 lint"
shellcheck install.sh verify/verify.sh environment/setup.sh site/build.sh ee-agent-kit/lead/gate-and-push.sh tools/ci/apt_archive.sh tools/ci/apt_cache.sh
"$PY" -m ruff check tools tests verify ee-agent-kit/lead
"$PY" -m ruff format --check tools tests verify ee-agent-kit/lead

step "2/4 kit checks"
kit_checks

step "3/4 doctor"
python3 tools/workcenter doctor

step "4/4 tests"
# 1 pytest per processor, files split by verify/shards.csv; red when a shard fails, ends before
# pytest's end of session, the ids run differ from the ids 1 process collects, or a test's skip or
# xfail marks differ between its shard and 1 process.
"$PY" verify/testshards.py run --table verify/shards.csv --python "$PY"

step ""
printf '\n== time\n'
printf '%s\n' "${timings[@]}"
printf '%5d s  in all\n' "$SECONDS"
printf '\nVERIFY GREEN\n'
