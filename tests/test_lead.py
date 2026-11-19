"""The lead's tools in ee-agent-kit/lead/: which piece of work has finished (landed.py), the health gate
run alone with the push behind its verdict (gate-and-push.sh), what keeps the machine busy (quiet.py),
and the 3 example scripts for a host that runs workflow scripts.

No test reaches a network or a real `make verify`: a stand-in `make` and a stand-in `ps` go first on
PATH, and the remote is a bare repository made in the test's own folder.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LEAD = ROOT / "ee-agent-kit" / "lead"
LANDED = LEAD / "landed.py"
GATE = LEAD / "gate-and-push.sh"
QUIET = LEAD / "quiet.py"
JOURNAL = ROOT / "tests" / "lead" / "journal.jsonl"
SCRIPTS = ("roadmap-lane.js", "second-attack.js", "user-round.js")


def landed(state: Path, *journals: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(LANDED), str(state), *map(str, journals)], capture_output=True, text=True
    )


def test_landed_names_the_finished_piece_and_says_what_the_others_wait_for(tmp_path):
    """The canned journal holds 3 pieces. alpha: built, reviewed (2 findings), fixed (1 fixed, 1
    refuted): finished, its head is the fix's. beta: reviewed with 1 finding, no fix: waits. gamma:
    built, no review: waits. The state file then holds ["alpha"], and a second run finds nothing new
    (exit 1) and prints the same 2 waiting lines."""
    state = tmp_path / "landed.json"
    first = landed(state, JOURNAL)
    assert first.returncode == 0, first.stderr
    assert first.stdout == (
        "=== LANDED alpha  head dddddddddddd\n"
        "summary: alpha builds\n"
        "evidence: tests/test_alpha.py holds it\n"
        "not_done: []\n"
        "reviews: 1\n"
        "review 1: sound with findings: 2 edge cases | findings: 2\n"
        "evidence_holds: yes\n"
        'fix 1: fixed 1 | not_fixed: ["F2: refuted"]\n'
        "tests: 5 passed in 1.20s\n"
        "waiting beta: review 1 has 1 finding and no fix yet\n"
        "waiting gamma: no review yet\n"
    )
    assert json.loads(state.read_text(encoding="utf-8")) == ["alpha"]
    again = landed(state, JOURNAL)
    assert again.returncode == 1
    assert again.stdout == (
        "waiting beta: review 1 has 1 finding and no fix yet\n"
        "waiting gamma: no review yet\n"
        "landed: nothing new\n"
    )
    assert json.loads(state.read_text(encoding="utf-8")) == ["alpha"]


def entry(kind: str, agent: str, label_or_result) -> str:
    if kind == "started":
        return json.dumps({"type": "started", "agentId": agent, "label": label_or_result})
    return json.dumps({"type": "result", "agentId": agent, "result": label_or_result})


def test_a_piece_the_first_review_calls_not_sound_lands_only_after_a_second_review(tmp_path):
    """delta: review 1 says `not sound` with 1 finding and a fix follows. It waits for review 2. Once
    review 2 says `sound` with 0 findings it lands with 2 reviews; with 0 findings no fix 2 is asked,
    and its head and tests are fix 1's."""
    lines = [
        entry("started", "d1", "build:delta"),
        entry("result", "d1", {"head": "1" * 40, "summary": "s", "evidence": "e", "not_done": []}),
        entry("started", "d2", "attack:delta"),
        entry("result", "d2", {"verdict": "Not sound: a false pass", "findings": [{"id": "F1"}]}),
        entry("started", "d3", "fix:delta"),
        entry(
            "result",
            "d3",
            {"head": "2" * 40, "fixed": ["F1"], "not_fixed": [], "tests_last_line": "7 passed"},
        ),
    ]
    journal = tmp_path / "journal.jsonl"
    journal.write_text("\n".join(lines) + "\n", encoding="utf-8")
    state = tmp_path / "landed.json"
    first = landed(state, journal)
    assert first.returncode == 1
    assert first.stdout == (
        "waiting delta: review 1 said not sound; a second review is needed before it lands\n"
        "landed: nothing new\n"
    )
    lines += [
        entry("started", "d4", "attack2:delta"),
        entry("result", "d4", {"verdict": "sound: tried 6 inputs", "findings": []}),
    ]
    journal.write_text("\n".join(lines) + "\n", encoding="utf-8")
    second = landed(state, journal)
    assert second.returncode == 0, second.stderr
    assert second.stdout.splitlines() == [
        "=== LANDED delta  head 222222222222",
        "summary: s",
        "evidence: e",
        "not_done: []",
        "reviews: 2",
        "review 1: Not sound: a false pass | findings: 1",
        "evidence_holds: ",
        "fix 1: fixed 1 | not_fixed: []",
        "review 2: sound: tried 6 inputs | findings: 0",
        "tests: 7 passed",
    ]


def test_a_helper_that_ended_with_no_result_is_named_not_counted_as_finished(tmp_path):
    """A build or a review whose result is null has not finished: a review with no result is no review
    with 0 findings."""
    lines = [
        entry("started", "e1", "build:eps"),
        entry("result", "e1", None),
        entry("started", "z1", "build:zeta"),
        entry("result", "z1", {"head": "3" * 40}),
        entry("started", "z2", "attack:zeta"),
        entry("result", "z2", None),
        entry("started", "h1", "build:eta"),
    ]
    journal = tmp_path / "journal.jsonl"
    journal.write_text("\n".join(lines) + "\n", encoding="utf-8")
    run = landed(tmp_path / "landed.json", journal)
    assert run.returncode == 1
    assert run.stdout == (
        "waiting eps: the build ended with no result; read its journal before starting it again\n"
        "waiting eta: no build result yet\n"
        "waiting zeta: review 1 ended with no result; start a new review\n"
        "landed: nothing new\n"
    )


def write_journal(path: Path, lines: list[str]) -> Path:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def reviewed(branch: str, review, fix="none") -> list[str]:
    """A built piece of `branch` with 1 review result and, unless fix is "none", 1 fix result."""
    lines = [
        entry("started", f"{branch}1", f"build:{branch}"),
        entry("result", f"{branch}1", {"head": "a" * 40, "summary": f"{branch} builds"}),
        entry("started", f"{branch}2", f"attack:{branch}"),
        entry("result", f"{branch}2", review),
    ]
    if fix != "none":
        lines += [entry("started", f"{branch}3", f"fix:{branch}"), entry("result", f"{branch}3", fix)]
    return lines


SOUND_1 = {"verdict": "sound with findings", "findings": [{"id": "F1"}]}


@pytest.mark.parametrize(
    "review, fix, why",
    [
        ("I ran out of time before I could review anything.", "none", "review 1 has no verdict"),
        ({}, "none", "review 1 has no verdict"),
        ({"verdict": "", "findings": []}, "none", "review 1 has no verdict"),
        ({"verdict": 3, "findings": []}, "none", "review 1 has no verdict"),
        ({"findings": []}, "none", "review 1 has no verdict"),
        ({"verdict": "sound"}, "none", "review 1 has no list of findings"),
        ({"verdict": "sound with findings", "findings": 2}, "none", "review 1 has no list of findings"),
        (SOUND_1, None, "the fix of review 1 ended with no result; start a new fix"),
        (
            SOUND_1,
            {"head": "c" * 40, "fixed": None, "not_fixed": []},
            "the fix of review 1 has no list fixed",
        ),
        (SOUND_1, {"head": "c" * 40, "not_fixed": []}, "the fix of review 1 has no list fixed"),
        (
            SOUND_1,
            {"head": "c" * 40, "fixed": [], "not_fixed": "F1"},
            "the fix of review 1 has no list not_fixed",
        ),
    ],
)
def test_a_review_or_a_fix_that_did_not_report_its_verdict_is_not_landed(tmp_path, review, fix, why):
    """A review is finished when it gives a verdict (a string that is not empty) and a list of findings;
    a fix, when it gives a list `fixed` and, if it gives one, a list `not_fixed`. Anything else waits, in 1
    line, with exit 1: it was not judged, so it is not passed."""
    journal = write_journal(tmp_path / "j.jsonl", reviewed("alpha", review, fix))
    run = landed(tmp_path / "landed.json", journal)
    assert (run.returncode, run.stderr) == (1, "")
    assert run.stdout == f"waiting alpha: {why}\nlanded: nothing new\n"


def test_a_review_started_twice_counts_both_results(tmp_path):
    """attack:alpha started as r1 and r2. r2 says `not sound` with F1, then r1 says `sound` with none. Both
    count: 1 finding (0 + 1) with no fix, so it waits. With a fix of F1 it waits for a second review, as
    review 1 said not sound. A review restarted after a null result counts the one that reported; a review
    started again that has not reported yet holds the piece."""
    build = [
        entry("started", "b1", "build:alpha"),
        entry("result", "b1", {"head": "a" * 40, "summary": "alpha builds"}),
    ]
    twice = [
        entry("started", "r1", "attack:alpha"),
        entry("started", "r2", "attack:alpha"),
        entry("result", "r2", {"verdict": "not sound: a false pass", "findings": [{"id": "F1"}]}),
        entry("result", "r1", {"verdict": "sound", "findings": []}),
    ]
    journal = write_journal(tmp_path / "j.jsonl", build + twice)
    run = landed(tmp_path / "landed.json", journal)
    assert run.stdout == "waiting alpha: review 1 has 1 finding and no fix yet\nlanded: nothing new\n"
    fix = [
        entry("started", "f1", "fix:alpha"),
        entry("result", "f1", {"head": "c" * 40, "fixed": ["F1"], "not_fixed": []}),
    ]
    write_journal(journal, build + twice + fix)
    run = landed(tmp_path / "landed.json", journal)
    assert run.stdout == (
        "waiting alpha: review 1 said not sound; a second review is needed before it lands\n"
        "landed: nothing new\n"
    )
    pending = [
        entry("started", "r1", "attack:alpha"),
        entry("result", "r1", {"verdict": "sound", "findings": []}),
        entry("started", "r2", "attack:alpha"),
    ]
    write_journal(journal, build + pending)
    run = landed(tmp_path / "landed.json", journal)
    assert run.stdout == (
        "waiting alpha: review 1 was started again and has not reported yet\nlanded: nothing new\n"
    )
    restarted = [
        entry("started", "r1", "attack:alpha"),
        entry("result", "r1", None),
        entry("started", "r2", "attack:alpha"),
        entry("result", "r2", {"verdict": "sound", "findings": []}),
    ]
    write_journal(journal, build + restarted)
    run = landed(tmp_path / "landed.json", journal)
    assert run.returncode == 0, run.stdout
    assert run.stdout.splitlines()[:1] + run.stdout.splitlines()[5:6] == [
        "=== LANDED alpha  head aaaaaaaaaaaa",
        "review 1: sound | findings: 0",
    ]


def test_a_build_or_fix_with_2_results_lands_on_neither(tmp_path):
    """2 fixes of 1 review give 2 heads; the tool cannot know which one is the branch."""
    lines = reviewed("alpha", SOUND_1) + [
        entry("started", "f1", "fix:alpha"),
        entry("started", "f2", "fix:alpha"),
        entry("result", "f1", {"head": "c" * 40, "fixed": ["F1"]}),
        entry("result", "f2", {"head": "d" * 40, "fixed": ["F1"]}),
    ]
    run = landed(tmp_path / "landed.json", write_journal(tmp_path / "j.jsonl", lines))
    assert run.stdout == (
        "waiting alpha: 2 results for fix:alpha (heads cccccccccccc, dddddddddddd); it lands on neither\n"
        "landed: nothing new\n"
    )


def test_the_same_agent_id_in_2_journals_names_2_helpers(tmp_path):
    """run1 and run2 both call their helpers a1 and a2. alpha (run1): review 1 has 1 finding, no fix:
    waits. delta (run2): sound, 0 findings: lands. The block of delta is built from run2 alone."""
    run1 = [
        entry("started", "a1", "build:alpha"),
        entry("result", "a1", {"head": "a" * 40, "summary": "alpha builds"}),
        entry("started", "a2", "attack:alpha"),
        entry("result", "a2", {"verdict": "not sound: a false pass", "findings": [{"id": "F1"}]}),
    ]
    run2 = [
        entry("started", "a1", "build:delta"),
        entry("result", "a1", {"head": "d" * 40, "summary": "delta builds"}),
        entry("started", "a2", "attack:delta"),
        entry("result", "a2", {"verdict": "sound", "findings": []}),
    ]
    one = write_journal(tmp_path / "run1.jsonl", run1)
    two = write_journal(tmp_path / "run2.jsonl", run2)
    run = landed(tmp_path / "landed.json", one, two)
    assert run.returncode == 0, run.stderr
    assert run.stdout.splitlines() == [
        "waiting alpha: review 1 has 1 finding and no fix yet",
        "=== LANDED delta  head dddddddddddd",
        "summary: delta builds",
        "evidence: ",
        "not_done: []",
        "reviews: 1",
        "review 1: sound | findings: 0",
        "evidence_holds: ",
        "tests: ",
    ]


def test_1_agent_id_started_under_2_labels_in_1_journal_is_refused(tmp_path):
    lines = [entry("started", "a1", "build:alpha"), entry("started", "a1", "attack:alpha")]
    journal = write_journal(tmp_path / "j.jsonl", lines)
    run = landed(tmp_path / "landed.json", journal)
    assert (run.returncode, run.stdout) == (2, "")
    assert run.stderr.splitlines() == [
        f"landed: {journal} starts agent a1 as build:alpha and as attack:alpha; 1 id is 1 helper"
    ]


def test_a_journal_that_cannot_be_read_is_a_bad_call_not_nothing_new(tmp_path):
    """A typo in a journal's path must not read as `no piece has finished`."""
    state = tmp_path / "landed.json"
    for path, why in ((tmp_path / "missing.jsonl", "no such file"), (tmp_path, "a folder")):
        run = landed(state, JOURNAL, path)
        assert (run.returncode, run.stdout) == (2, ""), path
        assert run.stderr.splitlines() == [f"landed: cannot read the journal {path}: {why}"]
    assert not state.exists()


def test_landed_refuses_a_bad_call_in_1_line(tmp_path):
    bare = subprocess.run([sys.executable, str(LANDED)], capture_output=True, text=True)
    assert bare.returncode == 2 and bare.stderr.startswith("usage: landed.py <state file> <journal>...")
    state = tmp_path / "landed.json"
    state.write_text('{"alpha": 1}', encoding="utf-8")
    bad = landed(state, JOURNAL)
    assert bad.returncode == 2
    assert bad.stderr.splitlines() == [f"landed: {state} is not a JSON list of branches"]
    assert bad.stdout == ""


# gate-and-push.sh


def git(repo: Path, *args: str) -> str:
    identity = ["-c", "user.name=Owner", "-c", "user.email=owner@example.org", "-c", "commit.gpgsign=false"]
    ran = subprocess.run(["git", "-C", str(repo), *identity, *args], capture_output=True, text=True)
    assert ran.returncode == 0, ran.stderr
    return ran.stdout.strip()


@pytest.fixture
def gate_setup(tmp_path):
    """A bare remote whose branch `work` is at commit A, a clone on `work` at commit B (1 after A), a
    stand-in make that answers as STANDIN says, and a quiet check that always finds the machine quiet."""
    remote = tmp_path / "remote.git"
    remote.mkdir()
    git(remote, "init", "-q", "--bare")
    tree = tmp_path / "tree"
    tree.mkdir()
    git(tree, "init", "-q")
    git(tree, "checkout", "-q", "-b", "work")
    git(tree, "remote", "add", "origin", str(remote))
    (tree / "a.txt").write_text("1\n")
    git(tree, "add", "a.txt")
    git(tree, "commit", "-q", "-m", "A")
    base = git(tree, "rev-parse", "HEAD")
    git(tree, "push", "-q", "origin", "work")
    (tree / "a.txt").write_text("2\n")
    git(tree, "commit", "-q", "-am", "B")
    head = git(tree, "rev-parse", "HEAD")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "make").write_text(
        "#!/bin/sh\n"
        "# called as: make -C <tree> verify\n"
        'echo "$*" >> "$STANDIN_CALLS"\n'
        'case "$STANDIN" in\n'
        '  green) echo "VERIFY GREEN" ;;\n'
        '  red) echo "VERIFY RED at 3/4 tests"; exit 1 ;;\n'
        '  silent) echo "all done" ;;\n'
        '  dirty) echo new > "$2/new.txt"; echo "VERIFY GREEN" ;;\n'
        '  slow) echo $$ > "$STANDIN_CALLS.pid"; sleep 60; echo "VERIFY GREEN" ;;\n'
        '  asleep) while [ ! -s "$STANDIN_SLEEPS" ]; do sleep 0.01; done; echo "VERIFY GREEN" ;;\n'
        "esac\n"
    )
    (bin_dir / "quiet").write_text("#!/bin/sh\nexit 0\n")
    for stub in bin_dir.iterdir():
        stub.chmod(0o755)
    gate_dir = tmp_path / "gate"
    gate_dir.mkdir()
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GATE_DIR": str(gate_dir),
        "GATE_QUIET": str(bin_dir / "quiet"),
        "GATE_QUIET_SECONDS": "0",
        "GATE_SAMPLE_SECONDS": "1",
        "STANDIN_CALLS": str(tmp_path / "make-calls"),
    }
    return {"tree": tree, "remote": remote, "base": base, "head": head, "env": env, "dir": gate_dir}


def gate(setup: dict, mode: str) -> subprocess.CompletedProcess:
    env = {**setup["env"], "STANDIN": mode}
    argv = ["bash", str(GATE), str(setup["tree"]), "work", setup["head"], setup["base"], "t1"]
    return subprocess.run(argv, env=env, capture_output=True, text=True, timeout=120)


def remote_head(setup: dict) -> str:
    return git(setup["remote"], "rev-parse", "refs/heads/work")


def test_a_green_gate_pushes_the_commit_and_removes_the_lock(gate_setup):
    run = gate(gate_setup, "green")
    assert run.returncode == 0, run.stdout + run.stderr
    assert remote_head(gate_setup) == gate_setup["head"]
    status = (gate_setup["dir"] / "gate-t1.status").read_text()
    assert f"PUSHED {gate_setup['head']} to work" in status
    assert "make verify ended with exit code 0" in status
    assert (gate_setup["dir"] / "verify-t1.log").read_text() == "VERIFY GREEN\n"
    assert not (gate_setup["dir"] / "GATE.lock").exists()
    calls = Path(gate_setup["env"]["STANDIN_CALLS"]).read_text().splitlines()
    assert calls == [f"-C {gate_setup['tree']} verify"]


def test_the_gate_ends_its_sampler_without_waiting_out_its_sleep(gate_setup):
    """The sampler looks every 60 s here; the stand-in make answers at once. The gate must not wait out
    the sampler's 60 s sleep before it pushes: it ends well under 30 s."""
    import time

    setup = {**gate_setup, "env": {**gate_setup["env"], "GATE_SAMPLE_SECONDS": "60"}}
    start = time.monotonic()
    run = gate(setup, "green")
    assert run.returncode == 0, run.stdout + run.stderr
    assert time.monotonic() - start < 30


# A BASH_ENV file for the gate's bash: it holds 1 process of the gate at 1 command until the test lets
# it go, so that a test chooses the moment a kill or an end reaches it. HOLD_WHERE=main holds the gate's
# own shell at the first command after its HOLD_NTH-th job starts (`&` or `coproc`): the job runs and
# the line after it has not kept its pid yet. HOLD_WHERE=nth holds the sampler (the process whose
# stdout is HOLD_SAMPLER_OUT, the gate's .foreign file) before its HOLD_NTH-th command; HOLD_LOG, when
# set, gets "<n> <command>" for each command the sampler runs. A hold writes "<pid> <command>" to
# HOLD_MARK, then waits with the builtin `read` on a FIFO opened read-write (no child, no data, no end)
# in 0.05 s steps, up to 30 s, until the test has made HOLD_MARK.sent.
HOLD = """\
set -T
HOLD_TOP=${HOLD_TOP:-$BASHPID}
__hold_owner=
__hold_wait() {
  echo "$BASHPID $BASH_COMMAND" > "$HOLD_MARK"
  for ((__hold_i = 0; __hold_i < 600; __hold_i++)); do
    [ ! -e "$HOLD_MARK.sent" ] || break
    read -r -t 0.05 _ <> "$HOLD_FIFO"
  done
}
__hold() {
  if [ "$__hold_owner" != "$BASHPID" ]; then
    __hold_owner=$BASHPID
    __hold_seen=$!
    __hold_jobs=0
    __hold_cmds=0
    __hold_sampler=
  fi
  if [ -z "$__hold_sampler" ] && [ "$BASHPID" != "$HOLD_TOP" ] && [ -n "${HOLD_SAMPLER_OUT:-}" ] \\
    && [[ /proc/$BASHPID/fd/1 -ef $HOLD_SAMPLER_OUT ]]; then
    __hold_sampler=1
  fi
  if [ -n "$__hold_sampler" ]; then
    __hold_cmds=$((__hold_cmds + 1))
    if [ -n "${HOLD_LOG:-}" ]; then echo "$__hold_cmds $BASH_COMMAND" >> "$HOLD_LOG"; fi
    if [ "$HOLD_WHERE" = nth ] && [ "$__hold_cmds" = "$HOLD_NTH" ]; then __hold_wait; fi
    return 0
  fi
  if [ "$!" = "$__hold_seen" ]; then return 0; fi
  __hold_seen=$!
  __hold_jobs=$((__hold_jobs + 1))
  if [ "$HOLD_WHERE" = main ] && [ "$BASHPID" = "$HOLD_TOP" ] && [ "$__hold_jobs" = "$HOLD_NTH" ]; then
    __hold_wait
  fi
  return 0
}
trap '__hold' DEBUG
"""


def left_of(marker: str) -> list[str]:
    """The processes that run (not zombies) with SAMPLER_RUN=<marker> in their environment."""
    found = []
    for p in Path("/proc").iterdir():
        if not p.name.isdigit():
            continue
        try:
            if f"SAMPLER_RUN={marker}".encode() not in (p / "environ").read_bytes().split(b"\0"):
                continue
            if (p / "stat").read_text().rsplit(")", 1)[1].split()[0] == "Z":
                continue
            args = (p / "cmdline").read_bytes().replace(b"\0", b" ").decode().strip()
            found.append(f"{p.name} {args}")
        except OSError:
            continue
    return found


def term_then_release(proc: subprocess.Popen, mark: Path) -> None:
    """SIGTERM the gate, then let the hold go: a trap that only notes the signal does not end `read`."""
    import signal

    proc.send_signal(signal.SIGTERM)
    Path(f"{mark}.sent").touch()


def held_gate(setup: dict, tmp_path: Path, mode: str, env: dict, on_mark=None) -> dict:
    """Run the gate with HOLD as BASH_ENV and the env given; with on_mark, call on_mark(proc, mark) once
    HOLD_MARK holds a line. Returns the exit code, the seconds to the gate's exit and from its exit to the
    end of its stdout and stderr (None: still open 10 s after), and what of the run still ran after that."""
    import signal
    import threading
    import time
    import uuid

    hook = tmp_path / "hold.bash"
    hook.write_text(HOLD)
    fifo = tmp_path / "hold.fifo"
    os.mkfifo(fifo)
    mark = tmp_path / "held"
    marker = uuid.uuid4().hex
    env = {
        **setup["env"],
        "STANDIN": mode,
        "BASH_ENV": str(hook),
        "HOLD_FIFO": str(fifo),
        "HOLD_MARK": str(mark),
        "HOLD_SAMPLER_OUT": str(setup["dir"] / "gate-t1.foreign"),
        "SAMPLER_RUN": marker,
        **env,
    }
    argv = ["bash", str(GATE), str(setup["tree"]), "work", setup["head"], setup["base"], "t1"]
    start = time.monotonic()
    proc = subprocess.Popen(argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    readers = [threading.Thread(target=f.read) for f in (proc.stdout, proc.stderr)]
    for r in readers:
        r.start()
    try:
        released = None
        if on_mark is not None:
            while not (mark.exists() and mark.read_text().strip()) and time.monotonic() - start < 30:
                time.sleep(0.01)
            assert mark.exists(), "the gate was never held"
            on_mark(proc, mark)
            released = time.monotonic() - start
        code = proc.wait(timeout=30)
        exited = time.monotonic() - start
        for r in readers:
            r.join(timeout=10)
        closed = None if any(r.is_alive() for r in readers) else time.monotonic() - start - exited
        return {
            "code": code,
            "exited": exited,
            "released": released,
            "closed": closed,
            "left": left_of(marker),
            "mark": mark,
        }
    finally:
        for line in left_of(marker):
            try:
                os.kill(int(line.split()[0]), signal.SIGKILL)
            except OSError:
                pass
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        for r in readers:
            r.join(timeout=10)


# The sampler's commands of its first loop up to its sleep; the ones after `read` run only once the gate
# has closed the sampler's pipe, and every run of the gate runs them.
SAMPLER_STEPS = ("true", "found=$(busy < /dev/null)", '[ -n "$found" ]', 'read -r -t "$SAMPLE" _')


@pytest.mark.parametrize("nth", range(1, len(SAMPLER_STEPS) + 1))
def test_the_gate_ends_its_sampler_at_any_command_of_its_loop_without_waiting_out_its_look(
    gate_setup, tmp_path, nth
):
    """The sampler looks every 60 s. It is held before its command `nth` of its first loop
    (SAMPLER_STEPS); the stand-in make then answers green, the gate ends the sampler, and 0.5 s later the
    hold lets go. The gate must end at once, with its pipes closed and nothing of the run left. An
    external `sleep "$SAMPLE"` in the sampler, ended by a kill that misses it, held the gate's stdout and
    stderr for 60 s (M272, the health gate of 2026-11-19 02:02 UTC); a sampler that the gate ends by
    closing its pipe, but that sleeps with an external `sleep`, makes the gate wait out the 60 s: the
    test fails on both: against a copy whose sampler sleeps with `sleep "$SAMPLE"`, 4 of 4 commands
    failed (2026-11-19). Against the fixed script each of the 4 passed 10 of 10 runs (2026-11-19, load
    2 to 5), the gate exiting 0.064 to 0.214 s after the hold let go; the bound of 10 s is over 45
    times the slowest."""
    import time

    log = tmp_path / "steps"
    sleeps = tmp_path / "sleeps"
    env = {
        "GATE_SAMPLE_SECONDS": "60",
        "STANDIN_SLEEPS": str(sleeps),
        "HOLD_WHERE": "nth",
        "HOLD_NTH": str(nth),
        "HOLD_LOG": str(log),
    }

    def answer_then_release(proc, mark):
        sleeps.write_text("go\n")
        time.sleep(0.5)
        Path(f"{mark}.sent").touch()

    run = held_gate(gate_setup, tmp_path, "asleep", env, on_mark=answer_then_release)
    held = run["mark"].read_text().split(" ", 1)[1].strip()
    assert held == SAMPLER_STEPS[nth - 1], log.read_text()
    assert run["code"] == 0
    assert run["exited"] - run["released"] < 10
    assert run["closed"] is not None, f"the gate's pipes were still open 10 s after it ended: {run['left']}"
    assert run["left"] == []
    assert remote_head(gate_setup) == gate_setup["head"]


@pytest.mark.parametrize("nth, job", [(1, "the sampler"), (2, "make")])
def test_a_sigterm_while_a_job_starts_ends_that_job_before_the_lock_goes(gate_setup, tmp_path, nth, job):
    """The gate's shell is held at the first command after the start of its job `nth` (1 the sampler's
    `coproc`, 2 make's `&`), before the line that keeps the job's pid, and the test sends SIGTERM there.
    Before the fix, finish() found no pid: 10 of 10 runs of each left the sampler looping for good (it
    held the gate's pipes), or make running after the lock was removed. After it, the signal waits until
    the pid is kept, and the job ends with the gate: 10 of 10 runs of each (2026-11-19, load 2 to 5)
    exited in 0.105 to 0.168 s (the sampler) and 0.105 to 2.061 s (make), the pipes closed 0.000 s after;
    the bound of 30 s is over 14 times the slowest."""
    env = {"GATE_SAMPLE_SECONDS": "60", "HOLD_WHERE": "main", "HOLD_NTH": str(nth)}
    run = held_gate(gate_setup, tmp_path, "slow", env, on_mark=term_then_release)
    assert run["mark"].read_text().split(" ", 1)[1].strip() == ("SAMPLER=$!", "MAKE_PID=$!")[nth - 1]
    assert run["code"] == 143
    assert run["exited"] < 30
    assert run["closed"] is not None, f"the gate's pipes were still open 10 s after it ended: {run['left']}"
    assert run["left"] == [], f"{job} runs on after the gate ended"
    assert not (gate_setup["dir"] / "GATE.lock").exists()
    assert remote_head(gate_setup) == gate_setup["base"]
    if nth == 1:
        assert not Path(gate_setup["env"]["STANDIN_CALLS"]).exists(), "make started after the signal"


def test_a_sigterm_before_setsid_has_made_makes_group_still_ends_make(gate_setup, tmp_path):
    """A stand-in setsid writes its mark and waits, as the real one does in its first instant, before it
    has made make's group; the test sends SIGTERM to the gate then. Before the fix the gate killed the
    group, which did not exist yet, and waited for make: it had not ended after 30 s in 10 of 10 runs.
    After it the gate ends the process itself when there is no group: 10 of 10 runs exited in 0.057 to
    0.135 s (2026-11-19, load 2 to 5); the bound of 30 s is over 200 times the slowest."""
    real_setsid = shutil.which("setsid")
    bin_dir = tmp_path / "bin2"
    bin_dir.mkdir()
    fifo = tmp_path / "setsid.fifo"
    os.mkfifo(fifo)
    (bin_dir / "setsid").write_text(
        f'#!/bin/sh\necho "$$ setsid" > "$HOLD_MARK"\nread _ <> "{fifo}"\nexec {real_setsid} "$@"\n'
    )
    (bin_dir / "setsid").chmod(0o755)
    env = {"PATH": f"{bin_dir}{os.pathsep}{gate_setup['env']['PATH']}", "HOLD_WHERE": "none", "HOLD_NTH": "0"}
    run = held_gate(gate_setup, tmp_path, "slow", env, on_mark=term_then_release)
    assert run["code"] == 143
    assert run["exited"] < 30
    assert run["left"] == []
    assert not Path(gate_setup["env"]["STANDIN_CALLS"]).exists(), "make ran after the signal"
    assert not (gate_setup["dir"] / "GATE.lock").exists()


@pytest.mark.parametrize("mode", ["red", "silent"])
def test_a_red_gate_or_one_with_no_green_line_pushes_nothing(gate_setup, mode):
    """`silent`: make exits 0 but prints no `VERIFY GREEN` line; the push is chained to the line."""
    run = gate(gate_setup, mode)
    assert run.returncode == 1, run.stdout + run.stderr
    assert remote_head(gate_setup) == gate_setup["base"]
    assert "RED: no push" in (gate_setup["dir"] / "gate-t1.status").read_text()
    assert not (gate_setup["dir"] / "GATE.lock").exists()


def test_a_tree_that_changed_during_the_gate_is_not_pushed(gate_setup):
    run = gate(gate_setup, "dirty")
    assert run.returncode == 3, run.stdout + run.stderr
    assert remote_head(gate_setup) == gate_setup["base"]
    assert (
        "STOP: the tree changed during the gate; no push"
        in (gate_setup["dir"] / "gate-t1.status").read_text()
    )
    assert not (gate_setup["dir"] / "GATE.lock").exists()


def test_a_gate_that_finds_the_lock_taken_stops_and_leaves_the_lock(gate_setup):
    """Another gate holds the lock: this one runs no make, pushes nothing, and leaves the other's lock
    as it was."""
    lock = gate_setup["dir"] / "GATE.lock"
    lock.write_text("2026-11-17T20:00:00Z\n")
    run = gate(gate_setup, "green")
    assert run.returncode == 3, run.stdout + run.stderr
    assert lock.read_text() == "2026-11-17T20:00:00Z\n"
    assert remote_head(gate_setup) == gate_setup["base"]
    assert not Path(gate_setup["env"]["STANDIN_CALLS"]).exists()
    assert f"STOP: {lock} exists: another gate runs" in run.stdout


def test_a_head_that_is_not_the_named_commit_stops_before_the_lock(gate_setup):
    setup = {**gate_setup, "head": gate_setup["base"]}
    run = gate(setup, "green")
    assert run.returncode == 3
    assert f"STOP: HEAD is not {gate_setup['base']}" in run.stdout
    assert not (gate_setup["dir"] / "GATE.lock").exists()


def test_gate_and_push_needs_its_folder(gate_setup):
    env = {k: v for k, v in gate_setup["env"].items() if k != "GATE_DIR"}
    argv = ["bash", str(GATE), str(gate_setup["tree"]), "work", gate_setup["head"], gate_setup["base"], "t1"]
    run = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=60)
    assert run.returncode == 2
    assert run.stderr.splitlines() == [
        "gate-and-push: GATE_DIR is not set: the folder for the lock and the logs"
    ]


def test_a_gate_whose_folder_does_not_exist_is_a_bad_call(gate_setup):
    """Exit 3 would tell the reader another gate holds the lock; there is no folder for a lock at all."""
    env = {**gate_setup["env"], "GATE_DIR": str(gate_setup["dir"] / "no-such-folder")}
    argv = ["bash", str(GATE), str(gate_setup["tree"]), "work", gate_setup["head"], gate_setup["base"], "t1"]
    run = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=60)
    assert (run.returncode, run.stdout) == (2, "")
    assert run.stderr.splitlines() == [
        f"gate-and-push: GATE_DIR {gate_setup['dir'] / 'no-such-folder'} is not a folder"
    ]


def test_a_remote_that_moved_after_the_lease_was_read_is_not_overwritten(gate_setup, tmp_path):
    """The lead read the lease A; then someone pushed C onto `work`. The lease no longer holds: the gate
    stops at the first refusal with exit 5, and the remote still holds C."""
    other = tmp_path / "other"
    subprocess.run(
        ["git", "clone", "-q", "-b", "work", str(gate_setup["remote"]), str(other)],
        check=True,
        capture_output=True,
    )
    (other / "b.txt").write_text("other\n")
    git(other, "add", "b.txt")
    git(other, "commit", "-q", "-m", "C")
    git(other, "push", "-q", "origin", "work")
    moved = git(other, "rev-parse", "HEAD")
    run = gate(gate_setup, "green")
    assert run.returncode == 5, run.stdout + run.stderr
    assert remote_head(gate_setup) == moved
    status = (gate_setup["dir"] / "gate-t1.status").read_text()
    assert f"PUSH REFUSED: work on origin is {moved}, not the lease {gate_setup['base']}" in status
    assert "push try" not in status
    assert not (gate_setup["dir"] / "GATE.lock").exists()


def alive(pid: int) -> bool:
    """A process that runs; a zombie (state Z) has ended."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return False
    return stat.rsplit(")", 1)[1].split()[0] != "Z"


def test_a_gate_stopped_by_sigterm_ends_make_and_its_sampler_before_it_frees_the_lock(gate_setup):
    """The stand-in make sleeps 60 s. SIGTERM to the gate: make and the gate's background sampler end with
    it, so no helper starts a test on a free lock while `make verify` still runs."""
    import signal
    import time

    env = {**gate_setup["env"], "STANDIN": "slow"}
    argv = ["bash", str(GATE), str(gate_setup["tree"]), "work", gate_setup["head"], gate_setup["base"], "t1"]
    proc = subprocess.Popen(argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    pid_file = Path(gate_setup["env"]["STANDIN_CALLS"] + ".pid")
    for _ in range(200):
        if pid_file.exists() and pid_file.read_text().strip():
            break
        time.sleep(0.1)
    make_pid = int(pid_file.read_text())
    assert (gate_setup["dir"] / "GATE.lock").exists()
    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=30)
    assert proc.returncode != 0
    time.sleep(1)
    assert not alive(make_pid), "make verify runs on after the gate ended"
    left = subprocess.run(["ps", "-ww", "-eo", "pid=,args="], capture_output=True, text=True).stdout
    assert [line for line in left.splitlines() if str(GATE) in line and str(gate_setup["tree"]) in line] == []
    assert not (gate_setup["dir"] / "GATE.lock").exists()
    assert remote_head(gate_setup) == gate_setup["base"]


# sh: wait until the last `&` job, a sleep, has exec'd (no single quotes, for use inside `sh -c '...'`).
EXECED = 'while [ "$(cat /proc/$!/comm 2>/dev/null)" != sleep ]; do :; done;'


def stand_in(tmp_path: Path, setup: dict, name: str, text: str) -> dict:
    """The setup's env with a stand-in `name` (a sh script) first on PATH."""
    bin_dir = tmp_path / "bin2"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / name).write_text("#!/bin/sh\n" + text)
    (bin_dir / name).chmod(0o755)
    return {**setup["env"], "PATH": f"{bin_dir}{os.pathsep}{setup['env']['PATH']}"}


def wait_for_text(path: Path, limit: float = 30.0) -> str:
    import time

    start = time.monotonic()
    while time.monotonic() - start < limit:
        if path.exists() and path.read_text().strip():
            return path.read_text()
        time.sleep(0.01)
    raise AssertionError(f"{path} was not written in {limit} s")


@pytest.mark.parametrize("target", ["group", "pid"])
def test_a_sigkill_to_the_gate_ends_its_sampler_and_closes_its_pipes(gate_setup, target):
    """A caller's harness ends the gate with SIGKILL, to its process group or to its pid alone, while
    make runs; nothing can be trapped. The sampler must not loop on: it would hold the gate's stderr, so
    a caller that reads the gate's output never sees its end, and it would run the quiet check for good.
    Make runs on in its own group; the lock stays (SIGKILL). With the sampler as its own process group
    and an external sleep, both cases left it looping, 1 of 1 run each (2026-11-19); the sampler as a
    coprocess in the gate's group whose pipe ends with the gate passed 10 of 10 runs of each (load 2 to
    5), each test's call 0.25 to 0.28 s with its setup. The 10 s the pipes may take is over 35 times
    that."""
    import signal
    import threading
    import time
    import uuid

    marker = uuid.uuid4().hex
    env = {**gate_setup["env"], "STANDIN": "slow", "SAMPLER_RUN": marker, "GATE_SAMPLE_SECONDS": "60"}
    argv = ["bash", str(GATE), str(gate_setup["tree"]), "work", gate_setup["head"], gate_setup["base"], "t1"]
    proc = subprocess.Popen(
        argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True
    )
    readers = [threading.Thread(target=f.read) for f in (proc.stdout, proc.stderr)]
    for r in readers:
        r.start()
    make_pid = int(wait_for_text(Path(gate_setup["env"]["STANDIN_CALLS"] + ".pid")))
    try:
        time.sleep(0.2)
        if target == "group":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            os.kill(proc.pid, signal.SIGKILL)
        proc.wait(timeout=30)
        for r in readers:
            r.join(timeout=10)
        assert not any(r.is_alive() for r in readers), (
            f"the gate's pipes were open 10 s after: {left_of(marker)}"
        )
        mine = []
        for line in left_of(marker):
            try:
                if os.getpgid(int(line.split()[0])) != make_pid:
                    mine.append(line)
            except ProcessLookupError:
                pass
        assert mine == [], "the sampler runs on after the gate"
    finally:
        for line in left_of(marker):
            try:
                os.kill(int(line.split()[0]), signal.SIGKILL)
            except OSError:
                pass
        for r in readers:
            r.join(timeout=10)


def test_the_lock_goes_only_after_every_process_of_makes_group_has_ended(gate_setup, tmp_path):
    """make starts a test that takes 1 s to end after SIGTERM; make itself ends at once. SIGTERM to the
    gate: the lock must still be there when the test looks, 1 s after its TERM, and the test must have
    ended when the gate exits. When the gate waited for make's pid alone, 1 of 1 run found the test still
    running at the gate's exit, with the lock gone (2026-11-19). The fixed script passed 10 of 10 runs
    (load 2 to 5), each call 2.10 to 3.03 s; the gate's 60 s is over 19 times that."""
    import signal

    report = tmp_path / "report"
    lock = gate_setup["dir"] / "GATE.lock"
    test_pid = tmp_path / "test.pid"
    env = stand_in(
        tmp_path,
        gate_setup,
        "make",
        f'echo "$*" >> "$STANDIN_CALLS"\n'
        f'sh -c \'trap "sleep 1; ls {lock} > {report} 2>&1; exit 1" TERM;'
        f" sleep 60 & {EXECED} echo $$ > {test_pid}; wait' &\n"
        "wait\n",
    )
    argv = ["bash", str(GATE), str(gate_setup["tree"]), "work", gate_setup["head"], gate_setup["base"], "t1"]
    proc = subprocess.Popen(argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    pid = int(wait_for_text(test_pid))
    proc.send_signal(signal.SIGTERM)
    out, err = proc.communicate(timeout=60)
    assert proc.returncode == 143, out + err
    assert not alive(pid), "make's test runs on after the gate ended"
    assert report.read_text().strip() == str(lock), "the lock was gone while make's test still ran"
    assert not lock.exists()


def test_a_process_of_makes_group_that_ignores_sigterm_gets_sigkill_after_the_stop_time(gate_setup, tmp_path):
    """make starts a test that ignores SIGTERM; GATE_STOP_SECONDS is 1. SIGTERM to the gate: the gate
    kills make's group after 1 s, then frees the lock. When the gate waited for make's pid alone, 1 of 1
    run left the test running (2026-11-19). The fixed script passed 10 of 10 runs (load 2 to 5), each
    call 2.91 to 3.02 s with its setup; the bound of 20 s is over 6 times the slowest."""
    import signal
    import time

    test_pid = tmp_path / "test.pid"
    env = stand_in(
        tmp_path,
        gate_setup,
        "make",
        f"sh -c 'trap \"\" TERM; echo $$ > {test_pid}; while :; do sleep 1; done' &\nwait\n",
    )
    env["GATE_STOP_SECONDS"] = "1"
    argv = ["bash", str(GATE), str(gate_setup["tree"]), "work", gate_setup["head"], gate_setup["base"], "t1"]
    proc = subprocess.Popen(argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    pid = int(wait_for_text(test_pid))
    try:
        start = time.monotonic()
        proc.send_signal(signal.SIGTERM)
        out, err = proc.communicate(timeout=60)
        took = time.monotonic() - start
        assert proc.returncode == 143, out + err
        assert took < 20
        assert not alive(pid), "make's test runs on after the gate ended"
        assert "make's process group still ran 1 s after the stop: sent it SIGKILL" in out
        assert not (gate_setup["dir"] / "GATE.lock").exists()
    finally:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


@pytest.mark.parametrize("second", ["a second SIGTERM", "a closed stdout"])
def test_nothing_cuts_short_the_end_of_a_stopped_gate(gate_setup, tmp_path, second):
    """make takes 1 s to end after SIGTERM. While the gate waits for it, a second SIGTERM comes, or the
    caller that reads the gate's stdout has gone, so the gate's next line meets a closed pipe. Either
    used to end the gate inside its EXIT trap: the lock stayed for good, every later gate stopped with
    'another gate runs', and make ended unattended; 1 of 1 run each (2026-11-19). The fixed script
    passed 10 of 10 runs of each (load 2 to 5), each call 1.07 to 1.19 s."""
    import signal

    stopping = tmp_path / "stopping"
    make_pid = tmp_path / "make.pid"
    env = stand_in(
        tmp_path,
        gate_setup,
        "make",
        # The pid is written once the trap is set and the sleep has exec'd: a TERM that reaches the
        # forked child before its exec is lost (sh's handler only notes it), the sleep then runs its
        # 60 s, and the gate rightly waits 30 s for it before SIGKILL.
        f"trap 'touch {stopping}; sleep 1; exit 1' TERM\nsleep 60 &\n{EXECED}echo $$ > {make_pid}\nwait\n",
    )
    argv = ["bash", str(GATE), str(gate_setup["tree"]), "work", gate_setup["head"], gate_setup["base"], "t1"]
    proc = subprocess.Popen(argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    pid = int(wait_for_text(make_pid))
    if second == "a closed stdout":
        proc.stdout.close()
    proc.send_signal(signal.SIGTERM)
    wait_for_file(stopping)
    if second == "a second SIGTERM":
        proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=60)
    proc.stderr.read()
    assert proc.returncode == 143
    assert not alive(pid), "make runs on after the gate ended"
    status = (gate_setup["dir"] / "gate-t1.status").read_text()
    assert "make verify was stopped" in status and "lock removed" in status, status
    assert not (gate_setup["dir"] / "GATE.lock").exists()


def wait_for_file(path: Path, limit: float = 30.0) -> None:
    import time

    start = time.monotonic()
    while not path.exists():
        assert time.monotonic() - start < limit, f"{path} was not made in {limit} s"
        time.sleep(0.01)


def test_the_sampler_notes_a_helper_when_the_gate_runs_on_a_terminal_set_to_tostop(gate_setup, tmp_path):
    """The gate runs on a terminal with `stty tostop`; the quiet check writes a warning to stderr and,
    once make runs, names a busy helper. A sampler in a background process group of its own was stopped
    by SIGTTOU at its first write to the terminal, and the .foreign file stayed empty (1 of 1 run,
    2026-11-19): the land skill found no helper's work. The fixed script passed 10 of 10 runs (load 2
    to 5)."""
    if shutil.which("script") is None:
        pytest.skip("script (util-linux) is not on PATH")
    import shlex

    go = tmp_path / "go"
    env = stand_in(
        tmp_path,
        gate_setup,
        "quiet",
        f"echo 'quiet: a warning' >&2\n[ -e {go} ] && echo '999 helper busy'\nexit 0\n",
    )
    env = stand_in(
        tmp_path, {**gate_setup, "env": env}, "make", f'touch {go}\nsleep 2.5\necho "VERIFY GREEN"\n'
    )
    env["GATE_QUIET"] = str(tmp_path / "bin2" / "quiet")
    argv = ["bash", str(GATE), str(gate_setup["tree"]), "work", gate_setup["head"], gate_setup["base"], "t1"]
    cmd = f"stty tostop; {shlex.join(argv)}"
    run = subprocess.run(
        ["script", "-qec", cmd, "/dev/null"],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        cwd=tmp_path,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert "999 helper busy" in (gate_setup["dir"] / "gate-t1.foreign").read_text()


def test_a_sampler_that_died_early_gets_no_signal_from_the_gate(gate_setup, tmp_path):
    """The sampler dies early (a stray SIGKILL), and its pid comes back as a helper's process group
    leader. The gate must send that helper nothing when it ends its sampler. When the gate ended its
    sampler with SIGKILL to the group of the sampler's pid, it killed the helper (1 of 1 run,
    2026-11-19); the gate that sends its sampler no signal passed 10 of 10 runs, none skipped. Taking
    the pid needs /proc/sys/kernel/ns_last_pid (root); without it the test skips."""
    import signal
    import time

    go = tmp_path / "go"
    make_pid = tmp_path / "make.pid"
    env = stand_in(
        tmp_path,
        gate_setup,
        "make",
        f'echo $$ > {make_pid}\nwhile [ ! -e {go} ]; do sleep 0.05; done\necho "VERIFY GREEN"\n',
    )
    env["GATE_SAMPLE_SECONDS"] = "60"
    argv = ["bash", str(GATE), str(gate_setup["tree"]), "work", gate_setup["head"], gate_setup["base"], "t1"]
    proc = subprocess.Popen(argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    helper = None
    try:
        mpid = int(wait_for_text(make_pid))
        kids = Path(f"/proc/{proc.pid}/task/{proc.pid}/children").read_text().split()
        sampler = [int(k) for k in kids if int(k) != mpid][0]
        os.kill(sampler, signal.SIGKILL)
        try:
            os.killpg(sampler, signal.SIGKILL)
        except ProcessLookupError:
            pass
        start = time.monotonic()
        while True:
            try:
                os.killpg(sampler, 0)
            except ProcessLookupError:
                if not alive(sampler) and not Path(f"/proc/{sampler}").exists():
                    break
            assert time.monotonic() - start < 30, "the sampler's pid stayed in use"
            time.sleep(0.01)
        for _ in range(50):
            try:
                Path("/proc/sys/kernel/ns_last_pid").write_text(str(sampler - 1))
            except OSError:
                pytest.skip("cannot write /proc/sys/kernel/ns_last_pid")
            h = subprocess.Popen(["setsid", "sleep", "100"])
            if h.pid == sampler:
                helper = h
                break
            h.kill()
            h.wait()
        if helper is None:
            pytest.skip("could not take the sampler's pid")
        time.sleep(0.1)
        assert os.getpgid(helper.pid) == helper.pid
        go.touch()
        out, err = proc.communicate(timeout=60)
        assert proc.returncode == 0, out + err
        time.sleep(0.2)
        assert helper.poll() is None, (
            f"the gate killed the helper that took its sampler's pid: {helper.poll()}"
        )
    finally:
        go.touch()
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        if helper is not None:
            helper.kill()
            helper.wait()


def test_gate_and_push_passes_shellcheck():
    if shutil.which("shellcheck") is None:
        pytest.skip("shellcheck is not on PATH")
    run = subprocess.run(["shellcheck", str(GATE)], capture_output=True, text=True)
    assert run.returncode == 0, run.stdout


# quiet.py

PS = """\
    1     0 init            /sbin/init
  100     1 bash            bash /lead/gate-and-push.sh
  101   100 make            make -C /scratch/wt/x verify
  200     1 kicad-cli       kicad-cli pcb drc board.kicad_pcb
  300     1 python3         python3 -m pytest tests/test_x.py
  310     1 pytest          /venv/bin/python /venv/bin/pytest -q tests/test_y.py
  320     1 workcenter      /usr/bin/python3 /usr/local/bin/workcenter gates v0.1
  330     1 python3         python3 /usr/local/bin/workcenter gates v0.2
  340     1 py.test         /venv/bin/python /venv/bin/py.test tests/test_z.py
  350     1 python3         python3 -m http.server
  400     1 node           node /scratch/wf/run.js
  401     1 node            node /elsewhere/app.js
  500     1 bash            bash /scratch/wait.sh
  501   500 sleep           sleep 30
  600     1 bash            bash /scratch/work.sh
  601   600 cat             cat notes
  700     1 vim             vim notes
  800     1 yosys           /opt/chip/bin/yosys -s synth.ys
  900     1 hostagent       hostagent --dir /scratch
"""


def test_quiet_names_engines_tests_and_scripts_in_the_given_folders(tmp_path):
    """The gate's own tree (100, 101) is left out; a script that only sleeps (500) waits for the lock
    and is not counted; a process named in QUIET_IGNORE (900, the host's own) is left out. A test run or
    a workcenter run started by its entry-point script, whose name ps gives as the command (310, 320,
    340) or which a python runs (330), is busy; a python that runs neither (350) is not."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    listing = tmp_path / "ps.txt"
    listing.write_text(PS)
    (bin_dir / "ps").write_text(f"#!/bin/sh\ncat {listing}\n")
    (bin_dir / "ps").chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "QUIET_IGNORE": "hostagent"}
    run = subprocess.run(
        [sys.executable, str(QUIET), "100", "/scratch", "/opt/chip"], env=env, capture_output=True, text=True
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout.splitlines() == [
        "200 kicad-cli kicad-cli pcb drc board.kicad_pcb",
        "300 python3 python3 -m pytest tests/test_x.py",
        "310 pytest /venv/bin/python /venv/bin/pytest -q tests/test_y.py",
        "320 workcenter /usr/bin/python3 /usr/local/bin/workcenter gates v0.1",
        "330 python3 python3 /usr/local/bin/workcenter gates v0.2",
        "340 py.test /venv/bin/python /venv/bin/py.test tests/test_z.py",
        "400 node node /scratch/wf/run.js",
        "600 bash bash /scratch/work.sh",
        "800 yosys /opt/chip/bin/yosys -s synth.ys",
    ]


# Each stand-in learns where to write 'up' from STANDIN_UP, not from its command line: a path under
# pytest's base folder (/tmp/pytest-of-<user>/...) would put the word pytest on it.
STANDIN_SLEEPS = (
    "import os, pathlib, time; pathlib.Path(os.environ['STANDIN_UP']).write_text('up'); time.sleep(60)"
)
STANDIN_WORKS = (
    "import os, pathlib; pathlib.Path(os.environ['STANDIN_UP']).write_text('up')\nwhile True: pass"
)
STANDIN_WAITS_ON_A_CHILD = (
    "import os, pathlib, subprocess; pathlib.Path(os.environ['STANDIN_UP']).write_text('up')\n"
    "subprocess.run(['sleep', '60'])"
)
# A width narrower than every stand-in's command line, as COLUMNS may set it for `ps` (M281).
NARROW_COLUMNS = "40"


@pytest.mark.parametrize("columns", [None, NARROW_COLUMNS], ids=["inherited-width", "narrow-width"])
def test_quiet_leaves_out_a_python_script_that_sleeps_with_nothing_below_it(tmp_path, columns):
    """A helper's script that waits for the gate's lock in `time.sleep` starts no `sleep` process
    (M277). With nothing below it and no processor time used for 2 s, it is quiet; counted as busy, it
    and the gate wait for each other. A script that works is busy, and so is one with a child: the
    child may be its test run. The real `ps` and /proc; the folder is a name on each command line.
    Only the 3 stand-ins' lines are read: the machine may run other things. Under a narrow COLUMNS
    the same holds: `ps` cut to that width would lose the folder at the end of each line (M281)."""
    import time

    folder = f"/quiet-standins-{os.getpid()}"
    gate = subprocess.Popen(["sleep", "60"])
    standins = {}
    try:
        for name, code in (
            ("sleeps", STANDIN_SLEEPS),
            ("works", STANDIN_WORKS),
            ("child", STANDIN_WAITS_ON_A_CHILD),
        ):
            up = tmp_path / f"{name}.up"
            argv = [sys.executable, "-c", code, folder]
            assert len(" ".join(argv)) > int(NARROW_COLUMNS)
            env = {**os.environ, "STANDIN_UP": str(up)}
            standins[name] = (subprocess.Popen(argv, env=env, start_new_session=True), up)
        for _proc, up in standins.values():
            for _ in range(100):
                if up.exists():
                    break
                time.sleep(0.1)
            assert up.exists(), "a stand-in did not start"
        time.sleep(0.5)
        env = dict(os.environ)
        if columns is not None:
            env["COLUMNS"] = columns
        run = subprocess.run(
            [sys.executable, str(QUIET), str(gate.pid), folder],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert run.returncode == 0, run.stderr
        printed = {int(line.split()[0]) for line in run.stdout.splitlines()}
        assert standins["sleeps"][0].pid not in printed
        assert standins["works"][0].pid in printed
        assert standins["child"][0].pid in printed
    finally:
        import signal

        for proc, _ in standins.values():
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
        gate.kill()
        gate.wait()


def test_quiet_refuses_a_root_that_is_no_number():
    run = subprocess.run([sys.executable, str(QUIET), "x"], capture_output=True, text=True)
    assert run.returncode == 2
    assert run.stderr.startswith("usage: quiet.py <pid whose tree is left out> [folder]...")


# the example scripts

SESSION_PATH = re.compile(r"/tmp/|/root/|/home/|scratchpad|session_[0-9a-z]{6,}")
MODEL = re.compile(r"\b(?:claude|anthropic|opus|sonnet|haiku|gpt-?\d|gemini|copilot)\b", re.I)


@pytest.mark.parametrize("name", SCRIPTS)
def test_each_example_script_parses_and_names_no_session_path_and_no_model(name, tmp_path):
    """The 3 scripts are examples for a host that runs workflow scripts: an async body that may
    `return` at its top level, with `meta` exported. Wrapped as an async function, node must parse
    it. Its paths and its models come from `args`."""
    text = (LEAD / "workflows" / name).read_text(encoding="utf-8")
    assert SESSION_PATH.findall(text) == []
    assert MODEL.findall(text) == []
    assert "args." in text
    if shutil.which("node") is None:
        pytest.skip("node is not on PATH")
    body = text.replace("export const meta", "const meta", 1)
    wrapped = tmp_path / "wrapped.mjs"
    wrapped.write_text(f"const args = {{}};\nexport default async function run() {{\n{body}\n}}\n")
    check = subprocess.run(["node", "--check", str(wrapped)], capture_output=True, text=True)
    assert check.returncode == 0, check.stderr
