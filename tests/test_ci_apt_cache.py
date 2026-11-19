"""apt's package files kept between CI runs of the install path (`tools/ci/apt_cache.sh`).

GitHub Actions does not run here, and no package host or cache service answers. The workflows are read as
YAML: the steps, their order around the install step, each condition, the key's parts, the pin of the
cache action. Each new step's script runs here under `bash -e` as the runner runs it, with stand-ins first
on PATH for `sudo`, `cp` and `apt-cache` (and `date` for the key's period). The stand-in `sudo` runs only
a stand-in of this test's own folder, and the stand-in `cp` refuses any path under /var: apt's real
archives folder is never named. The step's `/var/cache/apt/archives` is replaced by a folder of the test,
as tests/test_ci_kept_logs.py replaces `python3`. Nothing here runs apt-get, apt-cache, dpkg or install.sh.

What only a run on GitHub shows: that actions/cache restores and saves the folder, the time each takes,
that apt's "Need to get" line then names fewer bytes, and that the runner's apt-cache gives the SHA256
of every file (ee-agent-kit/CI.md, "apt's package files kept between runs").
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "ci" / "apt_cache.sh"
INSTALL_SH = ROOT / "install.sh"
FLOWS = ROOT / ".github" / "workflows"
PREFIX = "[apt-cache]"
ARCHIVES = "/var/cache/apt/archives"
ON_INSTALL = "steps.where.outputs.where == 'install'"
REAL_CP = shutil.which("cp") or "/usr/bin/cp"
BASH = shutil.which("bash") or "/bin/bash"

# The 2 jobs that run install.sh on a runner and keep apt's files: (workflow, job, the events that save).
JOBS = {
    "ci.yml": ("full", ("push", "workflow_dispatch")),
    "nightly.yml": ("verify", ("schedule", "workflow_dispatch")),
}


def flow(name: str) -> dict:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load((FLOWS / name).read_text(encoding="utf-8"))


def steps_of(name: str) -> list[dict]:
    return flow(name)["jobs"][JOBS[name][0]]["steps"]


def index(steps: list[dict], test) -> int:
    (i,) = [n for n, s in enumerate(steps) if test(s)]
    return i


def by_id(steps: list[dict], ident: str) -> dict:
    return steps[index(steps, lambda s: s.get("id") == ident)]


def copy_in(steps: list[dict]) -> dict:
    return steps[index(steps, lambda s: "apt_cache.sh restore" in s.get("run", ""))]


# ---------------------------------------------------------------- the workflows


@pytest.mark.parametrize("name", list(JOBS))
def test_the_steps_stand_in_order_around_the_install_step(name):
    """The key, the restore, the copy into apt's folder, then the hosts' ranking right before install.sh;
    after it, the check that keeps the files, then the save, then the gate."""
    steps = steps_of(name)
    order = [
        index(steps, lambda s: s.get("id") == "apt-cache-key"),
        index(steps, lambda s: s.get("id") == "apt-cache-restore"),
        index(steps, lambda s: "apt_cache.sh restore" in s.get("run", "")),
        index(steps, lambda s: "tools/ci/apt_archive.sh /etc/apt" in s.get("run", "")),
        index(steps, lambda s: "./install.sh" in s.get("run", "")),
        index(steps, lambda s: s.get("id") == "apt-cache-keep"),
        index(steps, lambda s: s.get("id") == "apt-cache-save"),
        index(steps, lambda s: s.get("id") == "verify"),
    ]
    assert order == sorted(order) and order[4] == order[3] + 1, order
    assert by_id(steps, "install")["run"].count("./install.sh") == 1


@pytest.mark.parametrize("name", list(JOBS))
def test_each_step_runs_on_the_install_path_only_and_the_save_after_a_good_install(name):
    """ci.yml: the steps before install.sh carry the install step's own condition; the check runs after
    a passed or a failed install (it says why nothing is saved), never on a cancelled run; the save only
    for a push to main or a run by hand, after a good install, when the check kept files. The nightly run
    has 1 path: no path in its conditions, and it saves on a night or a run by hand."""
    steps = steps_of(name)
    path = ON_INSTALL if name == "ci.yml" else None
    install = by_id(steps, "install")
    assert install.get("if") == path
    for step in (by_id(steps, "apt-cache-key"), by_id(steps, "apt-cache-restore"), copy_in(steps)):
        assert step.get("if") == path, step
    keep = by_id(steps, "apt-cache-keep")
    assert keep["if"] == ("!cancelled()" + (f" && {path}" if path else ""))
    events = " || ".join(f"github.event_name == '{e}'" for e in JOBS[name][1])
    save = by_id(steps, "apt-cache-save")
    want = (f"{path} && " if path else "") + (
        f"({events}) && steps.install.outcome == 'success' && steps.apt-cache-keep.outputs.save == 'true'"
    )
    assert save["if"] == want
    assert "pull_request" not in save["if"]


@pytest.mark.parametrize("name", list(JOBS))
def test_the_cache_action_is_pinned_by_its_major_tag_as_the_others_are(name):
    """checkout, setup-python, upload-artifact and github-script are pinned by their major tag (`@v4`);
    the restore and the save are the action's own 2 forms, each a step of its own."""
    steps = steps_of(name)
    pins = [s["uses"] for s in steps if "uses" in s]
    assert all(re.fullmatch(r"[\w-]+/[\w/-]+@v\d+", p) for p in pins), pins
    assert by_id(steps, "apt-cache-restore")["uses"] == "actions/cache/restore@v4"
    assert by_id(steps, "apt-cache-save")["uses"] == "actions/cache/save@v4"


@pytest.mark.parametrize("name", list(JOBS))
def test_the_restore_and_the_save_name_1_folder_and_the_key_step_s_key(name):
    """Both actions name the folder under the runner's temp and the key step's outputs; the restore
    falls back to the key step's prefixes. The restore, the copy and the save never fail the run (a
    cache is a speed-up), and each has a bound; the check has a bound and may fail the run."""
    steps = steps_of(name)
    folder = "${{ runner.temp }}/apt-archives"
    restore, save = by_id(steps, "apt-cache-restore"), by_id(steps, "apt-cache-save")
    assert restore["with"] == {
        "path": folder,
        "key": "${{ steps.apt-cache-key.outputs.key }}",
        "restore-keys": "${{ steps.apt-cache-key.outputs.restore-keys }}",
    }
    assert save["with"] == {"path": folder, "key": "${{ steps.apt-cache-key.outputs.key }}"}
    for step in (restore, copy_in(steps), save):
        assert step["continue-on-error"] is True and step["timeout-minutes"] > 0
    keep = by_id(steps, "apt-cache-keep")
    assert "continue-on-error" not in keep and keep["timeout-minutes"] > 0
    assert (
        by_id(steps, "apt-cache-key")["run"].strip()
        == 'bash tools/ci/apt_cache.sh key install.sh "$GITHUB_OUTPUT"'
    )
    assert (
        copy_in(steps)["run"].strip()
        == f'bash tools/ci/apt_cache.sh restore "$RUNNER_TEMP/apt-archives" {ARCHIVES}'
    )
    assert keep["run"].strip() == (
        f'bash tools/ci/apt_cache.sh keep "$RUNNER_TEMP/apt-archives" {ARCHIVES} "$GITHUB_OUTPUT"'
    )
    assert keep["env"] == {
        "EVENT": "${{ github.event_name }}",
        "INSTALLED": "${{ steps.install.outcome }}",
        "HIT": "${{ steps.apt-cache-restore.outputs.cache-hit }}",
        "KEY": "${{ steps.apt-cache-key.outputs.key }}",
    }


@pytest.mark.parametrize("name", list(JOBS))
def test_no_new_step_puts_an_expression_into_its_script_or_holds_a_secret(name):
    """Event data reaches a script only through `env:`; no step of the cache holds a secret."""
    steps = steps_of(name)
    ours = [s for s in steps if str(s.get("id", "")).startswith("apt-cache")] + [copy_in(steps)]
    assert len(ours) == 5
    for step in ours:
        assert "${{" not in step.get("run", "")
        assert "secrets." not in str(step)


def test_the_lint_line_and_the_gate_s_lint_check_the_script():
    """`make lint` and verify.sh's lint step run shellcheck on the script, as on apt_archive.sh."""
    for path in (ROOT / "Makefile", ROOT / "verify" / "verify.sh"):
        lines = path.read_text(encoding="utf-8").splitlines()
        (line,) = [x for x in lines if x.strip().startswith("shellcheck ") and "tools/ci/apt_archive.sh" in x]
        assert "tools/ci/apt_cache.sh" in line.split()


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="no shellcheck")
def test_shellcheck_passes_the_script():
    ran = subprocess.run(["shellcheck", str(SCRIPT)], capture_output=True, text=True, cwd=ROOT)
    assert ran.returncode == 0, ran.stdout + ran.stderr


# ---------------------------------------------------------------- stand-ins


def standins(tmp: Path, *, date: str = "2026-w47", answer: str = "") -> Path:
    """sudo runs only this folder's stand-ins; cp runs the real cp unless a path is under /var; apt-cache
    prints `answer`; date prints `date`. Each records its arguments in calls."""
    bin_ = tmp / "standin"
    bin_.mkdir()
    calls = tmp / "calls"
    (tmp / "apt-cache-answer").write_text(answer, encoding="utf-8")

    def write(name: str, body: str) -> None:
        (bin_ / name).write_text(
            f'#!/bin/bash\nprintf "%s\\n" "{name} $*" >> {calls}\n{body}\n', encoding="utf-8"
        )
        (bin_ / name).chmod(0o755)

    write(
        "sudo", f'case "$(command -v "$1")" in {bin_}/*) exec "$@" ;; esac\necho "refused: $1" >&2; exit 97'
    )
    write(
        "cp",
        'for a in "$@"; do case "$a" in /var/*) echo "refused: $a" >&2; exit 98 ;; esac; done\n'
        f'exec {REAL_CP} "$@"',
    )
    write("apt-cache", f"cat {tmp / 'apt-cache-answer'}")
    write("date", f'echo "{date}"')
    return bin_


def run(tmp: Path, bin_: Path, script: str, **env: str) -> subprocess.CompletedProcess:
    """`script` under `bash -e` in the checkout, as a step runs, with the stand-ins first on PATH."""
    script = script.replace(ARCHIVES, str(tmp / "archives"))
    full = {
        "PATH": f"{bin_}:/usr/bin:/bin",
        "RUNNER_TEMP": str(tmp / "runner"),
        "GITHUB_OUTPUT": str(tmp / "out"),
    }
    full.update(env)
    return subprocess.run([BASH, "-e", "-c", script], cwd=ROOT, env=full, capture_output=True, text=True)


def calls(tmp: Path) -> list[str]:
    path = tmp / "calls"
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def outputs(tmp: Path) -> str:
    path = tmp / "out"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def deb(folder: Path, name: str, body: bytes) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(body)
    return folder / name


def stanza(package: str, version: str, arch: str, body: bytes | None) -> str:
    """An `apt-cache show` record as apt prints it from an index (body None: from dpkg's status file,
    which has no SHA256)."""
    lines = [f"Package: {package}", f"Architecture: {arch}", f"Version: {version}"]
    if body is not None:
        lines += [f"Size: {len(body)}", f"SHA256: {hashlib.sha256(body).hexdigest()}"]
    return "\n".join(lines) + "\nDescription: x\n\n"


# ---------------------------------------------------------------- the key


def os_release(tmp: Path, text: str = 'NAME="Ubuntu"\nVERSION_ID="24.04"\nID=ubuntu\n') -> Path:
    path = tmp / "os-release"
    path.write_text(text, encoding="utf-8")
    return path


def key_of(tmp: Path, script: Path, **env: str) -> tuple[str, list[str], str]:
    bin_ = standins(tmp)
    step = by_id(steps_of("ci.yml"), "apt-cache-key")["run"].replace("install.sh", str(script))
    env = {"RUNNER_OS": "Linux", "RUNNER_ARCH": "X64", "OS_RELEASE": str(os_release(tmp)), **env}
    ran = run(tmp, bin_, step, **env)
    assert ran.returncode == 0, ran.stderr
    out = outputs(tmp).splitlines()
    (key,) = [x.removeprefix("key=") for x in out if x.startswith("key=")]
    start = out.index("restore-keys<<APT_CACHE_KEYS")
    end = out.index("APT_CACHE_KEYS")
    return key, out[start + 1 : end], ran.stdout


def test_the_key_names_the_runner_the_release_the_package_lines_and_the_week(tmp_path):
    script = tmp_path / "install.sh"
    script.write_text(INSTALL_SH.read_text(encoding="utf-8"), encoding="utf-8")
    key, falls, said = key_of(tmp_path, script)
    m = re.fullmatch(r"apt-archives-v1-Linux-X64-ubuntu-24\.04-([0-9a-f]{16})-2026-w47", key)
    assert m, key
    base = "apt-archives-v1-Linux-X64-ubuntu-24.04"
    assert falls == [f"{base}-{m[1]}-", f"{base}-"]
    assert said.splitlines() == [
        f"{PREFIX} key: {key}; without it, the newest save of {base}-{m[1]}-, else of {base}-"
    ]
    assert calls(tmp_path) == ["date -u +%G-w%V"]


def test_the_key_follows_the_lines_that_name_packages_and_sources_and_no_other(tmp_path):
    """The hash covers each `*_PACKAGES=(` and `*_LIBS=(` list to its `)`, the PPA's address, and every
    line that runs `apt-get install`: a change there makes a new key, a change of a comment elsewhere
    does not."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert "               python3 python3-venv python3-pip curl ca-certificates)" in text
    variants = {
        "same": text,
        "comment": text.replace("# KiCad 10 PPA, added", "# The KiCad 10 PPA, added", 1),
        "base": text.replace(
            "python3-pip curl ca-certificates)", "python3-pip curl wget ca-certificates)", 1
        ),
        "kicad": text.replace("kicad-templates)", "kicad-templates kicad-packages3d)", 1),
        "openems": text.replace("libhdf5-hl-100t64)", "libhdf5-hl-100t64 libfoo)", 1),
        "ppa": text.replace('kicad-10.0-releases/ubuntu/"', 'kicad-10.1-releases/ubuntu/"', 1),
        "jre": text.replace(
            "apt-get install -y --no-install-recommends openjdk-21-jre \\",
            "apt-get install -y --no-install-recommends openjdk-25-jre \\",
            1,
        ),
    }
    keys = {}
    for name, body in variants.items():
        assert name == "same" or body != text, name
        folder = tmp_path / name
        folder.mkdir()
        (folder / "install.sh").write_text(body, encoding="utf-8")
        keys[name] = key_of(folder, folder / "install.sh")[0]
    assert keys["comment"] == keys["same"]
    changed = {n for n in variants if keys[n] != keys["same"]}
    assert changed == {"base", "kicad", "openems", "ppa", "jre"}


def test_the_key_falls_back_to_unknown_where_the_runner_says_nothing(tmp_path):
    """No runner variables and no os-release: the key still forms (the run goes on), with `unknown`."""
    key, _, _ = key_of(tmp_path, INSTALL_SH, RUNNER_OS="", RUNNER_ARCH="", OS_RELEASE=str(tmp_path / "none"))
    assert key.startswith("apt-archives-v1-unknown-unknown-unknown-")


# ---------------------------------------------------------------- the restore


def restore(tmp: Path) -> subprocess.CompletedProcess:
    bin_ = standins(tmp)
    (tmp / "archives").mkdir(exist_ok=True)
    return run(tmp, bin_, copy_in(steps_of("ci.yml"))["run"])


def test_a_restore_copies_each_kept_deb_into_apt_s_folder_under_sudo(tmp_path):
    kept = tmp_path / "runner" / "apt-archives"
    deb(kept, "kicad_10.0.8~ubuntu24.04.1_amd64.deb", b"k" * 1000)
    deb(kept, "ngspice_42+ds-3build1_amd64.deb", b"n" * 24)
    ran = restore(tmp_path)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout.splitlines() == [f"{PREFIX} restored 2 files, 1024 bytes, into {tmp_path / 'archives'}"]
    got = sorted(p.name for p in (tmp_path / "archives").iterdir())
    assert got == ["kicad_10.0.8~ubuntu24.04.1_amd64.deb", "ngspice_42+ds-3build1_amd64.deb"]
    assert (tmp_path / "archives" / "ngspice_42+ds-3build1_amd64.deb").read_bytes() == b"n" * 24
    assert [c.split()[:2] for c in calls(tmp_path)] == [["sudo", "cp"], ["cp", "--preserve=timestamps"]]


def test_a_restore_of_an_empty_folder_copies_nothing(tmp_path):
    (tmp_path / "runner" / "apt-archives").mkdir(parents=True)
    ran = restore(tmp_path)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout.splitlines() == [f"{PREFIX} restored 0 files, 0 bytes, into {tmp_path / 'archives'}"]
    assert calls(tmp_path) == [] and list((tmp_path / "archives").iterdir()) == []


def test_a_restore_with_no_folder_says_apt_gets_every_file(tmp_path):
    ran = restore(tmp_path)
    assert ran.returncode == 0, ran.stderr
    where = tmp_path / "runner" / "apt-archives"
    assert ran.stdout.splitlines() == [
        f"{PREFIX} restored 0 files: {where} is not there (no save of this key or its fallbacks); "
        "apt gets every file"
    ]
    assert calls(tmp_path) == []


def test_a_restore_leaves_out_a_file_that_is_not_a_deb_and_a_link(tmp_path):
    """A link (to a .deb or anywhere) and a file of another kind never reach apt's folder; a folder named
    like a .deb neither."""
    kept = tmp_path / "runner" / "apt-archives"
    deb(kept, "curl_8.5.0-2ubuntu10.6_amd64.deb", b"c" * 10)
    deb(kept, "notes.txt", b"x")
    (tmp_path / "secret").write_bytes(b"s" * 7)
    (kept / "evil_1_amd64.deb").symlink_to(tmp_path / "secret")
    (kept / "dir_1_amd64.deb").mkdir()
    ran = restore(tmp_path)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout.splitlines() == [
        f"{PREFIX} restored 1 files, 10 bytes, into {tmp_path / 'archives'}; left out 3 that are not a "
        "regular .deb file: dir_1_amd64.deb, evil_1_amd64.deb, notes.txt"
    ]
    assert [p.name for p in (tmp_path / "archives").iterdir()] == ["curl_8.5.0-2ubuntu10.6_amd64.deb"]


def test_a_failed_copy_does_not_stop_the_run(tmp_path):
    """The stand-in cp refuses a path under /var: here the archives folder is one, as a copy that fails."""
    kept = tmp_path / "runner" / "apt-archives"
    deb(kept, "curl_8.5.0-2ubuntu10.6_amd64.deb", b"c")
    bin_ = standins(tmp_path)
    script = copy_in(steps_of("ci.yml"))["run"].replace(ARCHIVES, "/var/nothing-here")
    full = {"PATH": f"{bin_}:/usr/bin:/bin", "RUNNER_TEMP": str(tmp_path / "runner")}
    ran = subprocess.run([BASH, "-e", "-c", script], cwd=ROOT, env=full, capture_output=True, text=True)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout.splitlines() == [
        f"{PREFIX} restored 0 files: the copy into /var/nothing-here failed; apt gets every file"
    ]


# ---------------------------------------------------------------- the check and the keep

KICAD = ("kicad", "10.0.8~ubuntu24.04.1", "amd64", b"K" * 300)
EPOCH = ("libfoo", "1:2.0-1", "amd64", b"E" * 50)
GONE = ("ffmpeg", "7:6.1.1-3ubuntu5", "amd64", b"F" * 20)  # a version no index lists any more
FILES = {
    "kicad_10.0.8~ubuntu24.04.1_amd64.deb": KICAD,
    "libfoo_1%3a2.0-1_amd64.deb": EPOCH,
    "ffmpeg_7%3a6.1.1-3ubuntu5_amd64.deb": GONE,
}


def keep(tmp: Path, *, event="push", installed="success", hit="false", answer=None, files=FILES):
    for name, (_, _, _, body) in files.items():
        deb(tmp / "archives", name, body)
    if answer is None:
        answer = stanza(*KICAD) + stanza(*EPOCH) + stanza(*GONE[:3], None)
    bin_ = standins(tmp, answer=answer)
    step = by_id(steps_of("ci.yml"), "apt-cache-keep")["run"]
    env = {"EVENT": event, "INSTALLED": installed, "HIT": hit, "KEY": "apt-archives-v1-k"}
    return run(tmp, bin_, step, **env)


def checked(tmp: Path, n: int, m: int, k: int) -> str:
    return (
        f"{PREFIX} checked {n} files in {tmp / 'archives'} against apt's signed indexes: {m} match, "
        f"{k} that no index lists are left out"
    )


def test_a_good_install_on_main_keeps_the_files_an_index_lists_with_their_sha256(tmp_path):
    """The kept folder is made anew from apt's folder: the files apt's signed indexes list with the same
    SHA256 (an epoch's colon is %3a in the file's name), not one whose version only dpkg's status file
    knows. Then save=true."""
    kept = tmp_path / "runner" / "apt-archives"
    deb(kept, "old_1_amd64.deb", b"o")
    ran = keep(tmp_path)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout.splitlines() == [
        checked(tmp_path, 3, 2, 1),
        f"{PREFIX} saving 2 files, 350 bytes, under apt-archives-v1-k",
    ]
    assert sorted(p.name for p in kept.iterdir()) == [
        "kicad_10.0.8~ubuntu24.04.1_amd64.deb",
        "libfoo_1%3a2.0-1_amd64.deb",
    ]
    assert outputs(tmp_path) == "save=true\n"
    (asked,) = [c for c in calls(tmp_path) if c.startswith("apt-cache ")]
    assert asked.split()[1:] == [
        "show",
        "ffmpeg=7:6.1.1-3ubuntu5",
        "kicad=10.0.8~ubuntu24.04.1",
        "libfoo=1:2.0-1",
    ]


@pytest.mark.parametrize("event", ["schedule", "workflow_dispatch"])
def test_a_night_and_a_run_by_hand_save_too(tmp_path, event):
    ran = keep(tmp_path, event=event)
    assert ran.returncode == 0, ran.stderr
    assert outputs(tmp_path) == "save=true\n"


def test_a_failed_install_saves_nothing_and_checks_nothing(tmp_path):
    ran = keep(tmp_path, installed="failure")
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout.splitlines() == [
        f"{PREFIX} not saved: the install step ended with failure; only a good install saves"
    ]
    assert outputs(tmp_path) == "save=false\n"
    assert calls(tmp_path) == [] and not (tmp_path / "runner" / "apt-archives").exists()


@pytest.mark.parametrize("event", ["pull_request", "pull_request_target", ""])
def test_a_pull_request_checks_but_never_saves(tmp_path, event):
    """A pull request's run restores; its files are checked like any run's, and nothing is saved."""
    ran = keep(tmp_path, event=event)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout.splitlines() == [
        checked(tmp_path, 3, 2, 1),
        f"{PREFIX} not saved: a run of {event or 'no event'} restores and never saves; a push to main, "
        "the nightly run and a run by hand save",
    ]
    assert outputs(tmp_path) == "save=false\n"
    assert not (tmp_path / "runner" / "apt-archives").exists()


def test_a_restore_of_the_key_itself_saves_nothing(tmp_path):
    ran = keep(tmp_path, hit="true")
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout.splitlines()[1:] == [
        f"{PREFIX} not saved: the restore found this key itself (apt-archives-v1-k); "
        "a saved key cannot be written again"
    ]
    assert outputs(tmp_path) == "save=false\n"


def test_a_file_whose_bytes_are_not_the_index_s_fails_the_run_and_saves_nothing(tmp_path):
    """apt takes a file already in its folder by its size alone (apt 2.8.3, acquire-item.cc:3494-3512):
    a kept file of the right size and other bytes is installed. The check finds it after the install,
    names it, and fails the step; nothing is saved."""
    forged = ("kicad", "10.0.8~ubuntu24.04.1", "amd64", b"X" * 300)
    answer = stanza(*KICAD) + stanza(*EPOCH)
    ran = keep(tmp_path, answer=answer, files={"kicad_10.0.8~ubuntu24.04.1_amd64.deb": forged})
    assert ran.returncode == 1
    got, want = hashlib.sha256(b"X" * 300).hexdigest(), hashlib.sha256(b"K" * 300).hexdigest()
    assert ran.stdout.splitlines() == [
        f"{PREFIX} kicad_10.0.8~ubuntu24.04.1_amd64.deb: SHA256 {got}, but apt's index says {want}: apt took "
        "this kept file by its size and installed it; nothing is saved"
    ]
    assert outputs(tmp_path) == "save=false\n"
    assert not (tmp_path / "runner" / "apt-archives").exists()


def test_an_empty_archives_folder_saves_nothing(tmp_path):
    ran = keep(tmp_path, files={}, answer="")
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout.splitlines() == [
        checked(tmp_path, 0, 0, 0),
        f"{PREFIX} not saved: apt's folder holds no file an index lists",
    ]
    assert outputs(tmp_path) == "save=false\n"
    assert not [c for c in calls(tmp_path) if c.startswith("apt-cache ")]
