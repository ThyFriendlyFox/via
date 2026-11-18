"""The SIM gate's junction rule against a reference model written from the document, on generated cases.

4 reviews in a row each found a part over its limit that the gate passed under `--strict`; what ended
the run of holes was a model of the rule written from TI SPRA953D (not from tools/thermal.py), cases
generated over the whole input space, and each case run through the gate's own entry point
(`sim_thermal` of tools/workcenter, the function `gate_sim` calls) and through the model. This file
keeps that method: a fixed seed, no engine, and on any disagreement it fails with the smallest
disagreeing case printed.

The model's rules, each from its place in TI SPRA953D (the copy rules/references/index.json holds):
- Section 1.1, equation 1, page 2: TJ = TA + RthetaJA x power.
- Section 1.2, page 3: a 2s2p board gives a best case, a 1s board a typical one.
- Section 2, page 6: RthetaJC was devised for a case on a heat sink.
- Section 2.2, equation 4, page 7: TJ = TC + RthetaJC x power, a junction higher than reality.
- Section 2.2, equation 5, page 7: TJ = TA + (RthetaJC + Rtheta(CS) + Rtheta(SA)) x power, with a heat
  sink on the case, from the ambient alone.
- Section 2.2, equation 6, page 7: more accurate only if RthetaJA is known for the system configuration;
  not taken (section 1.1, page 2: the datasheet's RthetaJA is its test board's).
- Section 3, equation 8, page 8: TJ = TC(top) + psiJT x power; section 3.2, page 10: psiJT is not used
  with a heat sink.
- Section 4, figure 4-1, page 10: heat flows from the junction through the case and board to the air;
  RthetaJB is a first-pass estimation only.
- Section 5.1, equation 9, page 11: TJ = T(PCB) + psiJB x power.
What makes a part held, not held or failed under `--strict` is the simulate skill's (`A part's
temperature`, steps 1 to 4).
"""

from __future__ import annotations

import importlib.machinery
import json
import math
import random
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"

# The documents this file cites, by their ids in rules/references/index.json (`workcenter references rules`).
CITES = {
    "ti-spra953d": (
        "section 1.1, equation 1, page 2; section 1.2, page 3; section 2, page 6; section 2.2, equations 4, "
        "5 and 6, page 7; section 3, equation 8, page 8; section 3.2, page 10; section 4, figure 4-1, page "
        "10; section 5.1, equation 9, page 11"
    ),
}

SEED = 20261118
CASES = 14000  # 14.4 s in process (16.3 s with pytest's start) on 2026-11-18, under 20 s
MATCH = 0.01  # the skill, step 3: a run within 0.01 C of an ambient `from` names is judged from it
STATED_FIGURES = ("theta_jc", "theta_jb", "psi_jt", "psi_jb")
FIGURES = ("theta_ja", *STATED_FIGURES)
SINK_KEYS = ("name", "theta_cs", "theta_sa", "source")
CORNER_SETS = [[-40, 85], [-20, 60, 85], [-40, 25, 125], [0, 70], [-40, 0, 40, 85, 105]]
LIMITS = [85, 110, 125, 150]
RANGES = {
    "theta_ja": (40, 260),
    "theta_jc": (5, 130),
    "theta_jb": (10, 110),
    "psi_jt": (1, 40),
    "psi_jb": (10, 110),
}

# ---------------------------------------------------------------- the model


def resistance(value: object) -> bool:
    """A heat sink's resistance in C/W: a number above 0. A sink with no resistance to the air is no
    part, and equation 5 (section 2.2, page 7) asks for both."""
    return (
        isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0
    )


def refused(stated: dict | None) -> str | None:
    """Why the gate refuses a part's `from`, or None. A heat sink goes with RthetaJC only (section 2,
    page 6; psiJT not with one, section 3.2, page 10) and is named with the 2 resistances equation 5
    adds and their source (section 2.2, page 7)."""
    if not stated or "heat_sink" not in stated:
        return None
    if stated["figure"] != "theta_jc":
        return "heat_sink with a figure other than theta_jc"
    sink = stated["heat_sink"]
    if not isinstance(sink, dict):
        return "heat_sink not an object"
    if set(sink) != set(SINK_KEYS):
        return "heat_sink keys"
    if not all(isinstance(sink[k], str) and sink[k].strip() for k in ("name", "source")):
        return "heat_sink name or source not text"
    if not all(resistance(sink[k]) for k in ("theta_cs", "theta_sa")):
        return "heat_sink resistance not above 0"
    return None


def equation_5(term: dict, sink: dict, ambient: float, watts: float) -> float:
    """SPRA953D, section 2.2, equation 5, page 7."""
    return ambient + (term["theta_jc"] + sink["theta_cs"] + sink["theta_sa"]) * watts


def judge_part(term: dict | None, stated: dict | None, runs: list, narrower: bool, limit: float):
    """(status, reasons, rows) of 1 part: HELD, FAIL, or NJ (not judged or not held, a failure under
    `--strict`). `runs` holds (ambient in C, watts) for each run of the part's deck."""
    reasons: list[str] = []
    if term is None:
        return "NJ", ["no thermal"], []
    boards = term.get("boards", {})
    if stated and stated["figure"] not in term:
        if "theta_ja" not in term:
            return "NJ", ["stated figure lacking and no theta_ja"], []
        reasons.append("stated figure lacking")
        stated = None
    if not stated and "theta_ja" not in term:
        return "NJ", ["no theta_ja and nothing stated"], []
    if narrower:
        reasons.append("narrower deck block")
    sink = stated.get("heat_sink") if stated else None
    temps = {float(k): float(v) for k, v in (stated or {}).get("celsius", {}).items()}
    rows = []
    for ambient, watts in runs:
        # A stated temperature at or under the air is set aside: heat flows from the junction to the
        # air (section 4, figure 4-1, page 10).
        hit = [t for a, t in temps.items() if abs(a - ambient) <= MATCH and t > a]
        if hit:
            figure, start = stated["figure"], hit[0]
            junction = start + term[figure] * watts  # equations 4, 8 and 9 (pages 7, 8 and 11)
        elif "theta_ja" in term:
            figure, junction = "theta_ja", ambient + term["theta_ja"] * watts  # equation 1, page 2
        elif sink:
            reasons.append("a run with no stated case and no theta_ja")
            figure, junction = "theta_jc", -math.inf
        else:
            reasons.append("a run with no stated temperature and no theta_ja")
            continue
        if sink:
            # On a heat sink, equation 5 from the ambient at every run beside what judged it (section 2.2,
            # page 7): the greater judges.
            junction = max(junction, equation_5(term, sink, ambient, watts))
        rows.append({"ambient": ambient, "watts": watts, "figure": figure, "junction": junction})
    if any(t <= a for a, t in temps.items()):
        reasons.append("stated at or under the air")
    for a, t in temps.items():
        if t > a and not any(abs(a - ambient) <= MATCH for ambient, _ in runs):
            reasons.append("stated at an ambient no run stands at")
    used = {r["figure"] for r in rows} | ({"theta_jc"} if sink and rows else set())
    for figure in used:
        if figure not in boards:
            reasons.append(f"{figure} on no board")
    if any(r["figure"] == "theta_jb" for r in rows):
        reasons.append("theta_jb gives no bound")  # section 4, page 10
    stated_rows = [r for r in rows if r["figure"] != "theta_ja"]
    if stated_rows and not sink:
        # The 2s2p best case (section 1.2, page 3) is the floor a stated temperature is held to.
        if "theta_ja" not in term or boards.get("theta_ja") != "2s2p":
            reasons.append("stated with no 2s2p theta_ja to bound it")
        elif any(r["junction"] < r["ambient"] + term["theta_ja"] * r["watts"] for r in stated_rows):
            reasons.append("stated junction under the 2s2p best case")
    if any(r["junction"] > limit for r in rows):
        return "FAIL", reasons, rows
    return ("NJ" if reasons else "HELD"), reasons, rows


# ---------------------------------------------------------------- the generated cases


def thermal_term(rnd: random.Random) -> dict | None:
    if rnd.random() < 0.04:
        return None
    present = [f for f in FIGURES if rnd.random() < 0.55] or [rnd.choice(FIGURES)]
    term = {"junction_max": rnd.choice([125, 150, 175]), "page": [4, 5]}
    for figure in present:
        term[figure] = round(rnd.uniform(*RANGES[figure]), 1)
    boards = {}
    for figure in present:
        board = rnd.choices(["2s2p", "1s0p", None], [0.55, 0.25, 0.20])[0]
        if board:
            boards[figure] = board
    if boards:
        term["boards"] = {**boards, "page": 5}
    return term


def heat_sink(rnd: random.Random) -> object:
    """A heat sink as the gate asks for it, over a wide range, or wrong in 1 way."""
    sink = {
        "name": "a clip-on heat sink",
        "theta_cs": round(rnd.uniform(0.1, 5.0), 3),
        "theta_sa": round(math.exp(rnd.uniform(0, math.log(100.0))), 3),
        "source": "the sink's datasheet",
    }
    kind = rnd.choices(
        ["ok", "missing", "text", "extra", "text number", "negative", "zero", "bool", "blank", "whole"],
        [0.70, 0.07, 0.05, 0.03, 0.03, 0.03, 0.03, 0.02, 0.02, 0.02],
    )[0]
    key = rnd.choice(["theta_cs", "theta_sa"])
    if kind == "missing":
        del sink[rnd.choice(SINK_KEYS)]
    elif kind == "text":
        return rnd.choice(["a clip-on heat sink", "x", ""])
    elif kind == "extra":
        sink[rnd.choice(["theta_ca", "theta_jc", "note"])] = 1.0
    elif kind == "text number":
        sink[key] = str(sink[key])
    elif kind == "negative":
        sink[key] = -sink[key]
    elif kind == "zero":
        sink[key] = 0
    elif kind == "bool":
        sink[key] = True
    elif kind == "blank":
        sink[rnd.choice(["name", "source"])] = "  "
    elif kind == "whole":
        sink["theta_sa"] = int(round(sink["theta_sa"])) or 1
    return sink


def stated_block(rnd: random.Random, term: dict | None, ambients: list[float], watts_at) -> dict | None:
    if rnd.random() < 0.35:
        return None
    present = [f for f in STATED_FIGURES if term and f in term]
    figure = rnd.choice(present) if present and rnd.random() < 0.9 else rnd.choice(STATED_FIGURES)
    chosen = [a for a in ambients if rnd.random() < 0.6] or [rnd.choice(ambients)]
    if rnd.random() < 0.08:
        chosen.append(rnd.choice([30.0, 50.0, 95.0]))  # an ambient where maybe no run stands
    celsius = {}
    mode = rnd.choice(["under", "at", "hair", "well", "well", "well", "mixed"])
    for ambient in sorted(set(chosen)):
        how = rnd.choice(["under", "at", "hair", "well"]) if mode == "mixed" else mode
        if how == "under":
            temp = ambient - rnd.choice([0.001, 1, 10])
        elif how == "at":
            temp = ambient
        elif how == "hair":
            temp = ambient + 0.001
        else:
            temp = (
                ambient + rnd.uniform(0.5, 1.6) * rnd.uniform(20, 260) * watts_at(ambient) + rnd.uniform(0, 5)
            )
        celsius[f"{ambient:g}"] = round(temp, 3)
    block = {"figure": figure, "celsius": celsius, "source": "a generated statement"}
    if rnd.random() < 0.3:
        block["heat_sink"] = heat_sink(rnd)
        if rnd.random() < 0.85:
            block["figure"] = "theta_jc"
    return block


def make_case(rnd: random.Random) -> dict:
    corners = rnd.choice(CORNER_SETS)
    written = rnd.choice([25.0, 27.0])
    narrower = rnd.random() < 0.12
    deck_temps = list(corners)
    if narrower:
        deck_temps.remove(rnd.choice(deck_temps))
    ambients = sorted({written, *deck_temps})
    parts = []
    for k in range(1 if rnd.random() < 0.6 else 2):
        base = math.exp(rnd.uniform(math.log(0.001), math.log(2.0)))
        slope = rnd.uniform(-0.002, 0.004)
        same = k == 1 and rnd.random() < 0.3  # a second part of the same number
        term = parts[0]["term"] if same else thermal_term(rnd)
        parts.append(
            {
                "ref": f"U{k + 1}",
                "mpn": "PART-A" if same else f"PART-{'AB'[k]}",
                "term": term,
                "stated": stated_block(
                    rnd, term, ambients, lambda a, b=base, s=slope: b * (1 + s * (a - 25))
                ),
                "base": base,
                "slope": slope,
            }
        )
    fault = rnd.choices([None, "missing", "negative", "unknown", "dead"], [0.88, 0.03, 0.03, 0.03, 0.03])[0]
    return {
        "limit": rnd.choice(LIMITS),
        "written": written,
        "deck_temps": deck_temps,
        "narrower": narrower,
        "parts": parts,
        "fault": fault,
    }


def runs_of(case: dict) -> list | None:
    """The runs as gate_sim builds them: the deck as written first, then each corner at 2 tolerance ends."""
    temps = [("as written", case["written"])]
    for t in case["deck_temps"]:
        temps += [(f"{t:g} C, R1 -1 %", float(t)), (f"{t:g} C, R1 +1 %", float(t))]
    runs = []
    for label, ambient in temps:
        tolerance = 0.99 if "-1 %" in label else (1.01 if "+1 %" in label else 1.0)
        measures = {
            f"p_{p['ref'].lower()}": p["base"] * (1 + p["slope"] * (ambient - 25)) * tolerance
            for p in case["parts"]
        }
        runs.append((label, ambient, measures))
    if case["fault"] == "dead":
        return None
    if case["fault"] == "missing":
        del runs[-1][2]["p_u1"]
    if case["fault"] == "negative":
        runs[-1][2]["p_u1"] = -0.01
    if case["fault"] == "unknown":
        runs[0] = (runs[0][0], f"the deck ran at {case['written']:g} C and 85 C", runs[0][2])
    return runs


def model_verdict(case: dict) -> dict[str, str]:
    """Each part's status by the model."""
    for part in case["parts"]:
        if refused(part["stated"]):
            return {p["ref"]: "REFUSED" for p in case["parts"]}
    runs = runs_of(case)
    statuses = {}
    for part in case["parts"]:
        term, stated, key = part["term"], part["stated"], f"p_{part['ref'].lower()}"
        if term is None or (not (stated and stated["figure"] in term) and "theta_ja" not in term):
            statuses[part["ref"]] = judge_part(term, stated, [], False, case["limit"])[0]
        elif runs is None:
            statuses[part["ref"]] = "NJ"  # the deck did not run to its end
        elif any(key not in m or m[key] < 0 for _, _, m in runs):
            statuses[part["ref"]] = "FAIL"  # a power not printed, or under 0
        else:
            known = [(a, m[key]) for _, a, m in runs if not isinstance(a, str)]
            status = judge_part(term, stated, known, case["narrower"], case["limit"])[0]
            statuses[part["ref"]] = "NJ" if status == "HELD" and len(known) < len(runs) else status
    return statuses


# ---------------------------------------------------------------- the gate's own entry point


def load_cli() -> types.ModuleType:
    loader = importlib.machinery.SourceFileLoader("workcenter_cli_thermal_model", str(CLI))
    module = types.ModuleType("workcenter_cli_thermal_model")
    module.__file__ = str(CLI)
    sys.modules[module.__name__] = module  # dataclasses look the defining module up here
    loader.exec_module(module)
    return module


def write_case(case: dict, folder: Path, base_facts: dict) -> None:
    (folder / "library" / "facts").mkdir(parents=True)
    (folder / "sim").mkdir()
    for part in case["parts"]:
        facts = {k: v for k, v in base_facts.items() if k != "thermal"} | {"mpn": part["mpn"]}
        if part["term"] is not None:
            facts["thermal"] = part["term"]
        (folder / "library" / "facts" / f"{part['mpn'].lower()}.json").write_text(json.dumps(facts))
    plan = {"pack": f"../packs/limit-{case['limit']}.json", "parts": {}}
    for part in case["parts"]:
        entry = {"mpn": part["mpn"], "watts": f"ldo.p_{part['ref'].lower()}", "source": "input less output"}
        if part["stated"]:
            entry["from"] = part["stated"]
        plan["parts"][part["ref"]] = entry
    (folder / "sim" / "thermal.json").write_text(json.dumps(plan))


def gate_verdict(cli: types.ModuleType, case: dict, folder: Path) -> dict[str, str]:
    """Each part's status as `sim_thermal`, the step `gate_sim` takes, gives it."""
    th = cli.thermal()
    plan, problems = th.read_plan(folder / "sim", ["ldo"])
    if problems:
        return {p["ref"]: "REFUSED" for p in case["parts"]}
    unrun = {"ldo": "the deck's own block leaves a temperature of the file out"} if case["narrower"] else {}
    project = cli.Project(folder, folder.name, None, None, None)
    _, failures, not_judged = cli.sim_thermal(project, plan, {"ldo": runs_of(case)}, unrun)
    statuses = {}
    for part in case["parts"]:
        tag = (f"thermal: {part['ref']} (", f"thermal: {part['ref']}:")
        if any(line.startswith(tag) for line in failures):
            statuses[part["ref"]] = "FAIL"
        elif any(line.startswith(tag) for line in not_judged):
            statuses[part["ref"]] = "NJ"
        else:
            statuses[part["ref"]] = "HELD"
    return statuses


def write_packs(folder: Path) -> None:
    ecss = json.loads((ROOT / "rules" / "ratings" / "ecss-q-st-30-11c-rev2.json").read_text(encoding="utf-8"))
    folder.mkdir()
    for limit in LIMITS:
        rules = [r for r in ecss["rules"] if r.get("stress") != "junction.temperature"]
        rules.append(
            {
                "id": "junction.ic",
                "stress": "junction.temperature",
                "kinds": ["ic.linear", "ic.regulator", "ic.digital"],
                "celsius": limit,
                "where": "a limit made up for the test",
                "second_reader": "2026-11-18",
            }
        )
        pack = {**ecss, "pack": f"limit-{limit}", "rules": rules}
        (folder / f"limit-{limit}.json").write_text(json.dumps(pack))


def test_the_gate_agrees_with_the_model_on_generated_cases(tmp_path):
    """Every generated case through `sim_thermal` and through the model: each part held, failed, not
    judged or refused alike. A part the gate holds that the model fails is a false pass."""
    cli = load_cli()
    base_facts = json.loads((ROOT / "tests" / "boards" / "library" / "facts" / "ti-tlv755p.json").read_text())
    write_packs(tmp_path / "packs")
    rnd = random.Random(SEED)
    disagree = []
    for number in range(CASES):
        case = make_case(rnd)
        folder = tmp_path / f"c{number}"
        write_case(case, folder, base_facts)
        gate, model = gate_verdict(cli, case, folder), model_verdict(case)
        if gate != model:
            disagree.append((len(json.dumps(case)), number, gate, model, case))
    if disagree:
        _, number, gate, model, case = min(disagree, key=lambda d: d[0])
        raise AssertionError(
            f"{len(disagree)} of {CASES} cases disagree; the smallest, case {number}: gate {gate}, model "
            f"{model}\n{json.dumps(case, indent=1)}"
        )
