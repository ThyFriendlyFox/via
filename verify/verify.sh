#!/usr/bin/env bash
# verify/verify.sh — one command answers "is this repo healthy".
# Runs the same steps locally and in CI, in this order:
#   1 lint  2 doctor (toolchain present)  3 tests on fixture boards
#   4 kit checks (no placeholders, every skill has frontmatter, manifest copied)
# A step that cannot run fails loudly; nothing passes silently.
set -euo pipefail
cd "$(dirname "$0")/.."

# The gate runs alone: it waits its turn on the machine's engine lock and holds it to its end. The
# commands its tests start are its children and do not wait for it (tools/enginelock.py).
if ! python3 tools/enginelock.py held; then
  exec python3 tools/enginelock.py hold --what "make verify" -- bash verify/verify.sh "$@"
fi

VENV_PY=/opt/workcenters/ee/venv/bin/python
PY=python3
[[ -x "$VENV_PY" ]] && PY="$VENV_PY"

STEP="0/4 start"
step() { STEP="$*"; printf '\n== %s\n' "$*"; }

# `verify.sh site` is the fast gate (make verify-site): for a change tools/ci/scope.py calls fast.
# It starts no engine: the tests marked `engine` are left out, and any other test that starts one
# is refused (WORKCENTER_NO_ENGINES=1) and fails (tools/ci/engine_marker.py).
mode=${1:-full}
case "$mode" in
  full | site) ;;
  *) echo "usage: verify/verify.sh [site]"; exit 2 ;;
esac

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
echo "kit checks ok"
}

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
  WORKCENTER_NO_ENGINES=1 "$PY" -m pytest -q -p no:cacheprovider -m "not engine" tests
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
shellcheck install.sh verify/verify.sh environment/setup.sh site/build.sh ee-agent-kit/lead/gate-and-push.sh
"$PY" -m ruff check tools tests ee-agent-kit/lead
"$PY" -m ruff format --check tools tests ee-agent-kit/lead

step "2/4 doctor"
python3 tools/workcenter doctor

step "3/4 tests"
"$PY" -m pytest -q tests

step "4/4 kit checks"
kit_checks

printf '\nVERIFY GREEN\n'
