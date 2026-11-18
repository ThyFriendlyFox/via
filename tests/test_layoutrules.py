"""Layout rule packs: ESD protection at each connector (TI SLVA680A) and the 3:1 rule for power and ground
traces (TI SZZA009), judged from the board file (tools/layoutrules.py).

Every board here is drawn in the test, so each expected value is a sum shown in the docstring."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import boardrules  # noqa: E402
import layoutrules  # noqa: E402
from boardrules import Board, Pad, Track, Via, Zone  # noqa: E402
from ratings import Refusal  # noqa: E402

CITES = {
    "ti-slva680a": "section 1 and figure 1-2; section 2.1; section 2.3",
    "ti-szza009": "section 2.1.1",
}

ESD = layoutrules.read_pack(ROOT / "rules" / "board" / "ti-slva680a-esd.json")
EMI = layoutrules.read_pack(ROOT / "rules" / "board" / "ti-szza009-emi.json")
BOTH = ["F.Cu", "B.Cu"]


def board(copper: list[str] | None = None) -> Board:
    copper = copper or BOTH
    return Board(1.6, copper, dict.fromkeys(copper, 35.0), True, 400.0, "")


def esd_board(r1_at: tuple[float, float] = (10.0, 0.0)) -> Board:
    """J1 pin 1 (a through-hole pad) at (0, 0) on net A, D1 pin 1 at (2, 0), R1 pin 1 at `r1_at`; a 0.5 mm
    track on F.Cu from J1.1 through D1.1 to R1.1. D1 pin 2 is on GND, J1 pin 2 on GND."""
    b = board()
    b.pads += [
        Pad("J1", "1", "A", (0.0, 0.0), 0.85, BOTH),
        Pad("J1", "2", "GND", (0.0, 2.54), 0.85, BOTH),
        Pad("D1", "1", "A", (2.0, 0.0), 0.3, ["F.Cu"]),
        Pad("D1", "2", "GND", (4.0, 0.0), 0.3, ["F.Cu"]),
        Pad("R1", "1", "A", r1_at, 0.5, ["F.Cu"]),
        Pad("R1", "2", "GND", (r1_at[0] + 2, r1_at[1]), 0.5, ["F.Cu"]),
    ]
    b.tracks += [Track("A", "F.Cu", 0.5, (0.0, 0.0), (2.0, 0.0)), Track("A", "F.Cu", 0.5, (2.0, 0.0), r1_at)]
    b.nets = {"A", "GND"}
    return b


STATED = {"connectors": {"J1": "a cable to the user"}, "protectors": {"D1": "a TVS"}, "ground": ["GND"]}


def lines(findings) -> list[str]:
    return [f.line for f in findings]


def test_packs_name_their_document_and_pages():
    """Each rule of each pack names its page; the packs read back as 3 and 1 rules."""
    assert [r["id"] for r in ESD.rules] == ["protector", "nearest", "no-via"]
    assert [r["id"] for r in EMI.rules] == ["power-ratio"]
    assert ESD.document["number"] == "SLVA680A" and EMI.document["number"] == "SZZA009"


def test_esd_held():
    """D1.1 stands 2 mm from J1.1 and R1.1 stands 10 - 2 = 8 mm from D1.1: further, so nothing fails;
    J1.1 and D1.1 are 1 piece of F.Cu."""
    assert layoutrules.findings(esd_board(), ESD, STATED) == []


def test_esd_no_protector():
    """No protector named on net A: 1 fail, the rule `protector`, with its page."""
    out = lines(layoutrules.findings(esd_board(), ESD, {**STATED, "protectors": {}}))
    assert out == [
        "fail esd J1.1 A: no protector on the net [SLVA680A: section 1 and figure 1-2, page 2: ESD enters "
        "through a cable connection, and a TVS between the ESD source and the protected IC shunts it to "
        "ground]"
    ]


def test_esd_protected_part_nearer_than_the_connector():
    """R1.1 at (3, 1) stands sqrt(1 + 1) = 1.414 mm from D1.1, and D1.1 stands 2 mm from J1.1: 1.41 <= 2,
    1 fail of rule `nearest`."""
    out = lines(layoutrules.findings(esd_board((3.0, 1.0)), ESD, STATED))
    assert len(out) == 1
    assert out[0].startswith(
        "fail esd J1.1 A: R1.1 stands 1.41 mm from D1.1, and D1.1 stands 2 mm from J1.1 "
        "[SLVA680A: section 2.1"
    )


def test_esd_via_between_connector_and_protector():
    """The F.Cu track from J1.1 to D1.1 is replaced: B.Cu from J1.1 to a via at (1, 1), F.Cu from the via
    to D1.1. On F.Cu the track from (1, 1) to (2, 0) stands sqrt(2) = 1.414 mm from J1.1's centre, more
    than 0.25 + 0.85 = 1.1 mm: J1.1 and D1.1 meet only through the via. 1 fail of rule `no-via`."""
    b = esd_board()
    b.tracks = [
        Track("A", "B.Cu", 0.5, (0.0, 0.0), (1.0, 1.0)),
        Track("A", "F.Cu", 0.5, (1.0, 1.0), (2.0, 0.0)),
        Track("A", "F.Cu", 0.5, (2.0, 0.0), (10.0, 0.0)),
    ]
    b.vias.append(Via("A", (1.0, 1.0), 0.6, 0.3, BOTH))
    out = lines(layoutrules.findings(b, ESD, STATED))
    assert len(out) == 1
    assert out[0].startswith("fail esd J1.1 A: joined to D1.1 through a via [SLVA680A: section 2.1, page 4")


def test_esd_not_joined_is_not_judged():
    """With no copper on net A, J1.1 and D1.1 meet nowhere: the via rule is not judged, and says why."""
    b = esd_board()
    b.tracks = []
    assert lines(layoutrules.findings(b, ESD, STATED)) == [
        "not judged esd J1.1 A: no copper joins it to D1.1, so the path to the protector is not judged"
    ]


def test_esd_connector_not_stated_is_not_judged():
    """J2 is on the board and neither in `connectors` nor in `inside`."""
    b = esd_board()
    b.pads.append(Pad("J2", "1", "A", (20.0, 0.0), 0.85, BOTH))
    assert lines(layoutrules.findings(b, ESD, STATED)) == [
        "not judged esd J2: board-rules.json does not say whether it leaves the device "
        "(`connectors` or `inside`)"
    ]
    assert layoutrules.findings(b, ESD, {**STATED, "inside": ["J2"]}) == []


def test_esd_refuses_a_part_not_on_the_board():
    with pytest.raises(Refusal, match="connectors: J9 is not on the board"):
        layoutrules.findings(esd_board(), ESD, {**STATED, "connectors": {"J9": "a cable"}})


def test_esd_protector_with_no_pad_on_ground():
    """D1 is named a protector and both its pads stand on net A: it shunts nothing to ground (SLVA680A
    section 1, figure 1-2, page 2). 1 fail of rule `protector`."""
    b = esd_board()
    b.pads[3] = Pad("D1", "2", "A", (4.0, 0.0), 0.3, ["F.Cu"])
    assert [line.split(" [")[0] for line in lines(layoutrules.findings(b, ESD, STATED))] == [
        "fail esd J1.1 A: D1 stands on the net and has no pad on ground (GND)"
    ]


def test_esd_copper_reaches_the_protected_part_first():
    """The track runs J1.1 (0, 0) to (0, 3), to R1.1 at (6, 3), down to (6, 1), back to (2, 1) and down to
    D1.1 (2, 0). By centres D1.1 stands 2 mm from J1.1 and R1.1 sqrt(16 + 9) = 5 mm from D1.1, which
    passes; along the copper the line meets R1.1 before D1.1. 1 fail of rule `nearest`."""
    b = esd_board((6.0, 3.0))
    b.tracks = [
        Track("A", "F.Cu", 0.25, (0.0, 0.0), (0.0, 3.0)),
        Track("A", "F.Cu", 0.25, (0.0, 3.0), (6.0, 3.0)),
        Track("A", "F.Cu", 0.25, (6.0, 3.0), (6.0, 1.0)),
        Track("A", "F.Cu", 0.25, (6.0, 1.0), (2.0, 1.0)),
        Track("A", "F.Cu", 0.25, (2.0, 1.0), (2.0, 0.0)),
    ]
    assert [line.split(" [")[0] for line in lines(layoutrules.findings(b, ESD, STATED))] == [
        "fail esd J1.1 A: the copper from J1.1 reaches R1.1 before D1.1"
    ]


def test_esd_protected_part_nearer_along_the_copper():
    """J1.1 to D1.1 goes round: (0, 0) to (0, -5) to (2, -5) to (2, 0), 5 + 2 + 5 = 12 mm. D1.1 to R1.1
    at (10, 0) is 8 mm straight. By centres 8 > 2 passes; along the copper 8 <= 12: 1 fail of `nearest`."""
    b = esd_board()
    b.tracks = [
        Track("A", "F.Cu", 0.25, (0.0, 0.0), (0.0, -5.0)),
        Track("A", "F.Cu", 0.25, (0.0, -5.0), (2.0, -5.0)),
        Track("A", "F.Cu", 0.25, (2.0, -5.0), (2.0, 0.0)),
        Track("A", "F.Cu", 0.25, (2.0, 0.0), (10.0, 0.0)),
    ]
    assert [line.split(" [")[0] for line in lines(layoutrules.findings(b, ESD, STATED))] == [
        "fail esd J1.1 A: R1.1 lies 8 mm of copper from D1.1, and D1.1 lies 12 mm of copper from J1.1"
    ]


def tee_board(tracks: list[Track], u1_at: tuple[float, float]) -> Board:
    """J1.1 at (0, 0), D1.1 at (3, 0) with D1.2 on GND at (4.5, 0), U1.1 (the part D1 protects) at
    `u1_at`, all on net A, joined by `tracks`."""
    b = board()
    b.pads += [
        Pad("J1", "1", "A", (0.0, 0.0), 0.85, BOTH),
        Pad("J1", "2", "GND", (0.0, 2.54), 0.85, BOTH),
        Pad("D1", "1", "A", (3.0, 0.0), 0.3, ["F.Cu"]),
        Pad("D1", "2", "GND", (4.5, 0.0), 0.3, ["F.Cu"]),
        Pad("U1", "1", "A", u1_at, 0.3, ["F.Cu"]),
        Pad("U1", "4", "GND", (5.0, -5.0), 0.3, ["F.Cu"]),
    ]
    b.tracks += tracks
    b.nets = {"A", "GND"}
    return b


def test_esd_protected_part_nearer_the_connector_than_the_protector():
    """A T at J1.1: D1.1 3 mm across, U1.1 2.5 mm down. From the protector's side all holds: U1.1 stands
    sqrt(3^2 + 2.5^2) = 3.91 mm from D1.1 (> 3), and lies 3 + 2.5 = 5.5 mm of copper from it (> 3). But U1.1
    stands 2.5 mm from J1.1, nearer than D1.1 at 3 mm (SLVA680A section 2.3, Case 2, page 6)."""
    b = tee_board(
        [Track("A", "F.Cu", 0.25, (0.0, 0.0), (3.0, 0.0)), Track("A", "F.Cu", 0.25, (0.0, 0.0), (0.0, -2.5))],
        (0.0, -2.5),
    )
    assert [line.split(" [")[0] for line in lines(layoutrules.findings(b, ESD, STATED))] == [
        "fail esd J1.1 A: U1.1 stands 2.5 mm from J1.1, and D1.1 stands 3 mm from J1.1"
    ]


def test_esd_protected_part_nearer_the_connector_along_the_copper():
    """D1.1 at (3, 0) is reached round (0, 4) and (3, 4): 4 + 3 + 4 = 11 mm of copper. U1.1 at (-4, 0) is
    4 mm of copper from J1.1, straight, and stands 4 mm from it (> 3), 7 mm from D1.1 (> 3), and 11 + 4 =
    15 mm of copper from D1.1 (> 11). Along the copper the connector reaches U1.1 first: 4 <= 11."""
    b = tee_board(
        [
            Track("A", "F.Cu", 0.25, (0.0, 0.0), (0.0, 4.0)),
            Track("A", "F.Cu", 0.25, (0.0, 4.0), (3.0, 4.0)),
            Track("A", "F.Cu", 0.25, (3.0, 4.0), (3.0, 0.0)),
            Track("A", "F.Cu", 0.25, (0.0, 0.0), (-4.0, 0.0)),
        ],
        (-4.0, 0.0),
    )
    assert [line.split(" [")[0] for line in lines(layoutrules.findings(b, ESD, STATED))] == [
        "fail esd J1.1 A: U1.1 lies 4 mm of copper from J1.1, and D1.1 lies 11 mm of copper from J1.1"
    ]


def test_esd_part_at_the_same_distance_fails():
    """R1.1 at (2, 2) stands sqrt(0 + 4) = 2 mm from D1.1, the same as D1.1 from J1.1: not further."""
    out = lines(layoutrules.findings(esd_board((2.0, 2.0)), ESD, STATED))
    assert [line.split(" [")[0] for line in out] == [
        "fail esd J1.1 A: R1.1 stands 2 mm from D1.1, and D1.1 stands 2 mm from J1.1"
    ]


def test_esd_unconnected_connector_pin_is_not_failed():
    """J1 pin 3 has KiCad's net for a pin left open: no line of the connector, no fail."""
    b = esd_board()
    b.pads.append(Pad("J1", "3", "unconnected-(J1-Pad3)", (0.0, 5.08), 0.85, BOTH))
    assert layoutrules.findings(b, ESD, STATED) == []


def test_esd_connector_found_by_its_footprint():
    """CN1's reference is not J or P and digits; its footprint is in KiCad's Connector_USB library."""
    b = esd_board()
    b.pads.append(Pad("CN1", "1", "A", (20.0, 0.0), 0.85, BOTH, "Connector_USB:USB_C_Receptacle_GCT_USB4105"))
    assert lines(layoutrules.findings(b, ESD, STATED)) == [
        "not judged esd CN1: board-rules.json does not say whether it leaves the device "
        "(`connectors` or `inside`)"
    ]


@pytest.mark.parametrize(
    ("ref", "footprint"),
    [
        ("X1", "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2_1x02_P5.00mm_Horizontal"),
        ("TB1", "TerminalBlock:TerminalBlock_MaiXu_MX126-5.0-02P_1x02_P5.00mm"),
        ("BT1", "Battery:BatteryHolder_Keystone_3034_1x20mm"),
        ("X2", "MyProject:USB_C"),
    ],
)
def test_esd_connector_found_by_terminal_block_battery_library_or_letter_x(ref, footprint):
    """KiCad's TerminalBlock libraries and its Battery library hold parts a cable or a cell is fixed to, and
    X is a letter schematics give a connector: each is a connector, and one not stated is not judged. A
    crystal named X1 is then not judged too, until board-rules.json names it under `inside`."""
    b = esd_board()
    b.pads.append(Pad(ref, "1", "A", (20.0, 0.0), 0.85, BOTH, footprint))
    assert lines(layoutrules.findings(b, ESD, STATED)) == [
        f"not judged esd {ref}: board-rules.json does not say whether it leaves the device "
        "(`connectors` or `inside`)"
    ]


def test_esd_no_connector_named_is_not_judged():
    """`connectors` is empty: no line of the pack is judged, and the run says so."""
    out = lines(layoutrules.findings(esd_board(), ESD, {**STATED, "connectors": {}, "inside": ["J1"]}))
    assert out == ["not judged esd: board-rules.json names no part under `connectors`, so no line is judged"]


def power_board(width: float, copper: list[str] | None = None, mid_pad: bool = False) -> Board:
    """VBUS from P1 at (0, 0) to P2 at (4, 0) in 2 segments of `width` meeting at (2, 0)."""
    b = board(copper)
    b.pads += [
        Pad("P1", "1", "VBUS", (0.0, 0.0), 0.5, ["F.Cu"]),
        Pad("P2", "1", "VBUS", (4.0, 0.0), 0.5, ["F.Cu"]),
    ]
    if mid_pad:
        b.pads.append(Pad("C1", "1", "VBUS", (2.0, 0.0), 0.5, ["F.Cu"]))
    b.tracks += [
        Track("VBUS", "F.Cu", width, (0.0, 0.0), (2.0, 0.0)),
        Track("VBUS", "F.Cu", width, (2.0, 0.0), (4.0, 0.0)),
    ]
    b.nets = {"VBUS", "GND"}
    return b


POWER = {"power": ["VBUS"], "ground": ["GND"]}


def test_power_ratio_fails_over_3_to_1():
    """1 run of 2 + 2 = 4 mm at 1 mm wide: 4 to 1, over 3 to 1."""
    out = lines(layoutrules.findings(power_board(1.0), EMI, POWER))
    assert len(out) == 1
    assert out[0].startswith(
        "fail length to width VBUS on F.Cu from P1.1 (0, 0) to P2.1 (4, 0): 4 mm by 1 mm, 4 to 1, "
        "limit 3 to 1 [SZZA009: section 2.1.1, page 4"
    )


def test_power_ratio_held():
    """1.5 mm wide: 4 / 1.5 = 2.67 to 1. A pad at (2, 0) splits the run: 2 / 1 = 2 to 1 each."""
    assert layoutrules.findings(power_board(1.5), EMI, POWER) == []
    assert layoutrules.findings(power_board(1.0, mid_pad=True), EMI, POWER) == []


def test_power_ratio_takes_the_narrowest_width():
    """2 mm at 1 mm wide, then 2 mm at 2 mm wide: 4 mm by its narrowest 1 mm, 4 to 1."""
    b = power_board(1.0)
    b.tracks[1].width = 2.0
    out = lines(layoutrules.findings(b, EMI, POWER))
    assert [line.split(" [")[0] for line in out] == [
        "fail length to width VBUS on F.Cu from P1.1 (0, 0) to P2.1 (4, 0): 4 mm by 1 mm, 4 to 1, "
        "limit 3 to 1"
    ]


def six_mm(width: float) -> Board:
    """U1.1 at (0, 0) and C1.1 at (6, 0) on VBUS, F.Cu, by 2 segments of `width` meeting at (3, 0)."""
    b = board()
    b.pads += [
        Pad("U1", "1", "VBUS", (0.0, 0.0), 0.3, ["F.Cu"]),
        Pad("C1", "1", "VBUS", (6.0, 0.0), 0.3, ["F.Cu"]),
    ]
    b.tracks += [
        Track("VBUS", "F.Cu", width, (0.0, 0.0), (3.0, 0.0)),
        Track("VBUS", "F.Cu", width, (3.0, 0.0), (6.0, 0.0)),
    ]
    b.nets = {"VBUS", "GND"}
    return b


def test_power_ratio_runs_through_a_via():
    """A via at (3, 0) is no end of the trace: 6 mm by 1 mm, 6 to 1."""
    b = six_mm(1.0)
    b.vias.append(Via("VBUS", (3.0, 0.0), 0.6, 0.3, BOTH))
    assert [line.split(" [")[0] for line in lines(layoutrules.findings(b, EMI, POWER))] == [
        "fail length to width VBUS on F.Cu from C1.1 (6, 0) to U1.1 (0, 0): 6 mm by 1 mm, 6 to 1, "
        "limit 3 to 1"
    ]


def test_power_ratio_runs_across_layers():
    """F.Cu from U1.1 to a via at (3, 0), B.Cu from the via to C1.1 (on B.Cu): 3 + 3 = 6 mm by 1 mm."""
    b = six_mm(1.0)
    b.pads[1] = Pad("C1", "1", "VBUS", (6.0, 0.0), 0.3, ["B.Cu"])
    b.tracks[1].layer = "B.Cu"
    b.vias.append(Via("VBUS", (3.0, 0.0), 0.6, 0.3, BOTH))
    assert [line.split(" [")[0] for line in lines(layoutrules.findings(b, EMI, POWER))] == [
        "fail length to width VBUS on B.Cu and F.Cu from C1.1 (6, 0) to U1.1 (0, 0): 6 mm by 1 mm, 6 to 1, "
        "limit 3 to 1"
    ]


def test_power_ratio_through_overlaps_and_stubs():
    """6 mm by 1.9 mm is 6 / 1.9 = 3.16 to 1. A copy of the first half laid over it, or a 0.05 mm stub at
    (3, 0) inside its copper, adds no metal and ends no trace."""
    want = [
        "fail length to width VBUS on F.Cu from C1.1 (6, 0) to U1.1 (0, 0): 6 mm by 1.9 mm, 3.16 to 1, "
        "limit 3 to 1"
    ]
    over = six_mm(1.9)
    over.tracks.append(Track("VBUS", "F.Cu", 1.9, (0.0, 0.0), (3.0, 0.0)))
    assert [line.split(" [")[0] for line in lines(layoutrules.findings(over, EMI, POWER))] == want
    stub = six_mm(1.9)
    stub.tracks.append(Track("VBUS", "F.Cu", 1.9, (3.0, 0.0), (3.0, 0.05)))
    assert [line.split(" [")[0] for line in lines(layoutrules.findings(stub, EMI, POWER))] == want


def test_power_ratio_joins_an_end_inside_the_copper():
    """The second track starts at (3, 0.4), 0.4 mm off the first's centre line and inside its 1.9 mm of
    copper: 3 + 0.4 + 3 = 6.4 mm by 1.9 mm, 6.4 / 1.9 = 3.37 to 1."""
    b = six_mm(1.9)
    b.pads[1] = Pad("C1", "1", "VBUS", (6.0, 0.4), 0.3, ["F.Cu"])
    b.tracks[1] = Track("VBUS", "F.Cu", 1.9, (3.0, 0.4), (6.0, 0.4))
    assert [line.split(" [")[0] for line in lines(layoutrules.findings(b, EMI, POWER))] == [
        "fail length to width VBUS on F.Cu from C1.1 (6, 0.4) to U1.1 (0, 0): 6.4 mm by 1.9 mm, 3.37 to 1, "
        "limit 3 to 1"
    ]


def test_power_ratio_judges_ground_nets():
    """A GND track of 9 mm by 1 mm, GND under `ground` alone: 9 to 1 (SZZA009 2.1.1: power and ground)."""
    b = board()
    b.pads += [
        Pad("U1", "2", "GND", (0.0, 0.0), 0.3, ["F.Cu"]),
        Pad("C1", "2", "GND", (9.0, 0.0), 0.3, ["F.Cu"]),
    ]
    b.tracks.append(Track("GND", "F.Cu", 1.0, (0.0, 0.0), (9.0, 0.0)))
    b.nets = {"GND", "VBUS"}
    assert [line.split(" [")[0] for line in lines(layoutrules.findings(b, EMI, POWER))] == [
        "fail length to width GND on F.Cu from C1.2 (9, 0) to U1.2 (0, 0): 9 mm by 1 mm, 9 to 1, limit 3 to 1"
    ]


SQUARE = [(4.0, -3.0), (10.0, -3.0), (10.0, 3.0), (4.0, 3.0)]


def pour_board(pour_layer: str, via: bool, pad_in_pour: bool = False) -> Board:
    """U1.2 on GND at (0, 0) on F.Cu, a 0.25 mm F.Cu track to (6, 0), and a GND pour on `pour_layer` over x 4
    to 10, y -3 to 3; with `via`, a via at (6, 0); with `pad_in_pour`, C1.2 on B.Cu at (8, 0)."""
    b = board()
    b.pads += [
        Pad("U1", "2", "GND", (0.0, 0.0), 0.2, ["F.Cu"]),
        Pad("U1", "1", "VBUS", (0.0, -1.0), 0.2, ["F.Cu"]),
    ]
    if pad_in_pour:
        b.pads.append(Pad("C1", "2", "GND", (8.0, 0.0), 0.3, ["B.Cu"]))
    b.tracks.append(Track("GND", "F.Cu", 0.25, (0.0, 0.0), (6.0, 0.0)))
    if via:
        b.vias.append(Via("GND", (6.0, 0.0), 0.6, 0.3, BOTH))
    b.zones.append(Zone("GND", pour_layer, [SQUARE]))
    b.nets = {"VBUS", "GND"}
    return b


def test_power_ratio_through_a_via_into_the_pour_of_the_other_face():
    """6 mm of 0.25 mm track from U1.2 to a via at (6, 0) that drops into the B.Cu pour: 6 / 0.25 = 24 to 1,
    the pour met at the via. A pad of the pour (C1.2 at (8, 0) on B.Cu) changes nothing."""
    want = [
        "fail length to width GND on F.Cu from U1.2 (0, 0) to the GND pour on B.Cu (6, 0): 6 mm by 0.25 mm, "
        "24 to 1, limit 3 to 1"
    ]
    for pad_in_pour in (False, True):
        b = pour_board("B.Cu", via=True, pad_in_pour=pad_in_pour)
        assert [line.split(" [")[0] for line in lines(layoutrules.findings(b, EMI, POWER))] == want


def test_power_ratio_names_where_the_trace_meets_the_pour():
    """The track ends at (6, 0) inside the F.Cu pour over x 4 to 10: the line names (6, 0), not U1.2's
    (0, 0) at the other end."""
    b = pour_board("F.Cu", via=False)
    assert [line.split(" [")[0] for line in lines(layoutrules.findings(b, EMI, POWER))] == [
        "fail length to width GND on F.Cu from U1.2 (0, 0) to the GND pour on F.Cu (6, 0): 6 mm by 0.25 mm, "
        "24 to 1, limit 3 to 1"
    ]


ARC_PCB = """(kicad_pcb (version 20240108) (generator "pcbnew")
 (general (thickness 1.6))
 (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (44 "Edge.Cuts" user))
 (net 0 "") (net 1 "VBUS") (net 2 "GND")
 (footprint "Capacitor_SMD:C_0402_1005Metric" (layer "F.Cu") (at 9 9)
  (property "Reference" "C9") (pad "2" smd rect (at 0 0) (size 0.2 0.2) (layers "F.Cu") (net 2 "GND")))
 (footprint "Capacitor_SMD:C_0402_1005Metric" (layer "F.Cu") (at START)
  (property "Reference" "U1") (pad "1" smd rect (at 0 0) (size 0.2 0.2) (layers "F.Cu") (net 1 "VBUS")))
 (footprint "Capacitor_SMD:C_0402_1005Metric" (layer "F.Cu") (at END)
  (property "Reference" "C1") (pad "1" smd rect (at 0 0) (size 0.2 0.2) (layers "F.Cu") (net 1 "VBUS")))
 (arc (start START) (mid MID) (end END) (width WIDTH) (layer "F.Cu") (net 1))
)"""


@pytest.mark.parametrize(
    ("start", "mid", "end", "width", "want"),
    [
        # A half circle of radius 1 from (0, 0) through (1, -1) to (2, 0): pi x 1 = 3.14 mm by 1 mm. Its 2
        # chords would be 2 x sqrt(2) = 2.83 mm, under 3 to 1.
        ("0 0", "1 -1", "2 0", "1", "3.14 mm by 1 mm, 3.14 to 1"),
        # 270 degrees of radius 1 about (0, 0), from (1, 0) through (-0.70711, 0.70711) to (0, -1):
        # 3 x pi / 2 = 4.71 mm by 1.4 mm, 3.37 to 1. The chords: 2 x 1.848 = 3.70 mm, 2.64 to 1.
        ("1 0", "-0.70711 0.70711", "0 -1", "1.4", "4.71 mm by 1.4 mm, 3.37 to 1"),
    ],
)
def test_power_ratio_measures_an_arc_along_the_arc(start, mid, end, width, want):
    text = ARC_PCB.replace("START", start).replace("MID", mid).replace("END", end).replace("WIDTH", width)
    out = [
        line.split(" [")[0] for line in lines(layoutrules.findings(boardrules.read_board(text), EMI, POWER))
    ]
    assert len(out) == 1 and out[0].endswith(f": {want}, limit 3 to 1"), out


def test_power_ratio_only_on_two_layers():
    """The rule speaks of a two-layer board: a 4-layer board is outside it, and the note says so."""
    four = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
    assert layoutrules.findings(power_board(1.0, four), EMI, POWER) == []
    assert layoutrules.notes(power_board(1.0, four), EMI) == [
        "ti-szza009-emi power-ratio: the rule is for a board of 2 copper layers, and this one has 4"
    ]


def test_power_ratio_refuses_an_unknown_net():
    with pytest.raises(Refusal, match="power: VCC is no net of the board"):
        layoutrules.findings(power_board(1.0), EMI, {**POWER, "power": ["VCC"]})


def test_pack_asks_its_keys():
    with pytest.raises(Refusal, match="`power` is missing; the pack ti-szza009-emi asks it"):
        layoutrules.findings(power_board(1.0), EMI, {"ground": ["GND"]})
    with pytest.raises(Refusal, match="`ground` is missing; the pack ti-szza009-emi asks it"):
        layoutrules.findings(power_board(1.0), EMI, {"power": ["VBUS"]})


@pytest.mark.parametrize(
    ("key", "value", "match"),
    [
        ("not_judged", None, "ti-szza009-emi.json: not_judged: a list of places is asked"),
        ("copper_layers", 2.5, "rules 1: copper_layers: 2.5 is no whole number"),
    ],
)
def test_pack_refuses_a_wrong_value(tmp_path, key, value, match):
    data = json.loads((ROOT / "rules" / "board" / "ti-szza009-emi.json").read_text())
    if key == "not_judged":
        data[key] = value
    else:
        data["rules"][0][key] = value
    bad = tmp_path / "ti-szza009-emi.json"
    bad.write_text(json.dumps(data))
    with pytest.raises(Refusal, match=match):
        layoutrules.read_pack(bad)


def test_pack_refuses_unknown_check(tmp_path):
    data = json.loads((ROOT / "rules" / "board" / "ti-szza009-emi.json").read_text())
    data["rules"][0]["check"] = "guess"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(data))
    with pytest.raises(Refusal, match="rules 1: check: `guess` is no check"):
        layoutrules.read_pack(bad)


BOARDS = ROOT / "tests" / "boards"


def fixture_findings(name: str, data: dict | None = None, rename: tuple[str, str] | None = None) -> list[str]:
    folder = BOARDS / name
    data = boardrules.project_keys(data or json.loads((folder / "board-rules.json").read_text()))
    text = (folder / "layout.kicad_pcb").read_text()
    if rename:
        text = text.replace(f'"{rename[0]}"', f'"{rename[1]}"')
    b = boardrules.read_board(text)
    out = []
    for pack in data["layout"]:
        out += lines(
            layoutrules.findings(b, layoutrules.read_pack(ROOT / "rules" / "board" / f"{pack}.json"), data)
        )
    return out


def test_fixture_pass_layout_holds_both_packs():
    """J1.1 to D1.1 2.55 mm of 1.2 mm track, 2.125 to 1; D1.1 to C1.1 104 - 101.1125 = 2.8875 mm, 2.41
    to 1, and C1.1 stands 2.8875 mm from D1.1, further than D1.1 from J1.1 (2.55 mm)."""
    assert fixture_findings("pass-layout") == []


def test_fixture_fail_layout_esd_breaks_each_rule():
    """D2.1 at 108.4 - 1.05 = 107.35: 107.35 - 103 = 4.35 mm from J1.2; R1.1 at 112.2 - 0.9125 = 111.2875:
    3.9375 mm from D2.1, printed 3.94. VBUS reaches D1.1 through a via; DB has no TVS. VBUS's detour by the
    via is sqrt(1.5^2 + 1.5^2) + 1.05 + 1.5 = 2.1213 + 2.55 = 4.6713 mm of copper from J1.1 to D1.1 at
    (105.55, 104), and C1.1 at (105.55, 100.2 + 0.9125) lies 104 - 101.1125 = 2.8875 mm from D1.1."""
    out = fixture_findings("fail-layout-esd")
    assert [line.split(" [")[0] for line in out] == [
        "fail esd J1.1 VBUS: C1.1 lies 2.89 mm of copper from D1.1, "
        "and D1.1 lies 4.67 mm of copper from J1.1",
        "fail esd J1.1 VBUS: joined to D1.1 through a via",
        "fail esd J1.2 /DA: R1.1 stands 3.94 mm from D2.1, and D2.1 stands 4.35 mm from J1.2",
        "fail esd J1.3 /DB: no protector on the net",
    ]


def test_fixture_fail_layout_tee_branches_before_the_tvs():
    """VBUS branches at J1.1 (103, 104): D1.1 at 108.4 - 1.05 = 107.35, 4.35 mm across; the track up ends at
    100.2 + 0.9125 = 101.1125, 2.8875 mm, inside C1.1, whose centre the footprint puts at 100.2 + 0.95 =
    101.15. From D1.1, C1.1 stands sqrt(4.35^2 + 2.85^2) = 5.20 mm and lies 4.35 + 2.8875 = 7.24 mm of
    copper away, both more than 4.35; but it stands 104 - 101.15 = 2.85 mm from J1.1, nearer than D1.1."""
    assert [line.split(" [")[0] for line in fixture_findings("fail-layout-tee")] == [
        "fail esd J1.1 VBUS: C1.1 stands 2.85 mm from J1.1, and D1.1 stands 4.35 mm from J1.1"
    ]


def test_fixture_connector_renamed_cn1_is_not_judged():
    """fail-layout-esd with J1 named CN1 and `connectors` empty: CN1 is found by its footprint
    (Connector_PinHeader_2.54mm), and nothing passes."""
    data = {
        "layout": ["ti-slva680a-esd"],
        "connectors": {},
        "protectors": {"D1": "TVS diode", "D2": "TVS diode"},
        "ground": ["GND"],
    }
    assert fixture_findings("fail-layout-esd", data, ("J1", "CN1")) == [
        "not judged esd: board-rules.json names no part under `connectors`, so no line is judged",
        "not judged esd CN1: board-rules.json does not say whether it leaves the device "
        "(`connectors` or `inside`)",
    ]


def test_fixture_fail_layout_emi_breaks_its_rule_once():
    """C1 at y 99.4, the track ends at 99.4 + 0.9125 = 100.3125, inside pad 1, whose centre the footprint
    puts at 99.4 + 0.95 = 100.35; D1.1 at y 104: 104 - 100.3125 = 3.6875 mm of 1.2 mm track, 3.6875 / 1.2 =
    3.07 to 1, over 3 to 1. The line names each pad by its centre."""
    out = fixture_findings("fail-layout-emi")
    assert [line.split(" [")[0] for line in out] == [
        "fail length to width VBUS on F.Cu from C1.1 (105.55, 100.35) to D1.1 (105.55, 104): 3.69 mm by "
        "1.2 mm, 3.07 to 1, limit 3 to 1"
    ]


def test_board_rules_takes_layout_packs_without_a_voltage_pack():
    """board-rules.json with `layout` alone is read; one with neither is refused."""
    assert boardrules.project_keys({"layout": ["ti-szza009-emi"], "power": ["VBUS"], "ground": ["GND"]})[
        "layout"
    ] == ["ti-szza009-emi"]
    with pytest.raises(Refusal, match="names no pack"):
        boardrules.project_keys({})
