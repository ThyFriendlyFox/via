"""`fuse.current`: a fuse's current held to the share its pack names for its style and its rating.

NASA EEE-INST-002, section F3, table 4, page 6 of 7 (May 2003), derates a cartridge fuse by its rating:
50 % for 2, 2-1/2, 3, 4, 5, 7, 10 and 15 A; 45 % for 1 and 1-1/2 A; 40 % for 3/4 and 1/2 A; 35 % for
3/8 A; 30 % for 1/4 A; 25 % for 1/8 A; and 0.2 %/C more for the fuse body above 25 C. ECSS-Q-ST-30-11C
Rev.2, clause 6.17.2, table 6-17, page 49, derates a cermet fuse to 65 % up to 85 C of its case, falling
in a line to 50 % at 110 C; clause 6.17.1a says the table covers cermet fuses only. A fuse of another
style is held to its own rating.
"""

from __future__ import annotations

import json

import pytest
from test_ratings import (
    GND,
    LDO,
    NASA,
    NASA_SOURCE,
    PACKS,
    POWER_FET,
    V5,
    ceramic,
    circuit,
    entry,
    found,
    library,
    power_fet,
    project,
    ratings,
    regulator,
)

ECSS = ratings.read_pack(PACKS / "ecss-q-st-30-11c-rev2.json")
ECSS_SOURCE = "ECSS-Q-ST-30-11C Rev.2"
NASA_FUSE = f"{NASA_SOURCE}, section F3, table 4, page 6 of 7"
ECSS_FUSE = f"{ECSS_SOURCE}, clause 6.17.2, table 6-17, page 49"
NETS = {"V5": (4.5, 5.5), **GND}


def fused(tmp_path, kind: str, rated: float, amps: float, pack, ambient: float | None = None):
    """F1 from V5 to VF, and a capacitor from VF to GND; ratings.json states `amps` through F1."""
    net, mpns = circuit(
        F1=("F", "F-1", {"1": "V5", "2": "VF"}),
        C1=("100n", "C-16V", {"1": "VF", "2": "GND"}),
    )
    facts = library(tmp_path, entry(kind, "F-1", amps=rated), ceramic("C-16V", 16))
    return ratings.judge(net, mpns, facts, project(NETS, amps={"F1": amps}, ambient=ambient), pack)


def fuse_lines(report) -> list[str]:
    return [f.line for f in report.findings if f.part == "F1"]


def test_a_cartridge_fuse_of_2_a_is_held_to_half_its_rating(tmp_path):
    """Table 4, the row 2 ... 15 A: 50 %. 1.2 A / 2 A = 0.60 > 0.50 fails; 0.9 A / 2 A = 0.45 holds."""
    report = fused(tmp_path, "fuse.cartridge", 2.0, 1.2, NASA)
    assert found(report, "fail") == [
        "fail F1 F current, with the 1.2 A the project states: 1.2 A on 2 A rated is 0.60, the limit is 0.50 "
        f"[{NASA_FUSE}, its column Temperature Derating Factor: 0.2 % of the rating less for each C of the "
        "fuse body above 25 C]"
    ]
    assert report.findings[[f.part for f in report.findings].index("F1")].rule == "fuse.cartridge.current"
    held = fused(tmp_path, "fuse.cartridge", 2.0, 0.9, NASA)
    assert [line.split(" [")[0] for line in fuse_lines(held)] == [
        "hold F1 F current, with the 900 mA the project states: 900 mA on 2 A rated is 0.45, "
        "the limit is 0.50"
    ]


@pytest.mark.parametrize(
    ("rated", "amps", "status", "limit"),
    [
        (1.0, 0.45, "hold", "0.45"),  # 0.45 / 1 = 0.45, the row 1, 1-1/2: 45 %
        (1.5, 0.69, "fail", "0.45"),  # 0.69 / 1.5 = 0.46
        (0.75, 0.3, "hold", "0.40"),  # 0.3 / 0.75 = 0.40, the row 3/4: 40 %
        (0.5, 0.21, "fail", "0.40"),  # 0.21 / 0.5 = 0.42, the row 1/2: 40 %
        (0.375, 0.13, "hold", "0.35"),  # 0.13 / 0.375 = 0.347, the row 3/8: 35 %
        (0.25, 0.08, "fail", "0.30"),  # 0.08 / 0.25 = 0.32, the row 1/4: 30 %
        (0.125, 0.03, "hold", "0.25"),  # 0.03 / 0.125 = 0.24, the row 1/8: 25 %
        (15.0, 7.6, "fail", "0.50"),  # 7.6 / 15 = 0.507, the row 2 ... 15: 50 %
    ],
)
def test_each_row_of_table_4_holds_its_own_ratings(tmp_path, rated, amps, status, limit):
    lines = fuse_lines(fused(tmp_path, "fuse.cartridge", rated, amps, NASA))
    assert len(lines) == 1 and lines[0].startswith(f"{status} F1 F current"), lines
    assert f"the limit is {limit} [{NASA_FUSE}" in lines[0]


def test_a_rating_table_4_does_not_name_is_not_judged(tmp_path):
    """Table 4 names 6 rows of ratings; 6.3 A is in none of them, and nothing says which row it takes."""
    report = fused(tmp_path, "fuse.cartridge", 6.3, 1.0, NASA)
    assert found(report, "not judged") == [
        "not judged F1 F current, with the 1 A the project states: 1 A on 6.3 A rated: the pack names no "
        f"share for a rating of 6.3 A [{NASA_FUSE}, its column Temperature Derating Factor: 0.2 % of the "
        "rating less for each C of the fuse body above 25 C]"
    ]
    assert ratings.verdict(report) == ("RATINGS HELD, 1 NOT JUDGED", 0)
    at_its_rating = fused(tmp_path, "fuse.cartridge", 6.3, 6.3, NASA)  # 6.3 / 6.3 = 1.00: not over it
    assert found(at_its_rating, "fail") == [] and len(found(at_its_rating, "not judged")) == 1


@pytest.mark.parametrize(
    ("rated", "amps", "of_it"),
    [
        (6.3, 20.0, "3.17"),  # 20 / 6.3 = 3.1746: 6.3 A is in no row of table 4
        (20.0, 30.0, "1.50"),  # 30 / 20 = 1.50: table 4 ends at 15 A
    ],
)
def test_a_rating_table_4_does_not_name_is_still_held_to_the_part_s_own(tmp_path, rated, amps, of_it):
    """The table says nothing of the derated share, and the part's own rating, 1.00, holds all the same
    (rules/ratings/README.md: a stress with no rule is held to the part's own rating)."""
    report = fused(tmp_path, "fuse.cartridge", rated, amps, NASA)
    r, a = f"{rated:g} A", f"{amps:g} A"
    assert found(report, "fail") == [
        f"fail F1 F current, with the {a} the project states: {a} on {r} rated is {of_it}, the limit is "
        f"1.00, the part's own rating: the pack names no share for a rating of {r} [DS-1, rev A: the part's "
        "own rating]"
    ]
    assert ratings.verdict(report) == ("RATINGS NOT HELD (1 fail)", 1)


def test_a_rating_at_0_that_the_rule_names_no_share_for_fails_and_ends_no_run(tmp_path):
    """4 A at 25 C and 0 A at 150 C: at 150 C nothing of the rating is left. A pack whose rule names no
    share for that rating sent the part to its own rating, 1 A / 0 A, and the run ended in a
    ZeroDivisionError."""
    net, mpns = circuit(Q1=("FET", "FET-2", POWER_FET))
    nets = {"LOAD": (0.0, 12.6), "GATE": (0.0, 3.3), **GND}
    facts = library(tmp_path, power_fet(amps_drain=[[25, 4.0], [150, 0]]))
    rule = {"id": "q", "stress": "mosfet.drain_current", "kinds": ["transistor"], "where": "table 1, page 1"}
    pack = pack_of(tmp_path, {**rule, "by_rating": [{"rated": [4], "max": 0.5}]})
    report = ratings.judge(net, mpns, facts, project(nets, amps={"Q1": 1.0}, ambient=150), pack)
    assert [line.split(" [")[0] for line in found(report, "fail")] == [
        "fail Q1 FET drain current, with the 1 A the project states: 1 A on 0 A rated: "
        "nothing of the rating is left"
    ]


def test_the_body_above_25_c_takes_0_2_percent_of_the_rating_for_each_c(tmp_path):
    """At 75 C: 0.50 - 0.002 x (75 - 25) = 0.40. 0.85 A / 2 A = 0.425 fails there, and holds with no
    ambient stated, where the rule is judged as at 25 C."""
    hot = fused(tmp_path, "fuse.cartridge", 2.0, 0.85, NASA, ambient=75)
    assert [line.split(" [")[0] for line in fuse_lines(hot)] == [
        "fail F1 F current, with the 850 mA the project states: 850 mA on 2 A rated is 0.42, "
        "the limit is 0.40"
    ]
    assert "fuse.cartridge.current: the part's own heating above the ambient is not counted" in hot.notes
    cool = fused(tmp_path, "fuse.cartridge", 2.0, 0.85, NASA)
    assert fuse_lines(cool)[0].startswith("hold F1")
    assert "fuse.cartridge.current: judged as under 25 C, since the project states no ambient" in cool.notes


def test_a_cermet_fuse_is_held_to_ecss_table_6_17(tmp_path):
    """65 % up to 85 C: 1.4 A / 2 A = 0.70 fails, 1.2 A / 2 A = 0.60 holds at 80 C. At 100 C:
    0.65 + (0.50 - 0.65) x (100 - 85) / (110 - 85) = 0.56, and 0.60 fails."""
    assert found(fused(tmp_path, "fuse.cermet", 2.0, 1.4, ECSS), "fail") == [
        "fail F1 F current, with the 1.4 A the project states: 1.4 A on 2 A rated is 0.70, the limit is 0.65 "
        f"[{ECSS_FUSE}, a figure: 65 % up to 85 C of the case, in a line to 50 % at 110 C]"
    ]
    assert fuse_lines(fused(tmp_path, "fuse.cermet", 2.0, 1.2, ECSS, ambient=80))[0].startswith("hold F1")
    hot = fuse_lines(fused(tmp_path, "fuse.cermet", 2.0, 1.2, ECSS, ambient=100))
    assert hot[0].split(" [")[0] == (
        "fail F1 F current, with the 1.2 A the project states: 1.2 A on 2 A rated is 0.60, the limit is 0.56"
    )


@pytest.mark.parametrize(
    ("kind", "pack"),
    [
        ("fuse", NASA),  # a fuse of no named style
        ("fuse", ECSS),
        ("fuse.cermet", NASA),  # table 4 of NASA covers the cartridge style
        ("fuse.cartridge", ECSS),  # clause 6.17.1a: table 6-17 covers cermet fuses only
    ],
)
def test_a_fuse_neither_table_covers_is_held_to_its_own_rating(tmp_path, kind, pack):
    """1.2 A / 2 A = 0.60, under the part's own 1.00."""
    lines = fuse_lines(fused(tmp_path, kind, 2.0, 1.2, pack))
    assert lines == [
        "hold F1 F current, with the 1.2 A the project states: 1.2 A on 2 A rated is 0.60, the limit is 1.00 "
        "[DS-1, rev A: the part's own rating]"
    ]


def test_a_rating_written_with_more_digits_is_its_row_s_rating(tmp_path):
    """0.3750000001 A differs from 3/8 A by 2.7e-10 of it, under the command's 1e-9: the row 3/8 A,
    35 %. 0.13 A / 0.375 A = 0.347 holds."""
    lines = fuse_lines(fused(tmp_path, "fuse.cartridge", 0.3750000001, 0.13, NASA))
    assert lines[0].startswith("hold F1 F current") and "the limit is 0.35" in lines[0], lines


def test_a_styled_fuse_is_a_wire_as_a_fuse_is(tmp_path):
    """The input pin stands on V5F, behind a cartridge fuse from V5, and the capacitor from V5 to
    ground: the 2 nets are 1 node, and the capacitor is the one the datasheet asks for."""
    need = {"capacitor": {"from": "IN", "to": "GND", "farads_min": 0.5e-6}, "page": 5}
    net, mpns = circuit(
        U1=("LDO", "LDO-1", {**LDO, "1": ("V5F", "IN", "power_in")}),
        F1=("1A", "FUSE-1", {"1": "V5", "2": "V5F"}),
        C1=("1u", "C-16V", {"1": "V5", "2": "GND"}),
    )
    fuse = entry("fuse.cartridge", "FUSE-1", amps=1.0)
    facts = library(tmp_path, regulator(needs=[need]), ceramic("C-16V", 16), fuse)
    report = ratings.judge(net, mpns, facts, project(V5), NASA)
    assert "U1 pin IN (V5F) needs 500 nF to GND: C1 gives 1 uF" in [f.text for f in report.findings]
    assert found(report, "fail") == []


RULE = {"id": "f", "stress": "fuse.current", "kinds": ["fuse"], "where": "table 1, page 1"}
CASE_25 = {"temperature": "case", "celsius": 25, "falls_to": 0.0, "at": 275}


def pack_of(tmp_path, rule: dict):
    """The NASA pack's document with 1 rule, read as a pack."""
    data = json.loads((PACKS / "nasa-eee-inst-002.json").read_text(encoding="utf-8"))
    data["rules"] = [rule]
    path = tmp_path / "x.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return ratings.read_pack(path)


def test_a_row_with_no_above_of_its_own_takes_the_rule_s(tmp_path):
    """The rule's `above` falls from the row's 0.50 at 25 C to 0 at 275 C. At 75 C:
    0.50 + (0 - 0.50) x (75 - 25) / (275 - 25) = 0.50 - 0.10 = 0.40. The row of its own `above` keeps it:
    0.45 at 25 C to 0 at 250 C gives 0.45 - 0.45 x 50 / 225 = 0.35 at 75 C."""
    own = {"temperature": "case", "celsius": 25, "falls_to": 0.0, "at": 250}
    rows = [{"rated": [2], "max": 0.5}, {"rated": [1], "max": 0.45, "above": own}]
    pack = pack_of(tmp_path, {**RULE, "above": CASE_25, "by_rating": rows})
    share, _ = ratings.factor(pack.rules[0].at(2.0), 75)
    assert share == pytest.approx(0.40)
    share, _ = ratings.factor(pack.rules[0].at(1.0), 75)
    assert share == pytest.approx(0.35)


@pytest.mark.parametrize(
    ("rule", "message"),
    [
        ({**RULE}, "x.json: rule 1: `max` or `by_rating` is asked"),
        (
            {**RULE, "max": 0.5, "by_rating": [{"rated": [1], "max": 0.5}]},
            "x.json: rule 1: `max` and `by_rating` stand together; a rule holds 1 of them",
        ),
        ({**RULE, "by_rating": []}, "x.json: rule 1: by_rating: a list of shares is asked"),
        ({**RULE, "by_rating": [{"rated": [], "max": 0.5}]}, "x.json: rule 1: by_rating 1: rated: a list"),
        ({**RULE, "by_rating": [{"rated": [1], "max": 1.5}]}, "x.json: rule 1: by_rating 1: max: 1.5"),
        ({**RULE, "by_rating": [{"rated": [1]}]}, "x.json: rule 1: by_rating 1: `max` is missing"),
        (
            {**RULE, "by_rating": [{"rated": [1, 2], "max": 0.5}, {"rated": [2], "max": 0.4}]},
            "x.json: rule 1: by_rating 2: rated: 2 stands in by_rating 1 too",
        ),
        (
            {**RULE, "by_rating": [{"rated": [1], "max": 0.5, "above": {"temperature": "air"}}]},
            "x.json: rule 1: by_rating 1: above: `celsius` is missing",
        ),
        (
            {**RULE, "by_rating": [{"rated": [0], "max": 0.5}]},
            "x.json: rule 1: by_rating 1: rated: 0 is not above 0",
        ),
        (
            {**RULE, "by_rating": [{"rated": [1, -2], "max": 0.5}]},
            "x.json: rule 1: by_rating 1: rated: -2 is not above 0",
        ),
        (  # a rule's `above` is held to its form though every row has its own
            {
                **RULE,
                "above": {"temperature": "air", "bogus": 1},
                "by_rating": [{"rated": [1], "max": 0.5, "above": CASE_25}],
            },
            "x.json: rule 1: above: `bogus` is no key here; the keys are temperature, celsius, falls_to, at",
        ),
        (  # 1 and 1.0000000001 differ by 1e-10 of 1, under the 1e-9 Rule.at() matches a rating by
            {**RULE, "by_rating": [{"rated": [1], "max": 0.5}, {"rated": [1.0000000001], "max": 0.2}]},
            "x.json: rule 1: by_rating 2: rated: 1 stands in by_rating 1 too",
        ),
    ],
)
def test_a_rule_by_rating_that_is_wrong_in_1_place_is_refused_with_the_place(tmp_path, rule, message):
    with pytest.raises(ratings.Refusal) as caught:
        pack_of(tmp_path, rule)
    assert str(caught.value).startswith(message), caught.value
