"""A first design file: the template a reader copies, and the traps a small model met writing one.

`templates/project/design.py` generates, routes and passes ERC and DRC as it stands. A namespace that
is no `uuid.UUID`, a `power_nets` that is no dict, a flagged net `power_nets` does not name, a part
placed from another origin than the outline's and a route that joins nothing each stop with a message
that says what to write. The `pull:` line shows the entry it asks for. A design that passes a UUID
writes what it wrote before the messages: `tests/test_inspect.py` regenerates a fixture to its
committed bytes, and on the day of the change both forms of the schematic, the project and the board
came out equal from the generator before it and the generator after it.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import kicadgen  # noqa: E402

CLI = ROOT / "tools" / "workcenter"
TEMPLATE = ROOT / "templates" / "project" / "design.py"
LIBS = kicadgen.SYMBOL_DIR / "Device.kicad_sym"
JAR = Path("/opt/workcenters/ee/freerouting/freerouting.jar")

needs_libs = pytest.mark.skipif(not LIBS.is_file(), reason="KiCad symbol libraries are not installed")
needs_kicad = pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="kicad-cli is not installed")
needs_router = pytest.mark.skipif(
    not JAR.is_file() or shutil.which("java") is None, reason="FreeRouting is not installed"
)

HEADER = "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical"
R_0603 = "Resistor_SMD:R_0603_1608Metric"
C_0603 = "Capacitor_SMD:C_0603_1608Metric"


def board(mod=kicadgen, at: tuple[float, float] = (100.0, 100.0), wires: bool = False):
    """The template's circuit on the default outline, (100, 100) to (125, 120), its parts placed from
    `at`: the outline's own corner puts them on the board, (0, 0) is the trap. `mod` is the generator."""
    d = mod.Design(name="t", namespace=uuid.UUID(int=31))
    d.power_nets = {"VCC": "VCC", "GND": "GND"}
    d.flagged_nets = ["VCC", "GND"]
    d.sch_wires = wires
    ox, oy = at
    d.add(
        "J1",
        "Connector_Generic:Conn_01x03",
        "IN",
        HEADER,
        sch_at=(139.7, 83.82),
        pcb_at=(ox + 4.0, oy + 7.5),
        nets={"1": "VCC", "2": "OUT", "3": "GND"},
    )
    passives = [
        ("R1", "Device:R", "10k", R_0603, (101.6, 76.2), 6.0, {"1": "VCC", "2": "OUT"}),
        ("R2", "Device:R", "10k", R_0603, (101.6, 91.44), 10.0, {"1": "OUT", "2": "GND"}),
        ("C1", "Device:C", "100n", C_0603, (114.3, 91.44), 14.0, {"1": "OUT", "2": "GND"}),
    ]
    for ref, symbol, value, footprint, sch_at, y, nets in passives:
        d.add(ref, symbol, value, footprint, sch_at=sch_at, pcb_at=(ox + 10.0, oy + y), nets=nets)
    return d


def design_file(folder: Path, *body: str) -> Path:
    """A design file whose build() makes `d = board()`, runs the lines of `body` and returns `d`."""
    folder.mkdir(parents=True, exist_ok=True)
    lines = [
        "import sys",
        f"sys.path.insert(0, {str(ROOT / 'tools')!r})",
        f"sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})",
        "import kicadgen",
        "from test_designfile import board",
        "",
        "",
        "def build():",
        "    d = board()",
        *(f"    {line}" for line in body),
        "    return d",
    ]
    (folder / "design.py").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return folder / "design.py"


def run(*args: object) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI), *map(str, args)], capture_output=True, text=True, check=False
    )


def off_board(ref: str, x: str, y: str, at: str = "") -> str:
    """The `part:` line of a part at (x, y) off the default outline; `at` is the place it names."""
    hint = f", so a part {x} mm right of it and {y} mm below it is at pcb_at={at}" if at else ""
    return (
        f"{ref} at ({x}, {y}): every pad lies outside the outline, (100, 100) to (125, 120). pcb_at is in "
        f"board coordinates, as the outline is: the board's top left corner is (100, 100){hint}"
    )


# ------------------------------------------------------------ the template


@needs_libs
@needs_kicad
@needs_router
def test_the_template_generates_routes_and_passes_erc_and_drc(tmp_path):
    shutil.copy(TEMPLATE, tmp_path / "design.py")  # as a reader takes it: a copy in a project's folder
    r = run("design", tmp_path / "design.py", "--route")
    assert r.returncode == 0, r.stdout + r.stderr
    assert re.search(r"^  routed: [1-9]\d* segments, \d+ vias, DRC decides, 1 round", r.stdout, re.M), (
        r.stdout
    )
    assert not re.search(r"^  (part|pull|via|sim|island): ", r.stdout, re.M), r.stdout
    assert (tmp_path / "divider.kicad_sch").is_file() and (tmp_path / "divider.kicad_pcb").is_file()
    gates = run("--json", "gates", tmp_path, "--strict")
    assert gates.returncode == 0, gates.stdout + gates.stderr
    status = {record["gate"]: record["status"] for record in json.loads(gates.stdout)}
    assert (status["erc"], status["drc"]) == ("pass", "pass")


OPAMP = """    d.add(
        "U1",
        "Amplifier_Operational:MCP6001-OT",
        "MCP6001-OT",
        "Package_TO_SOT_SMD:SOT-23-5",
        sch_at=(152.4, 114.3),
        pcb_at=(118.0, 110.0),
        nets={"1": "OUT", "2": "GND", "3": "OUT", "4": "OUT", "5": "VCC"},
    )
    return d
"""


@needs_libs
def test_a_part_added_to_the_template_says_how_it_simulates_or_is_refused(tmp_path):
    """A small model put an op-amp on its first board and proved the circuit with a source of its own
    in the deck: GREEN, and nothing said which part the numbers were of. The template turns
    `check_sim` on, so the part's model, or the reason it has none, is written before a file is."""
    text = TEMPLATE.read_text(encoding="utf-8")
    assert text.count("    return d\n") == 1 and "d.check_sim = True" in text
    (tmp_path / "design.py").write_text(text.replace("    return d\n", OPAMP), encoding="utf-8")
    r = run("design", tmp_path / "design.py")
    assert r.returncode == 1, r.stdout + r.stderr
    assert [ln for ln in r.stdout.splitlines() if ln.startswith("  sim: ")] == [
        "  sim: U1: neither sim() nor no_sim(): say how the part simulates, or leave it out with the reason"
    ]
    # the connector's own line is what keeps the template itself clean
    bare = text.replace(
        '    d.no_sim("J1", "a connector: the header\'s pins are the circuit\'s terminals")\n', ""
    )
    assert bare != text
    (tmp_path / "design.py").write_text(bare, encoding="utf-8")
    r = run("design", tmp_path / "design.py")
    assert r.returncode == 1 and "  sim: J1: neither sim() nor no_sim()" in r.stdout


# ------------------------------------------------------------- the namespace


def test_a_namespace_that_is_no_uuid_is_refused_with_the_call_to_write(monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(kicadgen.uuid, "uuid4", lambda: uuid.UUID(int=7))
        for args, given in ((("filter",), "None"), (("filter", "filter"), "'filter'")):
            with pytest.raises(TypeError) as e:
                kicadgen.Design(*args)
            assert str(e.value) == (
                f"Design('filter'): namespace is {given}, not a uuid.UUID. Write "
                'Design("filter", uuid.UUID("00000000-0000-0000-0000-000000000007")) after `import uuid`. '
                "That UUID is new; keep it, since every UUID in the generated files comes from it."
            )
    # The call the message writes is one the class takes, and each message brings a UUID of its own.
    assert kicadgen.Design("filter", uuid.UUID("00000000-0000-0000-0000-000000000007")).name == "filter"
    offered = []
    for _ in range(2):
        with pytest.raises(TypeError) as e:
            kicadgen.Design("filter")
        offered.append(uuid.UUID(re.search(r'uuid\.UUID\("([0-9a-f-]{36})"\)', str(e.value)).group(1)))
    assert offered[0] != offered[1]


# -------------------------------------------------------------- power nets


@needs_libs
def test_power_nets_that_is_no_dict_is_refused_with_the_dict_to_write(tmp_path):
    tail = ": each power net, then the symbol of KiCad's power library that draws it."
    as_list = 'power_nets is a list, not a dict. Write d.power_nets = {"VCC": "VCC", "GND": "GND"}' + tail
    d = board()
    d.power_nets = ["VCC", "GND"]
    with pytest.raises(TypeError) as e:
        d.schematic()
    assert str(e.value) == as_list
    d.power_nets = {"VCC", "GND"}  # a set has no order: the example lists its names sorted
    with pytest.raises(TypeError) as e:
        d.check_power_nets()
    assert str(e.value) == (
        'power_nets is a set, not a dict. Write d.power_nets = {"GND": "GND", "VCC": "VCC"}' + tail
    )
    # Through the command the design stops when it is loaded: before the route, with nothing written.
    # It is 1 `file:` line and the red line, as every refusal of the step is: no traceback to read.
    r = run("design", design_file(tmp_path, 'd.power_nets = ["VCC", "GND"]'), "--route")
    assert r.returncode == 1 and r.stderr == ""
    red = "the design file is refused. Nothing is written: correct the file first."
    assert r.stdout.splitlines() == [f"  file: {as_list}", f"design {tmp_path.name} red: {red}"]
    assert list(tmp_path.glob("*.kicad_*")) == [] and not (tmp_path / "build").exists()
    # A refusal raised from a line of the design file names that line: the body starts at line 10.
    r = run("design", design_file(tmp_path / "n", 'kicadgen.Design("filter")'), "--json")
    said = json.loads(r.stdout)
    assert r.returncode == 1 and said["red"] == ["the design file is refused"]
    assert len(said["file_problems"]) == 1
    assert said["file_problems"][0].startswith(
        "line 10: Design('filter'): namespace is None, not a uuid.UUID."
    )


@needs_libs
def test_an_empty_list_of_power_nets_still_reads_as_none():
    """It never reached the line that fails, so a design that has one keeps writing what it wrote."""
    listed, empty = board(), board()
    listed.power_nets, listed.flagged_nets = [], []
    empty.power_nets, empty.flagged_nets = {}, []
    assert listed.schematic() == empty.schematic()


@needs_libs
def test_a_flagged_net_that_power_nets_does_not_name_is_refused_with_the_entry_to_write():
    d = board()
    d.power_nets = {"GND": "GND"}
    with pytest.raises(ValueError) as e:
        d.schematic()
    assert str(e.value) == (
        "flagged_nets names 'VCC', and power_nets does not. A PWR_FLAG stands on a power symbol: write "
        'd.power_nets["VCC"] = "VCC" (the net, then the symbol of KiCad\'s power library that draws it), '
        "or take the net out of flagged_nets."
    )
    d = board()
    d.flagged_nets = "GND"
    with pytest.raises(TypeError) as e:
        d.schematic()
    assert str(e.value) == "flagged_nets is the str 'GND', not a list. Write d.flagged_nets = [\"GND\"]."


@needs_libs
@pytest.mark.parametrize("wires", [False, True])
def test_a_power_symbol_the_library_lacks_is_refused_with_symbols_it_has(wires):
    d = board(wires=wires)
    d.power_nets = {"VCC": "VIN", "GND": "GND"}
    with pytest.raises(ValueError) as e:
        d.schematic()
    assert str(e.value) == (
        "power_nets['VCC'] is 'VIN', and KiCad's power library has no symbol of that name. Write one it "
        'has, as d.power_nets["VCC"] = "VCC": GND, VCC, VDD, VBUS, +3V3, +5V and +BATT are there, and '
        "`python3 tools/kicadgen.py pins power:VCC` prints a symbol that is."
    )
    for name in ("GND", "VCC", "VDD", "VBUS", "+3V3", "+5V", "+BATT"):  # the message's own list
        assert len(kicadgen.load_symbol(f"power:{name}").pins) == 1


# ---------------------------------------------------------- parts off the board


@needs_libs
def test_a_part_placed_from_another_origin_is_a_part_line_and_exit_1(tmp_path):
    lines = [
        off_board("J1", "4", "7.5", "(104, 107.5)"),
        off_board("R1", "10", "6", "(110, 106)"),
        off_board("R2", "10", "10", "(110, 110)"),
        off_board("C1", "10", "14", "(110, 114)"),
    ]
    assert board(at=(0.0, 0.0)).check_parts() == lines
    assert board().check_parts() == []
    r = run("design", design_file(tmp_path, "d = board(at=(0.0, 0.0))"))
    assert r.returncode == 1, r.stdout + r.stderr
    assert [ln for ln in r.stdout.splitlines() if ln.startswith("  part: ")] == [
        f"  part: {ln}" for ln in lines
    ]


@needs_libs
def test_a_part_off_the_board_for_another_reason_gets_no_place_to_write():
    """The place is named only where the part's own numbers, read from the corner, land on the board."""
    d = board()
    d.parts[1].pcb_at = (130.0, 106.0)  # 5 mm past the right edge: (230, 206) is no better
    d.parts[2].pcb_at = (-3.0, 4.0)
    assert d.check_parts() == [off_board("R1", "130", "106"), off_board("R2", "-3", "4")]


@needs_libs
def test_a_part_that_overhangs_the_edge_is_not_refused(tmp_path):
    # The header 2.5 mm above the top edge at y = 100: pad 1 spans y 96.65..98.35 off the board, pad 2
    # 99.19..100.89 across the edge, pad 3 is on the board.
    over = board()
    over.parts[0].pcb_at = (104.0, 97.5)
    assert over.check_parts() == []
    r = run("design", design_file(tmp_path, "d.parts[0].pcb_at = (104.0, 97.5)"))
    assert r.returncode == 0 and "part:" not in r.stdout, r.stdout + r.stderr
    # R1's pad 2 spans x 99.225..100.025 at x = 98.8, 0.025 mm onto the board past the left edge at
    # x = 100, and 99.175..99.975 at x = 98.75, 0.025 mm short of it.
    edge = board()
    edge.parts[1].pcb_at = (98.8, 106.0)
    assert edge.check_parts() == []
    edge.parts[1].pcb_at = (98.75, 106.0)
    assert edge.check_parts() == [off_board("R1", "98.75", "106")]


# ------------------------------------------------------------------ the route


@needs_libs
def test_the_connections_of_a_board_with_no_copper_are_counted():
    assert board().bare_connections() == 6  # VCC joins 2 pins, OUT 4, GND 3
    poured = board()
    poured.zone("GND", layers=("F.Cu", "B.Cu"), connect="solid")
    assert poured.bare_connections() == 4  # the pour carries GND
    tracked = board()
    tracked.track("OUT", [(104.0, 110.04), (109.175, 110.0)])
    assert tracked.bare_connections() == 0  # copper on 1 net: the DRC decides
    alone = board()
    del alone.parts[1:]
    assert alone.bare_connections() == 0  # 3 nets of 1 pin each: nothing to route


@needs_libs
@needs_router
def test_a_route_that_joins_nothing_is_exit_1_and_a_board_with_nothing_to_route_is_exit_0(tmp_path):
    # A keep-out over both faces of the whole board: every part is on it, and no track may leave a pad.
    wall = 'd.keepout([(100, 100), (125, 100), (125, 120), (100, 120)], layers=("F.Cu", "B.Cu"), name="wall")'
    r = run("design", design_file(tmp_path / "walled", wall), "--route", "--json")
    summary = json.loads(r.stdout)
    assert r.returncode == 1, r.stdout + r.stderr
    route = summary["route"]
    assert (route["segments"], route["vias"], route["unrouted"]) == (0, 0, 6)
    assert summary["part_problems"] == [] and summary["red"] == ["6 unrouted"]
    r = run("design", design_file(tmp_path / "alone", "del d.parts[1:]"), "--route")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "  routed: 0 segments, 0 vias, DRC decides, 1 round(s)" in r.stdout


# ------------------------------------------------------------------ the pull


@needs_libs
def test_the_pull_line_ends_with_the_entry_it_asks_for():
    d = kicadgen.Design(name="pulls", namespace=uuid.UUID(int=21))
    d.power_nets = {"GND": "GND", "+3V3": "+3V3"}
    mcu = {"24": "GATE", "3": "+3V3", "4": "GND"}
    d.add("U1", "MCU_ST_STM32G0:STM32G031G8Ux", "MCU", None, sch_at=(50.8, 50.8), nets=mcu)
    fet = {"1": "GATE", "2": "GND", "3": "OUT"}
    d.add("Q1", "Transistor_FET:DMG1012T", "Q", None, sch_at=(101.6, 50.8), nets=fet)
    assert d.undefined_inputs() == [
        "GATE: Q1.1 (G, input), driven only by U1.24 (high-impedance in reset), and no resistor to a rail "
        "holds it: add a pull, or name the net in defined_nets with the reason, as "
        'd.defined_nets["GATE"] = "a 10k resistor to a rail on the other board, R4"'
    ]
    d.defined_nets["GATE"] = "100k to GND on the driver board, R4"  # the entry, as the line writes it
    assert d.undefined_inputs() == []
