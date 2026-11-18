"""The apt step of install.sh when KiCad 10's package source does not answer.

On 2026-11-18 Launchpad's host answered 503 2 times. Job 134932219722: the index of the source did not
arrive, `apt-get update` ended with 0 and only `W:` lines, and apt installed Ubuntu's own KiCad 7.0.11.
Job 134906707485: the index arrived, a package file did not, the pipeline's `|| true` hid apt's exit
code. Both ended with `kicad-cli 10.x not found after install`.

Each test sources install.sh (its steps run only when it is executed) and runs `step_apt`.

The machine that runs these tests may run as root, and the script's steps write to /etc, /opt and
/usr/local. The first run of this file, before the script had its guard, sourced it as root: main()
ran and relinked /usr/local/bin/workcenter. So each test stays inside its own folder in 3 ways:
1. Every path the script writes or reads outside its folder is set in the environment before the
   script is sourced: WORKCENTER_ROOT, KICAD_KEYRING, KICAD_SOURCES, WORKCENTER_LINK, OS_RELEASE,
   JVM_DIR, HOME and TMPDIR all point into the test's folder. A lost guard runs main() there.
2. PATH holds only 2 folders the test makes. `bin/` holds the stand-ins: `apt-get`, `apt-cache`,
   `timeout`, `sleep`, `kicad-cli`, `curl`, `gpg`, `python3`, each writing its call to a calls file and
   answering from a bash snippet the test gives it; and the writers `chmod`, `install`, `mkdir`, `mv`,
   `rm`, `touch`, `ln`, `cp`, which write their call too and run the real program only when every
   absolute path among their arguments is inside the folder (else they write `REFUSED` and end with
   99). `tools/` links the programs that only read: `awk`, `basename`, `cat`, `dirname`, `find`,
   `grep`, `head`, `mktemp`, `sed`, `seq`, `tail`. No pip, venv, dpkg or real apt can be reached.
3. Each test ends by checking its calls file: no `REFUSED`, and no program it did not expect.
No test needs root, the network, real apt or a real wait.
"""

from __future__ import annotations

import ast
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "install.sh"
SAMPLES = ROOT / "tests" / "samples" / "install"
BASH = "/bin/bash"

SOURCE = "https://ppa.launchpadcontent.net/kicad/kicad-10.0-releases/ubuntu noble"
# Copied from the log of job 134932219722 at 15:57:17.
W_INDEX = (
    "W: Failed to fetch https://ppa.launchpadcontent.net/kicad/kicad-10.0-releases/ubuntu/dists/noble/InRelease"
    "  503  Service Unavailable [IP: 185.125.189.186 443]"
)
W_SOME = "W: Some index files failed to download. They have been ignored, or old ones used instead."
# Copied from the log of job 134906707485 at 15:44:22.
E_FETCH = (
    "E: Failed to fetch https://ppa.launchpadcontent.net/kicad/kicad-10.0-releases/ubuntu/pool/main/k/"
    "kicad-library-templates/kicad-templates_10.0.8%7eubuntu24.04.1_all.deb"
    "  503  Service Unavailable [IP: 185.125.189.186 443]"
)
E_SOME = "E: Unable to fetch some archives, maybe run apt-get update or try with --fix-missing?"
AGAIN = (
    "[install] KiCad 10 comes from a third party's package source (Launchpad's KiCad PPA). "
    "No KiCad was installed. Run the script again later."
)
LATER = (
    "[install] No package was installed. The files already downloaded stay in /var/cache/apt/archives. "
    "Run the script again later."
)

STUB = """#!/bin/bash
name="$(basename "$0")"
printf '%s %s\\n' "$name" "$*" >> "$STUB_DIR/calls"
n="$(grep -c "^${name} " "$STUB_DIR/calls")"
. "$STUB_DIR/answer-${name}.sh"
"""

# A writer runs the real program only on paths inside the test's folder.
FENCE = """for a in "$@"; do
  if [[ "$a" == /* && "$a" != "$STUB_DIR"/* ]]; then echo "REFUSED $name $*" >> "$STUB_DIR/calls"; exit 99; fi
done
exec {real} "$@"
"""
WRITERS = ["chmod", "install", "mkdir", "mv", "rm", "touch", "ln", "cp"]
READERS = ["awk", "basename", "cat", "dirname", "find", "grep", "head", "mktemp", "sed", "seq", "tail"]

DEFAULTS = {
    # The real program after the bound: the test sees each bound as the step passes it.
    "timeout": 'shift; exec "$@"',
    "sleep": "exit 0",
    "kicad-cli": '[[ -e "$STUB_DIR/installed" ]] && { echo 10.0.8; exit 0; }; exit 1',
    "apt-get": """case "$*" in
  *update*) exit 0 ;;
  *--download-only*)
    echo "Get:172 https://ppa.launchpadcontent.net/kicad/kicad-10.0-releases/ubuntu noble/main amd64 \\
kicad amd64 10.0.8~ubuntu24.04.1 [48.0 MB]"
    exit 0 ;;
  *install*)
    echo "Unpacking kicad (10.0.8~ubuntu24.04.1) ..."
    echo "Setting up kicad (10.0.8~ubuntu24.04.1) ..."
    touch "$STUB_DIR/installed"
    exit 0 ;;
esac""",
    "apt-cache": 'cat "$SAMPLES/policy-ppa.txt"',
    "curl": "echo 'a key'",
    "gpg": """if [[ "$*" == *--dearmor* ]]; then
  while (( $# )); do [[ "$1" == -o ]] && { cat > "$2"; exit 0; }; shift; done
fi
[[ "$*" == *--list-keys* ]] && echo "fpr:::::::::FDA854F61C4D0D9572BB95E5245D5502FAD7A805:"
exit 0""",
    "python3": "exit 7",
}

# The programs the apt step may call. A call of any other program fails the test.
STEP = {"apt-get", "apt-cache", "timeout", "sleep", "kicad-cli", "curl", "gpg"}
STEP |= {"install", "mv", "chmod", "rm", "touch"}


def folder(tmp_path: Path, answers: dict | None = None) -> dict:
    """Make the stand-ins, the readers and the folder's files; return the environment of a run."""
    bin_dir, tools = tmp_path / "bin", tmp_path / "tools"
    bin_dir.mkdir()
    tools.mkdir()
    fenced = {name: FENCE.format(real=shutil.which(name, path="/usr/bin:/bin")) for name in WRITERS}
    for name, answer in {**DEFAULTS, **fenced, **(answers or {})}.items():
        (tmp_path / f"answer-{name}.sh").write_text(answer + "\n", encoding="utf-8")
        stub = bin_dir / name
        stub.write_text(STUB, encoding="utf-8")
        stub.chmod(0o755)
    for name in READERS:
        (tools / name).symlink_to(shutil.which(name, path="/usr/bin:/bin"))
    (tmp_path / "os-release").write_text("VERSION_CODENAME=noble\n", encoding="utf-8")
    jvm = tmp_path / "jvm" / "lib"
    jvm.mkdir(parents=True)
    (jvm / "libawt_xawt.so").write_text("", encoding="utf-8")
    (tmp_path / "tmp").mkdir()
    (tmp_path / "calls").write_text("", encoding="utf-8")
    return {
        "PATH": f"{bin_dir}:{tools}",
        "HOME": str(tmp_path),
        "TMPDIR": str(tmp_path / "tmp"),
        "STUB_DIR": str(tmp_path),
        "SAMPLES": str(SAMPLES),
        "WORKCENTER_ROOT": str(tmp_path / "root"),
        "KICAD_KEYRING": str(tmp_path / "keyrings" / "kicad-10.0-releases.gpg"),
        "KICAD_SOURCES": str(tmp_path / "kicad-10.0-releases.sources"),
        "WORKCENTER_LINK": str(tmp_path / "workcenter"),
        "OS_RELEASE": str(tmp_path / "os-release"),
        "JVM_DIR": str(tmp_path / "jvm"),
    }


def calls_of(tmp_path: Path, expect: set | None = STEP) -> list[str]:
    """The calls file, after the check every test ends with: nothing refused, nothing unexpected."""
    calls = (tmp_path / "calls").read_text(encoding="utf-8").splitlines()
    assert [c for c in calls if c.startswith("REFUSED")] == []
    if expect is not None:
        assert {c.split(" ", 1)[0] for c in calls} <= expect, calls
    return calls


def script(path: Path, body: str) -> str:
    return f"set -euo pipefail\nsource {path}\n{body}\n"


def run(tmp_path: Path, answers: dict | None = None, env: dict | None = None, body: str = "step_apt"):
    """Source install.sh and run `body` with the stand-ins; return (exit code, stdout, stderr, calls)."""
    full_env = {**folder(tmp_path, answers), **(env or {})}
    proc = subprocess.run(
        [BASH, "-c", script(INSTALL, body)],
        capture_output=True,
        text=True,
        env=full_env,
        timeout=60,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr, calls_of(tmp_path)


def of(calls: list[str], name: str) -> list[str]:
    return [c for c in calls if c.split(" ", 1)[0] == name]


def updates(calls):
    return [c for c in of(calls, "apt-get") if " update" in c]


def installs(calls):
    """Every apt-get install, the download included."""
    return [c for c in of(calls, "apt-get") if " install " in c]


def test_index_on_the_first_try_then_the_download_then_the_install(tmp_path):
    """1 update, 0 waits, the candidates read, then the download (bounded) and the install from it."""
    code, out, err, calls = run(tmp_path)
    assert code == 0, err
    assert len(updates(calls)) == 1
    assert of(calls, "sleep") == []
    assert of(calls, "apt-cache") == ["apt-cache policy kicad kicad-symbols kicad-footprints kicad-templates"]
    download, install = installs(calls)
    assert "--download-only" in download and "--download-only" not in install
    assert "-o APT::Get::Download=false" in install
    # the download runs under its bound: 280 s by default
    assert "timeout 280 apt-get install" in "\n".join(of(calls, "timeout"))
    # the key was fetched and checked, and the sources file names the source
    assert (tmp_path / "keyrings" / "kicad-10.0-releases.gpg").read_text(encoding="utf-8") == "a key\n"
    assert "Suites: noble" in (tmp_path / "kicad-10.0-releases.sources").read_text(encoding="utf-8")
    # progress stays visible
    assert "[apt] Get:172 https://ppa.launchpadcontent.net/" in out
    assert "[apt] Setting up kicad (10.0.8~ubuntu24.04.1) ..." in out
    assert out.splitlines()[-1] == "[install] apt: done; kicad-cli 10.0.8"


def test_index_fails_2_times_then_arrives(tmp_path):
    """Tries 1 and 2 print the 503 line and end with 0 (as apt did in job 134932219722); try 3 is clean.
    3 updates, 2 waits of 20 s, then the install."""
    answer = f"""case "$*" in
  *update*) (( n <= 2 )) && {{ echo '{W_INDEX}' >&2; echo '{W_SOME}' >&2; }}; exit 0 ;;
esac
{DEFAULTS["apt-get"]}"""
    code, out, err, calls = run(tmp_path, {"apt-get": answer})
    assert code == 0, err
    assert len(updates(calls)) == 3
    assert of(calls, "sleep") == ["sleep 20", "sleep 20"]
    assert len(installs(calls)) == 2
    assert "[install] apt: update, try 3 of 3" in out
    assert out.splitlines()[-1] == "[install] apt: done; kicad-cli 10.0.8"


def test_index_never_arrives_stops_before_any_download(tmp_path):
    """3 tries (the default), 2 waits, 1 line with the source and apt's own line, exit 1, no install."""
    answer = f"""case "$*" in
  *update*) echo '{W_INDEX}' >&2; echo '{W_SOME}' >&2; exit 0 ;;
esac
{DEFAULTS["apt-get"]}"""
    code, out, err, calls = run(tmp_path, {"apt-get": answer}, body="step_apt; echo NEXT STEP")
    assert code == 1
    assert len(updates(calls)) == 3
    assert of(calls, "sleep") == ["sleep 20", "sleep 20"]
    assert installs(calls) == []
    assert of(calls, "apt-cache") == []
    stop = (
        "[install] ERROR: apt: the index of KiCad 10's package source did not arrive in 3 tries: "
        f"{SOURCE}; apt said: {W_INDEX}"
    )
    assert err.splitlines()[-2:] == [stop, AGAIN]
    assert "NEXT STEP" not in out


def test_the_tries_and_the_wait_are_read_from_the_environment(tmp_path):
    """KICAD_INDEX_TRIES=5 and KICAD_INDEX_WAIT=7: 5 updates, 4 waits of 7 s."""
    answer = f"""case "$*" in
  *update*) echo '{W_INDEX}' >&2; exit 0 ;;
esac"""
    code, _, err, calls = run(
        tmp_path, {"apt-get": answer}, env={"KICAD_INDEX_TRIES": "5", "KICAD_INDEX_WAIT": "7"}
    )
    assert code == 1
    assert len(updates(calls)) == 5
    assert of(calls, "sleep") == ["sleep 7"] * 4
    assert "did not arrive in 5 tries" in err


def test_an_update_that_does_not_end_is_a_failed_try(tmp_path):
    """The bound of 1 update is 75 s by default; `timeout` ends with 124 when it is reached."""
    answer = '[[ "$*" == *update* ]] && exit 124; shift; exec "$@"'
    code, _, err, calls = run(tmp_path, {"timeout": answer})
    assert code == 1
    assert of(calls, "timeout")[0] == "timeout 75 apt-get update -qq"
    assert len(of(calls, "timeout")) == 3
    stop = (
        "[install] ERROR: apt: the index of KiCad 10's package source did not arrive in 3 tries: "
        f"{SOURCE}; apt said: nothing: apt-get update did not end within 75 s (APT_UPDATE_TIMEOUT)"
    )
    assert err.splitlines()[-2:] == [stop, AGAIN]
    assert installs(calls) == []


def test_another_sources_warning_is_not_kicads(tmp_path):
    """A 503 of another source's index is apt's and the user's business: KiCad's index is there."""
    other = (
        "W: Failed to fetch http://azure.archive.ubuntu.com/ubuntu/dists/noble/InRelease"
        "  503  Service Unavailable"
    )
    answer = f"""case "$*" in
  *update*) echo '{other}' >&2; exit 0 ;;
esac
{DEFAULTS["apt-get"]}"""
    code, _, err, calls = run(tmp_path, {"apt-get": answer})
    assert code == 0, err
    assert len(updates(calls)) == 1


def test_a_candidate_from_ubuntu_stops_before_the_download(tmp_path):
    """The index arrives, but `kicad`'s candidate is Ubuntu's 7.0.11+dfsg-1build4: stop, no install."""
    code, out, err, calls = run(tmp_path, {"apt-cache": 'cat "$SAMPLES/policy-ubuntu-kicad.txt"'})
    assert code == 1
    assert installs(calls) == []
    stop = (
        "[install] ERROR: apt: KiCad 10's package source gave no candidate for kicad "
        "(apt has 7.0.11+dfsg-1build4 from http://azure.archive.ubuntu.com/ubuntu noble/universe): "
        f"{SOURCE}; apt said: nothing about this source"
    )
    assert err.splitlines()[-2:] == [stop, AGAIN]


def test_a_package_with_no_candidate_at_all_stops(tmp_path):
    """`apt-cache policy` prints nothing for a package it does not know: that is no candidate."""
    answer = "awk '/^kicad-templates:/{exit} {print}' \"$SAMPLES/policy-ppa.txt\""
    code, _, err, calls = run(tmp_path, {"apt-cache": answer})
    assert code == 1
    assert installs(calls) == []
    assert "gave no candidate for kicad-templates (apt has none): " in err.splitlines()[-2]


def test_a_failed_download_ends_with_apts_lines_and_stops_the_script(tmp_path):
    """apt-get ends with 100 and its E: lines (job 134906707485 at 15:44:22): exit 1, no install, no
    later step."""
    answer = f"""case "$*" in
  *--download-only*)
    echo "Get:172 https://ppa.launchpadcontent.net/x [48.0 MB]"
    echo '{E_FETCH}' >&2; echo '{E_SOME}' >&2; exit 100 ;;
esac
{DEFAULTS["apt-get"]}"""
    code, out, err, calls = run(tmp_path, {"apt-get": answer}, body="step_apt; echo NEXT STEP")
    assert code == 1
    assert [c for c in installs(calls) if "--download-only" not in c] == []
    assert E_FETCH in err.splitlines()
    assert "[apt] Get:172 https://ppa.launchpadcontent.net/x [48.0 MB]" in out
    stop = (
        "[install] ERROR: apt: the download ended with apt-get's exit code 100, within its bound of 280 s; "
        f"apt said: {E_FETCH}"
    )
    assert err.splitlines()[-2:] == [stop, LATER]
    assert "NEXT STEP" not in out
    assert of(calls, "kicad-cli") == ["kicad-cli version"]


def test_a_download_that_does_not_end_is_stopped_at_its_bound(tmp_path):
    """APT_DOWNLOAD_TIMEOUT=9: `timeout 9` ends with 124 and the line names the bound."""
    answer = '[[ "$*" == *--download-only* ]] && exit 124; shift; exec "$@"'
    code, _, err, calls = run(tmp_path, {"timeout": answer}, env={"APT_DOWNLOAD_TIMEOUT": "9"})
    assert code == 1
    assert [c for c in of(calls, "timeout") if "--download-only" in c][0].startswith(
        "timeout 9 apt-get install"
    )
    assert [c for c in installs(calls) if "--download-only" not in c] == []
    stop = (
        "[install] ERROR: apt: the download did not end within 9 s (APT_DOWNLOAD_TIMEOUT); apt said: nothing"
    )
    assert err.splitlines()[-2:] == [stop, LATER]


def test_a_progress_line_shows_while_apt_still_runs(tmp_path):
    """P2 step 1 and M86: the download's Get: line reaches the terminal before apt-get ends. The
    stand-in prints 1 line, then waits (at most 200 x 0.05 s = 10 s) for a file only the test writes
    once it has read that line."""
    answer = f"""case "$*" in
  *--download-only*)
    echo "Get:172 https://ppa.launchpadcontent.net/x [48.0 MB]"
    for _ in $(seq 200); do [[ -e "$STUB_DIR/go" ]] && exit 0; /bin/sleep 0.05; done
    exit 1 ;;
esac
{DEFAULTS["apt-get"]}"""
    env = folder(tmp_path, {"apt-get": answer})
    proc = subprocess.Popen(
        [BASH, "-c", script(INSTALL, "step_apt")],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    seen = []
    for line in proc.stdout:
        seen.append(line)
        if line.startswith("[apt] Get:172"):
            break
    assert seen and seen[-1] == "[apt] Get:172 https://ppa.launchpadcontent.net/x [48.0 MB]\n"
    assert proc.poll() is None  # apt-get is still running
    (tmp_path / "go").write_text("", encoding="utf-8")
    rest, _ = proc.communicate(timeout=30)
    assert proc.returncode == 0
    assert rest.splitlines()[-1] == "[install] apt: done; kicad-cli 10.0.8"
    calls_of(tmp_path)


def test_every_package_installed_and_apt_silent_passes(tmp_path):
    """KiCad 10 is there and apt prints no line: grep ends with 1, apt with 0, and apt's code decides."""
    (tmp_path / "installed").write_text("", encoding="utf-8")
    code, out, err, calls = run(tmp_path, {"apt-get": "exit 0"})
    assert code == 0, err
    assert "[apt]" not in out
    assert len(installs(calls)) == 2
    assert out.splitlines()[-1] == "[install] apt: done; kicad-cli 10.0.8"


def test_an_install_that_fails_after_the_download_stops(tmp_path):
    """apt-get ends with 100 on the install from the downloaded files: exit 1, the line names it."""
    answer = """case "$*" in
  *update*|*--download-only*) exit 0 ;;
  *install*) echo "E: Sub-process /usr/bin/dpkg returned an error code (1)" >&2; exit 100 ;;
esac"""
    code, _, err, _ = run(tmp_path, {"apt-get": answer})
    assert code == 1
    assert err.splitlines()[-1] == (
        "[install] ERROR: apt: the install from the downloaded files ended with apt-get's exit code 100; "
        "apt said: E: Sub-process /usr/bin/dpkg returned an error code (1)"
    )


def test_the_last_check_says_what_it_checked(tmp_path):
    """apt says all went well, but kicad-cli prints 7.0.11: the backstop names the command and the value."""
    answer = '[[ -e "$STUB_DIR/installed" ]] && { echo 7.0.11; exit 0; }; exit 1'
    code, _, err, _ = run(tmp_path, {"kicad-cli": answer})
    assert code == 1
    assert err.splitlines()[-1] == (
        "[install] ERROR: apt: after the install `kicad-cli version` prints 7.0.11, not 10.x"
    )


def test_kicad_10_present_skips_the_source_step(tmp_path):
    """No key, no sources file, no candidates read; 1 update, then the download and the install."""
    (tmp_path / "installed").write_text("", encoding="utf-8")
    code, out, err, calls = run(tmp_path)
    assert code == 0, err
    assert "[install] apt: KiCad 10 present (10.0.8); PPA step skipped" in out
    assert of(calls, "curl") == [] and of(calls, "apt-cache") == []
    assert not (tmp_path / "kicad-10.0-releases.sources").exists()
    assert len(updates(calls)) == 1
    assert " kicad " not in installs(calls)[0] + " "


def test_skip_apt_runs_nothing(tmp_path):
    code, out, err, calls = run(tmp_path, env={"SKIP_APT": "1"})
    assert code == 0, err
    assert out == "[install] apt: skipped (SKIP_APT=1)\n"
    assert calls == []


def test_sourcing_the_script_runs_no_step(tmp_path):
    code, out, err, calls = run(tmp_path, body="true")
    assert (code, out, err, calls) == (0, "", "", [])


GUARD = 'if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then\n  main "$@"\nfi\n'


def test_a_lost_guard_is_seen_and_stays_in_the_folder(tmp_path):
    """The script with its last line as it was before the guard (`main "$@"`), sourced the same way:
    main() runs, so the test above would fail on it. As root it runs the steps inside the folder; as
    another user it stops at "run as root". Either way no writer was refused a path outside."""
    text = INSTALL.read_text(encoding="utf-8")
    assert text.endswith(GUARD)
    env = folder(tmp_path)
    copy = tmp_path / "src" / "install.sh"
    copy.parent.mkdir()
    copy.write_text(text[: -len(GUARD)] + 'main "$@"\n', encoding="utf-8")
    proc = subprocess.run(
        [BASH, "-c", script(copy, "true")], capture_output=True, text=True, env=env, timeout=60, check=False
    )
    assert proc.stdout + proc.stderr != ""
    calls_of(tmp_path, expect=None)


def test_executing_the_script_runs_main(tmp_path):
    """`bash install.sh --check` reaches main, which hands over to `python3 tools/workcenter doctor`;
    the stand-in python3 ends with 7, and so does the script."""
    env = folder(tmp_path)
    proc = subprocess.run(
        [BASH, str(INSTALL), "--check"], capture_output=True, text=True, env=env, timeout=60, check=False
    )
    assert proc.returncode == 7
    assert calls_of(tmp_path, expect={"python3"}) == [f"python3 {ROOT}/tools/workcenter doctor"]


def test_main_runs_the_steps_in_the_same_order():
    text = INSTALL.read_text(encoding="utf-8")
    main = text[text.index("\nmain() {") :]
    assert re.findall(r"^  (step_\w+)$", main, re.M) == [
        "step_apt",
        "step_freerouting",
        "step_openems",
        "step_python",
        "step_link",
    ]


def test_every_path_written_outside_the_root_can_be_moved():
    """The paths a lost guard would reach are read from the environment, each with its real default,
    and no other path under /etc, /opt or /usr/local is in the script's code."""
    text = INSTALL.read_text(encoding="utf-8")
    for name, default in [
        ("KICAD_KEYRING", "/etc/apt/keyrings/kicad-10.0-releases.gpg"),
        ("KICAD_SOURCES", "/etc/apt/sources.list.d/kicad-10.0-releases.sources"),
        ("WORKCENTER_LINK", "/usr/local/bin/workcenter"),
        ("OS_RELEASE", "/etc/os-release"),
        ("JVM_DIR", "/usr/lib/jvm"),
    ]:
        assert f'{name}="${{{name}:-{default}}}"' in text
    assert 'WC_ROOT="${WORKCENTER_ROOT:-/opt/workcenters/${WC_NAME}}"' in text
    code = [line for line in text.splitlines() if not line.lstrip().startswith("#") and ":-/" not in line]
    assert [line for line in code if re.search(r"/(?:etc|usr/local|opt)/", line)] == []


def assigned(name: str) -> int:
    (value,) = re.findall(rf'^{name}="\${{{name}:-(\d+)}}"$', INSTALL.read_text(encoding="utf-8"), re.M)
    return int(value)


def test_the_worst_case_of_the_apt_step_fits_the_jobs_limit():
    """CI's `full` job has 1800 s (.github/workflows/ci.yml, timeout-minutes: 30). The passing run of
    2026-11-18 (job 134889089620) used 8 s for the checkout (14:53:47 to 14:53:55), 32 s for the
    steps after apt (316 s in all, less 284 s of apt), 31 s to unpack and set up (14:58:08 to 14:58:39)
    and 1152 s for `make verify` (14:59:12 to 15:18:24): 1800 - 8 - 32 - 31 - 1152 = 577 s are left
    for the updates, the waits and the download. 3 x 75 + 2 x 20 + 280 = 545 s."""
    tries, wait = assigned("KICAD_INDEX_TRIES"), assigned("KICAD_INDEX_WAIT")
    update, download = assigned("APT_UPDATE_TIMEOUT"), assigned("APT_DOWNLOAD_TIMEOUT")
    assert (tries, wait, update, download) == (3, 20, 75, 280)
    assert tries * update + (tries - 1) * wait + download <= 1800 - 8 - 32 - 31 - 1152


def test_the_step_holds_no_bare_bound():
    """Every wait and bound of the apt step is a named variable. curl's own bounds on the key
    (`--connect-timeout 20`) belong to the key fetch, which this change leaves as it was."""
    text = INSTALL.read_text(encoding="utf-8")
    step = text[text.index("\nkicad10_present() {") : text.index("\nstep_freerouting() {")]
    assert re.findall(r"(?<![-\w])(?:sleep|timeout) [0-9]", step) == []
    assert re.findall(r"(?:Retries|Timeout)=[0-9]", step) == []


def test_the_script_parses_and_shellcheck_is_clean():
    proc = subprocess.run(["bash", "-n", str(INSTALL)], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
    proc = subprocess.run(["shellcheck", str(INSTALL)], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout


def test_each_mutation_of_the_list_changes_1_place_of_the_script():
    """tests/install_mutations.py: an edit of the step that moves an anchor fixes it in the same commit."""
    tree = ast.parse((ROOT / "tests" / "install_mutations.py").read_text(encoding="utf-8"))
    found = {n.targets[0].id: ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)}
    text = INSTALL.read_text(encoding="utf-8")
    names = [m[0].split()[0] for m in found["MUTATIONS"]]
    assert len(names) == len(set(names))
    for name, path, old, new in found["MUTATIONS"]:
        assert path == "install.sh", name
        assert text.count(old) == 1, name
        assert old != new, name
    assert "tests/test_install_apt.py" in found["TEST"]
