#!/bin/bash
# Run a tree's health gate alone and push its commit only on VERIFY GREEN: the way for a machine with no
# CI (PROCESSES.md P14 step 4, P31 steps 6 and 7; where CI runs, its `verdict` gates). It takes the lock, waits until no helper's engine or test runs, runs
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
#                        verify-<label>.log, gate-<label>.status, gate-<label>.foreign, and
#                        gate-<label>.look (the output of the gate's last git call or quiet look)
#   GATE_FOLDERS         more folders whose scripts count as a helper's work, ':' between them
#   GATE_QUIET           the program that prints busy processes (default: quiet.py beside this file)
#   GATE_QUIET_SECONDS   seconds between 2 looks for quiet, a number, 0 or more (default 15)
#   GATE_QUIET_TRIES     quiet looks in a row before the gate starts, a whole number above 0 (default 3)
#   GATE_QUIET_LIMIT     whole seconds to wait for quiet before it stops (default 3600)
#   GATE_SAMPLE_SECONDS  seconds between 2 looks for helpers' work during the gate, a number above 0
#                        (default 20)
#   GATE_STOP_SECONDS    whole seconds a stopped make, and its process group, get to end before SIGKILL
#                        (default 30)
#
# Exit: 0 pushed; 1 the gate was red; 2 a bad call (GATE_DIR unset or no folder, or a GATE_QUIET_SECONDS,
# GATE_QUIET_TRIES, GATE_QUIET_LIMIT, GATE_SAMPLE_SECONDS or GATE_STOP_SECONDS it cannot use); 3 stopped
# (HEAD, branch, tree or lock); 4 no quiet in time; 5 the push failed: the remote branch is no longer
# the lease, or 5 tries failed; 6 the quiet check failed; 129, 130 or 143 stopped by SIGHUP, SIGINT or
# SIGTERM, and 141 by a closed stdout or stderr, with make's whole process group ended first; a git
# that one of those signals ended is a stop too. A signal that comes while `git push` runs ends the
# gate once the push has ended, which may have pushed <commit>: after 129, 130, 141 or 143, read the
# remote branch. A signal in the gate's first instants, before its traps are set, ends it with no
# lock made. bash can lose a signal that comes while it parses a $(...) (bash 5.2): the gate's own
# shell runs none once its traps are set, but if a stop does not end the gate, send it again.
# Needs bash 4.2 or later, git, setsid (util-linux) and ps.

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
T=$1
BRANCH=$2
EXPECT=$3
LEASE=$4
LABEL=$5
REMOTE=${6:-$2}
STEP=${GATE_QUIET_SECONDS:-15}
TRIES=${GATE_QUIET_TRIES:-3}
LIMIT=${GATE_QUIET_LIMIT:-3600}
SAMPLE=${GATE_SAMPLE_SECONDS:-20}
STOP=${GATE_STOP_SECONDS:-30}
LOG=$GATE_DIR/verify-$LABEL.log
OUT=$GATE_DIR/gate-$LABEL.status
FOREIGN=$GATE_DIR/gate-$LABEL.foreign
LOOK=$GATE_DIR/gate-$LABEL.look
LOCK=$GATE_DIR/GATE.lock
FOLDERS=("$GATE_DIR")
if [ -n "${GATE_FOLDERS:-}" ]; then
  IFS=: read -r -a MORE <<< "$GATE_FOLDERS"
  FOLDERS+=("${MORE[@]}")
fi
if [[ ! $STOP =~ ^(0|[1-9][0-9]{0,8})$ ]]; then
  echo "gate-and-push: GATE_STOP_SECONDS must be whole seconds, 0 or more: $STOP" >&2
  exit 2
fi
if [[ ! $SAMPLE =~ ^([0-9]+(\.[0-9]+)?|\.[0-9]+)$ ]] || [[ ! $SAMPLE =~ [1-9] ]]; then
  echo "gate-and-push: GATE_SAMPLE_SECONDS must be a number of seconds above 0: $SAMPLE" >&2
  exit 2
fi
if [[ ! $STEP =~ ^([0-9]+(\.[0-9]+)?|\.[0-9]+)$ ]]; then
  echo "gate-and-push: GATE_QUIET_SECONDS must be a number of seconds, 0 or more: $STEP" >&2
  exit 2
fi
if [[ ! $TRIES =~ ^[1-9][0-9]{0,8}$ ]]; then
  echo "gate-and-push: GATE_QUIET_TRIES must be a whole number above 0: $TRIES" >&2
  exit 2
fi
if [[ ! $LIMIT =~ ^(0|[1-9][0-9]{0,8})$ ]]; then
  echo "gate-and-push: GATE_QUIET_LIMIT must be whole seconds, 0 or more: $LIMIT" >&2
  exit 2
fi

# On any exit after the lock, a signal's too, make's whole process group and then the sampler end
# first, and the lock goes last: a helper that waits for the lock to go must never start while
# `make verify` still runs.
SAMPLER=
MAKE_PID=
MAKE_GROUP=
LOCKED=
# quit <code>: every exit after the traps are set. It ignores further signals before it exits: a
# signal that came between `exit` and the first line of finish() ran `exit` inside the EXIT trap, cut
# finish() short and left the lock for good, with make running.
# shellcheck disable=SC2317  # run by the traps
quit() {
  trap '' HUP INT TERM PIPE
  exit "$1"
}
# A signal that comes between a job's `&` and the line that keeps its pid would find no pid to end,
# and one between the lock and the line that notes it would leave the lock: from here to the lock,
# and while a job starts, a signal is only noted, and it ends the gate once the pid or the lock is
# kept. The traps are set before the gate's first command that is not a builtin, so every stop after
# that ends with a listed code. A signal to the gate's process group (a Ctrl-C) also ends the git or
# the quiet look that runs: look() then ends the gate with that signal's code.
SIGNAL=
hold_signals() { trap 'SIGNAL=129' HUP; trap 'SIGNAL=130' INT; trap 'SIGNAL=143' TERM; trap 'SIGNAL=141' PIPE; }
take_signals() {
  trap 'quit 129' HUP
  trap 'quit 130' INT
  trap 'quit 143' TERM
  trap 'quit 141' PIPE
  if [ -n "$SIGNAL" ]; then quit "$SIGNAL"; fi
}
hold_signals

# The gate's own shell takes no output through $(...): a signal that comes while bash parses one can
# make its trap fail to parse, and the stop is lost. Times come from printf and SECONDS, and a
# command's output from the file $LOOK.
# look <command>...: runs the command with its output in $LOOK and returns its exit code. A command
# that SIGHUP, SIGINT, SIGPIPE or SIGTERM ended ends the gate with that code: a stop, not a moved HEAD,
# a busy machine or a failed check.
look() {
  "$@" > "$LOOK"
  local rc=$?
  case $rc in 129 | 130 | 141 | 143) quit "$rc" ;; esac
  return "$rc"
}
look readlink -f "$0"
read -r HERE < "$LOOK"
QUIET=${GATE_QUIET:-${HERE%/*}/quiet.py}
: > "$OUT"
: > "$FOREIGN"
say() {
  local now
  TZ=UTC printf -v now '%(%H:%M:%S)T' -1
  echo "$now $*" >> "$OUT"
  echo "$now $*"
}
busy() { "$QUIET" "$$" "${FOLDERS[@]}"; }
# git_line <git arguments>: the first word of git's output in $line.
git_line() {
  line=
  look git -C "$T" "$@"
  read -r line _ < "$LOOK"
}

git_line rev-parse HEAD
if [ "$line" != "$EXPECT" ]; then say "STOP: HEAD is not $EXPECT"; exit 3; fi
git_line rev-parse "refs/heads/$BRANCH"
if [ "$line" != "$EXPECT" ]; then say "STOP: $BRANCH is not $EXPECT"; exit 3; fi
look git -C "$T" status --short
if [ -s "$LOOK" ]; then say "STOP: the tree is not clean"; cat "$LOOK" >> "$OUT"; exit 3; fi

# child_runs <pid>: the pid is a child of this shell that has not ended. A pid this shell has reaped,
# bash's own reaping included, may be another process's by now: it never gets a signal.
# shellcheck disable=SC2317  # run by the traps
child_runs() {
  local stat
  read -r stat 2>/dev/null < "/proc/$1/stat" || return 1
  stat=${stat##*) }
  [ "${stat%% *}" != Z ] || return 1
  stat=${stat#* }
  [ "${stat%% *}" = "$$" ]
}
# kill_tree <pid>: SIGKILL to the process and to every process under it. Each one is stopped before
# its children are read: a stopped process reaps none, so each number read is still that child's when
# its SIGKILL goes. Called only on this shell's child that has not ended.
# shellcheck disable=SC2317  # run by the traps
kill_tree() {
  local kids=() more task kid
  kill -STOP "$1" 2>/dev/null || return 0
  for task in /proc/"$1"/task/*/children; do
    more=()
    read -r -a more 2>/dev/null < "$task"
    kids+=("${more[@]}")
  done
  for kid in "${kids[@]}"; do kill_tree "$kid"; done
  kill -KILL "$1" 2>/dev/null
}
# The sampler is a coprocess in the gate's own process group. It sleeps with the builtin `read -t` on
# its stdin, a pipe whose only write end this shell holds (bash closes a coprocess's pipes in every
# other process it starts). Closing that end, or any death of this shell, SIGKILL too, ends the
# sampler's `read` at once, and the sampler ends after the look it is in. Only a look that still runs
# 10 s later gets a signal: SIGKILL to the sampler and its look, while the sampler is this shell's
# child that has not ended.
# shellcheck disable=SC2317  # run by the traps
end_sampler() {
  if [ -z "$SAMPLER" ]; then return 0; fi
  if [ -n "${SAMPLER_IO[1]:-}" ]; then
    to_sampler=${SAMPLER_IO[1]}
    exec {to_sampler}>&-
  fi
  tenths=0
  while child_runs "$SAMPLER"; do
    if [ "$tenths" -ge 100 ]; then
      kill_tree "$SAMPLER"
      say "the sampler's look still ran 10 s after its end: sent the sampler and its look SIGKILL"
      break
    fi
    sleep 0.1
    tenths=$((tenths + 1))
  done
  wait "$SAMPLER" 2>/dev/null
  SAMPLER=
}
# make_runs: make, or a process of its group, still runs. make is reaped as soon as it has ended: an
# ended make that is not reaped keeps its group, and its number, in use.
# shellcheck disable=SC2317  # run by the traps
make_runs() {
  if [ -n "$MAKE_PID" ]; then
    if child_runs "$MAKE_PID"; then return 0; fi
    wait "$MAKE_PID" 2>/dev/null
    MAKE_PID=
  fi
  [ -n "$MAKE_GROUP" ] && kill -0 -- "-$MAKE_GROUP" 2>/dev/null
}
# make's tests can take longer than make to end, and some may run on after make ended; GNU make itself
# waits for its children after SIGTERM. The lock goes only once make and its whole process group have
# ended, after SIGKILL to them if they still run STOP s later. Linux gives no process the number of a
# group that has members, so a signal to make's group reaches only make's own processes.
# shellcheck disable=SC2317  # run by the traps
end_make() {
  if [ -n "$MAKE_PID" ] && child_runs "$MAKE_PID"; then
    # Until setsid has made make's group, a kill of the group finds none: end the process itself.
    kill -TERM -- "-$MAKE_PID" 2>/dev/null || kill -TERM "$MAKE_PID" 2>/dev/null
    say "make verify was stopped"
  elif [ -n "$MAKE_GROUP" ] && kill -TERM -- "-$MAKE_GROUP" 2>/dev/null; then
    say "make ended, and processes of its group still ran: sent them SIGTERM"
  fi
  tenths=0
  while make_runs; do
    if [ "$tenths" -eq $((STOP * 10)) ]; then
      if ! kill -KILL -- "-$MAKE_GROUP" 2>/dev/null && child_runs "$MAKE_PID"; then
        kill -KILL "$MAKE_PID" 2>/dev/null
      fi
      say "make's process group still ran $STOP s after the stop: sent it SIGKILL"
    elif [ "$tenths" -gt $((STOP * 10 + 100)) ]; then
      say "make's process group still holds processes 10 s after SIGKILL"
      break
    fi
    sleep 0.1
    tenths=$((tenths + 1))
  done
  MAKE_PID=
  MAKE_GROUP=
}
# shellcheck disable=SC2317  # run by the traps
finish() {
  # Nothing may cut this short, or the lock stays for good: not a second signal, and not a write to
  # a caller's pipe that has closed. make ends before the sampler: a look that hangs must not hold
  # off make's stop.
  trap '' HUP INT TERM PIPE
  if [ -z "$LOCKED" ]; then return 0; fi
  end_make
  end_sampler
  rm -f "$LOCK"
  say "lock removed"
}
trap finish EXIT
if [ -n "$SIGNAL" ]; then quit "$SIGNAL"; fi
# The lock is made only if no file is there (noclobber), so 2 gates never run at once, and a gate
# that finds another's lock leaves it in place. It is made in this shell, whose traps only note a
# signal here: a subshell would have its traps reset, and a signal to the gate's group would kill it
# after it made the file, leaving the lock for good under a false 'another gate runs'.
set -C
if ! { TZ=UTC printf '%(%Y-%m-%dT%H:%M:%SZ)T\n' -1 > "$LOCK"; } 2>/dev/null; then
  set +C
  say "STOP: $LOCK exists: another gate runs"
  exit 3
fi
LOCKED=1
set +C
take_signals

say "lock made; waiting for quiet"
quiet=0
began=$SECONDS
waited=0
while [ "$quiet" -lt "$TRIES" ]; do
  if ! look busy; then say "STOP: the quiet check $QUIET failed"; quit 6; fi
  if [ -s "$LOOK" ]; then quiet=0; else quiet=$((quiet + 1)); fi
  sleep "$STEP"
  waited=$((SECONDS - began))
  if [ "$waited" -ge "$LIMIT" ] && [ "$quiet" -lt "$TRIES" ]; then
    say "STOP: no quiet after $LIMIT s"
    busy >> "$OUT"
    quit 4
  fi
done
say "quiet for $TRIES looks after $waited s; the gate starts"

# While the gate runs, note each engine, test run or script of a helper: the gate must run alone. A
# look that fails is noted too: it saw nothing, which is not quiet. `read` ends with a status over 128
# only when its time is up; the end of its pipe ends the loop (end_sampler).
hold_signals
coproc SAMPLER_IO {
  while true; do
    # A quiet check that reads its stdin gets end of file at once, not this pipe, which ends only
    # with the gate.
    found=$(busy < /dev/null) || found="the quiet check $QUIET failed: whether a helper ran is not known"
    if [ -n "$found" ]; then
      date -u +%H:%M:%S
      echo "$found"
    fi
    read -r -t "$SAMPLE" _
    rc=$?
    if [ "$rc" -le 128 ]; then break; fi
  done >> "$FOREIGN"
}
SAMPLER=$!
take_signals

START=$SECONDS
# make runs in its own process group (setsid), so a stop ends it with every test it started; `wait`
# lets a signal to the gate through at once.
hold_signals
setsid make -C "$T" verify > "$LOG" 2>&1 &
MAKE_PID=$!
MAKE_GROUP=$MAKE_PID
take_signals
wait "$MAKE_PID"
RC=$?
say "make verify ended with exit code $RC after $((SECONDS - START)) s"
# What make left in its group ends now, before the push: once the group is empty its number is free
# for any process, and the gate must not keep it.
end_make
end_sampler
tail -3 "$LOG" >> "$OUT"

if [ "$RC" -ne 0 ] || ! grep -q '^VERIFY GREEN' "$LOG"; then say "RED: no push"; quit 1; fi
git_line rev-parse HEAD
if [ "$line" != "$EXPECT" ]; then say "STOP: HEAD moved during the gate; no push"; quit 3; fi
look git -C "$T" status --short
if [ -s "$LOOK" ]; then
  say "STOP: the tree changed during the gate; no push"
  cat "$LOOK" >> "$OUT"
  quit 3
fi

n=0
delay=2
until git -C "$T" push --force-with-lease="$REMOTE:$LEASE" origin "$EXPECT:refs/heads/$REMOTE" >> "$OUT" 2>&1; do
  n=$((n + 1))
  # A lease that no longer holds will not hold on a second try: someone else pushed. Stop at once.
  git_line ls-remote origin "refs/heads/$REMOTE" 2>/dev/null
  if [ -n "$line" ] && [ "$line" != "$LEASE" ]; then
    say "PUSH REFUSED: $REMOTE on origin is $line, not the lease $LEASE; read it and land again"
    quit 5
  fi
  if [ "$n" -ge 5 ]; then say "PUSH FAILED after $n tries"; quit 5; fi
  say "push try $n failed; again in $delay s"
  sleep "$delay"
  delay=$((delay * 2))
done
say "PUSHED $EXPECT to $REMOTE"
git -C "$T" ls-remote origin "refs/heads/$REMOTE" >> "$OUT" 2>&1
quit 0
