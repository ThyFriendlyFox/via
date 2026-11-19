"""`workcenter doctor` holds the Python environment to requirements.txt.

On 2026-11-18 a stray run of install.sh added 12 packages to a machine's venv, and doctor's `venv` line
read `ok` as before: it asked only whether the folder was there. A venv that lacked a pinned package,
or held another version of it, read `ok` too, until a command failed on an import far from the cause.
The check reads installed metadata (importlib.metadata) and runs no pip. Every test here points it at
a made-up folder of *.dist-info, never at the machine's own venv."""

from __future__ import annotations

import importlib.machinery
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"


def load_cli_module():
    loader = importlib.machinery.SourceFileLoader("workcenter_cli", str(CLI))
    module = types.ModuleType("workcenter_cli")
    module.__file__ = str(CLI)
    sys.modules[module.__name__] = module
    loader.exec_module(module)
    return module


wc = load_cli_module()

# The marker environment of a made-up interpreter: what the venv's own Python would say.
ENV = {
    "python_version": "3.12",
    "python_full_version": "3.12.3",
    "sys_platform": "linux",
    "platform_system": "Linux",
    "platform_machine": "x86_64",
    "os_name": "posix",
    "implementation_name": "cpython",
    "platform_python_implementation": "CPython",
}


def dist(site: Path, folder: str, name: str, version: str, *requires: str) -> None:
    """1 installed package's metadata, as pip leaves it: <folder>-<version>.dist-info/METADATA."""
    info = site / f"{folder}-{version}.dist-info"
    info.mkdir(parents=True)
    lines = ["Metadata-Version: 2.1", f"Name: {name}", f"Version: {version}"]
    lines += [f"Requires-Dist: {r}" for r in requires]
    (info / "METADATA").write_text("\n".join(lines) + "\n", encoding="utf-8")


def check(tmp_path: Path, requirements: str, *dists: tuple) -> dict:
    site = tmp_path / "venv" / "lib" / "python3.12" / "site-packages"
    site.mkdir(parents=True, exist_ok=True)
    for d in dists:
        dist(site, *d)
    req = tmp_path / "requirements.txt"
    req.write_text(requirements, encoding="utf-8")
    return wc.requirements_row(req, [site], [site], ENV, fix="PIP -r REQ")


PINS = "# a comment\n\nkikit==1.8.1\nPyYAML==6.0.3\n"


def test_all_pins_met_is_ok_and_says_how_many(tmp_path):
    row = check(
        tmp_path,
        PINS,
        ("kikit", "KiKit", "1.8.1", "pcbnewTransition>=0.5"),
        ("pcbnewtransition", "pcbnewTransition", "0.5.2"),
        ("pyyaml", "PyYAML", "6.0.3"),
    )
    assert row["ok"] is True
    assert row["version"] == "2 of 2 pins met"
    assert row["missing"] == [] and row["other"] == [] and row["extra"] == [] and row["unread"] == []
    assert row["lines"] == []


def test_a_missing_pin_is_named_with_the_command_that_puts_it_right(tmp_path):
    row = check(tmp_path, PINS, ("pyyaml", "PyYAML", "6.0.3"))
    assert row["ok"] is False
    assert row["version"] == "1 of 2 pins met"
    assert row["missing"] == ["kikit==1.8.1"]
    assert row["lines"] == ["missing: kikit==1.8.1; put right with: PIP -r REQ"]


def test_a_pin_at_another_version_is_named_with_both_versions(tmp_path):
    row = check(tmp_path, PINS, ("kikit", "KiKit", "1.8.1"), ("pyyaml", "PyYAML", "6.0.2"))
    assert row["ok"] is False
    assert row["other"] == ["PyYAML==6.0.3 (6.0.2 installed)"]
    assert row["lines"] == ["other version: PyYAML==6.0.3 (6.0.2 installed); put right with: PIP -r REQ"]


def test_a_pin_with_extras_and_a_marker(tmp_path):
    """An extra's own dependencies are accounted for; a pin whose marker is false here is not asked."""
    reqs = (
        'pkg[cli]==1.0 ; python_version >= "3.10" and sys_platform == "linux"\n'
        "winonly==2.0 ; sys_platform == 'win32'\n"
        'oldpy==3.0 ; python_version < "3.9"\n'
    )
    row = check(
        tmp_path,
        reqs,
        ("pkg", "pkg", "1.0", 'click>=8 ; extra == "cli"', 'docs-only ; extra == "docs"'),
        ("click", "click", "8.5.0"),
        ("docs_only", "docs-only", "1.0"),
    )
    assert row["ok"] is True and row["version"] == "1 of 1 pins met"
    assert row["extra"] == ["docs-only 1.0"]


def test_names_match_by_pep_503_case_and_separators(tmp_path):
    reqs = "pdfminer.six==20260107\nkicad-python==0.8.0\nPyYAML==6.0.3\n"
    row = check(
        tmp_path,
        reqs,
        ("pdfminer_six", "pdfminer.six", "20260107"),
        ("kicad_python", "kicad_python", "0.8.0"),
        ("pyyaml", "pyyaml", "6.0.3"),
    )
    assert row["ok"] is True and row["version"] == "3 of 3 pins met"
    assert row["extra"] == []


def test_a_version_pin_with_fewer_zeros_is_the_same_version(tmp_path):
    row = check(tmp_path, "a==1.0\n", ("a", "a", "1.0.0"))
    assert row["ok"] is True and row["other"] == []


def test_an_unreadable_line_is_said_and_does_not_crash(tmp_path):
    reqs = "this is not a pin!\nkikit==1.8.1\nbad==1.0 ; python_version ?? '3'\n-e git+https://x/y\n"
    row = check(tmp_path, reqs, ("kikit", "KiKit", "1.8.1"))
    assert row["ok"] is True
    assert row["unread"] == [
        "line 1: this is not a pin!",
        "line 3: bad==1.0 ; python_version ?? '3'",
        "line 4: -e git+https://x/y",
    ]
    assert row["lines"] == [
        "not read: line 1: this is not a pin!; line 3: bad==1.0 ; python_version ?? '3'; "
        "line 4: -e git+https://x/y"
    ]


def test_extra_packages_are_a_note_and_never_a_fault(tmp_path):
    row = check(
        tmp_path,
        "kikit==1.8.1\n",
        ("kikit", "KiKit", "1.8.1"),
        ("click", "click", "8.5.0"),
        ("zeta", "Zeta", "0.1"),
        ("pip", "pip", "26.3"),
    )
    assert row["ok"] is True
    assert row["extra"] == [
        "click 8.5.0",
        "Zeta 0.1",
    ]  # pip is install.sh's own (`pip install --upgrade pip`)
    assert row["lines"] == [
        "note, not a fault: 2 installed that requirements.txt does not account for: click 8.5.0, Zeta 0.1"
    ]


def test_a_pin_met_outside_the_venv_counts_and_what_lies_outside_is_never_extra(tmp_path):
    """The venv sees the system's packages (install.sh: --system-site-packages): a pin met there is met,
    and the system's own packages are not the venv's extras."""
    own = tmp_path / "venv" / "lib" / "python3.12" / "site-packages"
    system = tmp_path / "system"
    own.mkdir(parents=True)
    dist(system, "pillow", "pillow", "12.3.0")
    dist(system, "requests", "requests", "2.34.2")
    req = tmp_path / "requirements.txt"
    req.write_text("Pillow==12.3.0\n", encoding="utf-8")
    row = wc.requirements_row(req, [own, system], [own], ENV, fix="F")
    assert row["ok"] is True and row["extra"] == []


def test_the_venv_earlier_in_the_path_wins_over_the_system(tmp_path):
    own = tmp_path / "venv" / "lib" / "python3.12" / "site-packages"
    system = tmp_path / "system"
    dist(own, "numpy", "numpy", "2.5.4")
    dist(system, "numpy", "numpy", "2.5.3")
    req = tmp_path / "requirements.txt"
    req.write_text("numpy==2.5.4\n", encoding="utf-8")
    assert wc.requirements_row(req, [own, system], [own], ENV, fix="F")["ok"] is True
    req.write_text("numpy==2.5.3\n", encoding="utf-8")
    assert wc.requirements_row(req, [own, system], [own], ENV, fix="F")["other"] == [
        "numpy==2.5.3 (2.5.4 installed)"
    ]


def test_an_unreadable_requirements_file_is_said(tmp_path):
    row = wc.requirements_row(tmp_path / "absent.txt", [], [], ENV, fix="F")
    assert row["ok"] is False
    assert row["lines"][0].startswith("not read: ") and "absent.txt" in row["lines"][0]


def test_the_fix_is_the_command_install_sh_runs():
    """The same pip line as install.sh's venv step (read, never run: M261)."""
    text = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert '"${venv}/bin/pip" install -q -r "${SRC_DIR}/requirements.txt"' in text
    venv = Path("/w/venv")
    assert wc.requirements_fix(venv, Path("/s")) == "/w/venv/bin/pip install -q -r /s/requirements.txt"


def fake_venv(tmp_path: Path, script: str) -> Path:
    """A made-up venv whose bin/python is a shell script: the probe runs it, never a real venv's pip."""
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True, exist_ok=True)
    py = venv / "bin" / "python"
    py.write_text("#!/bin/sh\n" + script + "\n", encoding="utf-8")
    py.chmod(0o755)
    return venv


def test_the_probe_path_reads_the_system_site_and_keeps_extras_to_the_venv(tmp_path):
    """The path every real machine takes: the venv's Python says its sys.path. A pin met in the system's
    site-packages is met, not missing; a package there is not an extra; one in the venv is."""
    own = tmp_path / "venv" / "lib" / "python3.12" / "site-packages"
    system = tmp_path / "system"
    dist(own, "kikit", "KiKit", "1.8.1")
    dist(own, "zeta", "Zeta", "0.1")
    dist(system, "pillow", "Pillow", "12.3.0")
    dist(system, "requests", "requests", "2.34.2")
    said = {"path": ["", str(own), str(system)], "env": ENV}
    venv = fake_venv(tmp_path, f"cat <<'EOF'\n{json.dumps(said)}\nEOF")
    src = tmp_path / "src"
    src.mkdir()
    (src / "requirements.txt").write_text("kikit==1.8.1\nPillow==12.3.0\n", encoding="utf-8")
    row = wc.requirements_doctor_row(venv, src)
    assert row["ok"] is True and row["version"] == "2 of 2 pins met"
    assert row["missing"] == [] and row["extra"] == ["Zeta 0.1"]


def test_the_probe_runs_no_code_from_the_folder_doctor_runs_in(tmp_path, monkeypatch):
    """A `platform.py` in the folder doctor runs from would shadow the standard library in `-c`."""
    here = tmp_path / "here"
    here.mkdir()
    ran = tmp_path / "ran"
    (here / "platform.py").write_text(f"open({str(ran)!r}, 'w').close()\nraise SystemExit(3)\n")
    monkeypatch.chdir(here)
    venv = fake_venv(tmp_path, f'exec {sys.executable} "$@"')
    paths, own, env = wc.venv_site(venv)
    assert not ran.exists()
    assert paths and own == [] and env["os_name"] == "posix"


def test_a_probe_that_does_not_answer_leaves_the_row_advisory(tmp_path):
    """The venv's Python failed (a timeout on a loaded machine, a shadowed module): nothing is read, so
    no pin is called missing and the workcenter is not degraded by this row."""
    venv = fake_venv(tmp_path, "echo broken; exit 3")
    (venv / "lib" / "python3.12" / "site-packages").mkdir(parents=True)
    src = tmp_path / "src"
    src.mkdir()
    (src / "requirements.txt").write_text("kikit==1.8.1\n", encoding="utf-8")
    row = wc.requirements_doctor_row(venv, src)
    assert row["advisory"] is True and row["ok"] is False
    assert row.get("missing", []) == []
    assert len(row["lines"]) == 1 and row["lines"][0].startswith("not checked: the venv's Python ")
    assert wc.doctor_checks_degraded({"requirements": row}) == []
    # No venv Python at all: the `venv` row degrades already; this one is advisory and says nothing.
    (venv / "bin" / "python").unlink()
    row = wc.requirements_doctor_row(venv, src)
    assert row["advisory"] is True and row["lines"] == []


def test_the_text_output_prints_a_row_and_its_lines_under_it():
    row = {"required": False, "ok": False, "version": "1 of 2 pins met", "lines": ["missing: a", "b"]}
    assert wc.doctor_row_text("requirements", row) == [
        "  absent   requirements 1 of 2 pins met",
        "                        missing: a",
        "                        b",
    ]


def test_range_pins_are_compared(tmp_path):
    """`>=`, `<`, `~=` and `!=` are held as `==` is; a line of 2 specifiers must meet both."""
    cases = {
        "numpy>=2.5\n": ("1.0", False),
        "numpy>=2.5\n ": ("2.5.0", True),
        "numpy<3\n": ("2.9", True),
        "numpy!=1.0\n": ("1.0", False),
        "numpy!=1.*\n": ("1.4", False),
        "numpy~=2.5\n": ("1.0", False),
        "numpy~=2.5\n ": ("3.0", False),
        "numpy~=2.5\n  ": ("2.9", True),
        "numpy>=2,==1.0\n": ("1.0", False),
        "numpy==2.0.*\n": ("2.1", False),
        "numpy==2.0.*\n ": ("2", True),
    }
    for number, (reqs, (have, ok)) in enumerate(cases.items()):
        row = check(tmp_path / str(number), reqs, ("numpy", "numpy", have))
        assert row["ok"] is ok, (reqs, have, row)
        assert row["version"] == f"{int(ok)} of 1 pins met", (reqs, have, row)


def test_a_range_pin_on_a_pre_release_is_said_not_read(tmp_path):
    row = check(tmp_path, "numpy>=2.5\n", ("numpy", "numpy", "2.6rc1"))
    assert row["ok"] is True and row["version"] == "0 of 1 pins met"
    assert row["unread"] == ["line 1: numpy>=2.5 (2.6rc1 installed, not compared)"]


def test_pip_comment_and_continuation_rules(tmp_path):
    """A tab before `#` starts a comment; a `\\` joins the next line; `--hash=` is an option, not the pin."""
    reqs = "a==1.0\t# c\nb==2.0 \\\n    --hash=sha256:ab \\\n    --hash=sha256:cd\nc==3.0\n"
    row = check(tmp_path, reqs, ("a", "a", "1.0"))
    assert row["unread"] == []
    assert row["missing"] == ["b==2.0", "c==3.0"]
    assert row["version"] == "1 of 3 pins met"


def test_2_installs_of_1_package_in_1_folder_are_a_fault(tmp_path):
    """Both metadata folders on disk: which version importlib reports hangs on the folder order."""
    row = check(tmp_path, "a==1.0\n", ("a", "a", "1.0"), ("A", "a", "2.0"))
    assert row["ok"] is False
    site = tmp_path / "venv" / "lib" / "python3.12" / "site-packages"
    assert row["broken"] == [f"a 1.0 and 2.0 in {site}"]
    assert row["lines"][0] == (
        f"broken: 1 package installed more than once in 1 folder: a 1.0 and 2.0 in {site}; "
        "remove the stale *.dist-info folder, then: PIP -r REQ"
    )
    # Every pin met, and 1 other package twice: still a fault.
    row = check(tmp_path / "2", "a==1.0\n", ("a", "a", "1.0"), ("z", "z", "1.0"), ("Z", "z", "2.0"))
    assert row["missing"] == [] and row["other"] == [] and row["version"] == "1 of 1 pins met"
    assert row["ok"] is False and len(row["broken"]) == 1
    # 2 metadata folders of 1 version (Ubuntu's python3-cryptography ships a dist-info and an
    # egg-info): the version does not hang on the order, so no fault.
    row = check(tmp_path / "3", "a==1.0\n", ("a", "a", "1.0"), ("y", "y", "41.0.7"), ("Y", "y", "41.0.7"))
    assert row["ok"] is True and row["broken"] == []


def test_doctor_has_a_requirements_row_that_degrades_and_extras_that_do_not(tmp_path, monkeypatch):
    """cmd_doctor's row: a missing pin puts `requirements` in `degraded`; extras alone leave it out."""
    rows = {}

    def fake(ok: bool) -> dict:
        return {"required": False, "ok": ok, "version": "x", "lines": []}

    for ok in (True, False):
        monkeypatch.setattr(wc, "requirements_doctor_row", lambda ok=ok: fake(ok))
        rows[ok] = wc.doctor_checks_degraded({"requirements": wc.requirements_doctor_row()})
    assert rows == {True: [], False: ["requirements"]}
