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
    run = landed(tmp_path / "landed.json", journal, tmp_path / "missing.jsonl")
    assert run.returncode == 1
    assert run.stdout == (
        "waiting eps: the build ended with no result; read its journal before starting it again\n"
        "waiting eta: no build result yet\n"
        "waiting zeta: review 1 ended with no result; start a new review\n"
        "landed: nothing new\n"
    )


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
  400     1 node            node /scratch/wf/run.js
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
    and is not counted; a process named in QUIET_IGNORE (900, the host's own) is left out."""
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
        "400 node node /scratch/wf/run.js",
        "600 bash bash /scratch/work.sh",
        "800 yosys /opt/chip/bin/yosys -s synth.ys",
    ]


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
