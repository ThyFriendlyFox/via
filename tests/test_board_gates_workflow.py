"""`.github/workflows/board-gates.yml`: `workcenter gates` for a board repository, as 1 reusable workflow.

GitHub Actions does not run here, and no registry or Docker daemon answers. Each step is held by its own
text, run under `bash -e` as the runner runs a `run:` step, with a stand-in for every command whose answer
depends on the machine (`docker`, `sudo`, `id`, the workcenter itself): PROCESSES.md P2 step 8. A small
runner below walks the whole job on both paths, the image and install.sh, with GitHub's `if:` and step
outputs. 2 engine tests run the gates step on this machine's toolchain, on a copy of 1 fixture each.

What only a real run in a board repository shows: that GitHub resolves the `uses:` line and the matrix
from the input, that the caller's token may pull the image, the summary as GitHub renders it, the
install path's time on a runner, and on the image path, which is the normal one: `docker run --user`
writing the board's files, `image.py check` inside the image, and the gates with no home for that user.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import image  # noqa: E402

FLOWS = ROOT / ".github" / "workflows"
FLOW = FLOWS / "board-gates.yml"
FIXTURE_FLOW = FLOWS / "board-fixture.yml"
SKILL = ROOT / ".claude" / "skills" / "board-ci" / "SKILL.md"
USES = "ThyFriendlyFox/via/.github/workflows/board-gates.yml"
PIN = "<sha>"
INSTALL = "./install.sh"
ARCHIVE = "sudo env APT_ARCHIVE_CI=1 bash tools/ci/apt_archive.sh /etc/apt"
REAL_PYTHON = shutil.which("python3") or sys.executable


def flow(path: Path = FLOW) -> dict:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def job() -> dict:
    return flow()["jobs"]["gates"]


def step_named(start: str) -> dict:
    (step,) = [s for s in job()["steps"] if s.get("name", "").startswith(start)]
    return step


def stub(folder: Path, name: str, body: str) -> None:
    folder.mkdir(exist_ok=True)
    (folder / name).write_text(f"#!/bin/bash\n{body}\n", encoding="utf-8")
    (folder / name).chmod(0o755)


# ---------------------------------------------------------------- the workflow's shape


def test_a_caller_names_its_projects_and_every_input_has_its_default():
    """A caller passes nothing and gets the gates of its root folder, not strict, in the image of the
    workcenter's main where it can be pulled, else on install.sh after the archive step."""
    f = flow()
    assert list(f[True]) == ["workflow_call"]
    inputs = f[True]["workflow_call"]["inputs"]
    defaults = {name: spec.get("default") for name, spec in inputs.items()}
    assert defaults == {
        "projects": '["."]',
        "strict": False,
        "workcenter-repository": "ThyFriendlyFox/via",
        "workcenter-ref": "main",
        "use-image": True,
        "apt-ubuntu-archive": True,
    }
    assert {name: spec["type"] for name, spec in inputs.items()} == {
        "projects": "string",
        "strict": "boolean",
        "workcenter-repository": "string",
        "workcenter-ref": "string",
        "use-image": "boolean",
        "apt-ubuntu-archive": "boolean",
    }
    assert all(spec.get("description") for spec in inputs.values())


def test_1_job_per_project_reads_the_board_and_nothing_more():
    """P2 step 7: a step that loops over boards grows with each; each board is a job of its own, under
    its own limit, and 1 red board does not cancel the others. The token reads the repository and
    writes nothing: the check and the summary are the output (the item's scope guard). R16-F2: the
    package is public, so the job asks for no `packages: read`."""
    f = flow()
    assert list(f["jobs"]) == ["gates"]
    j = job()
    assert j["strategy"] == {"fail-fast": False, "matrix": {"project": "${{ fromJSON(inputs.projects) }}"}}
    assert j["permissions"] == {"contents": "read"}
    assert j["runs-on"] == "ubuntu-24.04"
    runs = "\n".join(s.get("run", "") for s in j["steps"])
    assert re.findall(r"\b(gh|curl|wget)\b", runs) == []


def test_the_board_then_the_workcenter_are_checked_out_and_keep_no_credentials():
    steps = job()["steps"]
    board, via = steps[0], steps[1]
    assert board["uses"] == "actions/checkout@v4" and board["with"] == {"persist-credentials": False}
    assert via["uses"] == "actions/checkout@v4"
    assert via["with"] == {
        "repository": "${{ inputs.workcenter-repository }}",
        "ref": "${{ inputs.workcenter-ref }}",
        "path": ".via",
        "persist-credentials": False,
    }


def test_no_step_logs_in_or_holds_the_jobs_token():
    """R16-F2: `docker login` with the job's token stored it in ~/.docker/config.json, and on the install
    path the gates and the board's decks then ran on the host as that user. The package is public: an
    anonymous pull needs no login, so no step holds the token."""
    text = FLOW.read_text(encoding="utf-8")
    assert "docker login" not in text
    assert "github.token" not in text and "secrets." not in text
    for step in job()["steps"]:
        assert "TOKEN" not in step.get("env", {}), step.get("name")


def test_no_run_line_holds_an_expression():
    """A project's name and every input reach a script through `env:` alone: a folder named
    `$(rm -rf ~)` stays a word (GitHub's "Security hardening for GitHub Actions", script injection)."""
    for step in job()["steps"]:
        assert "${{" not in step.get("run", ""), step.get("name")


def test_the_job_order_is_tag_where_archive_install_gates_summary():
    names = [s.get("name", s.get("uses")) for s in job()["steps"]]
    conds = [s.get("if") for s in job()["steps"]]
    install = "steps.where.outputs.where == 'install'"
    assert conds == [None, None, None, None, install, install, None, "always()"], names
    assert [s.get("id") for s in job()["steps"]][2:4] == ["tag", "where"]


def test_shellcheck_reads_every_run_step_clean(tmp_path):
    """The runner runs each `run:` with bash; shellcheck reads each as a bash script of its own."""
    if shutil.which("shellcheck") is None:
        pytest.skip("shellcheck is not on PATH")
    scripts = []
    for i, step in enumerate(job()["steps"]):
        if "run" in step:
            scripts.append(tmp_path / f"step-{i}.sh")
            scripts[-1].write_text("#!/bin/bash\n" + step["run"], encoding="utf-8")
    assert len(scripts) == 6
    ran = subprocess.run(["shellcheck", *map(str, scripts)], capture_output=True, text=True)
    assert ran.returncode == 0, ran.stdout


# ---------------------------------------------------------------- the install path is CI's


def ci_install_line() -> str:
    full = flow(FLOWS / "ci.yml")["jobs"]["full"]
    (line,) = [s["run"] for s in full["steps"] if INSTALL in s.get("run", "")]
    return line


def test_the_install_path_runs_the_archive_step_then_install_sh_with_cis_2_bounds():
    """CI's install path: tools/ci/apt_archive.sh, then install.sh, both from the workcenter's checkout.
    The runner's regional mirror crawled to the download's bound in CI runs 44402154007 and 44432768560,
    and the archive step's first run, CI run 44444183056, installed in 1 min 29 s (ee-agent-kit/CI.md,
    "Toolchain step"). The 2 bounds are CI's: 120 s for each index update and 570 s for the download.
    REQUIRE_FREEROUTING is not set: the 4 gates route nothing, so a blocked FreeRouting download does
    not turn a board red."""
    archive, install = step_named("Ask Ubuntu's own archive"), step_named("Install the workcenter")
    for step in (archive, install):
        assert step["working-directory"] == ".via"
    assert [x.strip() for x in archive["run"].splitlines()].count(ARCHIVE) == 1
    assert archive["env"] == {"ENABLED": "${{ inputs.apt-ubuntu-archive }}"}
    bounds = dict(re.findall(r"\b(APT_(?:UPDATE|DOWNLOAD)_TIMEOUT)=(\S+)", install["run"]))
    assert bounds == dict(re.findall(r"\b(APT_(?:UPDATE|DOWNLOAD)_TIMEOUT)=(\S+)", ci_install_line()))
    assert bounds == {"APT_UPDATE_TIMEOUT": "120", "APT_DOWNLOAD_TIMEOUT": "570"}
    assert install["run"].strip() == f"sudo env APT_UPDATE_TIMEOUT=120 APT_DOWNLOAD_TIMEOUT=570 {INSTALL}"


def test_the_jobs_limit_holds_the_worst_apt_step_and_leaves_the_gates_their_time():
    """45 minutes, the nightly run's: 2700 s. The job's 2 bounds hold the key, the update and the main
    download to 88 + 3 x 120 + 2 x 20 + 570 = 1058 s (ee-agent-kit/CI.md, "Toolchain step"; this job sets
    no APT_OTHER_TIMEOUT, so the openEMS step's download has no bound here) and the steps around it took 9 + 27 + 28 = 64 s in
    job 134941364976 (tests/test_install_apt.py, the worst case's docstring): 2700 - 1058 - 64 = 1578 s
    are left for the checkouts, the pull and the gates."""
    assert job()["timeout-minutes"] == 45
    assert 45 * 60 - (88 + 3 * 120 + 2 * 20 + 570) - (9 + 27 + 28) == 1578


def test_the_limits_comment_names_the_install_steps_with_no_bound_of_their_own():
    """R16-F6: 1578 s is not a worst case. install.sh's main() also runs step_freerouting and step_openems
    (curl with no --max-time) and step_python (pip), and has no switch that skips them; only the job's
    45 minutes bounds them. The comment names them, and the skill gives a time it can source (CI.md: the
    install step took 1 min 29 s in CI run 44444183056), not "2 to 10 minutes"."""
    script = (ROOT / "install.sh").read_text(encoding="utf-8")
    main = re.search(r"^main\(\) \{\n(.*?)^\}", script, re.S | re.M)
    for name in ("step_freerouting", "step_openems", "step_python"):
        assert re.search(rf"^\s+{name}$", main.group(1), re.M), name
    comments = " ".join(
        line.strip().lstrip("#").strip()
        for line in FLOW.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("#")
    )
    assert "step_freerouting, step_openems and step_python" in comments
    assert "not a worst case" in comments
    skill = " ".join(SKILL.read_text(encoding="utf-8").split())
    assert "2 to 10 minutes" not in skill
    assert "1 min 29 s" in skill and "44444183056" in skill


@pytest.mark.parametrize("value", ["true", "false"])
def test_the_archive_step_runs_under_sudo_unless_the_input_is_false(tmp_path, value):
    """`sudo` is a stand-in that writes its arguments and runs nothing. `false` turns the step off with
    1 line that names the input."""
    bin_ = tmp_path / "bin"
    calls = tmp_path / "calls"
    stub(bin_, "sudo", f'printf "%s\\n" "$*" >> {calls}')
    env = {"PATH": str(bin_), "ENABLED": value}
    run = step_named("Ask Ubuntu's own archive")["run"]
    ran = subprocess.run(["/bin/bash", "-e", "-c", run], env=env, capture_output=True, text=True)
    assert ran.returncode == 0, ran.stderr
    said = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
    if value == "false":
        assert said == []
        assert ran.stdout.splitlines() == [
            "[apt-archive] off: the input apt-ubuntu-archive is false; apt keeps the runner's mirror"
        ]
    else:
        assert said == [ARCHIVE.removeprefix("sudo ")]


# ---------------------------------------------------------------- where the gates run


def where_case(tmp_path: Path, use: str, pull: int, said: str) -> tuple[int, str, dict, list]:
    bin_ = tmp_path / f"bin-{use}-{pull}"
    calls = tmp_path / f"calls-{use}-{pull}"
    body = (
        f'printf "%s\\n" "$*" >> {calls}\n'
        'case "$1" in\n'
        '  pull) if [ "$PULL" = 0 ]; then echo "$3"; else printf "%b" "$SAID" >&2; fi; exit $PULL ;;\n'
        "esac\n"
        "exit 9"
    )
    stub(bin_, "docker", body)
    out = tmp_path / f"out-{use}-{pull}"
    out.write_text("", encoding="utf-8")
    env = {
        "PATH": f"{bin_}:/usr/bin:/bin",
        "USE_IMAGE": use,
        "IMAGE": "ghcr.io/o/via",
        "TAG": "tc-0123456789abcdef",
        "GITHUB_ACTOR": "a",
        "GITHUB_OUTPUT": str(out),
        "PULL": str(pull),
        "SAID": said,
    }
    run = step_named("Where the gates run")["run"]
    ran = subprocess.run(["bash", "-e", "-c", run], env=env, capture_output=True, text=True)
    outputs = dict(line.split("=", 1) for line in out.read_text(encoding="utf-8").splitlines())
    seen = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
    return ran.returncode, ran.stdout, outputs, seen


def test_a_pulled_image_is_where_the_gates_run(tmp_path):
    code, out, outputs, seen = where_case(tmp_path, "true", 0, "")
    ref = "ghcr.io/o/via:tc-0123456789abcdef"
    assert code == 0
    assert outputs == {"where": "image", "image": ref, "reason": f"the registry gave {ref}"}
    assert out.splitlines() == [f"where: image: the registry gave {ref}"]
    assert seen == [f"pull --quiet {ref}"]


def test_an_image_the_registry_refuses_sends_the_gates_to_install_sh_with_dockers_last_line(tmp_path):
    """The registry refuses a pull when it holds no image of that toolchain, or when the package is not
    public. No login is made (R16-F2)."""
    said = "Error response from daemon: Head x: unauthorized\\nError response from daemon: denied"
    code, out, outputs, seen = where_case(tmp_path, "true", 1, said)
    ref = "ghcr.io/o/via:tc-0123456789abcdef"
    reason = f"the registry gave no {ref}: Error response from daemon: denied"
    assert code == 0
    assert outputs == {"where": "install", "image": "", "reason": reason}
    assert out.splitlines() == [f"where: install: {reason}"]
    assert seen == [f"pull --quiet {ref}"]


def test_a_refusal_with_no_words_names_dockers_exit_code(tmp_path):
    code, _, outputs, _ = where_case(tmp_path, "true", 125, "")
    assert code == 0 and outputs["where"] == "install"
    assert (
        outputs["reason"]
        == "the registry gave no ghcr.io/o/via:tc-0123456789abcdef: docker pull exit code 125"
    )


def test_use_image_false_asks_no_registry(tmp_path):
    code, out, outputs, seen = where_case(tmp_path, "false", 0, "")
    assert code == 0 and seen == []
    assert outputs == {"where": "install", "image": "", "reason": "the input use-image is false"}


# ---------------------------------------------------------------- the gates step


GREEN_TABLE = (
    "| Gate | Status | Summary |\n|---|---|---|\n"
    "| ERC | pass | 0 errors, 0 warnings |\n"
    "| DRC | pass | 0 violations |\n"
    "| SIM | pass | 1 decks, 46 corner runs, 0 failures |\n"
    "| EXPORT | pass | gerbers |\n\n"
    "GREEN on 2026-11-19: `workcenter gates` with KiCad 10.0.8, ngspice 42.\n"
)
# The stand-ins write $TABLE where --report names, as `workcenter gates` does.
WRITES = 'prev=""; for a in "$@"; do [ "$prev" = --report ] && printf "%s" "$TABLE" > "$a"; prev=$a; done'


def gates_case(
    tmp_path: Path,
    where: str,
    code: int = 0,
    strict: str = "false",
    id_code: int = 0,
    project: str = "v0.2/display",
    table: str = GREEN_TABLE,
    out: list | None = None,
):
    bin_ = tmp_path / "bin"
    calls = tmp_path / "calls"
    calls.unlink(missing_ok=True)
    shutil.rmtree(tmp_path / "rt", ignore_errors=True)
    stub(bin_, "python3", f'printf "python3 %s\\n" "$*" >> {calls}; {WRITES}; exit $CODE')
    stub(bin_, "docker", f'printf "docker %s\\n" "$*" >> {calls}; {WRITES}; exit $CODE')
    stub(bin_, "id", 'case "$1" in -u) echo 1001; exit $ID_CODE ;; -g) echo 121 ;; esac')
    env = {
        "PATH": f"{bin_}:/usr/bin:/bin",
        "WHERE": where,
        "IMAGE": "ghcr.io/o/via:tc-x",
        "PROJECT": project,
        "STRICT": strict,
        "RUNNER_TEMP": str(tmp_path / "rt"),
        "GITHUB_WORKSPACE": "/ws",
        "CODE": str(code),
        "ID_CODE": str(id_code),
        "TABLE": table,
    }
    ran = subprocess.run(
        ["bash", "-e", "-c", step_named("workcenter gates")["run"]], env=env, text=True, capture_output=True
    )
    if out is not None:
        out[:] = ran.stdout.splitlines()
    said = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
    return ran.returncode, [line.replace(str(tmp_path / "rt"), "/rt") for line in said]


def test_the_install_path_runs_the_checkouts_workcenter_and_its_exit_code_is_the_check(tmp_path):
    """`workcenter gates` exits 0 on GREEN, 1 on RED and 2 on SKIPPED (tools/workcenter, gates_verdict):
    the step ends with that code, so only GREEN is a green check. R16-N2: the project comes after `--`."""
    line = "python3 .via/tools/workcenter gates --report /rt/board-gates/board-gates.md"
    for code in (0, 1, 2):
        assert gates_case(tmp_path, "install", code) == (code, [line + " -- v0.2/display"])
    assert gates_case(tmp_path, "install", 0, "true") == (0, [line + " --strict -- v0.2/display"])


@pytest.mark.parametrize("where", ["install", "image"])
def test_a_project_named_like_an_option_goes_after_a_double_dash(tmp_path, where):
    """R16-N2: `PROJECT=--help` reached argparse as an option: it printed its usage, exit 0, and the job
    was green with nothing judged. The name now follows `--`, on both paths."""
    code, calls = gates_case(tmp_path, where, 0, project="--help")
    assert code == 0
    (call,) = calls
    assert call.endswith(" gates --report /rt/board-gates/board-gates.md -- --help"), call


def test_a_project_named_help_is_judged_as_a_folder_by_the_real_workcenter(tmp_path):
    """R16-N2 with the real `workcenter gates` (no engine starts: the folder is not there). Before the
    fix the step printed argparse's usage and ended 0 with no report; now the gates judge `--help` as a
    path, which is not found: red, and no usage text."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / ".via").symlink_to(ROOT)
    bin_ = tmp_path / "bin"
    stub(bin_, "python3", f'exec {sys.executable} "$@"')
    env = {
        "PATH": f"{bin_}:/usr/bin:/bin",
        "WHERE": "install",
        "PROJECT": "--help",
        "STRICT": "false",
        "RUNNER_TEMP": str(tmp_path / "rt"),
        "GITHUB_WORKSPACE": str(ws),
        "PYTHONDONTWRITEBYTECODE": "1",
        # The workcenter's own engine lock, in a folder of this test's: nothing here waits on another run.
        "WORKCENTER_LOCK_DIR": str(tmp_path / "lock"),
    }
    ran = subprocess.run(
        ["bash", "-e", "-c", step_named("workcenter gates")["run"]],
        cwd=ws,
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
    )
    assert ran.returncode == 1, ran.stdout + ran.stderr
    assert "usage:" not in ran.stdout + ran.stderr
    assert ran.stderr.strip().splitlines()[-1] == f"{ws / '--help'}: not found"


@pytest.mark.parametrize("project", ["", "v1\nv2", "v1\r"])
def test_a_project_name_that_cannot_be_passed_as_1_folder_is_refused_on_1_line(tmp_path, project):
    """R16-N2: an empty name would gate the workspace's root under no name, and a newline splits the
    log's and the summary's lines. The step runs nothing and says so on 1 line."""
    out: list = []
    assert gates_case(tmp_path, "install", 0, project=project, out=out) == (1, [])
    assert len(out) == 1 and out[0].startswith("RED: the project name "), out
    assert out[0].endswith("is not a folder the gates can be given: it is empty or holds a control character")


@pytest.mark.parametrize("where", ["install", "image"])
@pytest.mark.parametrize("table", ["", "usage: workcenter gates [-h] [--strict] project\n"])
def test_an_exit_code_0_with_no_green_line_in_the_report_is_red(tmp_path, where, table):
    """R16-N2: exit 0 alone was green; a help text or an empty output wrote no table and the check was
    green with nothing judged. Green now rests on the gates' own GREEN line in the report."""
    out: list = []
    code, _ = gates_case(tmp_path, where, 0, table=table, out=out)
    assert code == 1
    assert out == [
        "RED: v0.2/display: the gates exited 0, but their report holds no GREEN line: nothing was judged"
    ]


def test_a_green_report_with_no_row_for_a_gate_is_red(tmp_path):
    """R16-N2: the rule `ERC, DRC and EXPORT ran` read only rows at skip; a report with no EXPORT row
    passed it. A missing row is a gate not judged."""
    table = GREEN_TABLE.replace("| EXPORT | pass | gerbers |\n", "")
    out: list = []
    assert gates_case(tmp_path, "install", 0, table=table, out=out)[0] == 1
    assert out == [f"RED: v0.2/display: EXPORT not judged: no row in the gates table{NOT_JUDGED}"]


def test_the_image_path_runs_the_same_command_inside_it_as_the_runners_user(tmp_path):
    """R16-F1: the gates run the board's own sim decks, and ngspice runs a deck's `shell` lines with
    /bin/sh. In the image they get no network, `.via` read-only (mounted after the workspace, so it
    overlays it), and of the runner's temp folder only `board-gates/`, not the runner's file-command
    files beside it."""
    code, calls = gates_case(tmp_path, "image", 0, "true")
    assert code == 0
    assert calls == [
        "docker run --rm --network none --user 1001:121 -e CI -e GITHUB_ACTIONS "
        "-v /ws:/ws -v /ws/.via:/ws/.via:ro -v /rt/board-gates:/rt/board-gates -w /ws "
        "ghcr.io/o/via:tc-x bash -e -c python3 .via/tools/image.py check --src .via; "
        'python3 .via/tools/workcenter "$@" workcenter '
        "gates --report /rt/board-gates/board-gates.md --strict -- v0.2/display"
    ]
    assert gates_case(tmp_path, "image", 1)[0] == 1


def test_the_image_paths_mounts_give_the_decks_no_more_than_the_board_and_the_report():
    """R16-F1, held on the step's text: every `-v` of `docker run`, in its order, and `--network none`."""
    run = step_named("workcenter gates")["run"]
    (docker,) = re.findall(r"docker run (.*?)\n\s+\"\$IMAGE\"", run, re.S)
    assert re.findall(r"-v (\S+)", docker) == [
        '"$GITHUB_WORKSPACE":"$GITHUB_WORKSPACE"',
        '"$GITHUB_WORKSPACE/.via":"$GITHUB_WORKSPACE/.via":ro',
        '"$out":"$out"',
    ]
    assert "--network none" in docker
    assert '"$RUNNER_TEMP":"$RUNNER_TEMP"' not in run


def test_an_id_that_fails_stops_the_step_before_docker(tmp_path):
    """P2 step 8 and M269: inside docker's arguments the failure of `id` would be lost under bash -e."""
    assert gates_case(tmp_path, "image", 0, id_code=1) == (1, [])


def test_no_decided_path_is_a_red_step(tmp_path):
    assert gates_case(tmp_path, "") == (1, [])


NOT_JUDGED = (
    "; this check is green only when ERC, DRC and EXPORT ran "
    '(.claude/skills/board-ci/SKILL.md, "A board that is not there is red")'
)


def table_case(tmp_path: Path, where: str, table: str) -> tuple[int, list[str]]:
    """The gates step with `workcenter gates` (install) or `docker` (image) as a stand-in that writes
    $TABLE where --report names and exits 0, as GREEN does."""
    bin_ = tmp_path / "bin"
    temp = tmp_path / "rt"
    temp.mkdir()
    stub(bin_, "python3", WRITES)
    stub(bin_, "docker", WRITES)
    stub(bin_, "id", "echo 1001")
    env = {
        "PATH": f"{bin_}:/usr/bin:/bin",
        "WHERE": where,
        "IMAGE": "ghcr.io/o/via:tc-x",
        "PROJECT": "v1",
        "STRICT": "true",
        "RUNNER_TEMP": str(temp),
        "GITHUB_WORKSPACE": "/ws",
        "TABLE": table,
    }
    ran = subprocess.run(
        ["bash", "-e", "-c", step_named("workcenter gates")["run"]], env=env, text=True, capture_output=True
    )
    return ran.returncode, ran.stdout.splitlines()


NO_BOARD = (
    "| Gate | Status | Summary |\n|---|---|---|\n"
    "| ERC | pass | 0 errors, 0 warnings |\n"
    "| DRC | skip | no board in project |\n"
    "| SIM | pass | 1 decks, 46 corner runs, 0 failures |\n"
    "| EXPORT | skip | no board in project |\n\n"
    "GREEN (nothing to run for: drc, export) on 2026-11-19: "
    "`workcenter gates` with KiCad 10.0.8, ngspice 42.\n"
)


@pytest.mark.parametrize("where", ["install", "image"])
def test_a_project_whose_board_is_gone_is_red_though_the_gates_say_green(tmp_path, where):
    """R16-2: a pull request that deletes v1's .kicad_pcb. DRC and EXPORT return `skip, no board in
    project` (tools/workcenter, gate_drc and gate_export), ERC and SIM pass, and gates_verdict says
    `GREEN (nothing to run for: drc, export)` with exit code 0. The table above is the one the review's
    run wrote (attack-r16/nopcb.out). The check judged no board, so the step ends 1 with 1 line per gate
    that did not run: 2 lines, DRC then EXPORT, in the table's order."""
    code, out = table_case(tmp_path, where, NO_BOARD)
    assert code == 1
    assert out == [
        f"RED: v1: DRC not judged: no board in project{NOT_JUDGED}",
        f"RED: v1: EXPORT not judged: no board in project{NOT_JUDGED}",
    ]


NO_SCHEMATIC = (
    "| Gate | Status | Summary |\n|---|---|---|\n"
    "| ERC | skip | no schematic in project |\n"
    "| DRC | pass | 0 violations |\n"
    "| SIM | skip | no sim/*.cir in project |\n"
    "| EXPORT | pass | gerbers |\n\n"
    "GREEN (nothing to run for: erc, sim) on 2026-11-19\n"
)


def test_a_project_whose_schematic_is_gone_is_red_though_the_gates_say_green(tmp_path):
    """R16-F4 (a): a pull request that deletes the .kicad_sch. ERC is `skip, no schematic in project`
    (the checker's table); the step ends 1 with 1 line for ERC. SIM at skip adds no line."""
    code, out = table_case(tmp_path, "install", NO_SCHEMATIC)
    assert code == 1
    assert out == [f"RED: v1: ERC not judged: no schematic in project{NOT_JUDGED}"]


def test_a_red_checks_summary_says_why_it_is_red(tmp_path):
    """R16-F5: the gates said GREEN and the step ended red; the summary held only the table and its
    GREEN. The gates step writes each gate not judged into the report's folder, and the summary step
    puts them under the table."""
    assert table_case(tmp_path, "install", NO_SCHEMATIC)[0] == 1
    assert (tmp_path / "rt" / "board-gates" / "not-judged.txt").read_text(encoding="utf-8") == (
        "ERC not judged: no schematic in project\n"
    )
    code, text = summary_case(tmp_path, "install", NO_SCHEMATIC)
    assert code == 0
    assert text == (
        NO_SCHEMATIC + "\nThis check is red: the gates said GREEN, but these gates judged nothing:\n\n"
        "- ERC not judged: no schematic in project\n"
        "\nWhere: install.sh: the input use-image is false.\n"
    )


def test_a_red_checks_summary_lists_every_gate_not_judged_in_the_tables_order(tmp_path):
    """R16-N3: with 1 gate not judged, `>>` cut to `>` in the gates step, and `sed` cut to its first line
    in the summary, both passed every test. NO_BOARD has 2: DRC, then EXPORT."""
    assert table_case(tmp_path, "install", NO_BOARD)[0] == 1
    assert (tmp_path / "rt" / "board-gates" / "not-judged.txt").read_text(encoding="utf-8") == (
        "DRC not judged: no board in project\nEXPORT not judged: no board in project\n"
    )
    code, text = summary_case(tmp_path, "install", NO_BOARD)
    assert code == 0
    assert text == (
        NO_BOARD + "\nThis check is red: the gates said GREEN, but these gates judged nothing:\n\n"
        "- DRC not judged: no board in project\n"
        "- EXPORT not judged: no board in project\n"
        "\nWhere: install.sh: the input use-image is false.\n"
    )


def test_a_project_with_no_sim_decks_stays_green_and_the_table_names_it(tmp_path):
    """SIM with no deck is `skip, no sim/*.cir in project` (tools/workcenter, gate_sim): the board was
    judged by ERC, DRC and EXPORT, so the check stays green; the summary's table shows the skip row."""
    table = (
        "| ERC | pass | 0 errors |\n| DRC | pass | 0 violations |\n"
        "| SIM | skip | no sim/*.cir in project |\n| EXPORT | pass | gerbers |\n"
        "GREEN (nothing to run for: sim) on 2026-11-19\n"
    )
    assert table_case(tmp_path, "install", table) == (0, [])


# ---------------------------------------------------------------- the summary


def summary_case(tmp_path: Path, where: str, report: str | None, project: str = "v0.2") -> tuple[int, str]:
    temp = tmp_path / "rt"
    (temp / "board-gates").mkdir(parents=True, exist_ok=True)
    (temp / "board-gates" / "board-gates.md").unlink(missing_ok=True)
    if report is not None:
        (temp / "board-gates" / "board-gates.md").write_text(report, encoding="utf-8")
    summary = tmp_path / "summary.md"
    summary.write_text("", encoding="utf-8")
    env = {
        "PATH": "/usr/bin:/bin",
        "RUNNER_TEMP": str(temp),
        "GITHUB_STEP_SUMMARY": str(summary),
        "PROJECT": project,
        "WHERE": where,
        "IMAGE": "ghcr.io/o/via:tc-x",
        "REASON": "the input use-image is false",
    }
    run = step_named("The gates table into the job's summary")["run"]
    ran = subprocess.run(["bash", "-e", "-c", run], env=env, capture_output=True, text=True)
    return ran.returncode, summary.read_text(encoding="utf-8")


def test_the_summary_holds_the_gates_table_and_where_the_gates_ran(tmp_path):
    """R16-F4 (c): the whole table, every row and its verdict line, not its first lines."""
    table = NO_BOARD.replace("skip | no board in project", "pass | 0 violations")
    assert summary_case(tmp_path, "image", table) == (0, table + "\nWhere: the image ghcr.io/o/via:tc-x.\n")
    assert summary_case(tmp_path, "install", table) == (
        0,
        table + "\nWhere: install.sh: the input use-image is false.\n",
    )


def test_a_run_with_no_table_says_so_and_names_no_path_it_did_not_take(tmp_path):
    code, text = summary_case(tmp_path, "", None)
    assert code == 0
    assert text == (
        "No gates table for <code>v0.2</code>: the gates step wrote none; its log says why.\n"
        "\nWhere: no path was decided: the job stopped before the step `where`.\n"
    )


def test_the_projects_name_reaches_the_summary_as_text_not_markup(tmp_path):
    """R16-N4: the name went into a code span as it was: a backtick closed the span, and `<` opened a
    tag. Every character outside letters, digits and ` ._/:,=+@-` goes in as a numeric entity."""
    code, text = summary_case(tmp_path, "", None, project="v1`<b>x</b>|*")
    assert code == 0
    first = text.splitlines()[0]
    assert first == (
        "No gates table for <code>v1&#96;&#60;b&#62;x&#60;/b&#62;&#124;&#42;</code>: "
        "the gates step wrote none; its log says why."
    )


def test_board_text_in_the_table_reaches_the_summary_with_no_tag(tmp_path):
    """R16-N4: a deck's first comment sentence goes into the decks table as written. In the summary every
    `<` outside the report's own `<!-- workcenter ... -->` markers is `&lt;`, so board text opens no tag;
    the markers stay comments."""
    table = (
        "# Gates report: board\n\n## board\n\n<!-- workcenter gates board -->\n"
        + GREEN_TABLE
        + "<!-- /workcenter gates board -->\n\n<!-- workcenter decks board -->\n"
        "| Deck | What it simulates | Bounds | Corner runs | Result |\n|---|---|---|---|---|\n"
        "| `sim/a.cir` | V(out) < 1 V <img src=x> | 1 | 2 | pass |\n"
        "<!-- /workcenter decks board -->\n"
    )
    code, text = summary_case(tmp_path, "install", table)
    assert code == 0
    assert "| `sim/a.cir` | V(out) &lt; 1 V &lt;img src=x> | 1 | 2 | pass |" in text.splitlines()
    assert "<img" not in text
    markers = [line for line in text.splitlines() if line.startswith("<!--")]
    assert markers == [
        "<!-- workcenter gates board -->",
        "<!-- /workcenter gates board -->",
        "<!-- workcenter decks board -->",
        "<!-- /workcenter decks board -->",
    ]


# ---------------------------------------------------------------- the whole job, on both paths

EXPR = re.compile(r"\$\{\{\s*([^}]*?)\s*\}\}")


def render(text: str, ctx: dict[str, str]) -> str:
    def one(m: re.Match) -> str:
        if m.group(1) not in ctx:
            raise KeyError(f"the runner here does not know {m.group(1)}")
        return ctx[m.group(1)]

    return EXPR.sub(one, str(text))


def holds(cond: str | None, ctx: dict[str, str], ok: bool) -> bool:
    """GitHub's `if:` for the 2 forms the workflow uses; no `if` is `success()`."""
    if cond == "always()":
        return True
    if not ok:
        return False
    if cond is None:
        return True
    m = re.fullmatch(r"(steps\.\w+\.outputs\.\w+) == '(\w+)'", cond)
    assert m, f"the runner here does not read `if: {cond}`"
    return ctx.get(m.group(1), "") == m.group(2)


def run_job(ws: Path, ctx: dict[str, str], env: dict[str, str]) -> tuple[list[tuple[str, int]], bool]:
    """Each `run:` step of the job in its order, as the runner runs it: `bash -e`, the step's `env:`
    rendered, its outputs read back from $GITHUB_OUTPUT. `uses:` steps are done by the test."""
    ran: list[tuple[str, int]] = []
    ok = True
    for i, step in enumerate(job()["steps"]):
        if "uses" in step or not holds(step.get("if"), ctx, ok):
            continue
        out = ws.parent / f"output-{i}"
        out.write_text("", encoding="utf-8")
        step_env = {**env, **{k: render(v, ctx) for k, v in step.get("env", {}).items()}}
        step_env["GITHUB_OUTPUT"] = str(out)
        cwd = ws / step.get("working-directory", ".")
        done = subprocess.run(
            ["bash", "-e", "-c", step["run"]], cwd=cwd, env=step_env, text=True, capture_output=True
        )
        ran.append((step["name"], done.returncode))
        ok = ok and done.returncode == 0
        for line in out.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            ctx[f"steps.{step['id']}.outputs.{key}"] = value
    return ran, ok


def whole_job(tmp_path: Path, pull: int, gates: int) -> tuple[list[tuple[str, int]], bool, list[str], str]:
    """The board's checkout is a folder; the workcenter's checkout `.via` is this repository (the tag step
    reads its HEAD with git, as on a runner). Stand-ins: `docker` (login and pull answer $PULL), `sudo`
    (runs nothing), `id`, and `python3`, which runs image.py for real and stands in for the workcenter:
    it writes $TABLE where --report names and exits $GATES."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / ".via").symlink_to(ROOT)
    temp = tmp_path / "rt"
    temp.mkdir()
    calls = tmp_path / "calls"
    bin_ = tmp_path / "bin"
    # pull names the ref it pulls; run names the image it runs, the word after `-w <folder>`.
    stub(
        bin_,
        "docker",
        'case "$1" in\n'
        f'  pull) printf "docker pull %s\\n" "$3" >> {calls}\n'
        '    [ "$PULL" = 0 ] || echo denied >&2; exit $PULL ;;\n'
        '  run) while [ "$1" != -w ]; do shift; done\n'
        f'    printf "docker run %s\\n" "$3" >> {calls}; {WRITES}; exit $GATES ;;\n'
        f'  *) printf "docker %s\\n" "$1" >> {calls}; cat > /dev/null; exit 0 ;;\n'
        "esac",
    )
    stub(bin_, "sudo", f'printf "sudo %s\\n" "$*" >> {calls}')
    stub(bin_, "id", 'case "$1" in -u) echo 1001 ;; -g) echo 121 ;; esac')
    stub(
        bin_,
        "python3",
        f'if [ "$1" = .via/tools/image.py ]; then exec {REAL_PYTHON} "$@"; fi\n'
        f'printf "python3 %s\\n" "$1 $2 ${{*: -1}}" >> {calls}\n'
        f"{WRITES}\n"
        "exit $GATES",
    )
    summary = tmp_path / "summary.md"
    summary.write_text("", encoding="utf-8")
    ctx = {
        "inputs.projects": '["."]',
        "inputs.strict": "false",
        "inputs.workcenter-repository": "ThyFriendlyFox/via",
        "inputs.workcenter-ref": "main",
        "inputs.use-image": "true",
        "inputs.apt-ubuntu-archive": "true",
        "matrix.project": ".",
    }
    env = {
        "PATH": f"{bin_}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "GITHUB_ACTOR": "a",
        "GITHUB_WORKSPACE": str(ws),
        "RUNNER_TEMP": str(temp),
        "GITHUB_STEP_SUMMARY": str(summary),
        "PULL": str(pull),
        "GATES": str(gates),
        "TABLE": GREEN_TABLE,
    }
    ran, ok = run_job(ws, ctx, env)
    return ran, ok, calls.read_text(encoding="utf-8").splitlines(), summary.read_text(encoding="utf-8")


def test_the_whole_job_falls_back_to_install_sh_when_the_image_is_refused(tmp_path):
    """The fallback is a path of its own: archive step, install.sh, then the gates on the workcenter that
    install.sh linked, and the summary. The tag is the content tag of this checkout's HEAD."""
    tag = image.content_tag(image.from_git(ROOT, "HEAD"))
    ran, ok, calls, summary = whole_job(tmp_path, pull=1, gates=0)
    assert ok
    assert [name for name, _ in ran] == [
        "The image of the workcenter's toolchain",
        "Where the gates run (the image of this toolchain, or install.sh) and why",
        "Ask Ubuntu's own archive, not the runner's regional mirror",
        "Install the workcenter toolchain (install.sh, with CI's 2 apt bounds)",
        "workcenter gates",
        "The gates table into the job's summary",
    ]
    assert calls == [
        f"docker pull ghcr.io/thyfriendlyfox/via:{tag}",
        ARCHIVE,
        f"sudo env APT_UPDATE_TIMEOUT=120 APT_DOWNLOAD_TIMEOUT=570 {INSTALL}",
        "python3 .via/tools/workcenter gates .",
    ]
    assert summary == (
        GREEN_TABLE + f"\nWhere: install.sh: the registry gave no ghcr.io/thyfriendlyfox/via:{tag}: denied.\n"
    )


def test_the_whole_job_runs_in_the_image_when_it_is_pulled_and_installs_nothing(tmp_path):
    """R16-F4 (d): `docker run` gets the `image:tag` that was pulled, not the tag step's name alone
    (which docker would run as `:latest`). No login is made (R16-F2)."""
    tag = image.content_tag(image.from_git(ROOT, "HEAD"))
    ran, ok, calls, summary = whole_job(tmp_path, pull=0, gates=0)
    assert ok and len(ran) == 4
    ref = f"ghcr.io/thyfriendlyfox/via:{tag}"
    assert calls == [f"docker pull {ref}", f"docker run {ref}"]
    assert summary == GREEN_TABLE + f"\nWhere: the image ghcr.io/thyfriendlyfox/via:{tag}.\n"


@pytest.mark.parametrize("pull", [0, 1])
def test_a_red_gate_is_a_red_job_and_its_summary_is_still_written(tmp_path, pull):
    ran, ok, _, summary = whole_job(tmp_path, pull=pull, gates=1)
    assert not ok
    assert ran[-2] == ("workcenter gates", 1)
    assert ran[-1] == ("The gates table into the job's summary", 0)
    assert "\nWhere: " in summary


# ---------------------------------------------------------------- this repository's own caller


def test_this_repository_calls_it_on_pass_rc_divider_with_the_workcenter_under_test():
    f = flow(FIXTURE_FLOW)
    on = f[True]
    assert set(on) == {"pull_request", "push", "workflow_dispatch"}
    watched = {".github/workflows/board-gates.yml", ".github/workflows/board-fixture.yml"}
    assert watched <= set(on["pull_request"]["paths"]) and watched <= set(on["push"]["paths"])
    assert on["pull_request"]["paths"] == on["push"]["paths"]
    assert on["push"]["branches"] == ["main"]
    assert f["permissions"] == {"contents": "read"}
    (caller,) = f["jobs"].values()
    assert caller["uses"] == "./.github/workflows/board-gates.yml"
    assert caller["with"] == {
        "projects": '["tests/boards/pass-rc-divider"]',
        "strict": True,
        "workcenter-repository": "${{ github.repository }}",
        "workcenter-ref": "${{ github.sha }}",
    }


def test_the_fixture_runs_when_a_file_the_job_executes_changes():
    """R16-4: the job runs the workcenter's checkout: tools/image.py (tag, check), tools/ci/apt_archive.sh,
    install.sh, and tools/workcenter with the modules it imports from tools/. install.sh reads
    requirements.txt, and the image of the toolchain is built from Dockerfile, install.sh and
    requirements.txt (tools/image.py, the content tag). A change to any of them runs the fixture."""
    on = flow(FIXTURE_FLOW)[True]
    executed = {"tools/**", "install.sh", "requirements.txt", "Dockerfile", "tests/boards/pass-rc-divider/**"}
    assert executed <= set(on["pull_request"]["paths"])
    assert executed <= set(on["push"]["paths"])


def skill_callers() -> dict:
    yaml = pytest.importorskip("yaml")
    text = SKILL.read_text(encoding="utf-8")
    block = re.search(r"```yaml\n(.*?)```", text, re.S).group(1)
    return yaml.safe_load(block)


def test_the_skills_caller_is_the_line_the_roadmap_names_and_passes_only_inputs_that_exist():
    caller = skill_callers()
    assert set(caller[True]) >= {"pull_request"}
    assert caller["permissions"] == {"contents": "read"}
    inputs = flow()[True]["workflow_call"]["inputs"]
    for gates in caller["jobs"].values():
        assert gates["uses"].split("@")[0] == USES
        assert set(gates.get("with", {})) <= set(inputs)
    assert "packages: read" not in SKILL.read_text(encoding="utf-8")


def test_the_skills_caller_pins_the_workflow_and_the_tools_to_1_commit():
    """R16-F3: `workcenter-ref` does not follow the ref of the `uses:` line, and both defaulted to the
    moving `main`. The caller pins 1 commit SHA in both places in every call, and the skill names no tag:
    none holds board-gates.yml yet. The workflow's header says the 2 refs are apart."""
    for gates in skill_callers()["jobs"].values():
        assert gates["uses"] == f"{USES}@{PIN}"
        assert gates["with"]["workcenter-ref"] == PIN
    skill = " ".join(SKILL.read_text(encoding="utf-8").split())
    assert "v0.1.0" not in skill
    assert "full commit SHA" in skill
    head = FLOW.read_text(encoding="utf-8").split("\nname:")[0]
    head = " ".join(line.lstrip("#").strip() for line in head.splitlines())
    assert "does not follow the ref of the `uses:` line" in head


def test_the_skill_says_the_check_runs_the_pull_requests_own_decks():
    """R16-F1: ngspice runs a deck's `shell` lines, so a fork's check is only as trustworthy as its
    diff; the skill says so, and what the image path holds the decks to."""
    skill = " ".join(SKILL.read_text(encoding="utf-8").split())
    assert "ngspice runs a deck's `shell` lines" in skill
    assert "only as trustworthy as its diff" in skill
    for point in ("`--network none`", "read-only", "`board-gates/`"):
        assert point in skill, point


def test_the_skill_names_every_file_of_a_board_repository_that_runs_code_during_the_gates():
    """R16-N1 (b): the skill pointed a reviewer at `sim/*.cir` alone. ngspice also reads the deck
    folder's `.spiceinit`, and a deck pulls in files (`.include`, `.lib`, `source`) and shared libraries
    (`codemodel`, `pre_osdi`); a pull request can change the caller itself; KiKit's preset can name Python
    (refused now); a planted Python module is not imported (tested below). The skill names each."""
    skill = " ".join(SKILL.read_text(encoding="utf-8").split())
    trust = skill.split("## The pull request's own files run")[1].split(" ## ")[0]
    for point in (
        "`sim/*.cir`",
        "`sim/.spiceinit`",
        "`.include`",
        "`.lib`",
        "`source`",
        "`codemodel`",
        "`pre_osdi`",
        "`.github/workflows/`",
        "`panel.json`",
        "`kikit/`",
        "`sitecustomize.py`",
        "the whole diff",
    ):
        assert point in trust, point
    assert "read a fork's `sim/*.cir` before you trust" not in skill


def test_the_skill_names_the_check_of_each_call():
    """R16-F7: the caller has 2 jobs, so a required check is `gates / gates <project>` or
    `gates-strict / gates <project>`."""
    skill = " ".join(SKILL.read_text(encoding="utf-8").split())
    step5 = skill.split("5. Make the check required")[1].split("##")[0]
    assert "`gates / gates <project>`" in step5 and "`gates-strict / gates <project>`" in step5


def test_the_skills_caller_shows_that_strict_holds_for_every_project_of_1_call():
    """R16-3: `strict` is 1 input of a call, so a project gated without --strict and a project gated
    with it are 2 jobs of the caller, each a call. The example names no real board's folders."""
    jobs = skill_callers()["jobs"]
    assert {name: (j["with"]["projects"], j["with"].get("strict", False)) for name, j in jobs.items()} == {
        "gates": ('["v1"]', False),
        "gates-strict": ('["v1/display"]', True),
    }
    text = " ".join(SKILL.read_text(encoding="utf-8").split())
    assert "`strict` holds for every project of 1 call" in text
    assert "v0.16" not in text


def test_the_docs_say_the_image_is_the_normal_path_and_name_what_only_a_real_run_shows():
    """R16-1: the registry gave the package's tag list and the manifest of tc-ad6cb1705e532dcc to an
    anonymous token on 2026-11-19, so the package is public and a board repository's run takes the image
    path. No document may say that every run takes the install path; the skill and CI.md name the image
    path's 3 points that only a run on GitHub shows: `docker run --user`, `image.py check`, and HOME."""
    skill = " ".join(SKILL.read_text(encoding="utf-8").split())
    head = FLOW.read_text(encoding="utf-8").split("\nname:")[0]
    ci = " ".join((ROOT / "ee-agent-kit" / "CI.md").read_text(encoding="utf-8").split())
    for text in (skill, " ".join(head.split()), ci):
        assert "every run takes the install path" not in text
        assert "While the package is private" not in text
        assert "the caller's token" not in text and "with the job's token" not in text
    for text in (skill, ci):
        assert "The image path is the normal path" in text
        for point in ("`--user`", "`image.py check`", "`HOME`"):
            assert point in text, point


# ---------------------------------------------------------------- the gates step on this machine's toolchain

needs_kicad = engine(pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="kicad-cli is not on PATH"))


def plant(folder: Path, marker: Path) -> None:
    """Python modules a board repository could carry, each writing 1 line to `marker` when imported:
    a `kikit/` package (with the `panelize_ui` the KiKit probe imports), `pcbnew.py` and
    `sitecustomize.py`."""
    line = f"open({str(marker)!r}, 'a').write(__name__ + ' ' + __file__ + '\\n')\n"
    (folder / "kikit").mkdir()
    (folder / "kikit" / "__init__.py").write_text(line, encoding="utf-8")
    (folder / "kikit" / "panelize_ui.py").write_text(line, encoding="utf-8")
    (folder / "pcbnew.py").write_text(line, encoding="utf-8")
    (folder / "sitecustomize.py").write_text(line, encoding="utf-8")


def real_gates(
    tmp_path: Path, fixture: str, strict: str, drop: str = "", planted: Path | None = None
) -> tuple[int, str, str]:
    """The install path's gates step and the summary step, as the runner runs them, on a copy of 1
    fixture: `.via` is this repository, python3 the real one. `drop`: a glob of the copy's files to
    delete first, as a pull request deletes them. `planted`: a marker file; the copy gets
    tests/samples/fab/panel.json, and Python modules that write to the marker are planted at the
    workspace's root and in the board's folder."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / ".via").symlink_to(ROOT)
    shutil.copytree(ROOT / "tests" / "boards" / fixture, ws / "board", ignore=shutil.ignore_patterns("build"))
    for gone in (ws / "board").glob(drop) if drop else []:
        gone.unlink()
    if planted is not None:
        shutil.copy(ROOT / "tests" / "samples" / "fab" / "panel.json", ws / "board" / "panel.json")
        plant(ws, planted)
        plant(ws / "board", planted)
    temp = tmp_path / "rt"
    temp.mkdir()
    summary = tmp_path / "summary.md"
    summary.write_text("", encoding="utf-8")
    env = {
        **os.environ,
        "WHERE": "install",
        "PROJECT": "board",
        "STRICT": strict,
        "RUNNER_TEMP": str(temp),
        "GITHUB_WORKSPACE": str(ws),
        "GITHUB_STEP_SUMMARY": str(summary),
        "REASON": "the input use-image is false",
    }
    gates = subprocess.run(
        ["bash", "-e", "-c", step_named("workcenter gates")["run"]],
        cwd=ws,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    summed = subprocess.run(
        ["bash", "-e", "-c", step_named("The gates table")["run"]],
        cwd=ws,
        env=env,
        capture_output=True,
        text=True,
    )
    assert summed.returncode == 0, summed.stderr
    return gates.returncode, gates.stdout, summary.read_text(encoding="utf-8")


def rows(summary: str) -> list[str]:
    return [line for line in summary.splitlines() if re.match(r"\| (ERC|DRC|SIM|EXPORT) \|", line)]


@needs_kicad
def test_pass_rc_divider_is_green_with_strict_and_its_table_is_the_summary(tmp_path):
    """tests/boards/README.md: pass-rc-divider is GREEN on `workcenter gates`, with `--strict` too. So
    the step ends 0 and each of the 4 rows says pass."""
    code, out, summary = real_gates(tmp_path, "pass-rc-divider", "true")
    assert code == 0, out
    assert [r.split(" | ")[:2] for r in rows(summary)] == [
        ["| ERC", "pass"],
        ["| DRC", "pass"],
        ["| SIM", "pass"],
        ["| EXPORT", "pass"],
    ]
    assert re.search(r"^GREEN on \d{4}-\d{2}-\d{2}: `workcenter gates` with KiCad ", summary, re.M)
    assert summary.endswith("\nWhere: install.sh: the input use-image is false.\n")


@needs_kicad
def test_fail_drc_clearance_is_a_red_step_and_the_table_says_where_it_stopped(tmp_path):
    """tests/boards/README.md: fail-drc-clearance is ERC pass, DRC fail. The gates stop at the first red,
    so SIM and EXPORT are not run (AGENTS.md invariant 4), and the step ends 1 (RED)."""
    code, out, summary = real_gates(tmp_path, "fail-drc-clearance", "false")
    assert code == 1, out
    assert [r.split(" | ")[:2] for r in rows(summary)] == [
        ["| ERC", "pass"],
        ["| DRC", "fail"],
        ["| SIM", "not run"],
        ["| EXPORT", "not run"],
    ]
    assert re.search(r"^RED on \d{4}-\d{2}-\d{2}: ", summary, re.M)


@needs_kicad
def test_pass_rc_divider_without_its_board_is_a_red_step_with_strict(tmp_path):
    """R16-2 on this machine's toolchain: pass-rc-divider with its .kicad_pcb deleted. The review's run
    (attack-r16/nopcb.out) printed ERC pass, DRC skip, SIM pass, EXPORT skip and
    `GREEN (nothing to run for: drc, export)`, exit code 0. The step now ends 1, and its last 2 lines
    name DRC and EXPORT as not judged."""
    code, out, summary = real_gates(tmp_path, "pass-rc-divider", "true", drop="*.kicad_pcb")
    assert code == 1, out
    assert [r.split(" | ")[:2] for r in rows(summary)] == [
        ["| ERC", "pass"],
        ["| DRC", "skip"],
        ["| SIM", "pass"],
        ["| EXPORT", "skip"],
    ]
    assert out.splitlines()[-2:] == [
        f"RED: board: DRC not judged: no board in project{NOT_JUDGED}",
        f"RED: board: EXPORT not judged: no board in project{NOT_JUDGED}",
    ]


@needs_kicad
def test_python_modules_a_board_repository_carries_are_not_imported_by_the_gates(tmp_path):
    """R16-N1 (a): EXPORT probed KiKit with `python -c "import kikit.panelize_ui"` in the gates' working
    directory, the workspace's root, which `-c` puts first on the import path: a `kikit/` folder in a
    pull request ran there. pass-rc-divider with a panel.json, and `kikit/`, `pcbnew.py` and
    `sitecustomize.py` that write a marker, at the root and in the board's folder: the gates are GREEN
    with the panel made by the real KiKit, and the marker is never written."""
    marker = tmp_path / "planted-ran.txt"
    code, out, summary = real_gates(tmp_path, "pass-rc-divider", "true", planted=marker)
    assert not marker.exists(), marker.read_text(encoding="utf-8")
    assert code == 0, out
    assert [r.split(" | ")[:2] for r in rows(summary)][-1] == ["| EXPORT", "pass"]
    assert re.search(r"panel \d+ x \d+ boards", summary), summary
