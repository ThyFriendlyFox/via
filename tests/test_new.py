"""`workcenter new` and the first answers of `workcenter next` on a new board (user round 1 of 2026-11-17).

The small user of that round made an empty folder, ran `next`, and got no command that starts a board.
Here an empty folder is answered with `workcenter new` at once, with every engine on PATH replaced by a
stand-in that records its call; `new` writes a project; `next` then names the design step, and on a
board generated without --route it names the route before the gates.
"""

from __future__ import annotations

import importlib.machinery
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
TEMPLATE = ROOT / "templates" / "project" / "design.py"
sys.path.insert(0, str(ROOT / "tools"))
import guide  # noqa: E402
import kicadgen  # noqa: E402

# Every engine a command of the workcenter starts by name (tools/workcenter's doctor, the chip gates'
# engines, the display server of the renders), and `flock`, which the small user waited on.
ENGINES = (
    "kicad-cli",
    "ngspice",
    "java",
    "Xvfb",
    "xvfb-run",
    "rsvg-convert",
    "ffmpeg",
    "openEMS",
    "iverilog",
    "vvp",
    "verilator",
    "yosys",
    "magic",
    "netgen",
    "openroad",
    "sta",
    "klayout",
    "flock",
)
# The parts file's header as `procure` reads it (tools/workcenter, PARTS_COLUMNS), and library/sources.csv's
# as `fetch --row` writes it (SOURCES_HEADER).
PARTS_HEADER = "Value,Footprint,Qty,Manufacturer,MPN,Supplier,SKU,Pack,Breaks\n"
SOURCES_HEADER = "MPN,Kind,URL,File,Member,Revision,Dated,Subckt,Ngspice,SHA256,Checked,Note\n"
# The fastest of 3 answers on an empty folder, in seconds. Measured on 2026-11-17 on this machine's 4
# processors at a load average of 3.3: 10 runs of `next` on an empty folder took 0.173 to 0.234 s. The
# round's candidate asks for an answer within a second; the fastest of 3 takes the scheduler's noise out.
BOUND = 1.0
# The folder tools/kicadgen.py reads (KICAD_SYMBOL_DIR), so `make verify-site` skips it as CI's fast job does.
needs_symbols = pytest.mark.skipif(
    not (kicadgen.SYMBOL_DIR / "Device.kicad_sym").is_file(), reason="KiCad's symbol library is absent"
)


def stand_ins(folder: Path) -> tuple[dict, Path]:
    """An environment whose PATH finds a stand-in first for each engine: it writes its name to the log
    and exits 97. The engines' own variables are taken out, so each is looked up on PATH."""
    bin_dir = folder / "engines"
    bin_dir.mkdir()
    log = folder / "called.log"
    for name in ENGINES:
        script = bin_dir / name
        script.write_text(
            f'#!/bin/sh\necho "{name} $*" >> {shlex.quote(str(log))}\nexit 97\n', encoding="utf-8"
        )
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
    env = {k: v for k, v in os.environ.items() if k not in ("KICAD_CLI", "NGSPICE", "JAVA")}
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    return env, log


def workcenter(*args: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI), *args], capture_output=True, text=True, check=False, env=env, timeout=120
    )


def ask(project: Path, env: dict) -> tuple[int, dict]:
    proc = workcenter("--json", "next", str(project), env=env)
    return proc.returncode, json.loads(proc.stdout)


def run_line(step: dict, env: dict) -> subprocess.CompletedProcess:
    """Run a step's RUN line as its reader does, with this checkout's `workcenter`."""
    words = shlex.split(step["run"])
    assert words[0] == "workcenter", step["run"]
    return workcenter(*words[1:], env=env)


def files(folder: Path) -> list[str]:
    return sorted(str(p.relative_to(folder)) for p in folder.rglob("*"))


# ------------------------------------------------------------- the round's test


@needs_symbols
def test_an_empty_folder_is_told_new_then_the_design_then_the_route(tmp_path):
    """The candidate's done_when: `next` on an empty folder, its RUN line, `next` again, with nothing
    read but what the lines name. No engine is called on the way: the board is generated without --route,
    which runs none.

    The template's board has 4 parts on 3 nets: J1 pins 1, 2, 3 on VCC, OUT, GND; R1 on VCC and OUT; R2
    and C1 on OUT and GND. VCC holds 2 pads (J1.1, R1.1), OUT 4 (J1.2, R1.2, R2.1, C1.1), GND 3 (J1.3,
    R2.2, C1.2): 2 + 4 + 3 = 9 pads on 3 nets. KiCad names the local net OUT `/OUT`."""
    env, log = stand_ins(tmp_path)
    board = tmp_path / "sensor-node"
    board.mkdir()
    code, step = ask(board, env)
    assert (code, step["run"]) == (1, f"workcenter new {board}")
    assert step["done_when"] == f"`workcenter next {board}` names the design step"
    made = run_line(step, env)
    assert made.returncode == 0, made.stdout + made.stderr
    assert made.stdout.splitlines()[-1] == (
        f"new: 4 files written, 0 kept. Next: edit {board}/design.py, then workcenter next {board}"
    )
    code, step = ask(board, env)
    assert (code, step["next"]) == (1, "Generate the KiCad project from its design file.")
    assert step["run"] == f"workcenter design {board}/design.py --route"
    # the user generates without --route: the route comes before the gates
    made = workcenter("design", str(board / "design.py"), env=env)
    assert made.returncode == 0, made.stdout + made.stderr
    code, step = ask(board, env)
    assert (code, step["next"]) == (1, "Route the board before the gates: nets on it have no copper yet.")
    assert step["run"] == f"workcenter design {board}/design.py --route"
    # 9 pads on 3 nets with no copper are 9 - 3 = 6 connections, KiCad DRC's count (test_route_open.py)
    assert step["why"] == "9 pads on 3 nets have no track, via or pour, 6 unconnected: /OUT, GND, VCC"
    assert "prints `route: 0 unconnected`" in step["done_when"]
    assert not log.exists(), log.read_text(encoding="utf-8")


def test_an_empty_folder_is_answered_at_once_and_starts_no_engine(tmp_path):
    """The small user's `next` sat 10 minutes with no output. On an empty folder the answer reads no
    report and starts no engine, so it comes within BOUND seconds whatever the engines are doing."""
    env, log = stand_ins(tmp_path)
    board = tmp_path / "empty"
    board.mkdir()
    took = []
    for _ in range(3):
        start = time.monotonic()
        code, step = ask(board, env)
        took.append(time.monotonic() - start)
        assert (code, step["run"]) == (1, f"workcenter new {board}")
    assert min(took) < BOUND, took
    assert not log.exists(), log.read_text(encoding="utf-8")
    assert files(board) == []  # `next` writes nothing


# ------------------------------------------------------------- what `new` writes


def test_new_writes_the_template_under_the_folders_name_and_the_headers(tmp_path):
    """design.py is the template with 2 lines changed: the name, from the folder's, and a namespace of
    its own. The parts file and library/sources.csv hold their headers alone, and the readers take them."""
    env, _ = stand_ins(tmp_path)
    board = tmp_path / "my board"
    made = workcenter("new", str(board), env=env)
    assert made.returncode == 0, made.stdout + made.stderr
    assert files(board) == [".gitignore", "design.py", "library", "library/sources.csv", "parts.csv"]
    ours = (board / "design.py").read_text(encoding="utf-8").splitlines()
    theirs = TEMPLATE.read_text(encoding="utf-8").splitlines()
    changed = [(a.strip(), b.strip()) for a, b in zip(theirs, ours, strict=True) if a != b]
    assert [a for a, _ in changed] == [
        'name="divider",',
        'namespace=uuid.UUID("7c1d9a52-3e4b-4f6a-8b0d-2a5e6f7c8d91"),',
    ]
    assert changed[0][1] == 'name="my-board",'
    assert (
        re.fullmatch(r'namespace=uuid\.UUID\("[0-9a-f-]{36}"\),', changed[1][1])
        and changed[1][1] != changed[1][0]
    )
    compile("\n".join(ours), "design.py", "exec")
    assert (board / "parts.csv").read_text(encoding="utf-8") == PARTS_HEADER
    assert (board / "library" / "sources.csv").read_text(encoding="utf-8") == SOURCES_HEADER
    cli = load_cli()
    assert cli.read_parts(board / "parts.csv") == []
    assert cli.find_sources(board) == board / "library" / "sources.csv"
    ignored = (board / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "build/" in ignored and "*.kicad_prl" in ignored
    # 2 projects get 2 namespaces: the same UUIDs in 2 boards would collide
    again = workcenter("new", str(tmp_path / "other"), env=env)
    assert again.returncode == 0
    first = changed[1][1]
    assert first not in (tmp_path / "other" / "design.py").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "design", ["design.py", "psu.kicad_pro", "psu.kicad_sch", "psu.kicad_pcb", "chip.json"]
)
def test_new_refuses_a_folder_that_holds_a_design_in_one_line(tmp_path, design):
    env, _ = stand_ins(tmp_path)
    board = tmp_path / "board"
    board.mkdir()
    (board / design).write_text("", encoding="utf-8")
    made = workcenter("new", str(board), env=env)
    assert made.returncode == 1
    assert made.stdout.splitlines() == [
        f"new: {board} holds a design already ({design}); nothing written. Next: workcenter next {board}"
    ]
    assert files(board) == [design]


def test_new_keeps_what_is_there_and_the_library_above(tmp_path):
    """A folder with a .gitignore of its own keeps it. A library/sources.csv in a folder above serves
    the project, as `fetch --row` finds it, so no second one is started under it."""
    env, _ = stand_ins(tmp_path)
    (tmp_path / "library").mkdir()
    (tmp_path / "library" / "sources.csv").write_text(SOURCES_HEADER, encoding="utf-8")
    board = tmp_path / "boards" / "psu"
    board.mkdir(parents=True)
    (board / ".gitignore").write_text("mine\n", encoding="utf-8")
    made = workcenter("new", str(board), env=env)
    assert made.returncode == 0, made.stdout + made.stderr
    assert made.stdout.splitlines() == [
        f"wrote {board}/design.py",
        f"wrote {board}/parts.csv",
        f"kept  {board}/.gitignore (it is there already)",
        f"kept  {tmp_path}/library/sources.csv (the library above serves this project)",
        f"new: 2 files written, 1 kept. Next: edit {board}/design.py, then workcenter next {board}",
    ]
    assert (board / ".gitignore").read_text(encoding="utf-8") == "mine\n"
    assert files(board) == [".gitignore", "design.py", "parts.csv"]


def test_new_refuses_a_file(tmp_path):
    env, _ = stand_ins(tmp_path)
    note = tmp_path / "note.txt"
    note.write_text("a note\n", encoding="utf-8")
    made = workcenter("new", str(note), env=env)
    assert (made.returncode, made.stdout.splitlines()) == (
        1,
        [f"new: {note} is a file; name a folder. Nothing written."],
    )


def test_new_refuses_a_folder_under_a_file_in_one_line(tmp_path):
    """A folder above the target is a file: no folder can be made under it. Review finding F1."""
    env, _ = stand_ins(tmp_path)
    note = tmp_path / "note.txt"
    note.write_text("a note\n", encoding="utf-8")
    made = workcenter("new", str(note / "sub"), env=env)
    assert (made.returncode, made.stdout.splitlines(), made.stderr) == (
        1,
        [f"new: {note} is a file, where {note}/sub/design.py needs a folder; nothing written."],
        "",
    )


@pytest.mark.parametrize(("there", "kind"), [("library", "file"), ("parts.csv", "folder")])
def test_new_checks_every_path_before_it_writes_one(tmp_path, there, kind):
    """A file `library` stops library/sources.csv, a folder `parts.csv` stops the parts file: the
    refusal is 1 line and the folder holds what it held. Review finding F2."""
    env, _ = stand_ins(tmp_path)
    board = tmp_path / "board"
    board.mkdir()
    if kind == "file":
        (board / there).write_text("x\n", encoding="utf-8")
        line = f"new: {board / there} is a file, where {board}/library/sources.csv needs a folder"
    else:
        (board / there).mkdir()
        line = f"new: {board / there} is a folder, where a file goes"
    made = workcenter("new", str(board), env=env)
    assert (made.returncode, made.stdout.splitlines(), made.stderr) == (1, [f"{line}; nothing written."], "")
    assert files(board) == [there]


def test_new_refuses_an_empty_name(tmp_path):
    """`new ""` would take the current folder, which the user did not name. Review finding F7."""
    env, _ = stand_ins(tmp_path)
    made = subprocess.run(
        [sys.executable, str(CLI), "new", ""],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        cwd=tmp_path,
    )
    assert (made.returncode, made.stdout.splitlines()) == (
        1,
        ["new: the folder's name is empty; name a folder. Nothing written."],
    )
    assert sorted(p.name for p in tmp_path.iterdir()) == ["engines"]


def test_new_under_a_git_folder_starts_its_own_library(tmp_path):
    """The board is a git repository of its own under a folder with a library: `find_sources`, which
    `fetch --row` and `sources` call, stops at the board's .git. So `new` starts a library in the board,
    and `find_sources(board)` finds it. Review finding F3."""
    env, _ = stand_ins(tmp_path)
    (tmp_path / "library").mkdir()
    (tmp_path / "library" / "sources.csv").write_text(SOURCES_HEADER, encoding="utf-8")
    board = tmp_path / "board"
    (board / ".git").mkdir(parents=True)
    made = workcenter("new", str(board), env=env)
    assert made.returncode == 0, made.stdout + made.stderr
    assert made.stdout.splitlines()[-1].startswith("new: 4 files written, 0 kept.")
    assert load_cli().find_sources(board) == board / "library" / "sources.csv"


# ------------------------------------------------------------- the route before the gates


BOARD_9 = """(kicad_pcb
\t(net 0 "")
\t(net 1 "VCC")
\t(net 2 "OUT")
\t(footprint "R" (pad "1" smd (net 1 "VCC")) (pad "2" smd (net 2 "OUT")))
\t(footprint "C" (pad "1" smd (net 2 "OUT")) (pad "2" smd (net 0 "")))
\t(footprint "J" (pad "1" thru_hole (net 1 "VCC")) (pad "2" thru_hole (net "unconnected-(J1-Pad2)"))
\t\t(pad "3" thru_hole (net 3 "LONE")))
{copper})
"""


@pytest.mark.parametrize(
    ("copper", "expected"),
    [
        # VCC: R.1 and J.1; OUT: R.2 and C.1. 2 + 2 = 4 pads on 2 nets. C.2 has no net, J.2 is a pin left
        # open, J.3 is the only pad of LONE: none of them asks for copper.
        ("", (4, ["OUT", "VCC"])),
        # a track on VCC by its number, as KiCad 9 writes it: OUT is left, 2 pads
        ('\t(segment (start 0 0) (end 1 0) (width 0.2) (layer "F.Cu") (net 1))\n', (2, ["OUT"])),
        # a track by its name, as KiCad 10 writes it, a via and a pour: nothing is left
        ('\t(arc (start 0 0) (mid 1 1) (end 2 0) (net "VCC"))\n\t(zone (net 2) (net_name "OUT"))\n', (0, [])),
        ('\t(via (at 0 0) (net "OUT"))\n\t(segment (net "VCC"))\n', (0, [])),
        # a name in quotes holds a parenthesis: it is no block
        ('\t(gr_text "a (b" (at 0 0))\n\t(segment (net "VCC"))\n', (2, ["OUT"])),
    ],
)
def test_unrouted_counts_the_pads_of_nets_with_no_copper(tmp_path, copper, expected):
    pcb = tmp_path / "b.kicad_pcb"
    pcb.write_text(BOARD_9.format(copper=copper), encoding="utf-8")
    assert guide.unrouted(pcb) == expected


def test_routed_fixture_boards_have_no_net_without_copper():
    """Every board the gates pass in the fixtures is routed: no route step would come before its gates."""
    boards = sorted((ROOT / "tests" / "boards").glob("pass-*/*.kicad_pcb"))
    assert boards
    assert [(b.parent.name, guide.unrouted(b)) for b in boards if guide.unrouted(b)[1]] == []


def test_the_route_step_comes_only_while_the_gates_are_to_run(tmp_path, monkeypatch):
    """With a current gates report the gates have judged the board: DRC's own line names an open net.
    The route step stands only before the first run, or when an input is newer than the report."""
    cli = load_cli()
    monkeypatch.setattr(cli, "KICAD_CLI", sys.executable)
    monkeypatch.setattr(
        guide,
        "subprocess",
        types.SimpleNamespace(run=lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="")),
    )
    board = tmp_path / "b"
    board.mkdir()
    (board / "design.py").write_text("# a design\n", encoding="utf-8")
    (board / "b.kicad_pcb").write_text(BOARD_9.format(copper=""), encoding="utf-8")
    step = guide.next_step(cli, str(board))
    assert step.next == "Route the board before the gates: nets on it have no copper yet."
    assert step.why == "4 pads on 2 nets have no track, via or pour, 2 unconnected: OUT, VCC"
    assert step.done_when == guide.ROUTED
    (board / "build").mkdir()
    gates = board / "build" / "gates.json"
    gates.write_text(json.dumps([]), encoding="utf-8")
    later = time.time() + 5
    os.utime(gates, (later, later))
    assert guide.next_step(cli, str(board)).next != step.next
    # the board changes after the run: the gates are to run again, and the route comes first
    os.utime(board / "b.kicad_pcb", (later + 5, later + 5))
    assert guide.next_step(cli, str(board)).next == step.next


def test_a_hand_drawn_board_gets_no_route_step(tmp_path, monkeypatch):
    """No design.py: there is no file to route with, so the gates are named, as before the route step
    came. Review finding F6, the guard `design.is_file()`."""
    cli = load_cli()
    monkeypatch.setattr(cli, "KICAD_CLI", sys.executable)
    board = tmp_path / "b"
    board.mkdir()
    (board / "b.kicad_pro").write_text("{}\n", encoding="utf-8")
    (board / "b.kicad_pcb").write_text(BOARD_9.format(copper=""), encoding="utf-8")
    assert guide.unrouted(board / "b.kicad_pcb")[1] == ["OUT", "VCC"]
    step = guide.next_step(cli, str(board), run_check=False)
    assert (step.next, step.why) == ("Run the gates.", "no build/gates.json yet")


def test_a_net_kicad_names_unconnected_asks_for_no_copper(tmp_path):
    """KiCad names a net `unconnected-(...)` for a pin left open; 2 pads on 1 such net still ask for no
    track. The board: VCC on R.1 and J.1, `unconnected-(J1-Pad2)` on J.2 and R.2, no copper: VCC's 2
    pads are counted, the other 2 are not. Review finding F6, the `unconnected-` guard."""
    pcb = tmp_path / "b.kicad_pcb"
    pcb.write_text(
        '(kicad_pcb\n\t(net 1 "VCC")\n\t(net 2 "unconnected-(J1-Pad2)")\n'
        '\t(footprint "R" (pad "1" smd (net 1 "VCC")) (pad "2" smd (net 2 "unconnected-(J1-Pad2)")))\n'
        '\t(footprint "J" (pad "1" smd (net 1 "VCC")) (pad "2" smd (net 2 "unconnected-(J1-Pad2)"))))\n',
        encoding="utf-8",
    )
    assert guide.unrouted(pcb) == (2, ["VCC"])


def test_a_board_that_is_not_utf8_is_read_and_answered(tmp_path):
    """Byte 0xe9 (latin-1 for e acute) in a net name: the board is read with the byte replaced, and
    `next` names the route, not a traceback. The net `V<0xe9>` holds R.1 and J.1: 2 pads on 1 net.
    Review finding F4."""
    env, _ = stand_ins(tmp_path)
    board = tmp_path / "b"
    board.mkdir()
    (board / "design.py").write_text("# a design\n", encoding="utf-8")
    (board / "b.kicad_pro").write_text("{}\n", encoding="utf-8")
    text = '(kicad_pcb\n\t(net 1 "V\xe9")\n\t(footprint "R" (pad "1" smd (net 1 "V\xe9")))\n'
    text += '\t(footprint "J" (pad "1" smd (net 1 "V\xe9"))))\n'
    (board / "b.kicad_pcb").write_bytes(text.encode("latin-1"))
    assert guide.unrouted(board / "b.kicad_pcb") == (2, ["V�"])
    proc = workcenter("next", "--trust-design", str(board), env=env)
    assert proc.returncode == 1 and "Traceback" not in proc.stderr, proc.stderr
    assert "Route the board before the gates" in proc.stdout


def test_the_help_of_next_says_exit_1_is_a_step_and_no_error():
    """Both helps say it: the command list of `workcenter --help`, and `workcenter next --help`, which
    is where a reader of `next` looks. Review finding F5."""
    for args in (["--help"], ["next", "--help"]):
        proc = subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True, check=False)
        text = " ".join(proc.stdout.split())
        assert "1 when a step is named (no error: do the step)" in text, args
    proc = subprocess.run([sys.executable, str(CLI), "--help"], capture_output=True, text=True, check=False)
    text = " ".join(proc.stdout.split())
    assert re.search(r"\bnew\b.*start a board project in a folder", text)


def load_cli():
    loader = importlib.machinery.SourceFileLoader("workcenter_cli_new", str(CLI))
    module = types.ModuleType("workcenter_cli_new")
    module.__file__ = str(CLI)
    sys.modules[module.__name__] = module
    loader.exec_module(module)
    return module
