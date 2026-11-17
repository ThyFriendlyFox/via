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
from boardrules import Board, Pad, Track, Via  # noqa: E402
from ratings import Refusal  # noqa: E402

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
    b.nets = {"VBUS"}
    return b


def test_power_ratio_fails_over_3_to_1():
    """1 run of 2 + 2 = 4 mm at 1 mm wide: 4 to 1, over 3 to 1."""
    out = lines(layoutrules.findings(power_board(1.0), EMI, {"power": ["VBUS"]}))
    assert len(out) == 1
    assert out[0].startswith(
        "fail length to width VBUS on F.Cu from (0, 0) to (4, 0): 4 mm by 1 mm, 4 to 1, limit 3 to 1 "
        "[SZZA009: section 2.1.1, page 4"
    )


def test_power_ratio_held():
    """1.5 mm wide: 4 / 1.5 = 2.67 to 1. A pad at (2, 0) splits the run: 2 / 1 = 2 to 1 each."""
    assert layoutrules.findings(power_board(1.5), EMI, {"power": ["VBUS"]}) == []
    assert layoutrules.findings(power_board(1.0, mid_pad=True), EMI, {"power": ["VBUS"]}) == []


def test_power_ratio_only_on_two_layers():
    """The rule speaks of a two-layer board: a 4-layer board is outside it, and the note says so."""
    four = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
    assert layoutrules.findings(power_board(1.0, four), EMI, {"power": ["VBUS"]}) == []
    assert layoutrules.notes(power_board(1.0, four), EMI) == [
        "ti-szza009-emi power-ratio: the rule is for a board of 2 copper layers, and this one has 4"
    ]


def test_power_ratio_refuses_an_unknown_net():
    with pytest.raises(Refusal, match="power: VCC is no net of the board"):
        layoutrules.findings(power_board(1.0), EMI, {"power": ["VCC"]})


def test_pack_asks_its_keys():
    with pytest.raises(Refusal, match="`power` is missing; the pack ti-szza009-emi asks it"):
        layoutrules.findings(power_board(1.0), EMI, {})


def test_pack_refuses_unknown_check(tmp_path):
    data = json.loads((ROOT / "rules" / "board" / "ti-szza009-emi.json").read_text())
    data["rules"][0]["check"] = "guess"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(data))
    with pytest.raises(Refusal, match="rules 1: check: `guess` is no check"):
        layoutrules.read_pack(bad)


BOARDS = ROOT / "tests" / "boards"


def fixture_findings(name: str) -> list[str]:
    folder = BOARDS / name
    data = boardrules.project_keys(json.loads((folder / "board-rules.json").read_text()))
    b = boardrules.read_board((folder / "layout.kicad_pcb").read_text())
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


def test_fixture_fail_layout_esd_breaks_each_rule_once():
    """D2.1 at 108.4 - 1.05 = 107.35: 107.35 - 103 = 4.35 mm from J1.2; R1.1 at 112.2 - 0.9125 = 111.2875:
    3.9375 mm from D2.1, printed 3.94. VBUS reaches D1.1 through a via; DB has no TVS."""
    out = fixture_findings("fail-layout-esd")
    assert [line.split(" [")[0] for line in out] == [
        "fail esd J1.1 VBUS: joined to D1.1 through a via",
        "fail esd J1.2 /DA: R1.1 stands 3.94 mm from D2.1, and D2.1 stands 4.35 mm from J1.2",
        "fail esd J1.3 /DB: no protector on the net",
    ]


def test_fixture_fail_layout_emi_breaks_its_rule_once():
    """C1 at y 99.4, its pad 1 at 99.4 + 0.9125 = 100.3125; D1.1 at y 104: 3.6875 mm of 1.2 mm track,
    3.6875 / 1.2 = 3.07 to 1, over 3 to 1."""
    out = fixture_findings("fail-layout-emi")
    assert [line.split(" [")[0] for line in out] == [
        "fail length to width VBUS on F.Cu from (105.55, 104) to (105.55, 100.312): 3.69 mm by 1.2 mm, "
        "3.07 to 1, limit 3 to 1"
    ]


def test_board_rules_takes_layout_packs_without_a_voltage_pack():
    """board-rules.json with `layout` alone is read; one with neither is refused."""
    assert boardrules.project_keys({"layout": ["ti-szza009-emi"], "power": ["VBUS"]})["layout"] == [
        "ti-szza009-emi"
    ]
    with pytest.raises(Refusal, match="names no pack"):
        boardrules.project_keys({})
