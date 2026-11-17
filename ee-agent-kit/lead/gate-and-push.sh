#!/bin/bash
# Run a tree's health gate alone and push its commit only on VERIFY GREEN (PROCESSES.md P14 step 2,
# P31 steps 6 and 7). It takes the lock, waits until no helper's engine or test runs, runs
# `make -C <tree> verify`, and pushes <commit> with a lease only when the gate printed `VERIFY GREEN`,
# exited 0, and the tree is still <commit> with nothing changed.
#
# usage: gate-and-push.sh <tree> <branch> <commit> <lease> <label> [remote branch]
#   <commit>  the full hash that must be HEAD and <branch>: from `git rev-parse`, never typed
#   <lease>   the full hash the remote branch holds now (`git ls-remote origin <remote branch>`)
#   <label>   names the files the run writes in GATE_DIR
#
# Environment:
#   GATE_DIR             required: the folder of the lock (GATE.lock) and of the run's files:
#                        verify-<label>.log, gate-<label>.status, gate-<label>.foreign
#   GATE_FOLDERS         more folders whose scripts count as a helper's work, ':' between them
#   GATE_QUIET           the program that prints busy processes (default: quiet.py beside this file)
#   GATE_QUIET_SECONDS   seconds between 2 looks for quiet (default 15)
#   GATE_QUIET_TRIES     quiet looks in a row before the gate starts (default 3)
#   GATE_QUIET_LIMIT     seconds to wait for quiet before it stops (default 3600)
#   GATE_SAMPLE_SECONDS  seconds between 2 looks for helpers' work during the gate (default 20)
#
# Exit: 0 pushed; 1 the gate was red; 2 a bad call (GATE_DIR unset or no folder); 3 stopped (HEAD,
# branch, tree or lock); 4 no quiet in time; 5 the push failed: the remote branch is no longer the lease,
# or 5 tries failed; 6 the quiet check failed; 129, 130 or 143 stopped by a signal, with make ended first.
# Needs bash, git, setsid (util-linux) and ps.

if [ $# -lt 5 ] || [ $# -gt 6 ]; then
  echo "usage: gate-and-push.sh <tree> <branch> <commit> <lease> <label> [remote branch]" >&2
  exit 2
fi
if [ -z "${GATE_DIR:-}" ]; then
  echo "gate-and-push: GATE_DIR is not set: the folder for the lock and the logs" >&2
  exit 2
fi
if [ ! -d "$GATE_DIR" ]; then
  echo "gate-and-push: GATE_DIR $GATE_DIR is not a folder" >&2
  exit 2
fi
HERE=$(dirname "$(readlink -f "$0")")
T=$1
BRANCH=$2
EXPECT=$3
LEASE=$4
LABEL=$5
REMOTE=${6:-$2}
QUIET=${GATE_QUIET:-$HERE/quiet.py}
STEP=${GATE_QUIET_SECONDS:-15}
TRIES=${GATE_QUIET_TRIES:-3}
LIMIT=${GATE_QUIET_LIMIT:-3600}
SAMPLE=${GATE_SAMPLE_SECONDS:-20}
LOG=$GATE_DIR/verify-$LABEL.log
OUT=$GATE_DIR/gate-$LABEL.status
FOREIGN=$GATE_DIR/gate-$LABEL.foreign
LOCK=$GATE_DIR/GATE.lock
FOLDERS=("$GATE_DIR")
if [ -n "${GATE_FOLDERS:-}" ]; then
  IFS=: read -r -a MORE <<< "$GATE_FOLDERS"
  FOLDERS+=("${MORE[@]}")
fi
: > "$OUT"
: > "$FOREIGN"
say() { echo "$(date -u +%H:%M:%S) $*" >> "$OUT"; echo "$(date -u +%H:%M:%S) $*"; }
busy() { "$QUIET" "$$" "${FOLDERS[@]}"; }

if [ "$(git -C "$T" rev-parse HEAD)" != "$EXPECT" ]; then say "STOP: HEAD is not $EXPECT"; exit 3; fi
if [ "$(git -C "$T" rev-parse "refs/heads/$BRANCH")" != "$EXPECT" ]; then say "STOP: $BRANCH is not $EXPECT"; exit 3; fi
if [ -n "$(git -C "$T" status --short)" ]; then say "STOP: the tree is not clean"; git -C "$T" status --short >> "$OUT"; exit 3; fi

# The lock is made only if no file is there (noclobber), so 2 gates never run at once, and a gate
# that finds another's lock leaves it in place.
if ! (set -C; date -u +%Y-%m-%dT%H:%M:%SZ > "$LOCK") 2>/dev/null; then
  say "STOP: $LOCK exists: another gate runs"
  exit 3
fi
# On any exit, a signal's too, the sampler and make's whole process group end first, and the lock goes
# last: a helper that waits for the lock to go must never start while `make verify` still runs.
SAMPLER=
MAKE_PID=
# shellcheck disable=SC2317  # run by the traps
finish() {
  if [ -n "$SAMPLER" ]; then kill "$SAMPLER" 2>/dev/null; wait "$SAMPLER" 2>/dev/null; fi
  if [ -n "$MAKE_PID" ] && kill -0 "$MAKE_PID" 2>/dev/null; then
    kill -TERM -- "-$MAKE_PID" 2>/dev/null
    wait "$MAKE_PID" 2>/dev/null
    say "make verify was stopped"
  fi
  rm -f "$LOCK"
  say "lock removed"
}
trap finish EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

say "lock made; waiting for quiet"
quiet=0
waited=0
while [ "$quiet" -lt "$TRIES" ]; do
  if ! found=$(busy); then say "STOP: the quiet check $QUIET failed"; exit 6; fi
  if [ -z "$found" ]; then quiet=$((quiet + 1)); else quiet=0; fi
  sleep "$STEP"
  waited=$((waited + STEP))
  if [ "$waited" -ge "$LIMIT" ] && [ "$quiet" -lt "$TRIES" ]; then
    say "STOP: no quiet after $LIMIT s"
    busy >> "$OUT"
    exit 4
  fi
done
say "quiet for $TRIES looks after $waited s; the gate starts"

# While the gate runs, note each engine, test run or script of a helper: the gate must run alone.
# Its sleep runs in the background, so a kill ends the sampler at once and not after the sleep.
(
  nap=
  # shellcheck disable=SC2317  # run by the trap
  trap 'if [ -n "$nap" ]; then kill "$nap" 2>/dev/null; fi; exit 0' TERM
  while true; do
    found=$(busy)
    if [ -n "$found" ]; then
      date -u +%H:%M:%S
      echo "$found"
    fi >> "$FOREIGN"
    sleep "$SAMPLE" &
    nap=$!
    wait "$nap"
  done
) &
SAMPLER=$!

START=$(date +%s)
# make runs in its own process group (setsid), so a stop ends it with every test it started; `wait`
# lets a signal to the gate through at once.
setsid make -C "$T" verify > "$LOG" 2>&1 &
MAKE_PID=$!
wait "$MAKE_PID"
RC=$?
MAKE_PID=
kill "$SAMPLER" 2>/dev/null
wait "$SAMPLER" 2>/dev/null
SAMPLER=
END=$(date +%s)
say "make verify ended with exit code $RC after $((END - START)) s"
tail -3 "$LOG" >> "$OUT"

if [ "$RC" -ne 0 ] || ! grep -q '^VERIFY GREEN' "$LOG"; then say "RED: no push"; exit 1; fi
if [ "$(git -C "$T" rev-parse HEAD)" != "$EXPECT" ]; then say "STOP: HEAD moved during the gate; no push"; exit 3; fi
if [ -n "$(git -C "$T" status --short)" ]; then
  say "STOP: the tree changed during the gate; no push"
  git -C "$T" status --short >> "$OUT"
  exit 3
fi

n=0
delay=2
until git -C "$T" push --force-with-lease="$REMOTE:$LEASE" origin "$EXPECT:refs/heads/$REMOTE" >> "$OUT" 2>&1; do
  n=$((n + 1))
  # A lease that no longer holds will not hold on a second try: someone else pushed. Stop at once.
  now=$(git -C "$T" ls-remote origin "refs/heads/$REMOTE" 2>/dev/null | cut -f1)
  if [ -n "$now" ] && [ "$now" != "$LEASE" ]; then
    say "PUSH REFUSED: $REMOTE on origin is $now, not the lease $LEASE; read it and land again"
    exit 5
  fi
  if [ "$n" -ge 5 ]; then say "PUSH FAILED after $n tries"; exit 5; fi
  say "push try $n failed; again in $delay s"
  sleep "$delay"
  delay=$((delay * 2))
done
say "PUSHED $EXPECT to $REMOTE"
git -C "$T" ls-remote origin "refs/heads/$REMOTE" >> "$OUT" 2>&1
exit 0
