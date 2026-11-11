"""A generated schematic that simulates: `Design.sim()`, `no_sim()`, `sim_directives`, `check_sim`.

A design says how each part simulates and kicadgen writes KiCad's Sim fields on the symbols, so the
netlist `kicad-cli sch export netlist --format spice` writes runs in ngspice. The trap these tests
keep closed: KiCad binds a model's node that a pin map leaves out to a pin by position and says
nothing, so `sim_problems()` refuses a map that is not whole. Each expected netlist line and each
value was read from a run on KiCad 10.0.8 and ngspice 42; the voltages were computed by hand first.
"""

from __future__ import annotations

import json
import math
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
needs_libs = pytest.mark.skipif(
    not (kicadgen.SYMBOL_DIR / "Device.kicad_sym").is_file(),
    reason="KiCad symbol libraries are not installed",
)
needs_kicad = pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="kicad-cli is not installed")
needs_ngspice = pytest.mark.skipif(shutil.which("ngspice") is None, reason="ngspice is not installed")

# A mixer (out = k_in * in + 0.1 * en) whose 4 nodes are in another order than the symbol's 5 pins, a
# diode and a 3-terminal MOSFET. `k_in` comes from a directive on the schematic.
LIBRARY = """* models for the generated schematic's tests
.subckt MIX IN GND EN OUT
B1 OUT GND V = {k_in}*V(IN,GND) + 0.1*V(EN,GND)
.ends MIX
.model DX D (is=1e-14 n=1)
.model MYVD VDMOS (vto=1.5 kp=0.5 rd=0.1)
.model M4 NMOS (level=1 vto=1)
"""
MIX_PINS = {"1": "IN", "2": "GND", "3": "EN", "4": None, "5": "OUT"}


def circuit() -> kicadgen.Design:
    """A divider, the mixer on a regulator's symbol, a diode, a MOSFET and a connector; nothing said
    about simulation yet."""
    d = kicadgen.Design(name="simtest", namespace=uuid.UUID("11111111-2222-3333-4444-555555555559"))
    d.power_nets = {"GND": "GND"}
    d.flagged_nets = ["GND"]
    g = 2.54
    d.add("R1", "Device:R", "10k", None, sch_at=(20 * g, 20 * g), nets={"1": "VIN", "2": "MID"})
    d.add("R2", "Device:R", "10k 1%", None, sch_at=(20 * g, 30 * g), nets={"1": "MID", "2": "GND"})
    d.add(
        "U1",
        "Regulator_Linear:AP2112K-3.3",
        "MIX",
        None,
        sch_at=(40 * g, 20 * g),
        nets={"1": "VIN", "2": "GND", "3": "MID", "5": "OUT"},
    )
    d.add("R3", "Device:R", "1k", None, sch_at=(60 * g, 20 * g), nets={"1": "VIN", "2": "DA"})
    d.add("D1", "Device:D", "DX", None, sch_at=(60 * g, 30 * g), nets={"1": "GND", "2": "DA"})
    d.add("R4", "Device:R", "1k", None, sch_at=(80 * g, 20 * g), nets={"1": "VIN", "2": "DRAIN"})
    d.add(
        "Q1",
        "Transistor_FET:2N7002",
        "MYVD",
        None,
        sch_at=(80 * g, 30 * g),
        nets={"1": "VIN", "2": "GND", "3": "DRAIN"},
    )
    d.add(
        "J1",
        "Connector_Generic:Conn_01x02",
        "IN",
        None,
        sch_at=(10 * g, 20 * g),
        nets={"1": "VIN", "2": "GND"},
    )
    return d


def declared() -> kicadgen.Design:
    """The circuit with every part's simulation said."""
    d = circuit()
    d.sim("R2", device="R", params="r=10k")
    d.sim("U1", library="models/test.lib", name="MIX", pins=MIX_PINS)
    d.sim("D1", library="models/test.lib", name="DX", pins={"1": "K", "2": "A"})
    d.sim("Q1", library="models/test.lib", name="MYVD", pins={"1": "G", "2": "S", "3": "D"})
    d.no_sim("J1", "a connector")
    d.sim_directives = [".param k_in=0.3"]
    d.check_sim = True
    return d


def project(tmp_path: Path, design: kicadgen.Design) -> Path:
    """The design's schematic and project in tmp_path, with the model library beside them."""
    (tmp_path / "models").mkdir(exist_ok=True)
    (tmp_path / "models" / "test.lib").write_text(LIBRARY, encoding="utf-8")
    (tmp_path / "simtest.kicad_sch").write_text(design.schematic(), encoding="utf-8")
    (tmp_path / "simtest.kicad_pro").write_text(design.project(), encoding="utf-8")
    return tmp_path / "simtest.kicad_sch"


def export(sch: Path) -> tuple[int, list[str]]:
    out = sch.with_suffix(".cir")
    proc = subprocess.run(
        ["kicad-cli", "sch", "export", "netlist", "--format", "spice", "--output", str(out), str(sch)],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, out.read_text(encoding="utf-8").splitlines() if out.is_file() else []


# ----------------------------------------------------------- pure logic


def test_a_plain_value_is_one_kicad_was_seen_to_read_as_a_number():
    """Each list is what `kicad-cli sch export netlist --format spice` did with the value of an R on
    KiCad 10.0.8: the first came out as numbers, the second as written or as a line with no nodes."""
    numbers = "10k 4k7 0R 1M 0.1 4R7 1k5 100 2.2K 0 100n 4.7uF 1u 10p 0.1uF 1n5 10uH 4u7 1e3 100nF 10mR"
    numbers += (
        " 4M7 4m7 4p7 2K2 1.5k 1R 0R1 47k5 1.2Meg 1meg 1G 4,7k 10kR 1.0 22pF 0.47 .47 47E3 1MEG 1T 100f 1e-6"
    )
    for value in [*numbers.split(), "10 k"]:
        assert kicadgen.PLAIN_VALUE_RE.fullmatch(value), value
    for value in ["10k 1%", "100nF/50V", "DNP", "10kΩ", "10K0", "R47", "10µ", "10k Ohm", "1µF", "5mm"]:
        assert not kicadgen.PLAIN_VALUE_RE.fullmatch(value), value
    for value in ["10kOhm", "10k5%", "~", "", "red"]:
        assert not kicadgen.PLAIN_VALUE_RE.fullmatch(value), value


def test_a_library_is_read_for_its_subcircuits_and_models():
    text = """* a comment
.SUBCKT Reg IN GND
+ EN OUT PARAMS: vref=1.2 ; the nodes end at params:
R1 IN OUT 1
.ends
.subckt Two a b gain=2
.ends
.model DX D(is=1e-14
+ n=1)
.MODEL Fet VDMOS (vto=1.5)  $ a comment in the line
"""
    assert kicadgen.spice_models(text) == {
        "reg": ("subckt", ["IN", "GND", "EN", "OUT"]),
        "two": ("subckt", ["a", "b"]),
        "dx": ("model", ["d"]),
        "fet": ("model", ["vdmos"]),
    }
    assert kicadgen.spice_models(LIBRARY)["mix"] == ("subckt", ["IN", "GND", "EN", "OUT"])


def test_a_librarys_includes_are_read_with_it(tmp_path):
    """KiCad finds a model that a library takes from another file; so does the check. A loop of
    includes ends, and a file that is not there adds nothing."""
    (tmp_path / "inner").mkdir()
    (tmp_path / "outer.lib").write_text(
        '* outer\n.include "inner/mix.lib"\n.lib inner/none.lib\n', encoding="utf-8"
    )
    (tmp_path / "inner" / "mix.lib").write_text(
        ".subckt MIX a b\n.ends\n.include ../outer.lib\n", encoding="utf-8"
    )
    text = kicadgen.spice_library_text(tmp_path / "outer.lib")
    assert kicadgen.spice_models(text) == {"mix": ("subckt", ["a", "b"])}
    assert kicadgen.spice_library_text(tmp_path / "none.lib") == ""


# ------------------------------------------------- what the design writes


def placed_symbols(sch: str) -> dict[str, dict[str, str]]:
    """Each symbol placed on the sheet, by reference: its Sim fields and whether it is left out of the
    simulation. The copies under lib_symbols are the library's own and are not looked at."""
    placed = {}
    for sym in kicadgen.children(kicadgen.parse(sch), "symbol"):
        props = {str(a[0]): str(a[1]) for a in map(kicadgen.atoms, kicadgen.children(sym, "property"))}
        fields = {name: text for name, text in props.items() if name.startswith("Sim.")}
        fields["exclude_from_sim"] = str(kicadgen.atoms(kicadgen.child(sym, "exclude_from_sim"))[0])
        placed[props["Reference"]] = fields
    return placed


@needs_libs
def test_a_design_that_says_nothing_about_simulation_writes_none_of_it():
    """Board repositories compare a regenerated schematic and project with the committed ones byte for
    byte (`workcenter design --check`), so nothing new is written unless the design asks for it.
    `tests/test_inspect.py` regenerates a whole fixture to its committed bytes."""
    d = circuit()
    sch, pro = d.schematic(), d.project()
    assert not d.simulates() and d.sim_problems() == []
    placed = placed_symbols(sch)
    assert set(placed) >= {p.ref for p in d.parts}
    assert all(fields == {"exclude_from_sim": "no"} for fields in placed.values())
    assert "(text " not in sch and "simulation_model_issue" not in pro
    # the library's own copy of a symbol keeps the Sim fields KiCad's library gives it, as before
    assert '(property "Sim.Device" "D"' in sch


@needs_libs
def test_the_fields_kicad_reads_are_written_on_each_symbol():
    d = declared()
    sch = d.schematic()
    placed = placed_symbols(sch)
    assert d.simulates()
    assert placed["U1"] == {
        "exclude_from_sim": "no",
        "Sim.Library": "models/test.lib",
        "Sim.Name": "MIX",
        "Sim.Pins": "1=IN 2=GND 3=EN 5=OUT",
    }
    # a 2-pin R, C or L declared without pins takes KiCad's names for a passive's ends
    assert placed["R2"] == {
        "exclude_from_sim": "no",
        "Sim.Device": "R",
        "Sim.Params": "r=10k",
        "Sim.Pins": "1=+ 2=-",
    }
    assert placed["Q1"]["Sim.Pins"] == "1=G 2=S 3=D" and placed["D1"]["Sim.Name"] == "DX"
    assert placed["R1"] == {"exclude_from_sim": "no"}
    assert placed["J1"] == {"exclude_from_sim": "yes"}
    assert [ref for ref, fields in placed.items() if fields["exclude_from_sim"] == "yes"] == ["J1"]
    assert '(text ".param k_in=0.3"' in sch
    severities = json.loads(d.project())["erc"]["rule_severities"]
    assert severities["simulation_model_issue"] == "error"


def on_a_board() -> kicadgen.Design:
    """The mixer and a resistor with footprints, the mixer bound to its model, the resistor saying
    nothing about simulation."""
    d = kicadgen.Design(name="simtest", namespace=uuid.UUID("11111111-2222-3333-4444-55555555555a"))
    d.power_nets = {"GND": "GND"}
    d.flagged_nets = ["GND"]
    g = 2.54
    d.add("U1", "Regulator_Linear:AP2112K-3.3", "MIX", "Package_TO_SOT_SMD:SOT-23-5", sch_at=(40 * g, 20 * g),
          pcb_at=(108.0, 110.0), nets={"1": "VIN", "2": "GND", "3": "MID", "5": "OUT"})  # fmt: skip
    d.add("R1", "Device:R", "10k", "Resistor_SMD:R_0603_1608Metric", sch_at=(20 * g, 20 * g),
          pcb_at=(116.0, 110.0), nets={"1": "VIN", "2": "MID"})  # fmt: skip
    d.sim("U1", library="models/test.lib", name="MIX", pins=MIX_PINS)
    return d


def footprint_fields(pcb: str) -> dict[str, dict[str, tuple[str, bool]]]:
    """Each footprint's Sim properties, by reference: the text and whether it is hidden."""
    placed = {}
    for fp in kicadgen.children(kicadgen.parse(pcb), "footprint"):
        props = kicadgen.children(fp, "property")
        ref = next(str(kicadgen.atoms(p)[1]) for p in props if str(kicadgen.atoms(p)[0]) == "Reference")
        placed[ref] = {
            str(kicadgen.atoms(p)[0]): (str(kicadgen.atoms(p)[1]), kicadgen.child(p, "hide") is not None)
            for p in props
            if str(kicadgen.atoms(p)[0]).startswith("Sim.")
        }
    return placed


@needs_libs
def test_a_footprint_carries_its_symbols_sim_fields_hidden():
    """KiCad's own update from the schematic copies every symbol field onto the footprint; a footprint
    without the Sim fields is a parity warning in the DRC ("Missing symbol field 'Sim.Library'"). A
    part that says nothing about simulation gets none, so a board that simulates nothing is written as
    before."""
    placed = footprint_fields(on_a_board().board())
    assert placed["U1"] == {
        "Sim.Library": ("models/test.lib", True),
        "Sim.Name": ("MIX", True),
        "Sim.Pins": ("1=IN 2=GND 3=EN 5=OUT", True),
    }
    assert placed["R1"] == {}


@needs_libs
@needs_kicad
def test_a_board_with_a_bound_part_has_no_parity_warning(tmp_path):
    d = on_a_board()
    project(tmp_path, d)
    (tmp_path / "simtest.kicad_pcb").write_text(d.board(), encoding="utf-8")
    report = tmp_path / "drc.json"
    subprocess.run(
        ["kicad-cli", "pcb", "drc", "--schematic-parity", "--format", "json", "--output", str(report),
         str(tmp_path / "simtest.kicad_pcb")],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    parity = json.loads(report.read_text(encoding="utf-8"))["schematic_parity"]
    assert [v["description"] for v in parity if v["type"] == "footprint_symbol_field_mismatch"] == []


@needs_libs
def test_pin_numbers_given_as_numbers_are_taken_as_text():
    d = circuit()
    d.sim("D1", library="models/test.lib", name="DX", pins={1: "K", 2: "A"})
    assert d.sims["D1"]["pins"] == {"1": "K", "2": "A"} and d.sim_problems() == []
    assert placed_symbols(d.schematic())["D1"]["Sim.Pins"] == "1=K 2=A"


@needs_libs
def test_a_part_that_is_not_in_the_design_is_refused_at_once():
    d = circuit()
    with pytest.raises(KeyError, match="X9: no such part"):
        d.sim("X9", device="R", params="r=1")
    with pytest.raises(KeyError, match="X9: no such part"):
        d.no_sim("X9", "nothing")


# ------------------------------------------------------------ the check


def problems(tmp_path: Path, act) -> list[str]:
    (tmp_path / "models").mkdir(exist_ok=True)
    (tmp_path / "models" / "test.lib").write_text(LIBRARY, encoding="utf-8")
    d = circuit()
    act(d)
    return d.sim_problems(tmp_path)


@needs_libs
def test_a_whole_design_has_no_problem_and_the_files_are_read_only_with_a_folder(tmp_path):
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "test.lib").write_text(LIBRARY, encoding="utf-8")
    d = declared()
    assert d.sim_problems(tmp_path) == []
    assert d.sim_problems() == []
    d.sim("D1", library="models/none.lib", name="DX", pins={"1": "K", "2": "A"})
    assert d.sim_problems() == []  # no folder given, no file looked for
    assert d.sim_problems(tmp_path) == [f"D1: library models/none.lib is not a file in {tmp_path}"]


@needs_libs
def test_a_map_that_leaves_a_node_or_a_pin_out_is_refused(tmp_path):
    """The trap: KiCad binds the node a map leaves out by position, with exit code 0."""
    got = problems(
        tmp_path,
        lambda d: d.sim(
            "U1", library="models/test.lib", name="MIX", pins={"1": "IN", "2": "GND", "5": "OUT"}
        ),
    )
    assert got == [
        "U1: pins leaves out 3, 4: map each to a node of the model, or to None for a pin the model has "
        "no node for",
        "U1: no pin maps to EN of .subckt MIX: KiCad would bind it by position",
    ]
    got = problems(tmp_path, lambda d: d.sim("U1", library="models/test.lib", name="MIX"))
    assert got == [
        "U1: no pins: KiCad would bind the symbol's pins by position; map each of 1, 2, 3, 4, 5 to a "
        "node of the model, or to None"
    ]


@needs_libs
def test_each_way_a_binding_is_wrong_has_its_line(tmp_path):
    lib = {"library": "models/test.lib"}
    cases = [
        (
            lambda d: d.sim("U1", **lib, name="MIX", pins={**MIX_PINS, "1": "VIN"}),
            [
                "U1: pins names VIN, no node of .subckt MIX: its nodes are IN, GND, EN, OUT",
                "U1: no pin maps to IN of .subckt MIX: KiCad would bind it by position",
            ],
        ),
        (
            lambda d: d.sim("U1", **lib, name="MIX", pins={**MIX_PINS, "4": "IN"}),
            ["U1: pins maps 2 pins to IN: KiCad takes 1 pin for a node; map the others to None"],
        ),
        (
            lambda d: d.sim("D1", **lib, name="DY", pins={"1": "K", "2": "A"}),
            ["D1: models/test.lib holds no .subckt or .model named DY"],
        ),
        (
            lambda d: d.sim("D1", name="DX", pins={"1": "K", "2": "A"}),
            ["D1: name DX without the library that holds it"],
        ),
        (
            lambda d: d.sim("D1", **lib, pins={"1": "K", "2": "A"}),
            ["D1: library models/test.lib without the name of a .subckt or .model in it"],
        ),
        (lambda d: d.sim("D1", pins={"1": "K", "2": "A"}), ["D1: neither a library nor a device"]),
        (
            lambda d: (
                d.no_sim("J1", " "),
                d.no_sim("D1", "x"),
                d.sim("D1", device="D", pins={"1": "K", "2": "A"}),
            ),
            ["D1: both sim() and no_sim(): keep one", "J1: no_sim without a reason"],
        ),
    ]
    for act, want in cases:
        assert problems(tmp_path, act) == want
    got = problems(tmp_path, lambda d: d.sim("U1", **lib, name="MIX", pins={**MIX_PINS, "6": None}))
    assert got == ["U1: pins names 6, which Regulator_Linear:AP2112K-3.3 does not have"]


@needs_libs
def test_a_mosfet_model_with_4_terminals_on_a_3_pin_part_is_refused(tmp_path):
    """KiCad writes `MQ1 /DRAIN /VIN GND NC-Q1-0 M4` for it: a bulk on a node of its own."""
    got = problems(
        tmp_path,
        lambda d: d.sim("Q1", library="models/test.lib", name="M4", pins={"1": "G", "2": "S", "3": "D"}),
    )
    assert len(got) == 1 and got[0].startswith(
        "Q1: no pin maps to B of .model M4 (nmos): KiCad writes a node"
    )
    got = problems(
        tmp_path,
        lambda d: d.sim("D1", library="models/test.lib", name="DX", pins={"1": "C", "2": "A"}),
    )
    assert got[0] == "D1: pins names C, no node of .model DX (d): its nodes are A, K"


@needs_libs
def test_check_sim_asks_for_every_part_but_a_passive_kicad_reads(tmp_path):
    def act(d):
        d.add("LED1", "Device:LED", "0603", None, sch_at=(25.4, 101.6), nets={"1": "GND", "2": "DA"})
        d.check_sim = True

    got = problems(tmp_path, act)
    # R1, R3 and R4 are 2-pin parts named R with a value KiCad reads. LED1 starts with L, and KiCad
    # would write it as an inductor of 603 H: only a reference of R, C or L and digits is excused.
    assert [line.split(":")[0] for line in got] == ["R2", "U1", "D1", "Q1", "J1", "LED1"]
    assert got[0] == (
        "R2: KiCad does not read the value '10k 1%' as a number: give the part a sim() with its value "
        '(device="R", params="r=..."), or a no_sim() with the reason'
    )
    assert got[1] == (
        "U1: neither sim() nor no_sim(): say how the part simulates, or leave it out with the reason"
    )
    assert problems(tmp_path, lambda d: None) == []


# -------------------------------------------------- KiCad and ngspice


@needs_libs
@needs_kicad
def test_kicad_writes_the_netlist_the_design_declares(tmp_path):
    code, lines = export(project(tmp_path, declared()))
    assert code == 0
    assert lines[1] == f'.include "{tmp_path}/models/test.lib"'
    assert lines[2] == ".param k_in=0.3"
    assert sorted(lines[3:-1]) == [
        "D1 /DA GND DX",
        "MQ1 /DRAIN /VIN GND MYVD",
        "R1 /VIN /MID 10k",
        "R2 /MID GND 10k",
        "R3 /VIN /DA 1k",
        "R4 /VIN /DRAIN 1k",
        "XU1 /VIN GND /MID /OUT MIX",
    ]


@needs_libs
@needs_kicad
def test_kicad_finds_a_model_through_a_librarys_include_as_the_check_does(tmp_path):
    d = declared()
    d.sims["U1"]["library"] = "models/outer.lib"
    sch = project(tmp_path, d)
    (tmp_path / "models" / "inner").mkdir()
    (tmp_path / "models" / "outer.lib").write_text('* outer\n.include "inner/mix.lib"\n', encoding="utf-8")
    mix = LIBRARY[LIBRARY.index(".subckt MIX") : LIBRARY.index(".model DX")]
    (tmp_path / "models" / "inner" / "mix.lib").write_text(mix, encoding="utf-8")
    assert d.sim_problems(tmp_path) == []
    code, lines = export(sch)
    assert code == 0 and "XU1 /VIN GND /MID /OUT MIX" in lines
    assert f'.include "{tmp_path}/models/outer.lib"' in lines


@needs_libs
@needs_kicad
def test_without_the_declarations_kicad_writes_lines_ngspice_cannot_read(tmp_path):
    code, lines = export(project(tmp_path, circuit()))
    assert code == 0
    assert {"U1 __U1", "D1 __D1", "Q1 __Q1", "J1 __J1", "R2 /MID GND 10k 1%"} <= set(lines)


@needs_libs
@needs_kicad
def test_a_map_that_is_not_whole_is_bound_by_position_and_kicad_says_nothing(tmp_path):
    """Why sim_problems() refuses it. The map leaves out the model's EN node, with pins 1 and 2 swapped
    on purpose: KiCad still writes a 4-node line with exit code 0, EN taken from pin 3."""
    d = declared()
    d.sims["U1"]["pins"] = {"1": "GND", "2": "IN", "5": "OUT"}
    sch = project(tmp_path, d)
    assert "U1: no pin maps to EN of .subckt MIX: KiCad would bind it by position" in d.sim_problems(tmp_path)
    code, lines = export(sch)
    assert code == 0
    assert "XU1 GND /VIN /MID /OUT MIX" in lines


@needs_libs
@needs_kicad
@needs_ngspice
def test_the_exported_netlist_runs_and_gives_the_values_computed_by_hand(tmp_path):
    """5 V on VIN. The divider's middle is 2.5 V. The mixer gives 0.3 x 5 + 0.1 x 2.5 = 1.75 V, which
    it gives only when IN, EN and OUT are the pins the map names. The diode's 0.692888 V is the root of
    v = Vt ln((5 - v) / 1k / Is + 1) with Vt = k 300.15 K / q and Is = 1e-14 A; reversed it would sit
    at 5 V. The MOSFET is on, its drain within millivolts of ground; bound by position it would be off."""
    code, lines = export(project(tmp_path, declared()))
    assert code == 0 and lines[-1] == ".end"
    control = [
        "V1 /VIN GND DC 5",
        ".control",
        "op",
        'let vmid = v("/mid")',
        'let vout = v("/out")',
        'let vda = v("/da")',
        'let vdrain = v("/drain")',
        "print vmid vout vda vdrain",
        ".endc",
        ".end",
    ]
    (tmp_path / "run.cir").write_text("\n".join(lines[:-1] + control) + "\n", encoding="utf-8")
    proc = subprocess.run(
        ["ngspice", "-b", "run.cir"], cwd=tmp_path, capture_output=True, text=True, check=False
    )
    got = {m[0]: float(m[1]) for m in re.findall(r"^(v\w+) = (\S+)$", proc.stdout, re.M)}
    assert proc.returncode == 0 and set(got) == {"vmid", "vout", "vda", "vdrain"}, proc.stdout + proc.stderr
    vt = 8.617333262e-5 * 300.15
    vda = 0.69
    for _ in range(50):
        vda = vt * math.log((5 - vda) / 1e3 / 1e-14 + 1)
    assert got["vmid"] == pytest.approx(2.5, abs=1e-6)
    assert got["vout"] == pytest.approx(1.75, abs=1e-6)
    assert round(vda, 6) == 0.692888 and got["vda"] == pytest.approx(vda, abs=1e-5)
    assert 0 < got["vdrain"] < 0.01


@needs_libs
@needs_kicad
def test_the_erc_reports_a_binding_kicad_cannot_load(tmp_path):
    """The project raises `simulation_model_issue` to an error, so the ERC gate fails on a library that
    is not there; left at KiCad's default the same schematic reports nothing."""
    d = declared()
    d.sims["D1"]["library"] = "models/none.lib"
    sch = project(tmp_path, d)

    def issues() -> list[str]:
        report = tmp_path / "erc.json"
        subprocess.run(
            [
                "kicad-cli",
                "sch",
                "erc",
                "--format",
                "json",
                "--severity-all",
                "--output",
                str(report),
                str(sch),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        sheets = json.loads(report.read_text(encoding="utf-8"))["sheets"]
        return [
            f"{v['severity']} {v['items'][0]['description']}"
            for sheet in sheets
            for v in sheet["violations"]
            if v["type"] == "simulation_model_issue"
        ]

    assert issues() == ["error Symbol D1 [D]"]
    pro = json.loads((tmp_path / "simtest.kicad_pro").read_text(encoding="utf-8"))
    del pro["erc"]["rule_severities"]["simulation_model_issue"]
    (tmp_path / "simtest.kicad_pro").write_text(json.dumps(pro), encoding="utf-8")
    assert issues() == []


# ------------------------------------------------------ workcenter design


DESIGN = """
import sys
sys.path.insert(0, {tools!r})
sys.path.insert(0, {tests!r})
from test_simfields import declared

def build():
    d = declared()
    d.outline = (100.0, 100.0, 110.0, 110.0)
    PINS
    return d
"""


@needs_libs
def test_design_prints_each_problem_as_a_sim_line_and_exits_1(tmp_path):
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "test.lib").write_text(LIBRARY, encoding="utf-8")
    src = tmp_path / "design.py"
    body = DESIGN.format(tools=str(ROOT / "tools"), tests=str(Path(__file__).resolve().parent))
    cases = (
        ("pass", 0, ""),
        ('d.sims["U1"]["pins"] = {"1": "IN", "2": "GND", "4": None, "5": "OUT"}', 1, "3"),
    )
    for edit, want, left_out in cases:
        src.write_text(body.replace("PINS", edit), encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(CLI), "design", str(src)], capture_output=True, text=True, check=False
        )
        assert r.returncode == want, r.stdout + r.stderr
        assert ("  sim: " in r.stdout) == bool(want)
        if want:
            assert f"  sim: U1: pins leaves out {left_out}: map each to a node of the model" in r.stdout
            assert "  sim: U1: no pin maps to EN of .subckt MIX: KiCad would bind it by position" in r.stdout
            assert "design simtest red: 2 simulation problem(s)." in r.stdout
        assert (tmp_path / "simtest.kicad_sch").is_file()
