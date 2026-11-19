"""`workcenter` where no home folder is known (M299): HOME unset and the user id has no line in
/etc/passwd, as in Via's image run as the runner's user id. Path.home() raises RuntimeError there, and
tools/workcenter asked it at import: every command ended in a traceback before it began (pull request
124, job `full`: `RuntimeError: Could not determine home directory.`). conftest.no_home starts a
process under that condition; these tests start the CLI so and see each command do its work."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from conftest import no_home

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
INSTALL_HOOKS = ROOT / "tools" / "hooks" / "install_hooks.py"


def clean(ran: subprocess.CompletedProcess) -> None:
    both = ran.stdout + ran.stderr
    assert "Traceback" not in both and "RuntimeError" not in both, both


def test_the_condition_holds_path_home_raises_in_the_child(tmp_path):
    """The condition these tests make is the one CI met: Path.home() raises in the child."""
    script = tmp_path / "home.py"
    script.write_text("from pathlib import Path\nPath.home()\n", encoding="utf-8")
    ran = no_home(script)
    assert ran.returncode == 1
    assert ran.stderr.strip().splitlines()[-1] == "RuntimeError: Could not determine home directory."


def test_gates_on_a_folder_not_there_says_not_found(tmp_path):
    """The failure of pull request 124 reproduced: `gates -- --help` judges `--help` as a folder."""
    folder = tmp_path / "--help"
    ran = no_home(CLI, "gates", "--", folder, env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"})
    clean(ran)
    assert ran.returncode == 1, ran.stdout + ran.stderr
    assert ran.stderr.strip().splitlines()[-1] == f"{folder}: not found"


def test_help_starts_and_prints_the_usage():
    ran = no_home(CLI, "--help")
    clean(ran)
    assert ran.returncode == 0 and ran.stdout.startswith("usage: workcenter"), ran.stdout + ran.stderr


def test_next_answers_as_it_does_with_a_home(tmp_path):
    """No home changes nothing `next` says: the same lines and exit code as with HOME set."""
    with_home = subprocess.run(
        [sys.executable, str(CLI), "next", str(tmp_path)], capture_output=True, text=True, check=False
    )
    ran = no_home(CLI, "next", tmp_path)
    clean(ran)
    assert (ran.returncode, ran.stdout) == (with_home.returncode, with_home.stdout)
    assert "RUN        workcenter new " in ran.stdout


def test_doctors_hook_rows_name_the_settings_path_as_unknown(tmp_path):
    """`doctor` reads the user-wide settings for its 2 hook rows (it also starts kicad-cli and ngspice,
    so the rows are asked here without it). With no home they are absent, advisory, and the path says
    why and what to do; the doctor goes on."""
    script = tmp_path / "rows.py"
    script.write_text(
        "import json, runpy, sys\n"
        "cli = runpy.run_path(sys.argv[1], run_name='workcenter_cli')\n"
        "print(json.dumps([cli['hook_row'](n) for n in ('no_cd.py', 'no_script_test_edits.py')]))\n",
        encoding="utf-8",
    )
    ran = no_home(script, CLI)
    clean(ran)
    assert ran.returncode == 0, ran.stderr
    rows = json.loads(ran.stdout)
    unknown = (
        "unknown: no home folder is known (HOME is unset and the user id has no line in /etc/passwd); "
        "set HOME"
    )
    assert rows == [{"required": False, "advisory": True, "ok": False, "path": unknown}] * 2


def test_the_hook_installer_asks_for_home_or_settings_and_takes_settings(tmp_path):
    """The installer writes the user-wide settings: with no home and no --settings it refuses in 1 line
    a person can act on and writes nothing; named, the file gets both hooks."""
    ran = no_home(INSTALL_HOOKS)
    clean(ran)
    assert ran.returncode == 2 and ran.stdout == ""
    assert ran.stderr.splitlines() == [
        "hooks: no home folder is known (HOME is unset and the user id has no line in /etc/passwd): "
        "set HOME, or name the settings file with --settings"
    ]
    settings = tmp_path / "settings.json"
    ran = no_home(INSTALL_HOOKS, "--settings", settings)
    clean(ran)
    assert ran.returncode == 0 and len(ran.stdout.splitlines()) == 2, ran.stdout + ran.stderr
    assert json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
