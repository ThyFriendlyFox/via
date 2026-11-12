"""2 library footprints, each copied with 1 change so it fits this board and its fab.

    python3 footprints/make_footprints.py      # from the board's folder; writes footprints/wyvern.pretty/

- The SOM's receptacle. The Open-Q 845 uSOM puts JT1 and JT2 23.0 mm apart, centre to centre (its
  datasheet, Figure 7). KiCad's `Hirose_DF40HC(3.0)-100DS-0.4V_2x50_P0.4mm` draws the body 22.6 mm
  long (F.Fab, +-11.3 mm) and the courtyard 0.5 mm past it at each end (+-11.8 mm), so 2 of them at
  the SOM's spacing overlap by 0.6 mm though their bodies stand 0.4 mm apart. The copy's courtyard
  ends at +-11.45 mm, 0.15 mm past the body.
- The USB-C receptacle. KiCad's `USB_C_Receptacle_Amphenol_12401610E4-2A` draws the 4 shell tabs as
  0.8 x 1.4 mm pads round a 0.5 x 1.1 mm slot: a 0.15 mm ring, under Sierra Circuits' 6 mil
  (0.1524 mm). The copy's tab pads are 0.82 x 1.42 mm, a 0.16 mm ring. The 2 rear tabs stand
  0.29 mm from the receptacle's locating pegs, under Sierra's 13 mil from a hole to inner-layer
  copper. They hold the shell and nothing else, and the 2 front tabs ground it, so the copy leaves
  the rear 2 unnumbered: on no net, KiCad keeps their copper on the outer layers only.

Nothing else changes: the same pads, bodies and 3D models from KiCad's library.
"""

from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
KICAD = Path("/usr/share/kicad/footprints")
COPIES = [
    (
        "Connector_Hirose_DF40.pretty/Hirose_DF40HC(3.0)-100DS-0.4V_2x50_P0.4mm",
        "Hirose_DF40HC(3.0)-100DS-0.4V_2x50_P0.4mm_SOM",
        [("(start -11.8 -2.39)", "(start -11.45 -2.39)", 1), ("(end 11.8 2.39)", "(end 11.45 2.39)", 1)],
    ),
    (
        "Connector_USB.pretty/USB_C_Receptacle_Amphenol_12401610E4-2A",
        "USB_C_Receptacle_Amphenol_12401610E4-2A_Ring6mil",
        [("(size 0.8 1.4)", "(size 0.82 1.42)", 4)]
        + [
            (
                f'(pad "SH" thru_hole oval\n\t\t(at {x} -3.11)\n\t\t(size 0.8 1.4)\n\t\t(drill oval 0.5 1.1)\n'
                '\t\t(property pad_prop_mechanical)\n\t\t(layers "*.Cu" "*.Mask")\n\t\t(remove_unused_layers no)',
                f'(pad "" thru_hole oval\n\t\t(at {x} -3.11)\n\t\t(size 0.8 1.4)\n\t\t(drill oval 0.5 1.1)\n'
                '\t\t(property pad_prop_mechanical)\n\t\t(layers "*.Cu" "*.Mask")\n\t\t(remove_unused_layers yes)\n'
                '\t\t(keep_end_layers yes)',
                1,
            )
            for x in ("-4.13", "4.13")
        ],
    ),
]


def main() -> None:
    out_dir = HERE / "wyvern.pretty"
    out_dir.mkdir(exist_ok=True)
    for source, name, edits in COPIES:
        path = KICAD / f"{source}.kicad_mod"
        text = path.read_text(encoding="utf-8")
        for old, new, count in sorted(edits, key=lambda e: e[0].startswith("(size")):
            if text.count(old) != count:
                raise SystemExit(f"{path.name}: expected {count} '{old}', found {text.count(old)}; the library changed")
            text = text.replace(old, new)
        old_name = f'(footprint "{Path(source).name}"'
        if text.count(old_name) != 1:
            raise SystemExit(f"{path.name}: its name line changed")
        text = text.replace(old_name, f'(footprint "{name}"')
        (out_dir / f"{name}.kicad_mod").write_text(text, encoding="utf-8")
        print(f"wrote {out_dir / name}.kicad_mod")


if __name__ == "__main__":
    main()
