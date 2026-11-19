"""`workcenter doctor` holds the Python environment to requirements.txt.

On 2026-11-18 a stray run of install.sh added 12 packages to a machine's venv, and doctor's `venv` line
read `ok` as before: it asked only whether the folder was there. A venv that lacked a pinned package,
or held another version of it, read `ok` too, until a command failed on an import far from the cause.
The check reads installed metadata (importlib.metadata) and runs no pip. Every test here points it at
a made-up folder of *.dist-info, never at the machine's own venv."""

from __future__ import annotations

import importlib.machinery
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

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
    assert row["not_checked"] is True
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
    assert row["broken"] == [f"a 1.0 (a-1.0.dist-info) and 2.0 (A-2.0.dist-info) in {site}"]
    assert row["lines"][0] == (
        "broken: 1 package installed more than once in 1 folder: "
        f"a 1.0 (a-1.0.dist-info) and 2.0 (A-2.0.dist-info) in {site}; "
        "remove the one whose version is stale, then: PIP -r REQ"
    )
    # Every pin met, and 1 other package twice: still a fault.
    row = check(tmp_path / "2", "a==1.0\n", ("a", "a", "1.0"), ("z", "z", "1.0"), ("Z", "z", "2.0"))
    assert row["missing"] == [] and row["other"] == [] and row["version"] == "1 of 1 pins met"
    assert row["ok"] is False and len(row["broken"]) == 1
    # 2 metadata folders of 1 version (Ubuntu's python3-cryptography ships a dist-info and an
    # egg-info): the version does not hang on the order, so no fault.
    row = check(tmp_path / "3", "a==1.0\n", ("a", "a", "1.0"), ("y", "y", "41.0.7"), ("Y", "y", "41.0.7"))
    assert row["ok"] is True and row["broken"] == []


def raw_dist(site: Path, folder: str, metadata: bytes) -> Path:
    """1 metadata folder with the METADATA bytes given: for files pip would never write."""
    info = site / folder
    info.mkdir(parents=True)
    (info / "METADATA").write_bytes(metadata)
    return info


LATIN1 = b"Metadata-Version: 2.1\nName: numpy\nVersion: 2.5.4\nAuthor: Jos\xe9\n"


def test_metadata_that_is_not_utf8_is_not_read_and_does_not_crash(tmp_path):
    """An old package with a Latin-1 author name anywhere on the path (apt fills
    /usr/lib/python3/dist-packages) crashed doctor. Its folder is said under `not read`. A package no
    line names stays a note; a PINNED one whose metadata cannot be read is a fault of that pin (the
    venv cannot be shown to meet it), said with its folder, the reason and the put-right command."""
    site = tmp_path / "venv" / "lib" / "python3.12" / "site-packages"
    system = tmp_path / "system"
    dist(site, "kikit", "KiKit", "1.8.1")
    bad = raw_dist(site, "numpy-2.5.4.dist-info", LATIN1)
    old = raw_dist(system, "oldpkg-0.1.dist-info", b"Name: oldpkg\nVersion: 0.1\nAuthor: Jos\xe9\n")
    req = tmp_path / "requirements.txt"
    req.write_text("kikit==1.8.1\nnumpy==2.5.4\n", encoding="utf-8")
    row = wc.requirements_row(req, [site, system], [site], ENV, fix="F")
    assert row["ok"] is False and row["missing"] == [] and row["other"] == [] and row["extra"] == []
    assert row["version"] == "1 of 2 pins met"
    assert len(row["unread"]) == 2
    assert row["unread"][0].startswith(f"{bad}: metadata not read (UnicodeDecodeError: ")
    assert row["unread"][1].startswith(f"{old}: metadata not read (UnicodeDecodeError: ")
    assert len(row["unreadable"]) == 1
    assert row["unreadable"][0].startswith(f"numpy==2.5.4 ({bad}: metadata not read (UnicodeDecodeError: ")
    said = [line for line in row["lines"] if line.startswith("unreadable: ")]
    assert len(said) == 1 and said[0].startswith(f"unreadable: numpy==2.5.4 ({bad}: metadata not read (")
    assert said[0].endswith("; put right with: F")
    assert wc.doctor_checks_degraded({"requirements": row}) == ["requirements"]
    # Only the unpinned one unreadable (the checker's root29): a note, never a fault.
    req.write_text("kikit==1.8.1\n", encoding="utf-8")
    row = wc.requirements_row(req, [site, system], [site], ENV, fix="F")
    assert row["ok"] is True and row["version"] == "1 of 1 pins met" and row["unreadable"] == []
    assert wc.doctor_checks_degraded({"requirements": row}) == []


def test_a_pinned_package_with_no_version_line_is_a_fault_with_the_reason(tmp_path):
    site = tmp_path / "venv" / "lib" / "python3.12" / "site-packages"
    dist(site, "kikit", "KiKit", "1.8.1")
    info = raw_dist(site, "numpy-2.5.4.dist-info", b"Metadata-Version: 2.1\nName: numpy\n")
    req = tmp_path / "requirements.txt"
    req.write_text("kikit==1.8.1\nnumpy==2.5.4\n", encoding="utf-8")
    row = wc.requirements_row(req, [site], [site], ENV, fix="F")
    assert row["ok"] is False and row["other"] == [] and row["missing"] == [] and row["extra"] == []
    assert row["unread"] == [f"{info}: no Version in its metadata"]
    assert row["unreadable"] == [f"numpy==2.5.4 ({info}: no Version in its metadata)"]
    assert f"unreadable: numpy==2.5.4 ({info}: no Version in its metadata); put right with: F" in row["lines"]
    assert "( installed)" not in " ".join(row["lines"])


def test_an_unreadable_pinned_package_first_on_the_path_is_a_fault_over_one_behind_it(tmp_path):
    """The checker's R5: numpy-2.5.4.dist-info unreadable in the first folder, numpy 2.5.3 behind it.
    The import takes the first, which cannot be shown to meet the pin: a fault, and the image is
    refused (tools/image.py's judge_doctor, with no change of its own)."""
    first, behind = tmp_path / "first", tmp_path / "behind"
    bad = raw_dist(first, "numpy-2.5.4.dist-info", LATIN1)
    dist(behind, "numpy", "numpy", "2.5.3")
    req = tmp_path / "requirements.txt"
    req.write_text("numpy==2.5.4\n", encoding="utf-8")
    row = wc.requirements_row(req, [first, behind], [first], ENV, fix="F")
    assert row["ok"] is False and row["version"] == "0 of 1 pins met"
    assert row["unreadable"][0].startswith(f"numpy==2.5.4 ({bad}: metadata not read (")
    image = load_image_module()
    payload = {"status": "degraded", "checks": {"requirements": row}}
    assert "requirements: not ok in the image" in image.judge_doctor(payload, "x86_64")


def load_image_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("image_for_doctor_tests", ROOT / "tools" / "image.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BOMB = "1" + "0" * 4999  # 5000 digits: int() refuses more than 4300


def test_a_version_of_5000_digits_is_not_read_for_that_package_alone(tmp_path):
    """The checker's R2: 1 such package anywhere on the path made int() raise in the version readers,
    the guard turned the whole row off, and a real fault beside it went unsaid with doctor `ok`."""
    site = tmp_path / "site"
    dist(site, "numpy", "numpy", "2.5.3")
    zz = raw_dist(site, "zz-1.dist-info", f"Name: zz\nVersion: {BOMB}\n".encode())
    req = tmp_path / "requirements.txt"
    req.write_text("numpy==2.5.4\n", encoding="utf-8")
    row = wc.requirements_row(req, [site], [site], ENV, fix="F")
    assert row["ok"] is False and row["other"] == ["numpy==2.5.4 (2.5.3 installed)"]
    assert len(row["unread"]) == 1 and row["unread"][0].startswith(f"{zz}: Version not read (")
    assert row["extra"] == []
    # The readers themselves never raise.
    assert wc.release_key(BOMB) == ((), BOMB) and wc.epoch_release(BOMB) is None
    assert wc.release_parts(BOMB) is None and wc.spec_met(BOMB, ">=", "1") is None
    assert wc.spec_met("1.0", "==", BOMB) is False and wc.version_matches(BOMB, "1.*") is None
    with pytest.raises(ValueError):  # a marker not read, as every other the reader cannot read
        wc.marker_true(f'python_version >= "{BOMB}"', ENV)


def test_a_name_taken_from_a_folder_ends_at_the_last_dash_before_a_digit(tmp_path):
    """A metadata folder with no METADATA: its name is the folder's up to the last `-` followed by a
    digit, compared by PEP 503. It is pinned, so the pin is a fault (unreadable), never `missing`."""
    for number, (folder, pin) in enumerate(
        [
            ("a-b-1.0.dist-info", "a-b==1.0"),
            ("a_b-1.0.dist-info", "a-b==1.0"),
            ("weird.dist-info", "weird==1.0"),
            ("x-1.0-py3.13.egg-info", "x==1.0"),
        ]
    ):
        site = tmp_path / str(number)
        (site / folder).mkdir(parents=True)
        req = tmp_path / f"{number}.txt"
        req.write_text(pin + "\n", encoding="utf-8")
        row = wc.requirements_row(req, [site], [site], ENV, fix="F")
        assert row["missing"] == [], (folder, row)
        assert row["unreadable"] == [f"{pin} ({site / folder}: no Name in its metadata)"], (folder, row)
        assert row["ok"] is False


def doctor_with_a_check_that_raises(tmp_path: Path, *argv: str) -> subprocess.CompletedProcess:
    """The whole `doctor` in a subprocess, on a made-up root, with importlib.metadata.distributions
    replaced by a stand-in that raises: the check fails inside, where only cmd_doctor's guard holds it.
    kicad-cli, ngspice and java point at an absent path, so no engine starts."""
    base = tmp_path / "root"
    site = base / "venv" / "lib" / "python3.12" / "site-packages"
    if not site.is_dir():
        dist(site, "kikit", "KiKit", "1.8.1")
    fake_venv(base, f"cat <<'EOF'\n{json.dumps({'path': [str(site)], 'env': ENV})}\nEOF")
    absent = str(tmp_path / "absent")
    env = {**os.environ, "WORKCENTER_ROOT": str(base), "HOME": str(tmp_path)}
    env.update(KICAD_CLI=absent, NGSPICE=absent, JAVA=absent)
    stand_in = (
        "import importlib.metadata, runpy, sys\n"
        "def boom(*a, **k):\n"
        "    raise RuntimeError('a stand-in raised inside the check')\n"
        "importlib.metadata.distributions = boom\n"
        "cli = sys.argv[1]\n"
        "sys.argv = [cli, *sys.argv[2:]]\n"
        "runpy.run_path(cli, run_name='__main__')\n"
    )
    return subprocess.run(
        [sys.executable, "-c", stand_in, str(CLI), *argv],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
        timeout=120,
        check=False,
    )


def test_doctor_takes_the_requirements_row_through_its_guard_and_says_it_was_not_checked(tmp_path):
    """cmd_doctor must call the guarded row: called directly, the stand-in's error is a traceback.
    A row not checked is said on the status line and in --json, so nobody reads a plain `ok`."""
    proc = doctor_with_a_check_that_raises(tmp_path, "doctor")
    assert "Traceback" not in proc.stderr and "Traceback" not in proc.stdout, proc.stderr
    lines = proc.stdout.splitlines()
    assert "requirements not checked  (root " in lines[0], lines[0]
    assert any(
        line.strip() == "not checked: RuntimeError: a stand-in raised inside the check" for line in lines
    ), proc.stdout
    proc = doctor_with_a_check_that_raises(tmp_path, "--json", "doctor")
    payload = json.loads(proc.stdout)
    assert payload["not_checked"] == ["requirements"]
    assert payload["checks"]["requirements"]["advisory"] is True
    assert "requirements" not in payload["degraded"]


def test_the_status_line_names_a_row_not_checked():
    assert wc.doctor_status_words("ok", [], []) == "ok"
    assert wc.doctor_status_words("ok", [], ["requirements"]) == "ok, requirements not checked"
    assert (
        wc.doctor_status_words("degraded", ["freerouting"], ["requirements"])
        == "degraded, without freerouting; requirements not checked"
    )
    # The probe that did not answer is `not checked` too.
    row = {"required": False, "advisory": True, "ok": False, "not_checked": True, "lines": []}
    assert wc.doctor_not_checked({"requirements": row, "venv": {"ok": True}}) == ["requirements"]


DEEP = "(" * 2000 + "python_version >= '3'" + ")" * 2000


def test_a_marker_nested_2000_deep_is_not_read_and_does_not_crash(tmp_path):
    """In requirements.txt and in an installed package's Requires-Dist."""
    row = check(tmp_path / "a", f"kikit==1.8.1 ; {DEEP}\n", ("kikit", "KiKit", "1.8.1"))
    assert row["ok"] is True and row["extra"] == [] and len(row["unread"]) == 2
    assert row["unread"][0].startswith("line 1: kikit==1.8.1 ; (((") and len(row["unread"][0]) < 200
    assert row["unread"][1] == "line 1 names KiKit 1.8.1 (installed, the line not compared)"
    row = check(
        tmp_path / "b",
        "kikit==1.8.1\n",
        ("kikit", "KiKit", "1.8.1", f"zeta ; {DEEP}"),
        ("zeta", "zeta", "0.1"),
    )
    assert row["ok"] is True and row["version"] == "1 of 1 pins met" and row["extra"] == []
    assert len(row["unread"]) == 1 and len(row["unread"][0]) < 200
    assert row["unread"][0].startswith("KiKit 1.8.1: Requires-Dist zeta ; (((")
    assert row["unread"][0].endswith("(its marker not read)")


def test_a_file_with_a_byte_order_mark_is_read_as_pip_reads_it(tmp_path):
    """pip decodes requirements.txt by its BOM: a UTF-8 BOM hid the first pin, and UTF-16 was not read."""
    for number, encoding in enumerate(("utf-8-sig", "utf-16")):
        site = tmp_path / str(number) / "site"
        dist(site, "kikit", "KiKit", "1.8.1")
        req = tmp_path / str(number) / "requirements.txt"
        req.write_text("kikit==1.8.1\nnumpy==9.9\n", encoding=encoding)
        row = wc.requirements_row(req, [site], [site], ENV, fix="F")
        assert row["unread"] == [] and row["extra"] == [], (encoding, row)
        assert row["missing"] == ["numpy==9.9"] and row["version"] == "1 of 2 pins met"


def test_a_package_named_by_a_line_not_read_is_never_an_extra(tmp_path):
    """A URL requirement and a pin with a per-requirement option are not read; the package each names
    is said to be named by a line not compared, not called unaccounted for."""
    reqs = "kikit @ https://example.invalid/kikit-1.8.1.tar.gz\nnumpy==2.5.4 --config-settings x=y\n"
    row = check(
        tmp_path,
        reqs,
        ("kikit", "KiKit", "1.8.1", "pcbnewTransition>=0.5"),
        ("pcbnewtransition", "pcbnewTransition", "0.5.2"),
        ("numpy", "numpy", "2.5.4"),
        ("zeta", "zeta", "0.1"),
    )
    assert row["ok"] is True and row["extra"] == ["zeta 0.1"]
    assert row["unread"] == [
        "line 1: kikit @ https://example.invalid/kikit-1.8.1.tar.gz",
        "line 2: numpy==2.5.4 --config-settings x=y",
        "line 1 names KiKit 1.8.1 (installed, the line not compared)",
        "line 2 names numpy 2.5.4 (installed, the line not compared)",
    ]


def test_an_egg_info_beside_a_dist_info_is_named_as_it_is(tmp_path):
    site = tmp_path / "site"
    dist(site, "kikit", "KiKit", "1.8.1")
    (site / "KiKit-1.7.0-py3.13.egg-info").write_text("Name: KiKit\nVersion: 1.7.0\n", encoding="utf-8")
    req = tmp_path / "requirements.txt"
    req.write_text("kikit==1.8.1\n", encoding="utf-8")
    row = wc.requirements_row(req, [site], [site], ENV, fix="F")
    assert row["ok"] is False
    assert row["broken"] == [
        f"KiKit 1.7.0 (KiKit-1.7.0-py3.13.egg-info) and 1.8.1 (kikit-1.8.1.dist-info) in {site}"
    ]
    assert row["lines"][0].endswith("; remove the one whose version is stale, then: F")
    assert "*.dist-info" not in row["lines"][0]


def test_pep_440_local_labels_and_prefix_matches(tmp_path):
    """A public pin ignores a candidate's local label (`==2.0` matches `2.0+cpu`); a `.*` prefix
    compares the release segment, so a pre-release, post-release or local version within it matches."""
    cases = [
        ("numpy==2.5.*", "2.5.4rc1", True),
        ("numpy==2.5.*", "2.5.post1", True),
        ("numpy==2.5.*", "2.5.4+cpu", True),
        ("numpy==2.5.*", "2.6rc1", False),
        ("numpy==2.*", "1!2.0", False),
        ("numpy==1!2.*", "1!2.3", True),
        ("torch==2.0", "2.0+cpu", True),
        ("torch==2.0.0", "2.0+cpu", True),
        ("torch==2.0+cpu", "2.0+cpu", True),
        ("torch==2.0+cu121", "2.0+cpu", False),
        ("torch==2.1", "2.0+cpu", False),
        ("torch!=2.0", "2.0+cpu", False),
    ]
    for number, (pin, have, ok) in enumerate(cases):
        name = pin.split("=")[0].rstrip("!")
        row = check(tmp_path / str(number), pin + "\n", (name, name, have))
        assert row["ok"] is ok and row["unread"] == [], (pin, have, row)
        assert row["version"] == f"{int(ok)} of 1 pins met", (pin, have, row)


def test_any_exception_in_the_requirements_check_is_an_advisory_line(monkeypatch):
    """The row in cmd_doctor is guarded: whatever the check raises is 1 line, never a traceback and
    never `degraded` on its own."""

    def boom(*_a, **_k):
        raise RuntimeError("boom\nsecond line")

    monkeypatch.setattr(wc, "requirements_doctor_row", boom)
    row = wc.requirements_doctor_row_checked()
    assert row["advisory"] is True and row["ok"] is False
    assert row["lines"] == ["not checked: RuntimeError: boom second line"]
    assert row["not_checked"] is True
    assert wc.doctor_checks_degraded({"requirements": row}) == []


def test_doctor_with_unreadable_metadata_on_the_venv_path_prints_its_row(tmp_path):
    """The checker's reproducer: a made-up WORKCENTER_ROOT whose venv Python reports a folder holding
    a METADATA that is not UTF-8. Doctor exits as it does without that folder, with no traceback."""

    def root(name: str, with_bad: bool) -> Path:
        base = tmp_path / name
        site = base / "venv" / "lib" / "python3.12" / "site-packages"
        dist(site, "kikit", "KiKit", "1.8.1")
        paths = [str(site)]
        if with_bad:
            raw_dist(base / "badsite", "oldpkg-0.1.dist-info", b"Name: oldpkg\nAuthor: Jos\xe9\n")
            paths.append(str(base / "badsite"))
        fake_venv(base, f"cat <<'EOF'\n{json.dumps({'path': paths, 'env': ENV})}\nEOF")
        return base

    def doctor(base: Path) -> subprocess.CompletedProcess:
        # No engine starts: kicad-cli, ngspice and java are pointed at a path that is not there, so
        # doctor's exit code is the same `fail` on every machine, with or without the bad folder.
        absent = str(tmp_path / "absent")
        env = {**os.environ, "WORKCENTER_ROOT": str(base), "HOME": str(tmp_path)}
        env.update(KICAD_CLI=absent, NGSPICE=absent, JAVA=absent)
        return subprocess.run(
            [sys.executable, str(CLI), "doctor"],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(tmp_path),
            timeout=120,
            check=False,
        )

    good, bad = doctor(root("good", False)), doctor(root("bad", True))
    assert "Traceback" not in bad.stderr and "Traceback" not in bad.stdout, bad.stderr
    assert bad.returncode == good.returncode
    folder = tmp_path / "bad" / "badsite" / "oldpkg-0.1.dist-info"
    row = [line for line in bad.stdout.splitlines() if f"{folder}: metadata not read (" in line]
    assert len(row) == 1 and "UnicodeDecodeError" in row[0], bad.stdout
    assert row[0].lstrip().startswith(f"not read: {folder}: metadata not read (UnicodeDecodeError: ")


def test_doctor_has_a_requirements_row_that_degrades_and_extras_that_do_not(tmp_path, monkeypatch):
    """cmd_doctor's row: a missing pin puts `requirements` in `degraded`; extras alone leave it out."""
    rows = {}

    def fake(ok: bool) -> dict:
        return {"required": False, "ok": ok, "version": "x", "lines": []}

    for ok in (True, False):
        monkeypatch.setattr(wc, "requirements_doctor_row", lambda ok=ok: fake(ok))
        rows[ok] = wc.doctor_checks_degraded({"requirements": wc.requirements_doctor_row()})
    assert rows == {True: [], False: ["requirements"]}
