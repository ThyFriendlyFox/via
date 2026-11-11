# 3D bodies

KiCad's 3D library has no body for 4 of Hush's parts. `make_models.py` writes each from its
footprint's fab outline and the maker's drawing, with the workcenter's `tools/wrlgen.py`:

```sh
python3 models/make_models.py      # from the board's folder
```

| File | Part | Size |
|---|---|---|
| `im73a135.wrl` | MIC1, Infineon IM73A135V01 | a 4.0 x 3.0 x 1.2 mm LGA: a laminate base under a steel lid |
| `jack_pj320d.wrl` | J2, PJ-320D 3.5 mm jack | the body 11.8 x 5.8 x 5.0 mm, the collar a plug enters |
| `trimmer_tc33x.wrl` | RV1, Bourns TC33X | a 3.8 x 3.6 mm cermet base, the white rotor with its cross slot, 1.7 mm |
| `speaker_wires.wrl` | J3 | the speaker's 2 wires in their pads, red for + and black for - |

`design.py` names each with `d.model(..., replace=True)`. The speaker driver under the board is
not here: [`../assembly.py`](../assembly.py) builds it for the assembly scene.
