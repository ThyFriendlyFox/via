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


# A BASH_ENV file for the gate's bash: it holds 1 process of the gate at 1 command until a signal comes,
# so that a test chooses the moment a kill reaches it. HOLD_WHERE=main holds the gate's own shell, =sub
# the sampler (a subshell that shares the gate's stdout), each at the first command after its HOLD_NTH-th
# `&`: the job runs and the line after the `&` has not kept its pid yet. It writes "<pid> <command>" to
# HOLD_MARK, then waits with the builtin `read` on a FIFO opened read-write (no child, no data, no end)
# in 0.05 s steps, up to 30 s, until the test has sent its signal and made HOLD_MARK.sent.
HOLD = """\
set -T
HOLD_TOP=${HOLD_TOP:-$BASHPID}
__hold_owner=
__hold() {
  if [ "$__hold_owner" != "$BASHPID" ]; then
    __hold_owner=$BASHPID
    __hold_seen=$!
    __hold_jobs=0
    __hold_sampler=
    if [ "$BASHPID" != "$HOLD_TOP" ] && [[ /proc/$BASHPID/fd/1 -ef /proc/$HOLD_TOP/fd/1 ]]; then
      __hold_sampler=1
    fi
  fi
  if [ "$!" = "$__hold_seen" ]; then return 0; fi
  __hold_seen=$!
  __hold_jobs=$((__hold_jobs + 1))
  case "$HOLD_WHERE" in
    main) [ "$BASHPID" = "$HOLD_TOP" ] || return 0 ;;
    sub) [ -n "$__hold_sampler" ] || return 0 ;;
  esac
  if [ "$__hold_jobs" = "$HOLD_NTH" ]; then
    echo "$BASHPID $BASH_COMMAND" > "$HOLD_MARK"
    for ((__hold_i = 0; __hold_i < 600; __hold_i++)); do
      [ ! -e "$HOLD_MARK.sent" ] || break
      read -r -t 0.05 _ <> "$HOLD_FIFO"
    done
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


def held_gate(setup: dict, tmp_path: Path, mode: str, env: dict, signal_on_mark: bool) -> dict:
    """Run the gate with HOLD as BASH_ENV and the env given; with signal_on_mark, SIGTERM it once HOLD_MARK
    holds a line. Returns the exit code, the seconds to the gate's exit and from its exit to the end of
    its stdout and stderr (None: still open 10 s after), and what of the run still ran after that."""
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
        if signal_on_mark:
            while not (mark.exists() and mark.read_text().strip()) and time.monotonic() - start < 30:
                time.sleep(0.01)
            proc.send_signal(signal.SIGTERM)
            # The signal is sent before the hold lets go: a trap that only notes it does not end `read`.
            Path(f"{mark}.sent").touch()
        code = proc.wait(timeout=30)
        exited = time.monotonic() - start
        for r in readers:
            r.join(timeout=10)
        closed = None if any(r.is_alive() for r in readers) else time.monotonic() - start - exited
        return {"code": code, "exited": exited, "closed": closed, "left": left_of(marker), "mark": mark}
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


def test_a_kill_that_reaches_the_sampler_before_it_keeps_its_sleeps_pid_ends_the_sleep_too(
    gate_setup, tmp_path
):
    """The sampler is held at the first command after it started its 60 s sleep; the stand-in make
    answers once that sleep runs, and the gate ends the sampler. Before the fix the sampler's sleep ran in
    the background and its pid was kept on the next line (`nap=$!`): a TERM there found no pid, the
    sleep was left for 60 s and held the gate's stdout and stderr, so a caller that reads them waited
    60 s (the health gate of 2026-11-19 02:02 UTC, where it came by chance on a loaded machine). Here it
    comes there every time: before the fix, 10 of 10 runs left `sleep 60` and the pipes open 10 s after
    the gate's exit. After it, 10 of 10 runs (2026-11-19, load under 2): the gate exited in 0.115 to
    0.118 s, and its pipes closed 0.000 s after its exit. The margins: the bound of 30 s is over 250 times
    the slowest exit, and the 10 s the pipes may stay open is 10 s more than any run took."""
    real_sleep = shutil.which("sleep")
    bin_dir = tmp_path / "bin2"
    bin_dir.mkdir()
    sleeps = tmp_path / "sleeps"
    (bin_dir / "sleep").write_text(
        "#!/bin/sh\n"
        f'if [ "$1" = "$GATE_SAMPLE_SECONDS" ]; then echo $$ >> "{sleeps}"; fi\n'
        f'exec {real_sleep} "$@"\n'
    )
    (bin_dir / "sleep").chmod(0o755)
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{gate_setup['env']['PATH']}",
        "GATE_SAMPLE_SECONDS": "60",
        "STANDIN_SLEEPS": str(sleeps),
        "HOLD_WHERE": "sub",
        "HOLD_NTH": "1",
    }
    run = held_gate(gate_setup, tmp_path, "asleep", env, signal_on_mark=False)
    assert run["code"] == 0
    assert run["exited"] < 30
    assert run["closed"] is not None, f"the gate's pipes were still open 10 s after it ended: {run['left']}"
    assert run["left"] == []
    assert remote_head(gate_setup) == gate_setup["head"]


@pytest.mark.parametrize("nth, job", [(1, "the sampler"), (2, "make")])
def test_a_sigterm_while_a_job_starts_ends_that_job_before_the_lock_goes(gate_setup, tmp_path, nth, job):
    """The gate's shell is held at the first command after the `&` of its job `nth` (1 the sampler, 2 make),
    before the line that keeps the job's pid, and the test sends SIGTERM there. Before the fix, finish()
    found no pid: 10 of 10 runs of each left the sampler looping for good (it held the gate's pipes), or
    make running after the lock was removed. After it, the signal waits until the pid is kept, and the job
    ends with the gate: 10 of 10 runs of each exited in 0.105 to 0.116 s, the pipes closed 0.000 s after
    (2026-11-19, load under 2); the bound of 30 s is over 250 times the slowest."""
    env = {"GATE_SAMPLE_SECONDS": "60", "HOLD_WHERE": "main", "HOLD_NTH": str(nth)}
    run = held_gate(gate_setup, tmp_path, "slow", env, signal_on_mark=True)
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
    0.068 s (2026-11-19, load under 2); the bound of 30 s is over 400 times the slowest."""
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
    run = held_gate(gate_setup, tmp_path, "slow", env, signal_on_mark=True)
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
