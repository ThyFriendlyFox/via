"""`workcenter measure`: the plan of measurements for a built board.

For each bound of each sim deck: the pad of the board to probe (the net the deck's node names), the
pad of its reference, the instrument (from the deck's analysis and the quantity the measure reads),
the span the reading must fall in (the expect file's min and max), and what the SIM gate predicts from
a fresh run, as written and over its corners. The plan goes to <out>/measure/plan.md and plan.json,
with an empty Reading column for whoever measures. Standard library only, as the CLI is.
"""

from __future__ import annotations

import json
import re

# A vector ngspice computes, and what it is a quantity of.
VECTOR = re.compile(r"\b(vdb|vm|vr|vi|vp|v|i)\(([^)]*)\)", re.I)
QUANTITY = {
    "v": ("voltage", "V"),
    "vm": ("voltage", "V"),
    "vr": ("voltage", "V"),
    "vi": ("voltage", "V"),
    "vdb": ("level", "dB"),
    "vp": ("phase", "rad"),
    "i": ("current", "A"),
}
# A `meas` of a crossing (`when`, `trig ... targ`) gives a value on the analysis's own axis.
AXIS = {"ac": ("frequency", "Hz"), "tran": ("time", "s"), "dc": ("sweep value", "")}
SCOPE_AC = "signal generator into the deck's AC source and a 2-channel oscilloscope"
INSTRUMENT = {
    ("op", "voltage"): "DC voltmeter",
    ("dc", "voltage"): "DC voltmeter, with the deck's swept source on an adjustable supply",
    (
        "dc",
        "sweep value",
    ): "adjustable supply in place of the deck's swept source, and a DC voltmeter at the probe",
    ("tran", "voltage"): "oscilloscope",
    ("tran", "time"): "oscilloscope",
    ("ac", "frequency"): SCOPE_AC,
    ("ac", "voltage"): SCOPE_AC,
    ("ac", "level"): SCOPE_AC,
}
ANALYSES = {"op", "tran", "ac", "dc"}
GROUND = {"0", "gnd"}


def _lines(text: str) -> list[str]:
    """The deck's lines with continuation lines joined and comments dropped."""
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.split(";", 1)[0].rstrip()
        if not line.strip() or line.lstrip().startswith("*"):
            continue
        if line.startswith("+") and out:
            out[-1] += " " + line[1:].strip()
        else:
            out.append(line.strip())
    return out


def _vector(match: re.Match) -> tuple[str, str, list[str]]:
    nodes = [n.strip().lower() for n in match.group(2).split(",") if n.strip()]
    return match.group(1).lower(), match.group(0).lower(), nodes


# A number as a deck writes it: 37e-3, 1e6, 100u, .5
NUMBER = re.compile(r"(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?[a-z]*", re.I)
TOKEN = re.compile(r"(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?[a-z]*|[A-Za-z_]\w*|\S", re.I)


def _shape(expr: str) -> str:
    """How an expression with its one operand written X depends on X: "plain" (X, -X), "scaled" (X
    times, plus or minus constants, divided only by a constant) or "" (anything else: a function, a
    division by X, another name)."""
    tokens = TOKEN.findall(expr)
    if tokens.count("X") != 1:
        return ""
    for i, t in enumerate(tokens):
        if t == "X" or t in "+-*()" or NUMBER.fullmatch(t):
            continue
        if t == "/" and i + 1 < len(tokens) and NUMBER.fullmatch(tokens[i + 1]):
            continue
        return ""
    bare = [t for t in tokens if t not in "()"]
    return "plain" if bare in (["X"], ["-", "X"], ["+", "X"]) else "scaled"


def _read_let(expr: str, found: dict[str, dict], analysis: str, conditions: list[str]) -> dict:
    """What a `let` reads: 1 vector, or v(a) - v(b), or 1 measure, each only as _shape allows."""
    text = expr.strip()
    vectors = list(VECTOR.finditer(text))
    names = VECTOR.sub(" ", text).lower()
    known = [n for n in found if re.search(rf"(?<!\w){re.escape(n)}\b", names)]
    cannot = {"why": f"the plan cannot read {text}", "reads": text}
    if len(vectors) == 2 and not known:
        (ka, va, na), (kb, vb, nb) = (_vector(m) for m in vectors)
        rest = text[: vectors[0].start()] + " A " + text[vectors[0].end() : vectors[1].start()] + " B "
        rest += text[vectors[1].end() :]
        bare = [t for t in TOKEN.findall(rest) if t not in "()"]
        if ka == kb == "v" and len(na) == len(nb) == 1 and bare == ["A", "-", "B"]:
            return {
                "analysis": analysis,
                "quantity": "voltage",
                "unit": "V",
                "nodes": na + nb,
                "reads": text.lower(),
                "conditions": conditions,
            }
        return cannot
    if len(vectors) == 1 and not known:
        kind, reads, nodes = _vector(vectors[0])
        shape = _shape(text[: vectors[0].start()] + " X " + text[vectors[0].end() :])
        if not shape:
            return cannot
        quantity, unit = QUANTITY[kind]
        return {
            "analysis": analysis,
            "quantity": quantity,
            "unit": unit if shape == "plain" else "",
            "nodes": nodes if kind != "i" else [],
            "reads": reads if shape == "plain" else text.lower(),
            "conditions": conditions,
        }
    if len(known) == 1 and not vectors:
        base = found[known[0]]
        if "why" in base:
            return {**cannot, "why": f"it is worked from {known[0]}, and {base['why']}"}
        shape = _shape(re.sub(rf"(?<!\w){re.escape(known[0])}\b", " X ", text, flags=re.I))
        if not shape:
            return cannot
        if shape == "plain":
            return dict(base)
        # A measure scaled from another (`t_us = t * 1e6`) reads what that one reads, in a unit the
        # plan cannot name. A current keeps the vector it reads, which is what its line names.
        return {**base, "unit": "", "reads": text if base["nodes"] else base["reads"]}
    return cannot


def measures(deck: str) -> dict[str, dict]:
    """Each measure a deck computes (`let` after an analysis, or `meas`), with its analysis, the
    quantity it reads, its unit, the nodes of the vector it reads, that vector as written, and the
    `alter` lines in effect when its analysis ran. A measure the plan cannot read carries `why`."""
    found: dict[str, dict] = {}
    analysis = ""
    altered: dict[str, str] = {}
    conditions: list[str] = []
    for line in _lines(deck):
        words = line.split()
        head = words[0].lower().lstrip(".")
        if head in ANALYSES:
            analysis = head
            conditions = list(altered.values())
            continue
        if head in ("alter", "altermod") and len(words) > 1:
            # ngspice keeps an alter until the next one of the same element; the analysis after it runs
            # with it.
            key = re.split(r"[\s=]", line.split(None, 1)[1], maxsplit=1)[0].lower()
            altered.pop(key, None)
            altered[key] = " ".join(words)
        elif head == "reset":
            altered.clear()
        elif head == "let" and "=" in line:
            name, expr = line[3:].split("=", 1)
            found[name.strip().lower()] = _read_let(expr, found, analysis, conditions)
        elif head in ("meas", "measure") and len(words) > 3:
            kind, name, rest = words[1].lower(), words[2].lower(), " ".join(words[3:])
            crossing = words[3].lower() in ("when", "trig")
            match = VECTOR.search(rest)
            if match:
                vec = _vector(match)
                quantity, unit = AXIS.get(kind, ("", "")) if crossing else QUANTITY[vec[0]]
                found[name] = {
                    "analysis": kind,
                    "quantity": quantity,
                    "unit": unit,
                    "nodes": vec[2] if vec[0] != "i" else [],
                    "reads": vec[1],
                    "conditions": conditions,
                }
                continue
            # A meas over a vector the deck made with `let` reads what that let reads.
            arg = re.split(r"[\s=]", rest.split(None, 1)[1] if len(rest.split()) > 1 else "")[0].lower()
            base = found.get(arg)
            if base is None:
                found[name] = {"why": f"the plan cannot read meas {kind} {name} {rest}", "reads": rest}
            elif "why" in base:
                found[name] = {**base, "why": f"it is a meas over the let vector {arg}, and {base['why']}"}
            else:
                quantity, unit = AXIS.get(kind, ("", "")) if crossing else (base["quantity"], base["unit"])
                found[name] = {**base, "analysis": kind, "quantity": quantity, "unit": unit}
    return found


def sources(deck: str) -> list[dict]:
    """The deck's independent sources: name, its 2 nodes and its value as written."""
    found = []
    control = False
    for line in _lines(deck):
        low = line.lower()
        if low.startswith(".control"):
            control = True
        elif low.startswith(".endc"):
            control = False
        elif not control and low[:1] in ("v", "i"):
            words = line.split(None, 3)
            if len(words) >= 3:
                value = words[3] if len(words) > 3 else ""
                found.append(
                    {"name": words[0], "nodes": [words[1].lower(), words[2].lower()], "value": value}
                )
    return found


def _norm(net: str) -> str:
    return net.lower().rsplit("/", 1)[-1]


def _pad_key(pad: str) -> tuple:
    ref = pad.split()[0]
    prefix = re.match(r"[A-Za-z]*", ref).group(0).upper()
    rank = 0 if prefix == "TP" else 1 if prefix in ("J", "P") else 2
    return (rank, prefix, [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", pad)])


def matching_nets(node: str, nets: dict[str, list[str]]) -> list[str]:
    node = node.lower()
    if node in GROUND:
        return [n for n in nets if _norm(n) in GROUND]
    return [n for n in nets if _norm(n) == node]


def test_point(node: str, nets: dict[str, list[str]]) -> tuple[str, str] | None:
    """The board net a deck node names, and its pad to probe: a test point, else a connector's pin,
    else a part's pad. None when the node names no net, or more than 1."""
    found = matching_nets(node, nets)
    if len(found) != 1:
        return None
    return found[0], min(nets[found[0]], key=_pad_key)


def _where(node: str, nets: dict[str, list[str]]) -> tuple[str | None, str]:
    tp = test_point(node, nets)
    if tp:
        return f"{tp[1]} ({tp[0]})", ""
    count = len(matching_nets(node, nets))
    if count:
        return None, f"deck node {node} names {count} nets of the board"
    return None, f"deck node {node} names no net of the board"


def plan_rows(deck: str, found: dict, bounds: dict, sim: dict, nets: dict[str, list[str]]) -> list[dict]:
    """1 row per bound of the deck's expect file."""
    rows = []
    envelope = (sim.get("corners") or {}).get("envelope", {})
    for name, bound in bounds.items():
        row = {
            "deck": deck,
            "measure": name,
            "planned": False,
            "min": bound.get("min"),
            "max": bound.get("max"),
        }
        m = found.get(name)
        why = ""
        if not m:
            why = f"the deck computes no measure called {name}"
        elif "why" in m:
            why = m["why"]
        elif not m["nodes"]:
            why = (
                f"it reads {m['reads']}, a current: an ammeter goes in series, "
                "and the board names no place to open"
            )
        elif (m["analysis"], m["quantity"]) not in INSTRUMENT:
            why = (
                f"no instrument is named for a {m['quantity']} of a {m['analysis'] or 'missing'} analysis "
                f"({m['reads']})"
            )
        if not why:
            probe, why = _where(m["nodes"][0], nets)
            reference, why_ref = _where(m["nodes"][1] if len(m["nodes"]) > 1 else "0", nets)
            why = why or why_ref
        if why:
            row["why"] = why
            rows.append(row)
            continue
        env = envelope.get(name, {})
        corners = [env["min"], env["max"]] if "min" in env and "max" in env else None
        row.update(
            planned=True,
            quantity=m["quantity"],
            unit=m["unit"],
            probe=probe,
            reference=reference,
            instrument=INSTRUMENT[(m["analysis"], m["quantity"])],
            predicted=(sim.get("measures") or {}).get(name),
            corners=corners,
            conditions=m.get("conditions", []),
            source=bound.get("source", ""),
        )
        rows.append(row)
    return rows


def _num(x) -> str:
    return f"{x:.7g}"


def span(row: dict) -> str:
    unit = f" {row.get('unit', '')}".rstrip()
    lo, hi = row.get("min"), row.get("max")
    if lo is not None and hi is not None:
        return f"{_num(lo)} to {_num(hi)}{unit}"
    return f"at least {_num(lo)}{unit}" if lo is not None else f"at most {_num(hi)}{unit}"


def markdown(project: str, rows: list[dict], srcs: list[dict], sim_said: str) -> str:
    out = [
        f"# Plan of measurements: {project}",
        "",
        "Written by `workcenter measure`. Each row is 1 bound of a sim deck's expect file. Probe the",
        "pad against the reference pad, with the board powered as the deck's sources say, changed by the",
        "`alter` lines of the row's Conditions column, and write the reading in the last 2 columns: the",
        "reading, and whether it falls inside the span.",
        "",
        f"SIM: {sim_said}",
        "",
        "## Sources",
        "",
        "| Deck | Source | Value as the deck states it | Between |",
        "|---|---|---|---|",
    ]
    out += [f"| {s['deck']} | {s['name']} | {s['value']} | {s['at']} |" for s in srcs]
    out += [
        "",
        "## Readings",
        "",
        "| Deck | Measure | Conditions | Probe | Reference | Instrument | Span | Predicted | Corners "
        "| Reading | Inside? |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        if not r["planned"]:
            continue
        unit = f" {r['unit']}".rstrip()
        pred = f"{_num(r['predicted'])}{unit}" if r["predicted"] is not None else "not run"
        corners = (
            f"{_num(r['corners'][0])} to {_num(r['corners'][1])}{unit}" if r["corners"] else "no corners"
        )
        conditions = "; ".join(f"`{c}`" for c in r.get("conditions") or []) or "the sources as stated"
        out.append(
            f"| {r['deck']} | {r['measure']} | {conditions} | {r['probe']} | {r['reference']} | "
            f"{r['instrument']} | {span(r)} | {pred} | {corners} |  |  |"
        )
    missing = [r for r in rows if not r["planned"]]
    if missing:
        out += ["", "## Not planned", ""]
        out += [f"- {r['deck']} {r['measure']}: {r['why']}" for r in missing]
    return "\n".join(out) + "\n"


def cmd_measure_plan(args, cli) -> int:
    project = cli.find_project(args.project)
    out = cli.out_dir_for(project, args.out)
    sim_dir = project.dir / "sim"
    decks = sorted(sim_dir.glob("*.cir")) if sim_dir.is_dir() else []
    if not decks:
        print(f"measure: no sim/*.cir in {project.dir}: no deck predicts a value to measure")
        return 1
    nets = cli.fabfiles().board_facts(project.pcb.read_text(encoding="utf-8"))["nets"] if project.pcb else {}
    sim = cli.gate_sim(project, out)
    sim_said = f"{sim.status.upper()} {sim.summary}"
    rows: list[dict] = []
    srcs: list[dict] = []
    for deck in decks:
        text = deck.read_text(encoding="utf-8", errors="replace")
        bounds, problems = cli.read_expect(sim_dir / f"{deck.stem}.expect.json")
        for p in problems:
            print(f"NOT PLANNED {deck.stem}.expect.json: {p}")
        ran = sim.details.get("decks", {}).get(deck.stem, {})
        rows += plan_rows(deck.stem, measures(text), bounds, ran, nets if project.pcb else {})
        for s in sources(text):
            a, why_a = _where(s["nodes"][0], nets)
            b, why_b = _where(s["nodes"][1], nets)
            at = f"{a} to {b}" if a and b else (why_a or why_b)
            srcs.append({"deck": deck.stem, "name": s["name"], "value": s["value"], "at": at})
    if not project.pcb:
        for r in rows:
            r.update(planned=False, why="the project has no board to probe")
    folder = out / "measure"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "plan.json").write_text(
        json.dumps({"project": project.name, "sim": sim_said, "sources": srcs, "rows": rows}, indent=2),
        encoding="utf-8",
    )
    (folder / "plan.md").write_text(markdown(project.name, rows, srcs, sim_said), encoding="utf-8")
    print(f"SIM    {sim_said}")
    for r in rows:
        if r["planned"]:
            pred = _num(r["predicted"]) if r["predicted"] is not None else "not run"
            print(
                f"PLAN   {r['deck']} {r['measure']}: {r['instrument']} at {r['probe']} to {r['reference']}; "
                f"span {span(r)}; predicted {pred}"
            )
        else:
            print(f"NOT PLANNED {r['deck']} {r['measure']}: {r['why']}")
    planned = sum(1 for r in rows if r["planned"])
    print(f"{planned} bounds planned, {len(rows) - planned} not planned: {folder / 'plan.md'}")
    return 0 if rows and planned == len(rows) else 1


def register(sub, cli) -> None:
    """Add `measure` to the workcenter's parser; it sets `run` to its handler."""
    p = sub.add_parser(
        "measure",
        help="write the plan of measurements for a built board: for each sim bound the pad to probe, the "
        "instrument, the span the reading must fall in and the predicted value, into <out>/measure/",
    )
    p.add_argument("project", help="project directory or a .kicad_pro/.kicad_sch/.kicad_pcb file")
    p.add_argument("--out", help="output directory (default <project>/build)")
    p.set_defaults(run=lambda args: cmd_measure_plan(args, cli))
