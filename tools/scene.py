"""scene — a routed board with the bodies that are not on it, rendered from named views and turned.

The general part of an assembly script. A project's scene script holds only its placements:

    import scene

    s = scene.Scene("last_hit.kicad_pcb", out="build/assembly", name="last_hit_assembly")
    cart = s.wrlgen("cartridge-510", "cartridge_510.wrl", "--length", "52")
    for ref in ("J1", "J2"):
        s.place(cart, (*s.position(ref), 4.0))
    cell = s.cylinder("cell.wrl", d=10.0, length=44.0, color=(0.10, 0.35, 0.75))
    s.place(cell, (133.0, 106.35, 2.0))
    display = s.board_body("display/last_hit_display.kicad_pcb", origin="106.35x133mm")
    s.place(display, (*s.position("J6"), 0.0), rotate=(-90, 0, -90))
    s.stills({"assembly-iso": {"rotate": "-62,0,28", "perspective": True, "zoom": 0.7, "pivot": "0,0,2.6"}})
    s.spin("assembly-spin.gif", tilt=-66, zoom=0.5, pivot="0,0,2.4")

Positions are board millimetres (x right, y down, z up from the top face); a body is a VRML file in
KiCad's model unit, made here (`cylinder`, `box`, `write` with `wrlgen` meshes), by a `wrlgen` preset,
or from another board (`board_body`). Each body hangs on its own empty footprint at its position, so a
rotation is the body's own, read the way KiCad reads a model's (M42: opposite to the right-hand rule).

`workcenter pictures` runs a scene script with this folder on PYTHONPATH; by hand,
`PYTHONPATH=<workcenter>/tools python3 <script>`. Paths are relative to the script's folder. Needs
KiCad's pcbnew module and kicad-cli; `spin` needs FFmpeg. Writes only in `out`: bodies/ (the scene's
bodies), a copy of each body the board names under ${KIPRJMOD} at the same path, the scene's board,
the stills and the GIF. With WORKCENTER_SPIN_FRAMES set, `spin` draws that many frames; with
WORKCENTER_PICTURES_CHECK set (`workcenter pictures --frames N`), `stills` draws nothing and `spin`
also writes a sheet of its frames and prints `frames: <path>`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pcbnew

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import doctools  # noqa: E402
import wrlgen  # noqa: E402

KIPRJMOD = "${KIPRJMOD}"


def render_cmd(png: Path, pcb: Path, view: dict, width: int, height: int) -> list[str]:
    """kicad-cli's render of one view: rotate "x,y,z", zoom, pivot "x,y,z" in cm, pan, side, perspective."""
    cmd = ["kicad-cli", "pcb", "render", "--output", str(png), "--width", str(view.get("width", width))]
    cmd += ["--height", str(view.get("height", height)), "--background", "opaque", "--quality", "high"]
    cmd.append("--use-board-stackup-colors")  # the board's own colours, as `workcenter render` draws it
    for key in ("rotate", "zoom", "pivot", "pan", "side"):
        if key in view:
            cmd += [f"--{key}", str(view[key])]
    if view.get("perspective"):
        cmd.append("--perspective")
    cmd.append(str(pcb))
    if not os.environ.get("DISPLAY") and shutil.which("xvfb-run"):
        cmd = ["xvfb-run", "-a", *cmd]
    return cmd


class Scene:
    def __init__(
        self, board: str | Path, out: str | Path = "build/scene", name: str | None = None, base=None
    ):
        self.base = Path(base) if base else Path(sys.argv[0]).resolve().parent
        self.board_path = (self.base / board).resolve()
        if not self.board_path.is_file():
            sys.exit(f"scene: {self.board_path} missing: run `workcenter design` on its design file first")
        self.out = (self.base / out).resolve()
        self.models = self.out / "bodies"  # the scene's own; models/ may hold the board's
        self.models.mkdir(parents=True, exist_ok=True)
        self.name = name or f"{self.board_path.stem}_scene"
        self.board = pcbnew.LoadBoard(str(self.board_path))
        # The scene's board is saved in `out`, where ${KIPRJMOD} then points. pcbnew hands out copies
        # of a footprint's models, so a path set on one never reaches the saved board: the board's own
        # bodies are copied to the same place under `out` instead.
        self.copied = []
        for fp in self.board.GetFootprints():
            for m in fp.Models():
                rel = m.m_Filename[len(KIPRJMOD) + 1 :] if m.m_Filename.startswith(KIPRJMOD + "/") else ""
                src = self.board_path.parent / rel
                if rel and src.is_file() and rel not in self.copied:
                    (self.out / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, self.out / rel)
                    self.copied.append(rel)
        self.placed = 0
        self.check = bool(os.environ.get("WORKCENTER_PICTURES_CHECK"))

    # -------------------------------------------------------------- bodies

    def position(self, ref: str) -> tuple[float, float]:
        """A footprint's position on the board, in millimetres."""
        fp = self.board.FindFootprintByReference(ref)
        if fp is None:
            raise KeyError(f"scene: no footprint {ref} on {self.board_path.name}")
        p = fp.GetPosition()
        return pcbnew.ToMM(p.x), pcbnew.ToMM(p.y)

    def write(self, name: str, meshes: list, comment: str = "") -> Path:
        """Meshes built with wrlgen's primitives (Mesh, cylinder, box, prism, tube) as one body."""
        path = self.models / name
        wrlgen.write_wrl(path, meshes, comment or name)
        return path

    def cylinder(self, name: str, d: float, length: float, color=wrlgen.SILVER, caps=None) -> Path:
        """An upright cylinder on its axis from z = 0, its colour on the side; `caps` colours 0.4 mm at
        each end (a cell's can) when given."""
        r = d / 2
        meshes = []
        if caps:
            end = wrlgen.Mesh(caps)
            wrlgen.cylinder(end, 0.0, 0.0, 0.0, r - 0.05, 0.4)
            wrlgen.cylinder(end, 0.0, 0.0, length - 0.4, r - 0.05, 0.4)
            meshes.append(end)
            side = wrlgen.Mesh(color)
            wrlgen.cylinder(side, 0.0, 0.0, 0.4, r, length - 0.8)
        else:
            side = wrlgen.Mesh(color)
            wrlgen.cylinder(side, 0.0, 0.0, 0.0, r, length)
        return self.write(name, [*meshes, side], f"cylinder {d} x {length} mm")

    def box(self, name: str, size: tuple[float, float, float], color=wrlgen.GREY) -> Path:
        """A box centred on its position, from z = 0 up."""
        m = wrlgen.Mesh(color)
        wrlgen.box(m, 0.0, 0.0, 0.0, *size)
        return self.write(name, [m], f"box {size[0]} x {size[1]} x {size[2]} mm")

    def wrlgen(self, preset: str, name: str, *args: str) -> Path:
        """A body from one of wrlgen's presets (cartridge-510, connector-510, pouch-cell, ...)."""
        path = self.models / name
        subprocess.run(
            [sys.executable, str(HERE / "wrlgen.py"), preset, str(path), *map(str, args)], check=True
        )
        return path

    def copy(self, path: str | Path) -> Path:
        """A body the project keeps (its models/ folder), copied next to the scene's own."""
        src = (self.base / path).resolve()
        dest = self.models / src.name
        shutil.copyfile(src, dest)
        return dest

    def board_body(self, pcb: str | Path, origin: str | None = None, name: str | None = None) -> Path:
        """Another board with its parts as one body: kicad-cli's VRML export in KiCad's model unit, with
        `origin` ("XxYmm" in that board's frame) at the body's origin and its mid-plane at z = 0."""
        src = (self.base / pcb).resolve()
        path = self.models / (name or f"{src.stem}.wrl")
        cmd = ["kicad-cli", "pcb", "export", "vrml", "--units", "tenths", "--force", "--output", str(path)]
        cmd += ["--user-origin", origin] if origin else []
        subprocess.run([*cmd, str(src)], check=True, stdout=subprocess.DEVNULL)
        return path

    def place(
        self, body: str | Path, at: tuple[float, float, float], rotate=(0.0, 0.0, 0.0), scale=(1.0, 1.0, 1.0)
    ):
        """Put a body on the scene at board coordinates (x, y down, z up from the top face)."""
        self.placed += 1
        fp = pcbnew.FOOTPRINT(self.board)
        fp.SetReference(f"SCENE{self.placed}")
        fp.Reference().SetVisible(False)
        fp.Value().SetVisible(False)
        fp.SetAttributes(pcbnew.FP_SMD)  # the 3D views leave out a footprint marked neither SMD nor THT
        fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(at[0]), pcbnew.FromMM(at[1])))
        m = pcbnew.FP_3DMODEL()
        m.m_Filename = str(Path(body).resolve())
        m.m_Offset = pcbnew.VECTOR3D(0.0, 0.0, float(at[2]))
        m.m_Rotation = pcbnew.VECTOR3D(*map(float, rotate))
        m.m_Scale = pcbnew.VECTOR3D(*map(float, scale))
        fp.Models().push_back(m)
        self.board.Add(fp)
        return fp

    # ------------------------------------------------------------- outputs

    def save(self) -> Path:
        pcb = self.out / f"{self.name}.kicad_pcb"
        self.board.Save(str(pcb))
        return pcb

    def stills(self, views: dict[str, dict], width: int = 1600, height: int = 1000) -> list[Path]:
        """One PNG per named view into `out`. Nothing in the framing check."""
        if self.check:
            return []
        pcb = self.save()
        done = []
        for name, view in views.items():
            png = self.out / f"{name}.png"
            subprocess.run(render_cmd(png, pcb, view, width, height), check=True, stdout=subprocess.DEVNULL)
            print(f"scene: {png}")
            done.append(png)
        return done

    def spin(
        self, gif: str, tilt: float = -55.0, zoom: float = 1.0, pivot: str | None = None, frames: int = 36
    ):
        """The scene turning once round its vertical axis: `workcenter render --views spin` on the
        scene's board, the GIF moved to `out/<gif>`."""
        pcb = self.save()
        frames = int(os.environ.get("WORKCENTER_SPIN_FRAMES") or frames)
        work = self.out / "spin"
        cmd = [
            sys.executable,
            str(HERE / "workcenter"),
            "render",
            str(pcb),
            "--out",
            str(work),
            "--views",
            "spin",
        ]
        cmd += ["--spin-frames", str(frames), "--spin-tilt", f"{tilt:g}", "--spin-zoom", f"{zoom:g}"]
        cmd += ["--spin-pivot", pivot] if pivot else []
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
        path = (work / "render" / "board-spin.gif").replace(self.out / gif)
        print(f"scene: {path}")
        if self.check:
            sheet = path.with_name(f"{path.stem}-frames.png")
            if doctools.tile_frames(path, sheet, frames):
                print(f"frames: {sheet}")
        return path


if __name__ == "__main__":
    sys.exit("scene is a module: a project's scene script imports it (see its docstring)")
