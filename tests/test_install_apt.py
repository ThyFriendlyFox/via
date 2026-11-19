"""The apt step of install.sh when KiCad 10's package source does not answer.

On 2026-11-18 Launchpad's host answered 503 2 times. Job 134932219722: the index of the source did not
arrive, `apt-get update` ended with 0 and only `W:` lines, and apt installed Ubuntu's own KiCad 7.0.11.
Job 134906707485: the index arrived, a package file did not, the pipeline's `|| true` hid apt's exit
code. Both ended with `kicad-cli 10.x not found after install`.

Each test sources install.sh (its steps run only when it is executed) and runs `step_apt`.

The machine that runs these tests may run as root, and the script's steps write to /etc, /opt and
/usr/local. The first run of this file, before the script had its guard, sourced it as root: main()
ran and relinked /usr/local/bin/workcenter. So each test stays inside its own folder in 4 ways:
1. Every path the script writes or reads outside its folder is set in the environment before the
   script is sourced: WORKCENTER_ROOT, KICAD_KEYRING, KICAD_SOURCES, WORKCENTER_LINK, OS_RELEASE,
   JVM_DIR, CA_BUNDLE, HOME and TMPDIR all point into the test's folder, and the folder is the
   working directory. A lost guard runs main() there.
2. PATH holds only 2 folders the test makes. `bin/` holds the stand-ins: `apt-get`, `apt-cache`,
   `timeout`, `sleep`, `kicad-cli`, `curl`, `gpg`, `python3`, each writing its call to a calls file and
   answering from a bash snippet the test gives it; and the writers `chmod`, `install`, `mkdir`, `mv`,
   `rm`, `touch`, `ln`, `cp`, `tee`, `mktemp`, which write their call too and run the real program only
   when every path among their arguments, `..` resolved, is inside the folder (else they write
   `REFUSED` and end with 99). `tools/` holds the programs that read: `awk`, `sed` and `find` behind a
   guard that refuses what would make them write (`sed -i` and its `w` and `e` commands; an awk
   program with `>`, `|`, `system` or `getline` outside its texts and patterns, or `-i`, `-f`; find's
   `-delete`, `-exec`, `-ok` and `-fprint`), and links to `basename`, `cat`, `dirname`, `grep`, `head`,
   `seq`, `tail`, which cannot write. No pip, venv, dpkg or real apt can be reached.
3. A redirection of the shell (`>`) is no program and passes no fence: the script's code holds no
   literal path but its defaults, /dev/null and /var/lib/dpkg/status
   (test_no_literal_path_outside_the_folder_is_in_the_scripts_code).
4. Each test ends by checking its calls file: no `REFUSED`, and no program it did not expect.
No test needs root, the network, real apt or a real wait.
"""

from __future__ import annotations

import ast
import functools
import os
import re
import shlex
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "install.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
SAMPLES = ROOT / "tests" / "samples" / "install"
BASH = "/bin/bash"
# A person's computer has no total bound; CI sets these 2 in its install step (the workflow file, held to
# them by test_the_worst_case_of_the_apt_step_fits_the_jobs_limit).
CI = {"APT_UPDATE_TIMEOUT": "120", "APT_DOWNLOAD_TIMEOUT": "570"}

URL = "https://ppa.launchpadcontent.net/kicad/kicad-10.0-releases/ubuntu"
SOURCE = f"{URL} noble"
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
# Printed by the real apt-cache 2.8.3 on this machine with a second .sources file for the source under
# another key (-o Dir::Etc::sourceparts=<a folder with both files>); apt-get update reads the same list.
E_SIGNED = (
    f"E: Conflicting values set for option Signed-By regarding source {URL}/ noble: "
    "/etc/apt/keyrings/kicad-10.0-releases.gpg != /etc/apt/trusted.gpg.d/kicad-ubuntu-kicad-10_0-releases.gpg"
)
E_LIST = "E: The list of sources could not be read."
# Built from apt 2.8.3's templates (po/apt-all.pot: "The repository '%s' does not have a Release file.",
# "An error occurred during the signature verification. ... GPG error: %s: %s", "Could not get lock %s.
# It is held by process %d (%s)", "Unable to lock directory %s"), with the source named as apt names it
# (the address without its last slash, the suite); not printed by a real apt here.
E_RELEASE = f"E: The repository '{URL} bookworm Release' does not have a Release file."
N_SECURE = "N: Updating from such a repository can't be done securely, and is therefore disabled by default."
N_MANPAGE = "N: See apt-secure(8) manpage for repository creation and user configuration details."
W_GPG = (
    "W: An error occurred during the signature verification. The repository is not updated and the previous "
    f"index files will be used. GPG error: {URL} noble InRelease: The following signatures were invalid: "
    "EXPKEYSIG FDA854F61C4D0D95 Launchpad PPA for KiCad"
)
E_LOCK = "E: Could not get lock /var/lib/apt/lists/lock. It is held by process 2345 (apt-get)"
E_LOCKDIR = "E: Unable to lock directory /var/lib/apt/lists/"

NONE = "[install] This run installed no KiCad."
AGAIN = (
    f"{NONE} KiCad 10 comes from a third party's package source (Launchpad's KiCad PPA), "
    "which did not answer this time: run the script again later."
)
NOT_10 = (
    f"{NONE} KiCad 10 comes from a third party's package source (Launchpad's KiCad PPA), "
    "which does not offer every package as 10.x now: run the script again later."
)
OUTRANKED = (
    "A pin (apt_preferences) or another package source outranks KiCad 10's package source; "
    "`apt-cache policy kicad` shows which. Remove it, then run the script again."
)
# Both stops of the download say what a person's computer keeps and what an image build keeps: a failed
# step of a `docker build` keeps no file it fetched.
KEPT = (
    "On a computer, apt keeps the files it has downloaded and asks only for the rest; "
    "an image build keeps none from a failed step."
)
LATER = (
    "[install] No package was installed. A package source did not serve a file this time: "
    f"run the script again later. {KEPT}"
)
CUT = (
    f"[install] No package was installed. Run the script again. {KEPT} On a slow line, give it more "
    "seconds: sudo env APT_DOWNLOAD_TIMEOUT=<seconds> ./install.sh (sudo drops a variable set before it)."
)
# Copied from the log of the amd64 image build of pull request 92 on 2026-11-18 (#9 113.4): under
# --download-only apt-get prints 1 `E: Failed to fetch <address>  <reason>` line per file it did not get
# (apt 2.8.3, apt-private/private-download.cc:117), then `E: Some files failed to download`
# (apt-private/private-install.cc:399), and ends with 100 (apt-private/private-cmndline.cc:605).
E_KICAD = (
    "E: Failed to fetch https://ppa.launchpadcontent.net/kicad/kicad-10.0-releases/ubuntu/pool/main/k/kicad/"
    "kicad_10.0.8%7eubuntu24.04.1_amd64.deb  503  Service Unavailable [IP: 185.125.189.187 443]"
)
E_FILES = "E: Some files failed to download"
# Built from apt 2.8.3's template "You don't have enough free space in %s." (private-download.cc:156)
# with apt's archives folder; not printed by a real apt here.
E_SPACE = "E: You don't have enough free space in /var/cache/apt/archives/."

STUB = """#!/bin/bash
name="${0##*/}"
printf '%s %s\\n' "$name" "$*" >> "$STUB_DIR/calls"
n="$(@GREP@ -c "^${name} " "$STUB_DIR/calls")"
. "$STUB_DIR/answer-${name}.sh"
"""

# A writer runs the real program only when every path among its arguments (an option's `=value`
# included), `..` resolved against the folder it runs in, is inside the test's folder.
FENCE = """root="$(@REALPATH@ -m -- "$STUB_DIR")"
for a in "$@"; do
  p="$a"
  if [[ "$a" == -* ]]; then [[ "$a" == *=* ]] || continue; p="${a#*=}"; fi
  [[ -n "$p" ]] || continue
  r="$(@REALPATH@ -m -- "$p")"
  if [[ "$r" != "$root" && "$r" != "$root"/* ]]; then
    echo "REFUSED $name $*" >> "$STUB_DIR/calls"; exit 99
  fi
done
exec @REAL@ "$@"
"""
WRITERS = ["chmod", "install", "mkdir", "mv", "rm", "touch", "ln", "cp", "tee", "mktemp"]

# A reader that can write when told to runs the real program only when no argument tells it to.
GUARD = r"""#!/bin/bash
refuse() { echo "REFUSED @NAME@ $*" >> "$STUB_DIR/calls"; exit 99; }
sed_cmd='(^|[;{}/0-9$[:space:]])[wWe]([[:space:]]|$)'
for a in "$@"; do
  case "@NAME@" in
    sed)
      if [[ "$a" == --in-place* || "$a" =~ ^-[a-zA-Z]*i || "$a" =~ $sed_cmd ]]; then refuse "$@"; fi ;;
    awk)
      case "$a" in -i* | --include* | -f* | --file* | -E* | --exec*) refuse "$@" ;; esac
      bare="$(printf '%s' "$a" | @SED@ -E 's/"([^"\\]|\\.)*"//g; s#/([^/\\]|\\.)*/##g')"
      if [[ "$bare" == *'>'* || "$bare" == *'|'* || "$bare" == *system* || "$bare" == *getline* ]]; then
        refuse "$@"
      fi ;;
    find)
      case "$a" in
        -delete | -exec | -execdir | -ok | -okdir | -fprint | -fprint0 | -fprintf | -fls) refuse "$@" ;;
      esac ;;
  esac
done
exec @REAL@ "$@"
"""
GUARDED = ["awk", "sed", "find"]
READERS = ["basename", "cat", "dirname", "grep", "head", "readlink", "seq", "tail"]

# The stand-in python3 on the key's pipe reads all its input before it ends, as the real one does
# (json.load reads to the end first). One that ends unread races the stand-in curl: when python3 ends
# first, curl's write dies of SIGPIPE, pipefail fails the pipeline, and a test's answer rests on which
# process ended first (M270: IA82 survived 1 run in 3). Any other call of python3 reads nothing: its
# input is the test's, which may be a terminal.
DRAINS = 'case "$*" in *json.load*) cat > /dev/null ;; esac; '

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
    "python3": f"{DRAINS}exit 7",
}

# The programs the apt step may call. A call of any other program fails the test.
STEP = {"apt-get", "apt-cache", "timeout", "sleep", "kicad-cli", "curl", "gpg"}
STEP |= {"install", "mv", "chmod", "rm", "touch", "mktemp", "tee"}
# The key's second address answers JSON, which python3 reads (a stand-in here).
STEP |= {"python3"}


def real(name: str) -> str:
    found = shutil.which(name, path="/usr/bin:/bin")
    assert found, name
    return found


@functools.cache
def unfenced_in_the_script() -> tuple:
    """What the scans below find in install.sh: read once, before any test runs the script."""
    text = INSTALL.read_text(encoding="utf-8")
    return tuple(literal_paths(text)) + tuple(unfenced_writes(text))


def folder(tmp_path: Path, answers: dict | None = None, xawt: bool = True) -> dict:
    """Make the stand-ins, the readers and the folder's files; return the environment of a run. No test
    runs the script while the scans see a write that passes no fence: a redirection runs before any
    test could fail on it. `xawt`: the JVM of the 21 under JVM_DIR has AWT's X11 library, as after
    openjdk-21-jre."""
    assert unfenced_in_the_script() == ()
    # No stand-in python3 may end before it has read the key's pipe (M270).
    assert {**DEFAULTS, **(answers or {})}["python3"].startswith(DRAINS)
    bin_dir, tools = tmp_path / "bin", tmp_path / "tools"
    bin_dir.mkdir()
    tools.mkdir()
    fence = FENCE.replace("@REALPATH@", real("realpath"))
    fenced = {name: fence.replace("@REAL@", real(name)) for name in WRITERS}
    for name, answer in {**DEFAULTS, **fenced, **(answers or {})}.items():
        (tmp_path / f"answer-{name}.sh").write_text(answer + "\n", encoding="utf-8")
        stub = bin_dir / name
        stub.write_text(STUB.replace("@GREP@", real("grep")), encoding="utf-8")
        stub.chmod(0o755)
    for name in GUARDED:
        guard = GUARD.replace("@NAME@", name).replace("@REAL@", real(name)).replace("@SED@", real("sed"))
        (tools / name).write_text(guard, encoding="utf-8")
        (tools / name).chmod(0o755)
    for name in READERS:
        (tools / name).symlink_to(real(name))
    (tmp_path / "os-release").write_text("VERSION_CODENAME=noble\n", encoding="utf-8")
    (tmp_path / "ca-certificates.crt").write_text("a bundle\n", encoding="utf-8")
    (tmp_path / "jvm").mkdir()
    if xawt:
        jvm = tmp_path / "jvm" / "java-21-openjdk-amd64" / "lib"
        jvm.mkdir(parents=True)
        (jvm / "libawt_xawt.so").write_text("", encoding="utf-8")
    (tmp_path / "tmp").mkdir()
    (tmp_path / "archives" / "partial").mkdir(parents=True, exist_ok=True)
    (tmp_path / "sources.list.d").mkdir(exist_ok=True)
    (tmp_path / "calls").write_text("", encoding="utf-8")
    return {
        "PATH": f"{bin_dir}:{tools}",
        "HOME": str(tmp_path),
        "TMPDIR": str(tmp_path / "tmp"),
        "STUB_DIR": str(tmp_path),
        "SAMPLES": str(SAMPLES),
        "WORKCENTER_ROOT": str(tmp_path / "root"),
        "KICAD_KEYRING": str(tmp_path / "keyrings" / "kicad-10.0-releases.gpg"),
        "KICAD_SOURCES": str(tmp_path / "sources.list.d" / "kicad-10.0-releases.sources"),
        "WORKCENTER_LINK": str(tmp_path / "workcenter"),
        "OS_RELEASE": str(tmp_path / "os-release"),
        "JVM_DIR": str(tmp_path / "jvm"),
        "CA_BUNDLE": str(tmp_path / "ca-certificates.crt"),
        "APT_ARCHIVES": str(tmp_path / "archives"),
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


def run(
    tmp_path: Path,
    answers: dict | None = None,
    env: dict | None = None,
    body: str = "step_apt",
    xawt: bool = True,
):
    """Source install.sh and run `body` with the stand-ins; return (exit code, stdout, stderr, calls)."""
    full_env = {**folder(tmp_path, answers, xawt=xawt), **(env or {})}
    proc = subprocess.run(
        [BASH, "-c", script(INSTALL, body)],
        capture_output=True,
        text=True,
        env=full_env,
        cwd=tmp_path,
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


def update_says(*lines: str, code: int = 0) -> str:
    """An apt-get whose every update prints `lines` on stderr and ends with `code`."""
    printed = "; ".join(f"echo {shlex.quote(line)} >&2" for line in lines)
    return f"""case "$*" in
  *update*) {printed}; exit {code} ;;
esac
{DEFAULTS["apt-get"]}"""


def test_index_on_the_first_try_then_the_download_then_the_install(tmp_path):
    """1 update, 0 waits, the candidates read, then the download and the install from it. A person's
    computer sets no bound: no `timeout` runs, and apt's own per-file bounds stay."""
    code, out, err, calls = run(tmp_path)
    assert code == 0, err
    assert updates(calls) == ["apt-get update -q"]
    assert of(calls, "sleep") == []
    assert of(calls, "apt-cache") == ["apt-cache policy kicad kicad-symbols kicad-footprints kicad-templates"]
    download, install = installs(calls)
    assert "--download-only" in download and "--download-only" not in install
    assert download.startswith("apt-get install ") and "-o Acquire::http::Timeout=60" in download
    assert "-o APT::Get::Download=false" in install
    assert of(calls, "timeout") == []
    # the key was fetched within its bound (the second review's S2-5) and checked
    (fetch,) = of(calls, "curl")
    assert fetch.startswith("curl -fsSL --retry 3 --retry-max-time 20 --connect-timeout 20 --max-time 20 ")
    # the sources file names the source
    assert (tmp_path / "keyrings" / "kicad-10.0-releases.gpg").read_text(encoding="utf-8") == "a key\n"
    sources = tmp_path / "sources.list.d" / "kicad-10.0-releases.sources"
    assert "Suites: noble" in sources.read_text(encoding="utf-8")
    # progress stays visible
    assert "[apt] Get:172 https://ppa.launchpadcontent.net/" in out
    assert "[apt] Setting up kicad (10.0.8~ubuntu24.04.1) ..." in out
    assert out.splitlines()[-1] == "[install] apt: done; kicad-cli 10.0.8"


KEYSERVER_SAID = "curl: (28) Connection timed out after 20002 milliseconds"
LAUNCHPAD_SAID = "curl: (6) Could not resolve host: api.launchpad.net"
KEY_NOT_THERE = (
    f"{NONE} Check that this computer reaches keyserver.ubuntu.com or api.launchpad.net, "
    "then run the script again."
)


def key_stop(keyserver: str, launchpad: str) -> str:
    return (
        "[install] ERROR: apt: the PPA signing key did not arrive from keyserver.ubuntu.com "
        f"(curl said: {keyserver}) or from api.launchpad.net (curl said: {launchpad}); "
        "each try of each address had at most 20 s (KICAD_KEY_TIMEOUT)"
    )


def test_a_key_from_neither_address_stops_with_what_curl_said_and_not_a_mismatch(tmp_path):
    """Both addresses fail: the stop names both, the bound and curl's own error line of each, where it
    said "fingerprint mismatch" (or ended with the pipeline's code and no line). Nothing is written."""
    curl = f"""case "$*" in
  *keyserver.ubuntu.com*) echo {shlex.quote(KEYSERVER_SAID)} >&2; exit 28 ;;
  *) echo {shlex.quote(LAUNCHPAD_SAID)} >&2; exit 6 ;;
esac"""
    code, out, err, calls = run(tmp_path, {"curl": curl}, body="step_apt; echo NEXT STEP")
    assert code == 1, err
    assert "NEXT STEP" not in out
    assert "fingerprint" not in err
    assert err.splitlines()[-2:] == [key_stop(KEYSERVER_SAID, LAUNCHPAD_SAID), KEY_NOT_THERE]
    assert len(of(calls, "curl")) == 2 and updates(calls) == []
    assert sorted(p.name for p in (tmp_path / "keyrings").iterdir()) == []
    assert not (tmp_path / "sources.list.d" / "kicad-10.0-releases.sources").exists()


@pytest.mark.parametrize("python3", ["exit 7", "exit 0"], ids=["no JSON", "an empty string"])
def test_an_answer_that_holds_no_key_is_said_so(tmp_path, python3):
    """The keyserver answers nothing, and api.launchpad.net answers what is no JSON string (the stand-in
    python3 ends with 7) or an empty one (it prints nothing and ends with 0, so only the empty file
    tells): curl said nothing, and the stop says the answer held no key. python3 reads curl's answer
    before it ends (DRAINS), so curl ends with 0 and, for the empty string, every process of the
    pipeline does: only the empty file can send the script to the stop, whichever process ends first."""
    curl = 'case "$*" in *keyserver.ubuntu.com*) exit 0 ;; *) echo "<html>"; exit 0 ;; esac'
    gpg = 'while (( $# )); do [[ "$1" == -o ]] && { cat > "$2"; exit 0; }; shift; done; exit 0'
    answers = {"curl": curl, "gpg": gpg, "python3": DRAINS + python3}
    code, out, err, calls = run(tmp_path, answers, body="step_apt; echo NEXT STEP")
    assert code == 1, err
    assert len(of(calls, "python3")) == 1
    nothing = "nothing; the answer held no key"
    assert err.splitlines()[-2:] == [key_stop(nothing, nothing), KEY_NOT_THERE]


def test_a_key_with_another_fingerprint_is_a_mismatch(tmp_path):
    """A key that arrived with another fingerprint keeps its old stop, and is not trusted."""
    gpg = DEFAULTS["gpg"].replace("FDA854F61C4D0D9572BB95E5245D5502FAD7A805", "0" * 40)
    code, out, err, calls = run(tmp_path, {"gpg": gpg}, body="step_apt; echo NEXT STEP")
    assert code == 1
    assert err.splitlines()[-1] == "[install] ERROR: apt: PPA key fingerprint mismatch; refusing to trust it"
    assert not (tmp_path / "keyrings" / "kicad-10.0-releases.gpg").exists()
    assert updates(calls) == []


def test_the_bounds_ci_sets_run_the_update_and_the_download_under_timeout(tmp_path):
    """APT_UPDATE_TIMEOUT=120 and APT_DOWNLOAD_TIMEOUT=570, as CI's install step sets them: the update
    and the download run under `timeout`; the install from the downloaded files does not."""
    code, out, err, calls = run(tmp_path, env=CI)
    assert code == 0, err
    bounded = of(calls, "timeout")
    assert bounded[0] == "timeout 120 apt-get update -q"
    assert bounded[1].startswith("timeout 570 apt-get install -y --no-install-recommends --download-only ")
    assert len(bounded) == 2
    assert out.splitlines()[-1] == "[install] apt: done; kicad-cli 10.0.8"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("APT_DOWNLOAD_TIMEOUT", "abc"),
        ("APT_DOWNLOAD_TIMEOUT", "0"),
        ("APT_DOWNLOAD_TIMEOUT", "-5"),
        ("APT_DOWNLOAD_TIMEOUT", "10m"),
        ("APT_UPDATE_TIMEOUT", "abc"),
        ("APT_UPDATE_TIMEOUT", "0"),
    ],
)
def test_a_bound_that_is_not_a_whole_number_of_seconds_stops_before_anything_runs(tmp_path, name, value):
    """1 line that names the variable and its value; no program ran, SKIP_APT or not."""
    for skip in ("0", "1"):
        (tmp_path / skip).mkdir()
        code, out, err, calls = run(tmp_path / skip, env={name: value, "SKIP_APT": skip})
        assert (code, out, calls) == (1, "", [])
        assert err == (
            f"[install] ERROR: {name}={value} is not a whole number of seconds above 0; "
            f"set it to one, or leave {name} unset for no bound\n"
        )


def test_an_empty_bound_is_no_bound(tmp_path):
    """Set but empty is the default: no `timeout` runs."""
    code, _, err, calls = run(tmp_path, env={"APT_UPDATE_TIMEOUT": "", "APT_DOWNLOAD_TIMEOUT": ""})
    assert code == 0, err
    assert of(calls, "timeout") == []


@pytest.mark.parametrize("step", ["update", "download"])
def test_apts_own_code_124_with_no_bound_is_no_cut(tmp_path, step):
    """With no bound set, an exit code 124 is apt's own: the stop quotes it and names no bound."""
    if step == "update":
        answer = update_says(E_LOCKDIR, code=124)
        said = (
            "[install] ERROR: apt: the index of KiCad 10's package source did not arrive in 3 tries: "
            f"{SOURCE}; apt said: exit code 124: {E_LOCKDIR}"
        )
    else:
        answer = f"""case "$*" in
  *--download-only*) exit 124 ;;
esac
{DEFAULTS["apt-get"]}"""
        said = (
            "[install] ERROR: apt: the download ended with apt-get's exit code 124 after 1 pass of 5; "
            "apt said: nothing"
        )
    code, _, err, calls = run(tmp_path, {"apt-get": answer})
    assert code == 1
    assert of(calls, "timeout") == []
    assert err.splitlines()[-2] == said


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
    answers = {"apt-get": update_says(W_INDEX, W_SOME)}
    code, out, err, calls = run(tmp_path, answers, body="step_apt; echo NEXT STEP")
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
    """With CI's bound of 120 s on 1 update, `timeout` ends with 124 when it is reached. `apt-get update`
    fetches every source's index, and -qq names none: the stop blames no source (job 134906707485's
    slow minutes were an Ubuntu mirror's)."""
    answer = '[[ "$*" == *update* ]] && exit 124; shift; exec "$@"'
    code, _, err, calls = run(tmp_path, {"timeout": answer}, env=CI)
    assert code == 1
    assert of(calls, "timeout")[0] == "timeout 120 apt-get update -q"
    assert len(of(calls, "timeout")) == 3
    stop = (
        "[install] ERROR: apt: the index of KiCad 10's package source did not arrive in 3 tries: "
        f"{SOURCE}; apt said: nothing: `apt-get update` of every package source did not end within 120 s "
        f"(APT_UPDATE_TIMEOUT); the sources that had not answered in try 3: {URL}/ noble"
    )
    advice = (
        f"{NONE} `apt-get update` fetches the index of every package source on this computer, and they did "
        "not all arrive within APT_UPDATE_TIMEOUT this time: run the script again later."
    )
    assert err.splitlines()[-2:] == [stop, advice]
    assert "Launchpad" not in err
    assert installs(calls) == []


# The runner's layout (actions/runner-images, configure-apt-sources.sh, after tools/ci/apt_archive.sh): 2
# suites through the mirror list, the security suite from 1 host, and a third party's one-line source.
def runner_sources(tmp_path: Path) -> str:
    """Write the sources and the mirror list into the test's folder; return the list's source address."""
    listed = tmp_path / "apt-mirrors.txt"
    listed.write_text(
        "# the runner's list\nhttp://slow.example/ubuntu/\tpriority:1\nhttps://archive.ubuntu.com/ubuntu/\tpriority:2\n",
        encoding="utf-8",
    )
    (tmp_path / "sources.list.d").mkdir(exist_ok=True)
    (tmp_path / "sources.list.d" / "ubuntu.sources").write_text(
        f"Types: deb\nURIs: mirror+file:{listed}\nSuites: noble noble-updates\nComponents: main universe\n\n"
        "Types: deb\nURIs: http://security.ubuntu.com/ubuntu/\nSuites: noble-security\nComponents: main\n",
        encoding="utf-8",
    )
    (tmp_path / "sources.list").write_text(
        "# deb http://commented.example/ubuntu noble main\n"
        "deb [arch=amd64] https://packages.example.com/repo stable main\n",
        encoding="utf-8",
    )
    return f"mirror+file:{listed}"


# What apt printed before the bound ended a try: every source but the mirror list's 2 suites answered.
HEARD = (
    "Hit:1 http://security.ubuntu.com/ubuntu noble-security InRelease",
    f"Get:2 {URL} noble InRelease [24.3 kB]",
    "Ign:3 https://packages.example.com/repo stable InRelease",
)


def cut_update(*lines: str) -> str:
    """A `timeout` whose every update prints `lines` (apt's, on its standard output) and is cut (124)."""
    printed = "; ".join(f"echo {shlex.quote(line)}" for line in lines) or ":"
    return f'[[ "$*" == *update* ]] && {{ {printed}; exit 124; }}; shift; exec "$@"'


def silent(listed: str) -> str:
    """The mirror list's 2 suites, as a cut try names them: the list's hosts in its order."""
    hosts = "(slow.example, archive.ubuntu.com)"
    return f"{listed} noble {hosts}, {listed} noble-updates {hosts}"


def silent_line(try_: int, listed: str, shown: int) -> str:
    return (
        f"[install] apt: update, try {try_} of 3, did not end within 120 s (APT_UPDATE_TIMEOUT); the sources "
        f"that had not answered (no Hit, Get, Ign or Err line): {silent(listed)}; "
        f"apt's last {shown} lines of that try:"
    )


def test_a_cut_try_names_the_sources_that_had_not_answered_and_shows_apts_last_lines(tmp_path):
    """Job 135588570683 (2026-11-19): 3 tries of 120 s each, and the log said no more than that: -qq hid
    which source stalled. Now each cut try says which sources printed no Hit, Get, Ign or Err line (a
    mirror list's with its hosts in its order), then apt's own last lines of that try as apt printed
    them. The stop repeats the sources of the last try."""
    listed = runner_sources(tmp_path)
    code, out, err, calls = run(tmp_path, {"timeout": cut_update(*HEARD)}, env=CI)
    assert code == 1
    assert [c for c in of(calls, "timeout") if "update" in c] == ["timeout 120 apt-get update -q"] * 3
    lines = out.splitlines()
    for try_ in (1, 2, 3):
        at = lines.index(silent_line(try_, listed, 3))
        assert lines[at + 1 : at + 4] == [f"[apt] {x}" for x in HEARD]
    assert err.splitlines()[-2].endswith(f"; the sources that had not answered in try 3: {silent(listed)}")


def test_a_cut_try_shows_at_most_its_last_10_lines(tmp_path):
    """apt's lines of a cut try are shown unfiltered, but no more than the last 10: a try with 15 lines
    shows lines 6 to 15. A try that printed nothing says so."""
    runner_sources(tmp_path)
    many = [f"Hit:{n} http://security.ubuntu.com/ubuntu noble-security InRelease {n}" for n in range(1, 16)]
    code, out, _, _ = run(tmp_path, {"timeout": cut_update(*many)}, env=CI)
    assert code == 1
    lines = out.splitlines()
    at = [i for i, x in enumerate(lines) if x.startswith("[install] apt: update, try 1 of 3, did not end")]
    assert len(at) == 1 and lines[at[0]].endswith("; apt's last 10 lines of that try:")
    assert lines[at[0] + 1 : at[0] + 11] == [f"[apt] {x}" for x in many[5:]]
    (tmp_path / "quiet").mkdir()
    code, out, _, _ = run(tmp_path / "quiet", {"timeout": cut_update()}, env=CI)
    said = [x for x in out.splitlines() if "did not end within" in x]
    assert len(said) == 3 and all(x.endswith("; apt printed no line in that try") for x in said)


def test_between_2_cut_tries_the_named_command_moves_the_mirror_lists_silent_hosts(tmp_path):
    """The hook of the download (APT_SLOW_PASS_COMMAND, CI: tools/ci/apt_archive.sh --slow) runs between
    2 tries too, with the hosts of the mirror list's sources that had not answered, in the list's order:
    the first goes last. It runs before the wait, and not after the last try."""
    runner_sources(tmp_path)
    hook = 'printf "%s\\n" "$*" >> "$STUB_DIR/hooked"; echo "[apt-archive] moved"'
    env = {**CI, "APT_SLOW_PASS_COMMAND": "slow-pass --slow"}
    code, out, err, calls = run(tmp_path, {"timeout": cut_update(*HEARD), "slow-pass": hook}, env=env)
    assert code == 1
    steps = [c.split(" ", 1)[0] for c in calls if c.split(" ", 1)[0] in ("timeout", "slow-pass", "sleep")]
    assert steps == ["timeout", "slow-pass", "sleep", "timeout", "slow-pass", "sleep", "timeout"]
    assert of(calls, "slow-pass") == ["slow-pass --slow slow.example archive.ubuntu.com"] * 2
    said = "[install] apt: APT_SLOW_PASS_COMMAND: slow-pass --slow slow.example archive.ubuntu.com"
    assert out.splitlines().count(said) == 2


def test_a_silent_source_of_1_host_is_simply_tried_again(tmp_path):
    """Only KiCad 10's source (1 host, Launchpad's PPA) printed nothing: no mirror list holds it, so no
    command runs; the next try asks it again, and a hook that fails is said with the try's word."""
    runner_sources(tmp_path)
    heard = (
        "Hit:1 http://slow.example/ubuntu noble InRelease",
        "Get:2 https://archive.ubuntu.com/ubuntu noble-updates InRelease [126 kB]",
        *HEARD[0::2],
    )
    env = {**CI, "APT_SLOW_PASS_COMMAND": "slow-pass --slow"}
    code, out, err, calls = run(tmp_path, {"timeout": cut_update(*heard), "slow-pass": "exit 3"}, env=env)
    assert code == 1
    assert of(calls, "slow-pass") == [] and len(updates(calls)) == 0
    assert len([c for c in of(calls, "timeout") if "update" in c]) == 3
    assert err.splitlines()[-2].endswith(f"; the sources that had not answered in try 3: {URL}/ noble")


def test_a_hook_that_fails_between_2_tries_is_said_and_the_next_try_runs(tmp_path):
    runner_sources(tmp_path)
    env = {**CI, "APT_SLOW_PASS_COMMAND": "slow-pass --slow"}
    code, out, err, calls = run(tmp_path, {"timeout": cut_update(*HEARD), "slow-pass": "exit 3"}, env=env)
    assert code == 1
    failed = (
        "[install] WARN: apt: APT_SLOW_PASS_COMMAND ended with exit code 3; the next try asks the hosts "
        "in the order they had"
    )
    assert err.splitlines().count(failed) == 2
    assert len([c for c in of(calls, "timeout") if "update" in c]) == 3


def test_a_try_that_ends_shows_apts_warnings_but_not_its_progress(tmp_path):
    """The update runs with -q, so apt prints a Hit, Get, Ign or Err line per index: a try that ends
    shows apt's W: and E: lines and its Err: lines, as before, and not the others."""
    azure = "http://azure.archive.ubuntu.com/ubuntu"
    other = f"W: Failed to fetch {azure}/dists/noble/InRelease  503  Service Unavailable"
    answer = f"""case "$*" in
  *update*) echo {shlex.quote(HEARD[0])}; echo 'Err:4 {azure} noble InRelease'
    echo '  503  Service Unavailable'; echo 'Reading package lists...'
    echo {shlex.quote(other)} >&2; exit 0 ;;
esac
{DEFAULTS["apt-get"]}"""
    code, out, err, calls = run(tmp_path, {"apt-get": answer})
    assert code == 0, err
    assert updates(calls) == ["apt-get update -q"]
    assert "Hit:1" not in out + err and "Reading package lists" not in out + err
    assert "Err:4 http://azure.archive.ubuntu.com/ubuntu noble InRelease" in err.splitlines()
    assert other in err.splitlines()


def test_another_sources_warning_is_not_kicads(tmp_path):
    """A 503 of another source's index is apt's and the user's business: KiCad's index is there."""
    other = (
        "W: Failed to fetch http://azure.archive.ubuntu.com/ubuntu/dists/noble/InRelease"
        "  503  Service Unavailable"
    )
    code, _, err, calls = run(tmp_path, {"apt-get": update_says(other)})
    assert code == 0, err
    assert len(updates(calls)) == 1
    # apt's own lines reach the terminal (the second review's X3)
    assert other in err.splitlines()


def test_a_gpg_warning_on_the_source_is_a_failed_try(tmp_path):
    """apt names the source without its last slash in a GPG warning and ends with 0, keeping the old
    index: each try fails, and the stop quotes the warning."""
    code, _, err, calls = run(tmp_path, {"apt-get": update_says(W_GPG)})
    assert code == 1
    assert len(updates(calls)) == 3
    assert installs(calls) == []
    stop = (
        "[install] ERROR: apt: the index of KiCad 10's package source did not arrive in 3 tries: "
        f"{SOURCE}; apt said: {W_GPG}"
    )
    assert err.splitlines()[-2:] == [stop, f"{NONE} Fix what apt said, then run the script again."]


def test_a_release_the_source_does_not_serve_stops_at_once_and_removes_the_sources_file(tmp_path):
    """Debian bookworm: apt's E: line names the source as 'address suite Release', then 2 N: lines. 1 try,
    no wait; the stop quotes the E: line, not the last N: line, and says what is wrong; the sources file
    that would break every later `apt update` is removed."""
    bookworm = tmp_path / "os-release-bookworm"
    bookworm.write_text("VERSION_CODENAME=bookworm\n", encoding="utf-8")
    # a file of the system's beside the script's stays (the second review's X4)
    debian = tmp_path / "sources.list.d" / "debian.sources"
    debian.parent.mkdir()
    debian.write_text("Types: deb\n", encoding="utf-8")
    code, _, err, calls = run(
        tmp_path,
        {"apt-get": update_says(E_RELEASE, N_SECURE, N_MANPAGE, code=100)},
        env={"OS_RELEASE": str(bookworm)},
    )
    assert code == 1
    assert len(updates(calls)) == 1 and of(calls, "sleep") == []
    sources = tmp_path / "sources.list.d" / "kicad-10.0-releases.sources"
    assert not sources.exists()
    assert debian.read_text(encoding="utf-8") == "Types: deb\n"
    assert err.splitlines()[-2:] == [
        "[install] ERROR: apt: the index of KiCad 10's package source did not arrive in 1 try: "
        f"{URL} bookworm; apt said: {E_RELEASE}",
        f"[install] KiCad 10's package source serves no release for bookworm ({bookworm}); install.sh is for "
        f"Ubuntu 24.04 (noble). install.sh's own {sources} was removed. This run installed no KiCad.",
    ]


def test_a_missing_release_file_on_noble_is_a_failed_try_and_keeps_the_sources_file(tmp_path):
    """On noble, the source serves its release: apt's 'does not have a Release file' then means that the
    source, or a proxy on the way, answered 404 for InRelease and Release. That is tried again like any
    failed try, the sources file stays, and the stop says what to check (the second review's S2-3)."""
    e_noble = f"E: The repository '{URL} noble Release' does not have a Release file."
    code, _, err, calls = run(tmp_path, {"apt-get": update_says(e_noble, N_SECURE, N_MANPAGE, code=100)})
    assert code == 1
    assert len(updates(calls)) == 3
    assert (tmp_path / "sources.list.d" / "kicad-10.0-releases.sources").exists()
    assert err.splitlines()[-2:] == [
        "[install] ERROR: apt: the index of KiCad 10's package source did not arrive in 3 tries: "
        f"{SOURCE}; apt said: {e_noble}",
        f"{NONE} KiCad 10's package source, or a proxy on the way to it, served no Release file for noble: "
        "check that this computer reaches ppa.launchpadcontent.net, then run the script again.",
    ]


@pytest.mark.parametrize("codename", ["noble", "bookworm"])
def test_another_sources_missing_release_is_quoted_and_not_blamed_on_kicads(tmp_path, codename):
    """apt ends with 100 because another source has no Release file; no line names KiCad's source. The
    stop quotes apt's last E: line (not its last line, an N: line), tries again as for any cause it
    does not know, and leaves KiCad's sources file, which is not at fault; on a release KiCad's source
    does not serve too."""
    release = tmp_path / "os-release-x"
    release.write_text(f"VERSION_CODENAME={codename}\n", encoding="utf-8")
    e_other = (
        f"E: The repository 'http://dl.example.org/tool {codename} Release' does not have a Release file."
    )
    code, _, err, calls = run(
        tmp_path,
        {"apt-get": update_says(e_other, N_SECURE, N_MANPAGE, code=100)},
        env={"OS_RELEASE": str(release)},
    )
    assert code == 1
    assert len(updates(calls)) == 3
    assert (tmp_path / "sources.list.d" / "kicad-10.0-releases.sources").exists()
    assert err.splitlines()[-2:] == [
        "[install] ERROR: apt: the index of KiCad 10's package source did not arrive in 3 tries: "
        f"{URL} {codename}; apt said: exit code 100: {e_other}",
        f"{NONE} Fix what apt said, then run the script again.",
    ]


def test_a_second_key_for_the_source_stops_at_once_and_names_the_other_entries(tmp_path):
    """Another .sources file and a line of sources.list name the source with another key
    (add-apt-repository's): apt ends with 100 and E: Conflicting values. 1 try; the key apt named after
    '!=' and the enabled entries are named, not a commented line or a .save file that apt does not read
    (the second review's S2-6); the script's own file is removed, the others stay."""
    parts = tmp_path / "sources.list.d"
    parts.mkdir()
    other = parts / "kicad-ubuntu-kicad-10_0-releases-noble.sources"
    other.write_text(f"Types: deb\nURIs: {URL}/\nSuites: noble\n", encoding="utf-8")
    (parts / "kicad.list.save").write_text(f"deb {URL}/ noble main\n", encoding="utf-8")
    (parts / "old.list").write_text(f"# deb {URL}/ noble main\n", encoding="utf-8")
    listed = tmp_path / "sources.list"
    listed.write_text(
        f"deb http://archive.ubuntu.com/ubuntu noble main\ndeb {URL}/ noble main\n", encoding="utf-8"
    )
    trusted = "/etc/apt/trusted.gpg.d/kicad-ubuntu-kicad-10_0-releases.gpg"
    keyring = tmp_path / "keyrings" / "kicad-10.0-releases.gpg"
    # apt's line as E_SIGNED, with the test's keyring as the script's key
    e_signed = E_SIGNED.replace("/etc/apt/keyrings/kicad-10.0-releases.gpg", str(keyring))
    code, _, err, calls = run(tmp_path, {"apt-get": update_says(e_signed, E_LIST, code=100)})
    assert code == 1
    assert len(updates(calls)) == 1 and of(calls, "sleep") == []
    ours = parts / "kicad-10.0-releases.sources"
    assert not ours.exists() and other.exists() and listed.exists()
    assert err.splitlines()[-2:] == [
        "[install] ERROR: apt: the index of KiCad 10's package source did not arrive in 1 try: "
        f"{SOURCE}; apt said: {e_signed}",
        f"[install] Another entry names KiCad 10's package source with another key ({trusted}): {listed}, "
        f"{other}. install.sh's own {ours} was removed. Remove that entry, then run the script again. "
        "This run installed no KiCad.",
    ]


def test_a_second_key_with_no_entry_found_says_where_it_looked(tmp_path):
    """apt's line names 2 keys, neither the script's (another keyring setting), and no enabled entry
    names the source: both keys are quoted, and the stop says where it looked."""
    code, _, err, _ = run(tmp_path, {"apt-get": update_says(E_SIGNED, E_LIST, code=100)})
    assert code == 1
    parts = tmp_path / "sources.list.d"
    keys = (
        "/etc/apt/keyrings/kicad-10.0-releases.gpg != "
        "/etc/apt/trusted.gpg.d/kicad-ubuntu-kicad-10_0-releases.gpg"
    )
    assert err.splitlines()[-1] == (
        f"[install] Another entry names KiCad 10's package source with another key ({keys}): none found in "
        f"{tmp_path / 'sources.list'} or {parts}/*.list, *.sources. install.sh's own "
        f"{parts / 'kicad-10.0-releases.sources'} was removed. Remove that entry, then run the script again. "
        "This run installed no KiCad."
    )


def test_a_file_of_the_users_under_the_scripts_name_is_left_alone(tmp_path):
    """The user keeps their own entry at the script's path (here with Suites: noble on another key): the
    script does not overwrite it, does not remove it, fetches nothing, and names it (the second review's
    S2-7). The file next to it stays too."""
    parts = tmp_path / "sources.list.d"
    parts.mkdir()
    mine = (
        f"# mine\nTypes: deb\nURIs: {URL}/\nSuites: noble\nComponents: main\nSigned-By: {tmp_path}/mine.gpg\n"
    )
    ours = parts / "kicad-10.0-releases.sources"
    ours.write_text(mine, encoding="utf-8")
    (parts / "ubuntu.sources").write_text("Types: deb\n", encoding="utf-8")
    code, out, err, calls = run(tmp_path)
    assert code == 1
    assert ours.read_text(encoding="utf-8") == mine
    assert sorted(p.name for p in parts.iterdir()) == ["kicad-10.0-releases.sources", "ubuntu.sources"]
    assert updates(calls) == [] and of(calls, "curl") == [] and installs(calls) == []
    assert err.splitlines()[-2:] == [
        f"[install] ERROR: apt: {ours} is not the file install.sh writes for noble; "
        "install.sh leaves it as it is.",
        f"{NONE} Move that file out of {parts}, or remove it, then run the script again: install.sh writes "
        "its own there.",
    ]


def test_the_file_an_earlier_run_wrote_is_used_again(tmp_path):
    """A second run finds the sources file the first one wrote, byte for byte: it goes on."""
    code, _, err, _ = run(tmp_path)
    assert code == 0, err
    ours = tmp_path / "sources.list.d" / "kicad-10.0-releases.sources"
    first = ours.read_text(encoding="utf-8")
    (tmp_path / "installed").unlink()
    for name in ("bin", "tools", "jvm", "tmp"):
        shutil.rmtree(tmp_path / name)
    code, _, err, _ = run(tmp_path)
    assert code == 0, err
    assert ours.read_text(encoding="utf-8") == first


def test_a_held_apt_lock_is_named_and_not_blamed_on_the_source(tmp_path):
    """Another apt holds the lock: apt's lines name no source; the stop quotes apt's last E: line and
    says to wait for the other apt."""
    code, _, err, calls = run(tmp_path, {"apt-get": update_says(E_LOCK, E_LOCKDIR, code=100)})
    assert code == 1
    assert len(updates(calls)) == 3
    assert err.splitlines()[-2:] == [
        "[install] ERROR: apt: the index of KiCad 10's package source did not arrive in 3 tries: "
        f"{SOURCE}; apt said: exit code 100: {E_LOCKDIR}",
        f"{NONE} Another apt or dpkg holds its lock (an update or an install of its own): "
        "run the script again when it has ended.",
    ]


def test_a_candidate_from_ubuntu_stops_before_the_download(tmp_path):
    """The index arrives, but `kicad`'s candidate is Ubuntu's 7.0.11+dfsg-1build4: stop, no install."""
    code, out, err, calls = run(tmp_path, {"apt-cache": 'cat "$SAMPLES/policy-ubuntu-kicad.txt"'})
    assert code == 1
    assert installs(calls) == []
    stop = (
        "[install] ERROR: apt: not every KiCad package's candidate is 10.x from KiCad 10's package source: "
        "kicad (apt has 7.0.11+dfsg-1build4 from http://azure.archive.ubuntu.com/ubuntu noble/universe): "
        f"{SOURCE}; apt said: nothing about this source"
    )
    assert err.splitlines()[-2:] == [stop, NOT_10]


def test_a_10x_candidate_from_another_source_stops(tmp_path):
    """`kicad`'s candidate is 10.0.9-1 from another archive, and the source has 10.0.8: the version is
    10.x but not the source's, so the stop says that another source outranks it."""
    code, _, err, calls = run(tmp_path, {"apt-cache": 'cat "$SAMPLES/policy-mirror-kicad.txt"'})
    assert code == 1
    assert installs(calls) == []
    stop = (
        "[install] ERROR: apt: not every KiCad package's candidate is 10.x from KiCad 10's package source: "
        "kicad (apt prefers 10.0.9-1 from http://mirror.example.org/kicad noble/main to the source's "
        f"10.0.8~ubuntu24.04.1): {SOURCE}; apt said: nothing about this source"
    )
    assert err.splitlines()[-2:] == [stop, f"{NONE} {OUTRANKED}"]


def test_a_candidate_from_the_source_that_is_not_10x_stops(tmp_path):
    """The source itself offers `kicad` 9.0.7: the archive is right, the version is not."""
    code, _, err, calls = run(tmp_path, {"apt-cache": 'cat "$SAMPLES/policy-ppa-9.txt"'})
    assert code == 1
    assert installs(calls) == []
    stop = (
        "[install] ERROR: apt: not every KiCad package's candidate is 10.x from KiCad 10's package source: "
        f"kicad (apt has 9.0.7-1~ubuntu24.04.1 from {SOURCE}/main): {SOURCE}; "
        "apt said: nothing about this source"
    )
    assert err.splitlines()[-2:] == [stop, NOT_10]


def test_a_pin_to_ubuntus_kicad_is_named_and_the_kicad_there_is_unchanged(tmp_path):
    """Real `apt-cache policy` with a pin of Ubuntu's archive at 1001 (policy-pin-ubuntu.txt): the source
    has 10.0.8, the pin chose 7.0.11. The computer has KiCad 7.0.11, and the stop says it is unchanged."""
    code, _, err, calls = run(
        tmp_path,
        {"apt-cache": 'cat "$SAMPLES/policy-pin-ubuntu.txt"', "kicad-cli": "echo 7.0.11"},
    )
    assert code == 1
    assert installs(calls) == []
    ubuntu = "http://archive.ubuntu.com/ubuntu noble/universe"
    stop = (
        "[install] ERROR: apt: not every KiCad package's candidate is 10.x from KiCad 10's package source: "
        f"kicad (apt prefers 7.0.11+dfsg-1build4 from {ubuntu} to the source's 10.0.8~ubuntu24.04.1), "
        f"kicad-symbols (apt prefers 7.0.11-1 from {ubuntu} to the source's 10.0.8~ubuntu24.04.1), "
        f"kicad-footprints (apt prefers 7.0.11-1 from {ubuntu} to the source's 10.0.8~ubuntu24.04.1), "
        f"kicad-templates (apt prefers 7.0.9-1 from {ubuntu} to the source's 10.0.8~ubuntu24.04.1): "
        f"{SOURCE}; apt said: nothing about this source"
    )
    kept = "[install] This run installed no KiCad; the KiCad on this computer (7.0.11) is unchanged."
    assert err.splitlines()[-2:] == [stop, f"{kept} {OUTRANKED}"]


def test_a_package_with_no_candidate_at_all_stops(tmp_path):
    """`apt-cache policy` prints nothing for a package it does not know: that is no candidate."""
    answer = "awk '/^kicad-templates:/{exit} {print}' \"$SAMPLES/policy-ppa.txt\""
    code, _, err, calls = run(tmp_path, {"apt-cache": answer})
    assert code == 1
    assert installs(calls) == []
    none = "candidate is 10.x from KiCad 10's package source: kicad-templates (apt has none): "
    assert none in err.splitlines()[-2]
    # the source has no 10.x of it either: no pin is blamed (the second review's X2)
    assert err.splitlines()[-1] == NOT_10


def test_a_failing_apt_cache_stops_with_a_line(tmp_path):
    """`apt-cache policy` ends with 100: the step stops with its code and apt's E: line, not silently
    through `set -e`."""
    e_lists = "E: The package lists or status file could not be parsed or opened."
    code, out, err, calls = run(
        tmp_path, {"apt-cache": f"echo '{e_lists}' >&2; exit 100"}, body="step_apt; echo NEXT STEP"
    )
    assert code == 1
    assert installs(calls) == []
    assert "NEXT STEP" not in out
    # apt-cache's own line is shown as apt printed it, then the stop (the second review's X7)
    assert err.splitlines()[-3:] == [
        e_lists,
        "[install] ERROR: apt: `apt-cache policy kicad kicad-symbols kicad-footprints kicad-templates` ended "
        f"with exit code 100; apt said: {e_lists}",
        f"{NONE} Fix what apt said, then run the script again.",
    ]


def test_apt_speaks_in_the_c_locale_whatever_the_users_language(tmp_path):
    """In German, apt 2.8.3 prints `  Installationskandidat:` and `Holen:` (its de.po): the stand-ins
    answer in German unless LC_ALL=C. The step reads them in C, and LC_ALL is its own: unset after it."""
    policy = '[[ "${LC_ALL:-}" == C ]] && cat "$SAMPLES/policy-ppa.txt" || cat "$SAMPLES/policy-de.txt"'
    apt = f"""case "$*" in
  *--download-only*)
    if [[ "${{LC_ALL:-}}" == C ]]; then echo "Get:172 https://ppa.launchpadcontent.net/x [48.0 MB]"
    else echo "Holen:172 https://ppa.launchpadcontent.net/x [48.0 MB]"; fi
    exit 0 ;;
esac
{DEFAULTS["apt-get"]}"""
    code, out, err, _ = run(
        tmp_path,
        {"apt-cache": policy, "apt-get": apt},
        env={"LANG": "de_DE.UTF-8", "LANGUAGE": "de"},
        body='step_apt; echo "after: ${LC_ALL:-unset}"',
    )
    assert code == 0, err
    assert "[apt] Get:172 https://ppa.launchpadcontent.net/x [48.0 MB]" in out
    assert out.splitlines()[-1] == "after: unset"


@pytest.mark.parametrize("bounds", [{}, CI], ids=["no bound", "CI's bounds"])
def test_a_failed_download_ends_with_apts_lines_and_stops_the_script(tmp_path, bounds):
    """apt-get ends with 100 and its E: lines (job 134906707485 at 15:44:22) at every pass: 5 passes, 4
    waits of 20 s, then exit 1, no install, no later step; with a bound or without."""
    answer = f"""case "$*" in
  *--download-only*)
    echo "Get:172 https://ppa.launchpadcontent.net/x [48.0 MB]"
    echo '{E_FETCH}' >&2; echo '{E_SOME}' >&2; exit 100 ;;
esac
{DEFAULTS["apt-get"]}"""
    code, out, err, calls = run(tmp_path, {"apt-get": answer}, env=bounds, body="step_apt; echo NEXT STEP")
    assert code == 1
    assert [c for c in installs(calls) if "--download-only" not in c] == []
    assert E_FETCH in err.splitlines()
    assert "[apt] Get:172 https://ppa.launchpadcontent.net/x [48.0 MB]" in out
    within = ", within its bound of 570 s" if bounds else ""
    stop = (
        "[install] ERROR: apt: the download ended with apt-get's exit code 100 after 5 passes of 5"
        f"{within}; apt said: {E_FETCH}"
    )
    assert err.splitlines()[-2:] == [stop, LATER]
    assert len(installs(calls)) == 5 and of(calls, "sleep") == ["sleep 20"] * 4
    assert "NEXT STEP" not in out
    assert of(calls, "kicad-cli") == ["kicad-cli version"]


def test_a_download_404_says_to_fix_what_apt_said(tmp_path):
    """A 404 does not pass by itself (a file gone from the source, a stale index): 'again later' is said
    only for a 5xx (the second review's X6)."""
    e_404 = E_FETCH.replace("503  Service Unavailable", "404  Not Found")
    answer = f"""case "$*" in
  *--download-only*) echo '{e_404}' >&2; echo '{E_SOME}' >&2; exit 100 ;;
esac
{DEFAULTS["apt-get"]}"""
    code, _, err, calls = run(tmp_path, {"apt-get": answer})
    assert code == 1
    assert err.splitlines()[-2:] == [
        f"[install] ERROR: apt: the download ended with apt-get's exit code 100 after 5 passes of 5; "
        f"apt said: {e_404}",
        "[install] No package was installed. Fix what apt said, then run the script again.",
    ]


@pytest.mark.parametrize("rc", [1, 127])
def test_a_download_that_ends_with_another_code_stops(tmp_path, rc):
    """Not only 100 and 124: any code but 0 stops before the install (127: apt-get not found)."""
    answer = f"""case "$*" in
  *--download-only*) exit {rc} ;;
esac
{DEFAULTS["apt-get"]}"""
    code, _, err, calls = run(tmp_path, {"apt-get": answer})
    assert code == 1
    assert [c for c in installs(calls) if "--download-only" not in c] == []
    assert err.splitlines()[-2:] == [
        f"[install] ERROR: apt: the download ended with apt-get's exit code {rc} after 1 pass of 5; "
        "apt said: nothing",
        "[install] No package was installed. Fix what apt said, then run the script again.",
    ]


def test_a_download_that_does_not_end_is_stopped_at_its_bound(tmp_path):
    """APT_DOWNLOAD_TIMEOUT=9: `timeout 9` ends with 124 and the line names the bound."""
    answer = '[[ "$*" == *--download-only* ]] && exit 124; shift; exec "$@"'
    code, _, err, calls = run(tmp_path, {"timeout": answer}, env={"APT_DOWNLOAD_TIMEOUT": "9"})
    assert code == 1
    (bounded,) = [c for c in of(calls, "timeout") if "--download-only" in c]
    assert bounded.startswith("timeout 9 apt-get install")
    assert [c for c in installs(calls) if "--download-only" not in c] == []
    assert re.fullmatch(cut_stop(9, 1, "nothing"), err.splitlines()[-2]), err
    assert err.splitlines()[-1] == CUT


def test_a_cut_download_names_the_file_that_failed(tmp_path):
    """apt prints `Err:` for a file it could not fetch and goes on; the bound then cuts it, and apt
    prints no E: line. The Err: line is shown and the stop quotes it."""
    err_line = (
        "Err:175 https://ppa.launchpadcontent.net/kicad/kicad-10.0-releases/ubuntu noble/main amd64 "
        "kicad-templates all 10.0.8~ubuntu24.04.1"
    )
    apt = f"""case "$*" in
  *--download-only*) echo "Get:172 https://ppa.launchpadcontent.net/x [48.0 MB]"; echo '{err_line}'; exit 0 ;;
esac
{DEFAULTS["apt-get"]}"""
    cut = 'if [[ "$*" == *--download-only* ]]; then shift; "$@"; exit 124; fi; shift; exec "$@"'
    code, out, err, _ = run(tmp_path, {"apt-get": apt, "timeout": cut}, env=CI)
    assert code == 1
    assert f"[apt] {err_line}" in out
    seen = "hosts asked: ppa.launchpadcontent.net (1 Get, 0 Ign, 1 Err); 0 B arrived in {S} s"
    seen += ", of a size apt did not name"
    assert re.fullmatch(cut_stop(570, 1, err_line, seen=seen), err.splitlines()[-2]), err
    assert err.splitlines()[-1] == CUT


# What the stops of a bounded download say they saw when apt asked no host and nothing arrived. `{S}`
# stands for the whole seconds the shell counted, which a test cannot fix.
NOTHING_SEEN = "no host was asked for a file; 0 B arrived in {S} s, of a size apt did not name"


def pattern(text: str) -> str:
    """`text` as a regular expression, each `{S}` a whole number of seconds."""
    return re.escape(text).replace(re.escape("{S}"), r"[0-9]+")


def cut_stop(bound: int, passes: int, said: str, tries: int = 5, seen: str = NOTHING_SEEN) -> str:
    """The stop when APT_DOWNLOAD_TIMEOUT ends, as a pattern: the bound, the passes made, what arrived
    from which hosts (run 44506767788 said only `apt said: nothing`), and apt's line."""
    made = "1 pass" if passes == 1 else f"{passes} passes"
    return pattern(
        f"[install] ERROR: apt: the download did not end within {bound} s (APT_DOWNLOAD_TIMEOUT), the bound "
        f"of all its passes and waits, after {made} of {tries}; {seen}; apt said: {said}"
    )


def no_time_stop(passes: int, wait: int, bound: int, said: str, tries: int = 5) -> str:
    """The stop when a pass failed on a file and the wait would leave no time for another pass."""
    made = "1 pass" if passes == 1 else f"{passes} passes"
    return (
        f"[install] ERROR: apt: the download stopped after {made} of {tries}: the next wait of {wait} s "
        f"would leave no time for another pass within APT_DOWNLOAD_TIMEOUT={bound} s; apt said: {said}"
    )


def failed_stop(passes: int, said: str, tries: int = 5, rc: int = 100, bound: str = "") -> str:
    made = "1 pass" if passes == 1 else f"{passes} passes"
    within = f", within its bound of {bound} s" if bound else ""
    return (
        f"[install] ERROR: apt: the download ended with apt-get's exit code {rc} after {made} of {tries}"
        f"{within}; apt said: {said}"
    )


def pass_line(n: int, tries: int, files: int, wait: int) -> str:
    """The line of a failed pass that another follows."""
    word = "file" if files == 1 else "files"
    return (
        f"[install] apt: download pass {n} of {tries} failed on {files} {word}; apt said: {E_KICAD}; "
        f"waiting {wait} s"
    )


def download_fails(
    passes: int | None, *lines: str, code: int = 100, then: str = "exit 0", pause: str = ""
) -> str:
    """An apt-get whose first `passes` downloads (every download: None) print `lines` on stderr and end with
    `code`; a later one runs `then`. `pause` runs before either (a real wait, for the bound's tests)."""
    printed = "; ".join(f"echo {shlex.quote(line)} >&2" for line in lines) or "true"
    fails = "true" if passes is None else f"(( d <= {passes} ))"
    return f"""case "$*" in
  *--download-only*)
    d="$(grep -c -- '^apt-get .*--download-only' "$STUB_DIR/calls")"
    {pause or ":"}
    if {fails}; then {printed}; exit {code}; fi
    {then} ;;
esac
{DEFAULTS["apt-get"]}"""


def downloads(calls):
    return [c for c in installs(calls) if "--download-only" in c]


def test_a_file_not_served_for_2_passes_then_served_ends_in_an_install(tmp_path):
    """The amd64 image build of pull request 92 on 2026-11-18: KiCad 10's source answered 503 for 1 file.
    Here it does so for 2 passes (the first names 2 files), then serves it: 3 downloads, each a new
    `apt-get --download-only` (apt asks only for what it lacks), 1 line for each failed pass, 2 waits of
    the default 20 s, then the install from the downloaded files alone."""
    answer = f"""case "$*" in
  *--download-only*)
    d="$(grep -c -- '^apt-get .*--download-only' "$STUB_DIR/calls")"
    if (( d <= 2 )); then echo {shlex.quote(E_KICAD)} >&2; fi
    if (( d == 1 )); then echo {shlex.quote(E_FETCH)} >&2; fi
    if (( d <= 2 )); then echo {shlex.quote(E_FILES)} >&2; exit 100; fi
    exit 0 ;;
esac
{DEFAULTS["apt-get"]}"""
    code, out, err, calls = run(tmp_path, {"apt-get": answer})
    assert code == 0, err
    assert len(downloads(calls)) == 3
    assert len(set(downloads(calls))) == 1
    assert of(calls, "sleep") == ["sleep 20", "sleep 20"]
    lines = out.splitlines()
    assert [line for line in lines if " download pass " in line] == [
        pass_line(1, 5, 2, 20),
        pass_line(2, 5, 1, 20),
    ]
    (install,) = [c for c in installs(calls) if "--download-only" not in c]
    assert "-o APT::Get::Download=false" in install
    assert lines[-1] == "[install] apt: done; kicad-cli 10.0.8"


def test_a_file_never_served_stops_after_the_passes_it_was_given(tmp_path):
    """APT_DOWNLOAD_TRIES=3 and APT_DOWNLOAD_WAIT=7: 3 downloads, 2 waits of 7 s, 2 pass lines, then the
    stop with the count of passes and apt's line, and nothing installed."""
    env = {"APT_DOWNLOAD_TRIES": "3", "APT_DOWNLOAD_WAIT": "7"}
    answer = download_fails(None, E_KICAD, E_FILES)
    code, out, err, calls = run(tmp_path, {"apt-get": answer}, env=env, body="step_apt; echo NEXT STEP")
    assert code == 1
    assert len(downloads(calls)) == 3
    assert of(calls, "sleep") == ["sleep 7", "sleep 7"]
    assert [c for c in installs(calls) if "--download-only" not in c] == []
    assert [line for line in out.splitlines() if " download pass " in line] == [
        pass_line(1, 3, 1, 7),
        pass_line(2, 3, 1, 7),
    ]
    assert err.splitlines()[-2:] == [failed_stop(3, E_KICAD, tries=3), LATER]
    assert "NEXT STEP" not in out
    assert not (tmp_path / "installed").exists()


@pytest.mark.parametrize(
    ("lines", "rc"),
    [((E_SPACE,), 100), ((E_KICAD, E_FILES), 1), ((), 100)],
    ids=["no space", "a fetch line with another code", "no line"],
)
def test_a_failure_that_is_not_a_fetch_failure_stops_after_1_pass(tmp_path, lines, rc):
    """Only apt-get's code 100 with an `E: Failed to fetch` line is a source that did not serve a file:
    a full disk, any other code, or 100 with no such line stops at once, with no wait."""
    code, out, err, calls = run(tmp_path, {"apt-get": download_fails(None, *lines, code=rc)})
    assert code == 1
    assert len(downloads(calls)) == 1 and of(calls, "sleep") == []
    said = lines[0] if lines else "nothing"
    assert err.splitlines()[-2] == failed_stop(1, said, rc=rc)
    assert " download pass " not in out


def test_a_failure_of_another_kind_after_a_fetch_failure_stops_at_that_pass(tmp_path):
    """Pass 1: a file not served; pass 2: a full disk. 2 passes, 1 wait, and the stop quotes the disk."""
    answer = download_fails(1, E_KICAD, E_FILES, then=f"echo {shlex.quote(E_SPACE)} >&2; exit 100")
    code, out, err, calls = run(tmp_path, {"apt-get": answer})
    assert code == 1
    assert len(downloads(calls)) == 2 and of(calls, "sleep") == ["sleep 20"]
    assert err.splitlines()[-2:] == [
        failed_stop(2, E_SPACE),
        "[install] No package was installed. Fix what apt said, then run the script again.",
    ]


def bounds_of(calls) -> list[int]:
    """The seconds `timeout` was given for each download."""
    return [int(c.split()[1]) for c in of(calls, "timeout") if "--download-only" in c]


def test_the_bound_covers_the_passes_and_the_waits_together(tmp_path):
    """APT_DOWNLOAD_TIMEOUT=9, APT_DOWNLOAD_WAIT=1, 5 passes that fail at once: each pass gets what is left
    of the 9 s, the wait counted (the stand-in sleep takes no time), so each bound is at least 1 s below
    the one before. All 5 fit, and the stop is the passes', within the bound."""
    env = {"APT_DOWNLOAD_TIMEOUT": "9", "APT_DOWNLOAD_WAIT": "1"}
    code, out, err, calls = run(tmp_path, {"apt-get": download_fails(None, E_KICAD, E_FILES)}, env=env)
    assert code == 1
    given = bounds_of(calls)
    assert len(given) == 5 and given[0] == 9
    assert all(b - 2 <= a <= b - 1 for b, a in zip(given, given[1:], strict=False)), given
    assert of(calls, "sleep") == ["sleep 1"] * 4
    assert err.splitlines()[-2:] == [failed_stop(5, E_KICAD, bound="9"), LATER]


def test_a_bound_too_short_for_the_next_wait_and_pass_stops_with_the_count(tmp_path):
    """APT_DOWNLOAD_TIMEOUT=3, APT_DOWNLOAD_WAIT=1: no wait starts that would leave no second for the next
    pass. 5 passes do not fit: the stop names the wait, the bound and the passes made, fewer than 5, and
    no pass was given 0 s (which `timeout` reads as no bound)."""
    env = {"APT_DOWNLOAD_TIMEOUT": "3", "APT_DOWNLOAD_WAIT": "1"}
    code, out, err, calls = run(tmp_path, {"apt-get": download_fails(None, E_KICAD, E_FILES)}, env=env)
    assert code == 1
    given = bounds_of(calls)
    assert given[0] == 3 and 2 <= len(given) <= 3 and min(given) >= 1, given
    assert len(of(calls, "sleep")) == len(given) - 1
    assert err.splitlines()[-2:] == [no_time_stop(len(given), 1, 3, E_KICAD), LATER]


def test_the_time_apt_takes_counts_in_the_bound(tmp_path):
    """APT_DOWNLOAD_TIMEOUT=2, APT_DOWNLOAD_WAIT=0, each pass takes 1.2 s of real time: the passes' own
    time is taken from the bound, not only the waits. 1 or 2 passes (the shell counts whole seconds),
    never 5."""
    env = {"APT_DOWNLOAD_TIMEOUT": "2", "APT_DOWNLOAD_WAIT": "0"}
    answer = download_fails(None, E_KICAD, E_FILES, pause="/bin/sleep 1.2")
    code, out, err, calls = run(tmp_path, {"apt-get": answer}, env=env)
    assert code == 1
    given = bounds_of(calls)
    assert given in ([2], [2, 1]), given
    assert err.splitlines()[-2:] == [no_time_stop(len(given), 0, 2, E_KICAD), LATER]


def test_a_pass_cut_by_the_bound_stops_at_once_with_the_count(tmp_path):
    """Pass 1 is not served a file; `timeout` cuts pass 2 (124): no third pass, and the stop says 2."""
    cut = """cuts="$(grep -c '^timeout .*--download-only' "$STUB_DIR/calls")"
if [[ "$*" == *--download-only* ]] && (( cuts == 2 )); then exit 124; fi
shift; exec "$@\""""
    answers = {"apt-get": download_fails(None, E_KICAD, E_FILES), "timeout": cut}
    code, out, err, calls = run(tmp_path, answers, env={"APT_DOWNLOAD_TIMEOUT": "60"})
    assert code == 1
    assert len(bounds_of(calls)) == 2 and of(calls, "sleep") == ["sleep 20"]
    assert re.fullmatch(cut_stop(60, 2, "nothing"), err.splitlines()[-2]), err
    assert err.splitlines()[-1] == CUT


# ---------------------------------------------------------------- the watch of a pass
# CI run 44506767788 (job 135500622487, 2026-11-19): the download's 1 pass asked
# us-east-2.ec2.archive.ubuntu.com, which the probe had measured at 2468910 bytes/s; 26.6 MB of its
# files arrived in 550.7 s (48.3 kB/s), and the bound of 570 s ended the pass with `apt said: nothing`.
# The stand-in apt-get below writes bytes into the stand-in archives folder (APT_ARCHIVES), as apt
# does: a file grows in partial/. APT_WATCH_WINDOW=1 stands for CI's 120 s, so a test takes seconds.
NEED = "Need to get 10.0 MB of archives."
SLOW_GET = "Get:5 http://slow.example/ubuntu noble/main amd64 big amd64 1 [10.0 MB]"
FAST_GET = "Get:5 http://fast.example/ubuntu noble/main amd64 big amd64 1 [10.0 MB]"
WATCH = {"APT_DOWNLOAD_TIMEOUT": "8", "APT_DOWNLOAD_WAIT": "1", "APT_WATCH_WINDOW": "1"}


def trickle(gets: tuple = (SLOW_GET,), chunk: int = 1000, ticks: int = 400, then: str = "exit 1") -> str:
    """A pass that prints apt's size and its Get lines, then writes `chunk` bytes into partial/ every
    0.05 s, `ticks` times (400: 20 s, so that no stand-in outlives a failed test by long), then `then`."""
    printed = "; ".join(f"echo {shlex.quote(g)}" for g in gets)
    return f"""echo {shlex.quote(NEED)}; {printed}
        echo "$$" >> "$STUB_DIR/apt-pids"
        for _ in $(seq {ticks}); do
          printf '%0{chunk}d' 0 >> "$APT_ARCHIVES/partial/big.deb"; /bin/sleep 0.05
        done
        {then}"""


def served(get: str = FAST_GET) -> str:
    """A pass that gets the whole 10 MB at once and ends with 0."""
    return f"""echo {shlex.quote(NEED)}; echo {shlex.quote(get)}
        head -c 10000000 /dev/zero > "$APT_ARCHIVES/big.deb"; exit 0"""


def by_pass(*passes: str) -> str:
    """An apt-get whose n-th download runs the n-th of `passes`, and any later one the last."""
    arms = "\n".join(f"      {i})\n        {p} ;;" for i, p in enumerate(passes, 1))
    return f"""case "$*" in
  *--download-only*)
    d="$(grep -c -- '^apt-get .*--download-only' "$STUB_DIR/calls")"
    case "$d" in
{arms}
      *)
        {passes[-1]} ;;
    esac ;;
esac
{DEFAULTS["apt-get"]}"""


def alive(tmp_path: Path, within: float = 3.0) -> list[int]:
    """The stand-in apt-gets still running after `within` s: none may be left behind."""
    listed = tmp_path / "apt-pids"
    pids = [int(p) for p in listed.read_text().split()] if listed.exists() else []

    def running(pid: int) -> bool:
        try:
            state = Path(f"/proc/{pid}/status").read_text()
        except OSError:
            return False
        return "\nState:\tZ" not in state

    deadline = time.monotonic() + within
    while any(running(p) for p in pids) and time.monotonic() < deadline:
        time.sleep(0.05)
    return [p for p in pids if running(p)]


SLOW_LINE = (
    r"\[install\] apt: download pass 1 of 5 was too slow to finish: [0-9.]+ kB of 10\.0 MB arrived in "
    r"[0-9]+ s, [0-9.]+ kB/s over the last 1 s, leaving out a pause of 0\.[0-9] s, from slow\.example; "
    r"at that rate the rest needs [0-9]+ s, "
    r"and [0-9]+ s were left; waiting 1 s"
)


def test_a_pass_too_slow_to_finish_is_ended_and_the_next_pass_starts(tmp_path):
    """R1, R2: pass 1 trickles 20 kB/s of a 10 MB need into partial/ and would never end; the watch ends
    it after 1 window, says what it saw, and pass 2, after the wait, gets the file. Within the bound;
    no stand-in apt-get is left running."""
    began = time.monotonic()
    code, out, err, calls = run(tmp_path, {"apt-get": by_pass(trickle(), served())}, env=WATCH)
    took = time.monotonic() - began
    assert code == 0, err
    assert len(downloads(calls)) == 2 and of(calls, "sleep") == ["sleep 1"]
    assert took < 8, took
    (line,) = [x for x in out.splitlines() if " was too slow to finish" in x]
    assert re.fullmatch(SLOW_LINE, line), line
    assert f"[apt] {NEED}" in out.splitlines()
    assert out.splitlines()[-1] == "[install] apt: done; kicad-cli 10.0.8"
    assert alive(tmp_path) == []


def test_a_fast_start_does_not_hide_a_slow_pass(tmp_path):
    """Run 44506767788: the PPA's 4 files (60.5 MB) started in the first 3 s beside the slow host. Here
    5 MB arrive at once, then 20 kB/s: the rate is that of the last window, not of the whole pass, so the
    pass ends soon after 1 window (the whole pass's rate would keep it 4 s more)."""
    burst = trickle().replace(
        'echo "$$" >> "$STUB_DIR/apt-pids"',
        'echo "$$" >> "$STUB_DIR/apt-pids"; head -c 5000000 /dev/zero >> "$APT_ARCHIVES/partial/big.deb"',
    )
    began = time.monotonic()
    code, out, err, calls = run(
        tmp_path, {"apt-get": by_pass(burst)}, env={**WATCH, "APT_DOWNLOAD_TRIES": "1"}
    )
    took = time.monotonic() - began
    assert code == 1
    assert " was too slow to finish " in err.splitlines()[-2]
    assert took < 3.5, took
    assert alive(tmp_path) == []


def test_files_already_in_the_folder_are_not_progress(tmp_path):
    """apt's archives folder holds 10 MB from an earlier run: only the bytes that arrive in this pass
    count, so a slow pass is still ended."""
    (tmp_path / "archives").mkdir()
    (tmp_path / "archives" / "old.deb").write_bytes(b"\0" * 10_000_000)
    code, out, err, calls = run(tmp_path, {"apt-get": by_pass(trickle(), served())}, env=WATCH)
    assert code == 0, err
    (line,) = [x for x in out.splitlines() if " was too slow to finish" in x]
    assert re.fullmatch(SLOW_LINE, line), line
    assert alive(tmp_path) == []


STEP |= {"slow-pass"}


@pytest.mark.parametrize("ends", [0, 3], ids=["the command ends with 0", "the command fails"])
def test_after_a_slow_pass_the_named_command_runs_with_its_hosts_before_the_next(tmp_path, ends):
    """R2: APT_SLOW_PASS_COMMAND (CI: a mode of tools/ci/apt_archive.sh that puts the slow host last in
    the mirror list) runs between the 2 passes with the hosts of the slow pass, the most files first;
    pass 2 sees what it changed. A command that fails is said, and the next pass runs all the same."""
    hook = f'printf "%s\\n" "$*" >> "$STUB_DIR/hooked"; echo "[apt-archive] moved"; exit {ends}'
    second = f'[[ -e "$STUB_DIR/hooked" ]] && echo seen >> "$STUB_DIR/second"; {served()}'
    # The PPA's 1 file comes first, slow.example's 2 after it: slow.example served more files.
    gets = (
        "Get:172 https://ppa.launchpadcontent.net/x [48.0 MB]",
        SLOW_GET,
        SLOW_GET.replace("Get:5", "Get:6"),
    )
    two = trickle(gets)
    env = {**WATCH, "APT_SLOW_PASS_COMMAND": "slow-pass --slow"}
    code, out, err, calls = run(tmp_path, {"apt-get": by_pass(two, second), "slow-pass": hook}, env=env)
    assert code == 0, err
    steps = [c.split(" ", 1)[0] + (" download" if "--download-only" in c else "") for c in calls]
    steps = [s for s in steps if s in ("timeout download", "slow-pass", "sleep")]
    assert steps == ["timeout download", "slow-pass", "sleep", "timeout download"]
    assert of(calls, "slow-pass") == ["slow-pass --slow slow.example ppa.launchpadcontent.net"]
    assert (tmp_path / "second").read_text() == "seen\n"
    lines = out.splitlines()
    said = "[install] apt: APT_SLOW_PASS_COMMAND: slow-pass --slow slow.example ppa.launchpadcontent.net"
    assert said in lines and "[apt-archive] moved" in lines
    failed = (
        "[install] WARN: apt: APT_SLOW_PASS_COMMAND ended with exit code 3; the next pass asks the hosts "
        "in the order they had"
    )
    assert (failed in err.splitlines()) == (ends != 0)
    assert alive(tmp_path) == []


def test_without_the_variable_no_command_runs_and_the_next_pass_asks_again(tmp_path):
    """R2 on a person's computer, or a list of 1 host: no command is named; the slow pass ends, and the
    next asks again (apt keeps a finished file and continues a partial one: apt 2.8.3,
    apt-pkg/acquire-item.cc, pkgAcqArchive::pkgAcqArchive)."""
    code, out, err, calls = run(tmp_path, {"apt-get": by_pass(trickle(), served(SLOW_GET))}, env=WATCH)
    assert code == 0, err
    assert len(downloads(calls)) == 2
    assert "APT_SLOW_PASS_COMMAND" not in out + err


def slow_stop(passes: int, last: int, bound: int, tries: int = 5) -> str:
    """The stop after a slow pass that no other pass can follow, as a pattern (R3)."""
    made = "1 pass" if passes == 1 else f"{passes} passes"
    return (
        rf"\[install\] ERROR: apt: the download stopped after {made} of {tries}: pass {last} was too slow "
        rf"to finish within what was left of APT_DOWNLOAD_TIMEOUT={bound} s; hosts asked: slow\.example "
        rf"\({passes} Get, 0 Ign, 0 Err\); [0-9.]+ kB of 10\.0 MB arrived in [0-9]+ s, [0-9.]+ kB/s; "
        r"apt said: nothing"
    )


@pytest.mark.parametrize(
    ("env", "passes"),
    [({"APT_DOWNLOAD_TRIES": "2"}, 2), ({"APT_DOWNLOAD_TIMEOUT": "3", "APT_DOWNLOAD_WAIT": "2"}, 1)],
    ids=["the last pass", "no time for the wait"],
)
def test_a_slow_pass_that_no_pass_can_follow_stops_with_what_arrived_from_whom(tmp_path, env, passes):
    """R3: the stop names the hosts asked with their Get, Ign and Err lines, the bytes that arrived of
    the bytes apt named, the time and the rate, and the passes; then the advice for a slow line."""
    full = {**WATCH, **env}
    code, out, err, calls = run(tmp_path, {"apt-get": by_pass(trickle())}, env=full)
    assert code == 1
    assert len(downloads(calls)) == passes
    lines = err.splitlines()
    assert re.fullmatch(
        slow_stop(passes, passes, int(full["APT_DOWNLOAD_TIMEOUT"]), int(full.get("APT_DOWNLOAD_TRIES", 5))),
        lines[-2],
    ), lines[-2]
    assert lines[-1] == CUT
    assert alive(tmp_path) == []


def test_a_cut_at_the_bound_says_what_arrived_from_whom(tmp_path):
    """R3: the bound ends a pass the watch kept (a window longer than the bound): the stop says the
    hosts, the bytes of the bytes apt named, and the rate, where run 44506767788 said `apt said: nothing`."""
    env = {"APT_DOWNLOAD_TIMEOUT": "2", "APT_WATCH_WINDOW": "999"}
    cut = (
        'if [[ "$*" == *--download-only* ]]; then shift; "$@" & p=$!; /bin/sleep 1.5; kill "$p"; '
        'wait "$p"; exit 124; fi; shift; exec "$@"'
    )
    code, out, err, _ = run(tmp_path, {"apt-get": by_pass(trickle()), "timeout": cut}, env=env)
    assert code == 1
    seen = r"hosts asked: slow\.example \(1 Get, 0 Ign, 0 Err\); [0-9.]+ kB of 10\.0 MB arrived in [0-9]+ s"
    stop = (
        r"\[install\] ERROR: apt: the download did not end within 2 s \(APT_DOWNLOAD_TIMEOUT\), the bound "
        rf"of all its passes and waits, after 1 pass of 5; {seen}(, [0-9.]+ kB/s)?; apt said: nothing"
    )
    assert re.fullmatch(stop, err.splitlines()[-2]), err
    assert alive(tmp_path) == []


def test_a_healthy_pass_is_not_cut(tmp_path):
    """R5: 0.3 s before the first byte (apt reads its lists and connects), 1 big file (3 MB into
    partial/ at 1 MB/s), a pause of half a window (APT_FILE_TIMEOUT is half of CI's window: a stall apt
    ends itself), then 2 windows with nothing to fetch (apt's own work after the last byte): 1 pass,
    no cut."""
    grow = "for _ in $(seq {n}); do printf '%050000d' 0 >> \"$APT_ARCHIVES/partial/big.deb\"; "
    grow += "/bin/sleep 0.05; done"
    apt = (
        'echo "Need to get 3000 kB of archives."; echo "Get:5 http://fast.example/ubuntu big [3000 kB]"; '
        'echo "$$" >> "$STUB_DIR/apt-pids"; /bin/sleep 0.3; '
        + grow.format(n=20)
        + "; /bin/sleep 0.5; "
        + grow.format(n=40)
        + '; mv "$APT_ARCHIVES/partial/big.deb" "$APT_ARCHIVES/big.deb"; /bin/sleep 2; exit 0'
    )
    env = {"APT_DOWNLOAD_TIMEOUT": "10", "APT_WATCH_WINDOW": "1"}
    code, out, err, calls = run(tmp_path, {"apt-get": by_pass(apt)}, env=env)
    assert code == 0, err
    assert len(downloads(calls)) == 1
    assert " was too slow" not in out + err
    assert out.splitlines()[-1] == "[install] apt: done; kicad-cli 10.0.8"


def test_with_no_bound_nothing_watches_a_slow_pass(tmp_path):
    """R5: a person's computer sets no APT_DOWNLOAD_TIMEOUT: a slow line that makes progress finishes, as
    before; apt's size line is shown."""
    apt = by_pass(trickle(ticks=40, then="exit 0"))
    code, out, err, calls = run(tmp_path, {"apt-get": apt}, env={"APT_WATCH_WINDOW": "1"})
    assert code == 0, err
    assert len(downloads(calls)) == 1 and of(calls, "timeout") == []
    assert " was too slow" not in out + err
    assert f"[apt] {NEED}" in out.splitlines()


def test_a_signal_to_the_script_ends_the_watched_apt(tmp_path):
    """R5: Ctrl-C (SIGINT to the script's process group) while a watched pass runs. GNU timeout puts
    itself and apt in a process group of their own (coreutils' timeout.c calls setpgid unless
    --foreground), so Ctrl-C does not reach them; the stand-in timeout does the same with setsid. The
    watch, in the script's group, gets the signal and ends the command it started."""
    answers = {"apt-get": by_pass(trickle()), "timeout": 'shift; exec /usr/bin/setsid "$@"'}
    env = {**folder(tmp_path, answers), "APT_DOWNLOAD_TIMEOUT": "60"}
    env["APT_WATCH_WINDOW"] = "100"
    proc = subprocess.Popen(
        [BASH, "-c", script(INSTALL, "step_apt")],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        cwd=tmp_path,
        start_new_session=True,
    )
    deadline = time.monotonic() + 10
    while not (tmp_path / "apt-pids").exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert (tmp_path / "apt-pids").exists()
    time.sleep(0.3)
    os.killpg(proc.pid, signal.SIGINT)
    proc.communicate(timeout=20)
    assert proc.returncode != 0
    assert alive(tmp_path) == []


# ---------------------------------------------------------------- the rule of the watch, sample by sample
# apt_watched with a stand-in clock and stand-in byte counts: the n-th sample reads the n-th line of
# `times` (ms) and of `sizes` (bytes in the archives folder), so a test sets each number of the rule.
# The command runs until the last size is read. The watch still waits its real tick between samples
# (APT_WATCH_WINDOW=1: 41 ms).
FAKES = r"""
clock() {
  local -a s t
  mapfile -t s < "$STUB_DIR/sampled"
  mapfile -t t < "$STUB_DIR/times"
  local n=${#s[@]}
  if ((n >= ${#t[@]})); then n=$((${#t[@]} - 1)); fi
  printf '%s\n' "${t[n]}"
}
archive_bytes() {
  local -a s b
  echo x >> "$STUB_DIR/sampled"
  mapfile -t s < "$STUB_DIR/sampled"
  mapfile -t b < "$STUB_DIR/sizes"
  local n=$((${#s[@]} - 1))
  if ((n >= ${#b[@]} - 1)); then n=$((${#b[@]} - 1)); : > "$STUB_DIR/done"; fi
  printf '%s\n' "${b[n]}"
}
partial_bytes() { printf '%s\n' "${PRIOR:-0}"; }
shown="$STUB_DIR/shown"
watch="$STUB_DIR/watch"
: > "$watch"
"""
WAITS = 'while [[ ! -e "$STUB_DIR/done" ]]; do /bin/sleep 0.01; done; exit 0'
STEP |= {"waits"}


def judged_by_script(
    tmp_path: Path, times: list, sizes: list, secs: int = 8, prior: int = 0, need: str = NEED
):
    """The watch line apt_watched writes for these samples ("" when it ends no pass)."""
    (tmp_path / "times").write_text("".join(f"{t}\n" for t in times), encoding="utf-8")
    (tmp_path / "sizes").write_text("".join(f"{b}\n" for b in sizes), encoding="utf-8")
    (tmp_path / "sampled").write_text("", encoding="utf-8")
    (tmp_path / "shown").write_text(f"[apt] {need}\n", encoding="utf-8")
    body = FAKES + f'rc=0; apt_watched {secs} waits || rc=$?\ncat "$watch"'
    env = {"APT_WATCH_WINDOW": "1", "PRIOR": str(prior)}
    code, out, err, _ = run(tmp_path, {"waits": WAITS}, env=env, body=body)
    assert code == 0, err
    return out.strip()


def judged(at: list, had: list, secs: int, began: int, need: int, window: int):
    """install.sh's rule (pass_verdict), written again: the watch line's numbers when the pass is ended,
    else None. After 1 window, the rate of the last window leaves out the longest stretch in which a
    pause could hide (each run of samples with the same bytes, from the sample before it to the sample
    after it), at most half a window; the pass ends when that rate, kept up, would not fetch the rest in
    what is left of the bound."""
    now, got = at[-1], had[-1]
    if now - began < window * 1000:
        return None
    back = max(i for i, t in enumerate(at) if t <= now - window * 1000)
    pause, j, n = 0, back, len(at)
    while j < n:
        k = j
        while k + 1 < n and had[k + 1] == had[j]:
            k += 1
        lo, hi = (j - 1 if j > back else back), (k + 1 if k + 1 < n else n - 1)
        pause = max(pause, at[hi] - at[lo])
        j = k + 1
    pause = min(pause, window * 500)
    rate = (got - had[back]) * 1000 // (now - at[back] - pause)
    rest, left = need - got, max(secs - (now - began) // 1000, 0)
    if rate * left < rest:
        return ((now - began) // 1000, got, need, rate, rest, left, pause)
    return None


def model(times: list, sizes: list, secs: int = 8, prior: int = 0, need: int = 10_000_000, window: int = 1):
    """The watch line the rule writes for these samples, as text ("" when no pass is ended). Only growth
    counts: bytes apt removes are not lost progress."""
    at, had, got = [times[0]], [0], 0
    for t, b, before in zip(times[1:], sizes[1:], sizes[:-1], strict=True):
        got += max(b - before, 0)
        at.append(t)
        had.append(got)
        verdict = judged(at, had, secs, times[0], need - prior, window)
        if verdict:
            return " ".join(str(x) for x in verdict)
    return ""


EVERY_50 = list(range(0, 1001, 50))


@pytest.mark.parametrize(("got", "ended"), [(1_139_240, True), (1_139_241, False)])
def test_the_rule_ends_a_pass_1_byte_under_its_line_and_keeps_one_on_it(tmp_path, got, ended):
    """1 window (1000 ms), a sample every 50 ms, bytes growing evenly to `got`; 10 MB to fetch, 8 s
    of bound, so 7 s left. Each sample differs, so the longest stretch a pause could hide in is 2
    intervals, 100 ms: the rate is got / 0.9 s. got = 1139241: 1265823 B/s x 7 s = 8860761 >= the rest,
    8860759: kept. 1 byte less: 1265822 x 7 = 8860754 < 8860760: ended."""
    sizes = [got * i // 20 for i in range(21)]
    want = model(EVERY_50, sizes)
    assert bool(want) == ended
    if ended:
        assert want == "1 1139240 10000000 1265822 8860760 7 100"
    assert judged_by_script(tmp_path, EVERY_50, sizes) == want


def test_no_pass_is_judged_before_a_whole_window(tmp_path):
    """A pass that sends 1 kB in 950 ms is far too slow, but 1 window has not gone by: not judged. The
    same pass seen at 1000 ms is ended."""
    sizes = [50 * i for i in range(21)]
    assert judged_by_script(tmp_path, EVERY_50[:-1], sizes[:-1]) == ""
    assert model(EVERY_50, sizes) != ""


def test_a_late_pass_is_judged_by_the_time_left_not_by_the_bound(tmp_path):
    """8.05 MB by 5 s, then 450 kB in the last window (500 kB/s less a 100 ms pause): at 6 s of an 8 s
    bound, 2 s are left for the last 1.5 MB, so the pass is ended. With the whole bound, 8 s x 500 kB/s
    would be enough."""
    times = [0, *range(5000, 6001, 50)]
    sizes = [0, *(8_050_000 + 450_000 * i // 20 for i in range(21))]
    want = model(times, sizes)
    assert want == "6 8500000 10000000 500000 1500000 2 100"
    assert judged_by_script(tmp_path, times, sizes) == want


def test_a_pass_that_has_all_it_needs_is_not_ended_even_past_its_bounds_time(tmp_path):
    """9 MB by 1 s, then all 10 MB and 100 B more by 3.1 s of a 2 s bound (the watch can sample a little
    after it): no time is left, and none is needed."""
    times = [*EVERY_50, 3100]
    sizes = [9_000_000 * i // 20 for i in range(21)] + [10_000_100]
    assert model(times, sizes, secs=2) == ""
    assert judged_by_script(tmp_path, times, sizes, secs=2) == ""


def test_a_pause_of_half_a_window_is_left_out_of_the_rate(tmp_path):
    """Scaled from CI (window 120 s, apt's own 60 s on a silent server): nothing for 500 ms, then 2 MB/s.
    The window's rate, 1 MB/s, would need 9 s for the rest and 7 are left; the rate without the pause,
    2 MB/s, needs 4.5 s: the pass is kept. It finishes at 5.5 s of the 8 s."""
    sizes = [max(0, 2000 * (t - 500)) for t in EVERY_50]
    assert model(EVERY_50, sizes) == ""
    assert judged_by_script(tmp_path, EVERY_50, sizes) == ""


def test_a_pause_longer_than_half_a_window_counts_beyond_the_half(tmp_path):
    """Nothing for 800 ms, then 300 kB: only 500 ms are left out, so the rate is 600 kB/s, and 4.2 MB
    in 7 s is not the rest. Left out whole it would be 2 MB/s, enough."""
    sizes = [0 if t <= 800 else 300_000 * (t - 800) // 200 for t in EVERY_50]
    want = model(EVERY_50, sizes)
    assert want == "1 300000 10000000 600000 9700000 7 500"
    assert judged_by_script(tmp_path, EVERY_50, sizes) == want


def test_bytes_apt_removes_are_not_lost_progress(tmp_path):
    """apt removes a file with a wrong hash, or a partial file larger than the one it asks for, and
    fetches it again: 9 MB at once, removed at 800 ms, then 2 MB/s. The bytes that arrive count; the
    drop does not."""
    sizes = [9_000_000 if 0 < t < 800 else max(0, 2000 * (t - 800)) for t in EVERY_50]
    assert model(EVERY_50, sizes) == ""
    assert judged_by_script(tmp_path, EVERY_50, sizes) == ""


def test_bytes_in_partial_at_the_start_are_not_in_the_rest(tmp_path):
    """apt's "Need to get" counts a partial file at its full size (apt 2.8.3,
    apt-private/private-install.cc:299, FetchNeeded; apt-pkg/acquire.cc:909), though 8 MB of it are
    there. 400 kB arrive in the window: the rest is 1.6 MB, which 444 kB/s x 7 s fetch. Counted from
    the 10 MB it would be 9.6 MB, and the pass would be ended."""
    sizes = [8_000_000 + 400_000 * i // 20 for i in range(21)]
    assert model(EVERY_50, sizes, prior=8_000_000) == ""
    assert model(EVERY_50, sizes) != ""
    assert judged_by_script(tmp_path, EVERY_50, sizes, prior=8_000_000) == ""


def test_the_watch_samples_about_24_times_a_window(tmp_path):
    """A pause shorter than a sample's interval hides between 2 samples: the watch samples every
    APT_WATCH_WINDOW/24 s (5 s in CI). Over 1 s of real time with a window of 1 s, at least 12 samples
    (24 less the time each takes on a busy machine)."""
    waits = "/bin/sleep 1; exit 0"
    (tmp_path / "times").write_text("0\n", encoding="utf-8")
    (tmp_path / "sizes").write_text("0\n" * 1000, encoding="utf-8")
    (tmp_path / "sampled").write_text("", encoding="utf-8")
    (tmp_path / "shown").write_text(f"[apt] {NEED}\n", encoding="utf-8")
    body = FAKES + "apt_watched 8 waits"
    code, out, err, _ = run(tmp_path, {"waits": waits}, env={"APT_WATCH_WINDOW": "1"}, body=body)
    assert code == 0, err
    samples = len((tmp_path / "sampled").read_text().splitlines())
    assert 12 <= samples <= 26, samples


def test_the_watch_closes_what_it_opened(tmp_path):
    """After a watched pass the script holds the same open files as before it: each pass of 5 would
    leave 1 more."""
    fds = 'fds() { local f n=0; for f in /proc/$BASHPID/fd/*; do n=$((n + 1)); done; echo "$n"; }\n'
    body = FAKES + fds + 'before="$(fds)"; apt_watched 8 waits; echo "$before $(fds)"'
    (tmp_path / "times").write_text("0\n50\n", encoding="utf-8")
    (tmp_path / "sizes").write_text("0\n1\n", encoding="utf-8")
    (tmp_path / "sampled").write_text("", encoding="utf-8")
    (tmp_path / "shown").write_text(f"[apt] {NEED}\n", encoding="utf-8")
    code, out, err, _ = run(tmp_path, {"waits": WAITS}, env={"APT_WATCH_WINDOW": "1"}, body=body)
    assert code == 0, err
    before, after = out.split()
    assert before == after


# ---------------------------------------------------------------- the watch on the stand-in apt


def steady(stall: float, chunk: int, ticks: int, first: str = "") -> str:
    """A pass that prints apt's size, runs `first`, pauses `stall` s, then writes `chunk` bytes into
    partial/ every 0.05 s, `ticks` times, and ends with 0."""
    return f"""echo {shlex.quote(NEED)}; echo {shlex.quote(FAST_GET)}
        echo "$$" >> "$STUB_DIR/apt-pids"
        {first or ":"}
        /bin/sleep {stall}
        for _ in $(seq {ticks}); do
          printf '%0{chunk}d' 0 >> "$APT_ARCHIVES/partial/big.deb"; /bin/sleep 0.05
        done
        exit 0"""


def test_a_pause_of_half_the_window_then_a_rate_that_finishes_is_not_cut(tmp_path):
    """A pause of 0.5 s (half the window, as apt's 60 s is half of CI's 120 s), then 2 MB/s: the 10 MB are
    in by about 5.5 s of the 8 s bound. 1 pass, no cut."""
    code, out, err, calls = run(tmp_path, {"apt-get": by_pass(steady(0.5, 100000, 100))}, env=WATCH)
    assert code == 0, err
    assert " was too slow" not in out + err
    assert len(downloads(calls)) == 1


def test_a_file_removed_and_fetched_again_is_not_cut(tmp_path):
    """9 MB arrive, apt removes them at 0.8 s (a wrong hash) and fetches 10 MB at 2 MB/s: 1 pass, no cut,
    and no line with a negative number."""
    first = 'head -c 9000000 /dev/zero > "$APT_ARCHIVES/partial/big.deb"; /bin/sleep 0.8; '
    first += 'rm -f "$APT_ARCHIVES/partial/big.deb"'
    code, out, err, calls = run(tmp_path, {"apt-get": by_pass(steady(0, 100000, 100, first))}, env=WATCH)
    assert code == 0, err
    assert " was too slow" not in out + err
    assert len(downloads(calls)) == 1


def test_a_partial_file_at_the_start_counts_as_fetched(tmp_path):
    """8 MB of the 10 MB file are in partial/ from an earlier run; apt names 10 MB all the same. 2 MB come
    at 400 kB/s, in 5 s of the 8 s: 1 pass, no cut."""
    (tmp_path / "archives" / "partial").mkdir(parents=True)
    (tmp_path / "archives" / "partial" / "big.deb").write_bytes(b"\0" * 8_000_000)
    code, out, err, calls = run(tmp_path, {"apt-get": by_pass(steady(0, 20000, 100))}, env=WATCH)
    assert code == 0, err
    assert " was too slow" not in out + err
    assert len(downloads(calls)) == 1


def test_a_partial_file_apt_removes_is_0_bytes_in_the_stop_not_a_negative_number(tmp_path):
    """apt removes a partial file larger than the one it asks for (apt 2.8.3, pkgAcqArchive), then
    trickles: the stop says 0 B arrived."""
    (tmp_path / "archives" / "partial").mkdir(parents=True)
    (tmp_path / "archives" / "partial" / "old.deb").write_bytes(b"\0" * 5_000_000)
    slow = trickle(chunk=20).replace(
        'echo "$$" >> "$STUB_DIR/apt-pids"',
        'echo "$$" >> "$STUB_DIR/apt-pids"; rm -f "$APT_ARCHIVES/partial/old.deb"',
    )
    env = {**WATCH, "APT_DOWNLOAD_TRIES": "1"}
    code, out, err, calls = run(tmp_path, {"apt-get": by_pass(slow)}, env=env)
    assert code == 1
    stop = err.splitlines()[-2]
    assert "-" not in stop.split("hosts asked:")[1], stop
    assert "; 0 B of 10.0 MB arrived in " in stop, stop


def test_a_successful_download_leaves_no_temporary_file(tmp_path):
    """The watch's and the passes' files are removed when the download ends well, bounded or not."""
    code, out, err, calls = run(tmp_path, {"apt-get": by_pass(served())}, env=WATCH)
    assert code == 0, err
    assert list((tmp_path / "tmp").iterdir()) == []


def test_a_fetch_failure_after_a_slow_pass_is_not_taken_for_a_slow_pass(tmp_path):
    """Pass 1 is too slow and ended; pass 2 fails on 1 file, as a source that answers 503 does; pass 3
    gets it. Pass 2's line is that of a failed file: the watch's file of pass 1 does not speak for it."""
    fails = f"echo {shlex.quote(E_KICAD)} >&2; echo {shlex.quote(E_FILES)} >&2; exit 100"
    code, out, err, calls = run(tmp_path, {"apt-get": by_pass(trickle(), fails, served())}, env=WATCH)
    assert code == 0, err
    assert len(downloads(calls)) == 3
    lines = out.splitlines()
    assert pass_line(2, 5, 1, 1) in lines
    assert len([x for x in lines if " was too slow to finish" in x]) == 1


def test_a_rate_under_1_kB_s_still_says_how_long_the_rest_needs(tmp_path):
    """400 B/s: the line says the seconds the rest needs at that rate, as for any rate above 0."""
    env = {**WATCH, "APT_DOWNLOAD_TRIES": "2"}
    code, out, err, calls = run(tmp_path, {"apt-get": by_pass(trickle(chunk=20))}, env=env)
    assert code == 1
    (line,) = [x for x in out.splitlines() if " was too slow to finish" in x]
    assert re.search(r" [0-9]+ B/s over the last 1 s, .*; at that rate the rest needs [0-9]+ s, ", line), line


def test_the_watch_ends_the_slow_pass_of_run_44506767788_in_time_for_a_second_host():
    """R1's numbers, from the run and CI's arithmetic, with the rule written again above (`judged`),
    sampled every APT_WATCH_WINDOW/24 s as the script samples. Run 44506767788 (run-facts):
    us-east-2.ec2 completed 26600424 bytes in 550.7 s; the PPA's 4 files were 60.473 MB (when they ended
    is not in the log, so all of them may fall in the first window). A passing run fetched 281.1 MB in
    218 s (job 134889089620). CI: APT_DOWNLOAD_TIMEOUT=570.
    1. With the PPA's bytes in the first 5 s, the watch ends the pass by 2 windows at the latest.
    2. The next pass, on a host as fast as the passing run's, fetches all 281.1 MB in what is left after
       the wait.
    3. A pass at a steady rate that, with 1 pause of up to half a window (APT_FILE_TIMEOUT, apt's own
       60 s on a silent server), ends within the bound is never ended, wherever the pause falls: the
       rule leaves the longest still stretch out of the rate. The first rule (the window's whole rate)
       ended such a pass at 700 kB/s with a pause of 60 s at its start, at 120 s with 42 MB."""
    window = assigned("APT_WATCH_WINDOW")
    pause_max = assigned("APT_FILE_TIMEOUT", env=False)
    bound = int(ci_bounds()[0]["APT_DOWNLOAD_TIMEOUT"])
    wait = assigned("APT_DOWNLOAD_WAIT")
    size, healthy = 281_100_000, 281.1e6 / 218
    slow, ppa = 26600424 / 550.7, 60_473_000
    tick = window * 1000 // 24
    assert pause_max * 2 == window

    def pass_of(arrived, until: int) -> tuple:
        """The first verdict of the rule on a pass whose bytes at t ms are arrived(t)."""
        at, had = [], []
        for t in range(0, until, tick):
            at.append(t)
            had.append(int(arrived(t)))
            verdict = judged(at, had, bound, 0, size, window)
            if verdict:
                return verdict
        return None

    cut = pass_of(lambda t: min(ppa, ppa * t / 3000) + slow * t / 1000, bound * 1000)
    assert cut and cut[0] <= 2 * window, cut
    assert size / healthy <= bound - 2 * window - wait

    def paused(rate: float, start: int, length: int):
        return lambda t: rate * (t - min(max(t - start, 0), length)) / 1000

    for length in (0, 10_000, 30_000, pause_max * 1000):
        least = size / (bound - length / 1000)
        for rate in (least * 1.001, least * 1.05, least * 1.5, healthy, 700_000, 986_000):
            if rate < least * 1.001:
                continue
            ends = int((size / rate + length / 1000) * 1000)
            for start in range(0, ends - length, 7_000):
                assert pass_of(paused(rate, start, length), ends) is None, (length, rate, start)

    def whole_rate(at, had, now):
        back = max(i for i, t in enumerate(at) if t <= now - window * 1000)
        return (had[-1] - had[back]) * 1000 // (now - at[back])

    at = list(range(0, window * 1000 + 1, tick))
    had = [int(paused(700_000, 0, pause_max * 1000)(t)) for t in at]
    assert whole_rate(at, had, at[-1]) * (bound - window) < size - had[-1]
    assert judged(at, had, bound, 0, size, window) is None


def test_the_next_pass_starts_only_after_the_wait_has_ended(tmp_path):
    """The stand-in sleep marks its end after 0.2 s of real time; each download first writes how many
    waits had ended. A wait that runs beside the next pass (`sleep ... &`) gives 0, 0, 0: all passes back
    to back, the 1-pass failure of the image build again."""
    sleep = '/bin/sleep 0.2; echo ended >> "$STUB_DIR/slept"'
    apt = download_fails(None, E_KICAD, E_FILES).replace(
        '    d="$(grep',
        '    { cat "$STUB_DIR/slept" 2> /dev/null || true; } | grep -c ended >> "$STUB_DIR/seen" || true\n'
        '    d="$(grep',
        1,
    )
    env = {"APT_DOWNLOAD_TRIES": "3", "APT_DOWNLOAD_WAIT": "1"}
    code, _, err, _ = run(tmp_path, {"apt-get": apt, "sleep": sleep}, env=env)
    assert code == 1, err
    assert (tmp_path / "seen").read_text().split() == ["0", "1", "2"]


def test_a_wait_starts_while_more_than_the_wait_is_left(tmp_path):
    """APT_DOWNLOAD_TIMEOUT=60, APT_DOWNLOAD_WAIT=20, passes that fail at once: the passes get 60, 40 and
    20 s, less the whole seconds the shell counts, which stay far below the 20 s wait. After the third,
    20 s or less is left: no wait. Exactly 3 passes and 2 waits."""
    env = {"APT_DOWNLOAD_TIMEOUT": "60", "APT_DOWNLOAD_WAIT": "20"}
    code, out, err, calls = run(tmp_path, {"apt-get": download_fails(None, E_KICAD, E_FILES)}, env=env)
    assert code == 1
    given = bounds_of(calls)
    assert len(given) == 3 and given[0] == 60, given
    assert of(calls, "sleep") == ["sleep 20"] * 2
    assert err.splitlines()[-2:] == [no_time_stop(3, 20, 60, E_KICAD), LATER]


def test_a_wait_longer_than_the_time_left_says_so_and_keeps_apts_advice(tmp_path):
    """APT_DOWNLOAD_TIMEOUT=10 and the default wait of 20 s; the source answers 503 at once. The bound did
    not end and the line was not slow: the stop says the wait would leave no time, and keeps the advice
    for apt's 503 (run again later), not the advice for a slow line."""
    env = {"APT_DOWNLOAD_TIMEOUT": "10"}
    code, out, err, calls = run(tmp_path, {"apt-get": download_fails(None, E_KICAD, E_FILES)}, env=env)
    assert code == 1
    assert bounds_of(calls) == [10] and of(calls, "sleep") == []
    assert err.splitlines()[-2:] == [no_time_stop(1, 20, 10, E_KICAD), LATER]


def test_a_full_disk_says_fix_what_apt_said_when_no_time_is_left(tmp_path):
    """Pass 1: a file not served. Pass 2: 100 with a fetch line and a full disk first, with no time left
    for a wait: the stop keeps apt_advice's text for apt's first E: line."""
    env = {"APT_DOWNLOAD_TIMEOUT": "20", "APT_DOWNLOAD_WAIT": "10"}
    then = f"echo {shlex.quote(E_SPACE)} >&2; echo {shlex.quote(E_KICAD)} >&2; exit 100"
    answer = download_fails(1, E_KICAD, E_FILES, then=then)
    code, out, err, calls = run(tmp_path, {"apt-get": answer}, env=env)
    assert code == 1
    given = bounds_of(calls)
    assert len(given) == 2 and given[0] == 20, given
    assert err.splitlines()[-2:] == [
        no_time_stop(2, 10, 20, E_SPACE),
        "[install] No package was installed. Fix what apt said, then run the script again.",
    ]


def test_the_passes_lose_only_the_time_they_took(tmp_path):
    """APT_DOWNLOAD_TIMEOUT=100, APT_DOWNLOAD_WAIT=0, 5 passes that fail at once, well under 1 s in all:
    the whole seconds the shell counts sum to at most 1 over the run, so the last pass gets 99 s or more."""
    env = {"APT_DOWNLOAD_TIMEOUT": "100", "APT_DOWNLOAD_WAIT": "0"}
    code, out, err, calls = run(tmp_path, {"apt-get": download_fails(None, E_KICAD, E_FILES)}, env=env)
    assert code == 1
    given = bounds_of(calls)
    assert len(given) == 5 and given[0] == 100 and given[-1] >= 99, given
    assert err.splitlines()[-2:] == [failed_stop(5, E_KICAD, bound="100"), LATER]


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("APT_DOWNLOAD_TRIES", "abc"),
        ("APT_DOWNLOAD_TRIES", "0"),
        ("APT_DOWNLOAD_TRIES", "-1"),
        ("APT_DOWNLOAD_TRIES", "100"),
        ("APT_DOWNLOAD_TRIES", "2.5"),
        ("APT_DOWNLOAD_TRIES", "05"),
        ("APT_DOWNLOAD_WAIT", "abc"),
        ("APT_DOWNLOAD_WAIT", "-1"),
        ("APT_DOWNLOAD_WAIT", "1000"),
        ("APT_DOWNLOAD_WAIT", "1m"),
        ("APT_DOWNLOAD_WAIT", "007"),
        ("APT_WATCH_WINDOW", "0"),
        ("APT_WATCH_WINDOW", "1000"),
        ("APT_WATCH_WINDOW", "2m"),
        ("APT_WATCH_WINDOW", "060"),
    ],
)
def test_a_bad_number_of_passes_or_wait_stops_before_anything_runs(tmp_path, name, value):
    """1 line that names the variable, its value and the range; no program ran, SKIP_APT or not."""
    unit, top, default = {
        "APT_DOWNLOAD_TRIES": ("passes", "1 to 99", "5"),
        "APT_DOWNLOAD_WAIT": ("seconds", "0 to 999", "20"),
        "APT_WATCH_WINDOW": ("seconds", "1 to 999", "120"),
    }[name]
    for skip in ("0", "1"):
        (tmp_path / skip).mkdir()
        code, out, err, calls = run(tmp_path / skip, env={name: value, "SKIP_APT": skip})
        assert (code, out, calls) == (1, "", [])
        assert err == (
            f"[install] ERROR: {name}={value} is not a whole number of {unit} from {top}; "
            f"set it to one, or leave {name} unset for {default}\n"
        )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("APT_DOWNLOAD_TRIES", "99"),
        ("APT_DOWNLOAD_WAIT", "0"),
        ("APT_WATCH_WINDOW", "1"),
        ("APT_WATCH_WINDOW", "999"),
    ],
)
def test_the_ends_of_the_ranges_are_taken(tmp_path, name, value):
    code, _, err, _ = run(tmp_path, env={name: value})
    assert code == 0, err


def test_ci_and_the_image_build_leave_the_passes_and_the_wait_to_the_script():
    """No workflow that runs install.sh, and not the Dockerfile, sets APT_DOWNLOAD_TRIES or
    APT_DOWNLOAD_WAIT: CI and the image build run on the script's defaults."""
    texts = [path.read_text(encoding="utf-8") for path, _ in INSTALLING.values()]
    texts.append((ROOT / "Dockerfile").read_text(encoding="utf-8"))
    for text in texts:
        assert "APT_DOWNLOAD_TRIES" not in text and "APT_DOWNLOAD_WAIT" not in text


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
        cwd=tmp_path,
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
    backstop = "[install] ERROR: apt: after the install `kicad-cli version` prints 7.0.11, not 10.x"
    assert err.splitlines()[-1] == backstop


def test_kicad_10_present_skips_the_source_step(tmp_path):
    """No key, no sources file, no candidates read; 1 update with no bound (as before this change: a
    slow line is no reason to stop a computer that has KiCad 10, and CI never has it here), then the
    download and the install. CI's bounds are set, and still the update runs with none."""
    (tmp_path / "installed").write_text("", encoding="utf-8")
    code, out, err, calls = run(tmp_path, env=CI)
    assert code == 0, err
    assert "[install] apt: KiCad 10 present (10.0.8); PPA step skipped" in out
    assert of(calls, "curl") == [] and of(calls, "apt-cache") == []
    assert not (tmp_path / "sources.list.d" / "kicad-10.0-releases.sources").exists()
    assert updates(calls) == ["apt-get update -qq"]
    assert [c for c in of(calls, "timeout") if " update" in c] == []
    assert " kicad " not in installs(calls)[0] + " "


def test_kicad_10_present_and_a_failed_update_stops(tmp_path):
    """The update ends with 100: the step stops with that code before any download."""
    (tmp_path / "installed").write_text("", encoding="utf-8")
    code, _, err, calls = run(tmp_path, {"apt-get": update_says(E_LOCKDIR, code=100)})
    assert code == 1
    assert installs(calls) == []
    stop = "[install] ERROR: apt: apt-get update ended with exit code 100; apt's lines are above"
    assert err.splitlines()[-1] == stop


def test_skip_apt_runs_nothing(tmp_path):
    code, out, err, calls = run(tmp_path, env={"SKIP_APT": "1"})
    assert code == 0, err
    assert out == "[install] apt: skipped (SKIP_APT=1)\n"
    assert calls == []


# The java step. The apt step's package openjdk-21-jre-headless puts its java at
# <JVM_DIR>/java-21-openjdk-<arch>/bin/java. CI run 44444183056 (2026-11-19): apt set up 21.0.13.1, and
# doctor then read `absent   java         17.0.21`, the runner's own Java first on PATH. Each test puts a
# stand-in JVM there (it writes `jvm-java` to the calls file) and a stand-in `java` on the closed PATH.
JVM_JAVA = """#!/bin/bash
printf 'jvm-java %s\\n' "$*" >> "$STUB_DIR/calls"
echo 'openjdk version "@VERSION@" 2025-10-21' >&2
"""
ENGINES_MD = "FreeRouting needs Java 21 or newer (ee-agent-kit/docs/ENGINES.md)"


def java_step(
    tmp_path: Path,
    jvm: str = "",
    on_path: str = "",
    require: str = "1",
    stale: bool = False,
    jvms: dict | None = None,
    headless: tuple = (),
):
    """Run step_java with a JVM of version `jvm` under JVM_DIR (none when empty) and a `java` of version
    `on_path` on the closed PATH (none when empty). `jvms` adds JVM folders: name to the script of its
    bin/java, or to None for a folder without it. Each JVM with a java has lib/libawt_xawt.so, as
    openjdk-21-jre gives it, but those `headless` names (openjdk-21-jre-headless alone). Returns (exit
    code, stdout, stderr, calls, record)."""
    answers = {"java": f"echo 'openjdk version \"{on_path}\" 2025-10-21' >&2"} if on_path else {}
    env = {**folder(tmp_path, answers, xawt=False), "REQUIRE_FREEROUTING": require}
    folders = {"java-21-openjdk-amd64": JVM_JAVA.replace("@VERSION@", jvm)} if jvm else {}
    for name, body in {**folders, **(jvms or {})}.items():
        exe = tmp_path / "jvm" / name / "bin" / "java"
        (exe.parent.parent / "lib").mkdir(parents=True)
        if body is not None:
            exe.parent.mkdir()
            exe.write_text(body, encoding="utf-8")
            exe.chmod(0o755)
            if name not in headless:
                (exe.parent.parent / "lib" / "libawt_xawt.so").write_text("", encoding="utf-8")
    record = tmp_path / "root" / "java.path"
    if stale:
        record.parent.mkdir()
        record.write_text("/gone/bin/java\n", encoding="utf-8")
    proc = subprocess.run(
        [BASH, "-c", script(INSTALL, "step_java; echo NEXT STEP")],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=60,
        check=False,
    )
    calls = calls_of(tmp_path, expect={"java", "jvm-java", "mkdir", "rm"})
    return proc.returncode, proc.stdout, proc.stderr, calls, record


def test_the_installed_jvm_is_recorded_whatever_stands_first_on_path(tmp_path):
    """The runner of run 44444183056: a 21 from the apt step under JVM_DIR, a 17 first on PATH. The step
    records the 21's path for Via and passes with REQUIRE_FREEROUTING=1; the 17 is not asked."""
    code, out, err, calls, record = java_step(tmp_path, jvm="21.0.13", on_path="17.0.21", stale=True)
    java = tmp_path / "jvm" / "java-21-openjdk-amd64" / "bin" / "java"
    assert code == 0, err
    assert record.read_text(encoding="utf-8") == f"{java}\n"
    assert out.splitlines() == [
        f"[install] java: {java} (the JVM of the apt step's openjdk-21-jre-headless and openjdk-21-jre,"
        f" recorded in {record}), Java 21: Via runs it",
        "NEXT STEP",
    ]
    assert of(calls, "jvm-java") == ["jvm-java -version"] and of(calls, "java") == []


def test_with_no_installed_jvm_a_java_21_on_path_is_used_and_no_record_is_left(tmp_path):
    """No JVM under JVM_DIR (an image whose java came another way): the java on PATH, a 21, passes. An
    earlier run's record is removed: Via then reads PATH, as the step said."""
    code, out, err, calls, record = java_step(tmp_path, on_path="21.0.9", stale=True)
    assert code == 0, err
    assert not record.exists()
    assert out.splitlines()[0] == (
        f"[install] java: {tmp_path}/bin/java (the first java on PATH: no JVM of the apt step under "
        f"{tmp_path}/jvm), Java 21: Via runs it"
    )
    assert of(calls, "java") == ["java -version"]


ADVICE = (
    "[install] Install openjdk-21-jre-headless and openjdk-21-jre, the apt step's packages, so that "
    "their JVM is in {jvm} (java-21-openjdk-<arch>) with lib/libawt_xawt.so, then run the script again: "
    "install.sh records it for Via."
)


@pytest.mark.parametrize(
    ("jvm", "on_path", "what"),
    [
        (
            "",
            "17.0.21",
            "{tmp}/bin/java (the first java on PATH: no JVM of the apt step under {tmp}/jvm), Java 17",
        ),
        ("", "", "no java (no JVM of the apt step under {tmp}/jvm, and none on PATH)"),
        (
            "17.0.2",
            "21.0.9",
            "{tmp}/jvm/java-21-openjdk-amd64/bin/java (the JVM of the apt step's openjdk-21-jre-headless "
            "and openjdk-21-jre, recorded in {tmp}/root/java.path), Java 17",
        ),
    ],
    ids=["only a 17 on PATH", "no java", "the recorded JVM is a 17"],
)
def test_require_freerouting_ends_red_when_the_workcenters_java_is_not_freeroutings(
    tmp_path, jvm, on_path, what
):
    """REQUIRE_FREEROUTING=1 and the java the step leaves for Via is older than 21, or there is
    none: the step stops with the java it named, the Java FreeRouting needs, and what to do."""
    code, out, err, calls, record = java_step(tmp_path, jvm=jvm, on_path=on_path)
    assert code == 1
    assert "NEXT STEP" not in out
    named = what.format(tmp=tmp_path)
    assert err.splitlines()[-2:] == [
        f"[install] ERROR: java: Via would run {named}; {ENGINES_MD}, and REQUIRE_FREEROUTING=1",
        ADVICE.format(jvm=tmp_path / "jvm"),
    ]


def test_without_require_freerouting_an_old_java_is_a_warning(tmp_path):
    """REQUIRE_FREEROUTING=0, only a 17 on PATH: a warning that names it, and the run goes on."""
    code, out, err, calls, record = java_step(tmp_path, on_path="17.0.21", require="0")
    assert code == 0, err
    assert out.splitlines()[-1] == "NEXT STEP"
    assert err.splitlines() == [
        f"[install] WARN: java: Via would run {tmp_path}/bin/java (the first java on PATH: no JVM"
        f" of the apt step under {tmp_path}/jvm), Java 17; {ENGINES_MD}; doctor says java is absent until"
        " `sudo ./install.sh` records a Java 21"
    ]


def test_a_jvm_of_another_java_beside_the_21_is_not_recorded(tmp_path):
    """A JVM of openjdk-17 beside the 21 under JVM_DIR, a 17 first on PATH: the 21 is recorded."""
    code, out, err, calls, record = java_step(
        tmp_path,
        jvm="21.0.13",
        on_path="17.0.21",
        jvms={"java-17-openjdk-amd64": JVM_JAVA.replace("@VERSION@", "17.0.2")},
    )
    assert code == 0, err
    assert record.read_text(encoding="utf-8") == f"{tmp_path}/jvm/java-21-openjdk-amd64/bin/java\n"


def test_a_jvm_folder_without_its_java_is_passed_over(tmp_path):
    """A java-21-openjdk folder without bin/java (a package half removed), a 21 on PATH: the java on PATH
    passes, and nothing is recorded."""
    code, out, err, calls, record = java_step(
        tmp_path, on_path="21.0.9", jvms={"java-21-openjdk-amd64": None}
    )
    assert code == 0, err
    assert not record.exists()
    assert out.splitlines()[0] == (
        f"[install] java: {tmp_path}/bin/java (the first java on PATH: no JVM of the apt step under "
        f"{tmp_path}/jvm), Java 21: Via runs it"
    )


# A JVM of another architecture beside the machine's own (multiarch): exec gives the shell's 126.
FOREIGN_JAVA = """#!/bin/bash
printf 'jvm-java %s\\n' "$*" >> "$STUB_DIR/calls"
echo 'cannot execute binary file: Exec format error' >&2
exit 126
"""


@pytest.mark.parametrize(
    ("amd64", "recorded"),
    [
        (JVM_JAVA.replace("@VERSION@", "21.0.13"), "java-21-openjdk-amd64"),
        (FOREIGN_JAVA, "java-21-openjdk-arm64"),
    ],
    ids=["both run: the first", "the first does not run: the second"],
)
def test_of_2_jvms_of_the_21_the_first_that_runs_is_recorded(tmp_path, amd64, recorded):
    """2 java-21-openjdk folders, a 21 on PATH: the first in glob order whose java runs and names its
    version is recorded, and the step passes."""
    code, out, err, calls, record = java_step(
        tmp_path,
        on_path="21.0.9",
        jvms={
            "java-21-openjdk-amd64": amd64,
            "java-21-openjdk-arm64": JVM_JAVA.replace("@VERSION@", "21.0.4"),
        },
    )
    assert code == 0, err
    assert record.read_text(encoding="utf-8") == f"{tmp_path}/jvm/{recorded}/bin/java\n"
    assert out.splitlines()[-1] == "NEXT STEP"


def test_a_jvm_that_does_not_run_stops_with_what_it_said(tmp_path):
    """No JVM under JVM_DIR runs, REQUIRE_FREEROUTING=1: the step records the first, ends red, and its
    line says what that java printed and its exit code, not only that a Java 21 is needed."""
    broken = '#!/bin/bash\necho "Error: could not open jvm.cfg" >&2\nexit 1\n'
    code, out, err, calls, record = java_step(
        tmp_path,
        on_path="21.0.9",
        jvms={"java-21-openjdk-amd64": FOREIGN_JAVA, "java-21-openjdk-arm64": broken},
    )
    java = tmp_path / "jvm" / "java-21-openjdk-amd64" / "bin" / "java"
    assert code == 1
    assert "NEXT STEP" not in out
    assert record.read_text(encoding="utf-8") == f"{java}\n"
    assert err.splitlines()[-2:] == [
        f"[install] ERROR: java: Via would run {java} (the JVM of the apt step's "
        f"openjdk-21-jre-headless, recorded in {record}), whose -version said: cannot execute binary file: "
        f"Exec format error (exit 126); {ENGINES_MD}, and REQUIRE_FREEROUTING=1",
        ADVICE.format(jvm=tmp_path / "jvm"),
    ]


# Some images inject JAVA_TOOL_OPTIONS with a proxy address, and java prints it first
# (ee-agent-kit/AGENTS.md, the row `tools/workcenter` doctor).
PICKED_UP = """#!/bin/bash
printf 'jvm-java %s\\n' "$*" >> "$STUB_DIR/calls"
echo 'Picked up JAVA_TOOL_OPTIONS: -Dhttps.proxyHost=proxy -Dhttps.proxyPort=3128' >&2
echo 'openjdk version "@VERSION@" 2025-10-21' >&2
"""


@pytest.mark.parametrize(("version", "code"), [("17.0.2", 1), ("21.0.13", 0)], ids=["a 17", "a 21"])
def test_a_proxy_port_printed_before_the_version_is_not_read_as_it(tmp_path, version, code):
    """The JVM prints a `Picked up JAVA_TOOL_OPTIONS` line with port 3128 before its version: the step
    reads the version."""
    got, out, err, calls, record = java_step(
        tmp_path, on_path="21.0.9", jvms={"java-21-openjdk-amd64": PICKED_UP.replace("@VERSION@", version)}
    )
    assert got == code
    major = version.split(".")[0]
    assert (
        f"/bin/java (the JVM of the apt step's openjdk-21-jre-headless and openjdk-21-jre, recorded in "
        f"{record}), Java {major}" in (out + err)
    )


def test_install_sh_and_doctor_hold_freerouting_to_the_same_java():
    """install.sh's JAVA_MIN and tools/routers.py's JAVA_MIN, which doctor reads, are 1 number."""
    import sys

    sys.path.insert(0, str(ROOT / "tools"))
    import routers

    assert assigned("JAVA_MIN", env=False) == routers.JAVA_MIN == 21


# CI run 44515796762 (job 135531488086, 2026-11-19): the apt step installed openjdk-21-jre-headless, whose
# JVM has no lib/libawt_xawt.so (this machine's /var/lib/dpkg/info/openjdk-21-jre-headless:amd64.list
# names libawt.so and libawt_headless.so; openjdk-21-jre's names libawt_xawt.so). The step's check found
# the library elsewhere under /usr/lib/jvm, in a JDK of the runner's own, and installed nothing more; the
# java step recorded the headless JVM, and every route ended in "FreeRouting exited 1".
JRE_ANSWER = f"""case "$*" in
  *" openjdk-21-jre")
    echo "Setting up openjdk-21-jre:amd64 (21.0.13.1+1~us1-0ubuntu1~24.04) ..."
    touch "$STUB_DIR/jvm/java-21-openjdk-amd64/lib/libawt_xawt.so"
    exit 0 ;;
esac
{DEFAULTS["apt-get"]}"""


def test_the_x11_library_of_another_jdk_under_jvm_dir_does_not_stand_for_the_21s(tmp_path):
    """The runner of run 44515796762: a JDK of the runner's own under JVM_DIR has libawt_xawt.so, the 21
    of the apt step has none. The step installs openjdk-21-jre, which gives the 21 its library."""
    other = tmp_path / "jvm" / "temurin-17-jdk-amd64" / "lib"
    ours = tmp_path / "jvm" / "java-21-openjdk-amd64" / "lib"
    answers = {"apt-get": JRE_ANSWER}
    env = folder(tmp_path, answers, xawt=False)
    other.mkdir(parents=True)
    (other / "libawt_xawt.so").write_text("", encoding="utf-8")
    ours.mkdir(parents=True)
    proc = subprocess.run(
        [BASH, "-c", script(INSTALL, "step_apt")],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    calls = calls_of(tmp_path)
    assert [c for c in installs(calls) if c.endswith(" openjdk-21-jre")] == [
        "apt-get install -y --no-install-recommends openjdk-21-jre"
    ]
    assert (
        "[install] apt: install openjdk-21-jre (the JVM of the 21 under "
        f"{tmp_path}/jvm has no lib/libawt_xawt.so, which FreeRouting needs)"
    ) in proc.stdout.splitlines()
    assert (ours / "libawt_xawt.so").is_file()


def test_a_21_still_without_its_x11_library_after_openjdk_21_jre_stops(tmp_path):
    """openjdk-21-jre is installed and the 21's JVM still has no lib/libawt_xawt.so: the step stops and
    says where it looked."""
    env = folder(tmp_path, xawt=False)
    (tmp_path / "jvm" / "java-21-openjdk-amd64" / "lib").mkdir(parents=True)
    proc = subprocess.run(
        [BASH, "-c", script(INSTALL, "step_apt")],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=60,
        check=False,
    )
    calls_of(tmp_path)
    assert proc.returncode == 1
    assert proc.stderr.splitlines()[-1] == (
        f"[install] ERROR: lib/libawt_xawt.so not found in {tmp_path}/jvm/java-21-openjdk-* after "
        "installing openjdk-21-jre: FreeRouting cannot run"
    )


def test_the_21_with_its_x11_library_installs_nothing_more(tmp_path):
    """The 21's JVM has lib/libawt_xawt.so: no openjdk-21-jre is asked for."""
    code, out, err, calls = run(tmp_path)
    assert code == 0, err
    assert [c for c in installs(calls) if c.endswith(" openjdk-21-jre")] == []


NODRAW = ", whose JVM has no lib/libawt_xawt.so: a headless runtime, which cannot draw FreeRouting's window"
# The stop line's reason for a JVM that cannot draw: the library, not the Java version, which is fine.
NEEDS_X11 = (
    "FreeRouting needs a JVM with lib/libawt_xawt.so to draw its window (ee-agent-kit/docs/ENGINES.md)"
)


def test_a_21_that_cannot_draw_is_recorded_and_stops_with_why(tmp_path):
    """The only JVM of the 21 runs but has no lib/libawt_xawt.so, REQUIRE_FREEROUTING=1: the step records
    it (Via names it when it refuses it) and stops with what is missing and what to install. The line
    names the headless package alone, and its reason is the library, not a Java version."""
    code, out, err, calls, record = java_step(
        tmp_path, jvm="21.0.13", on_path="17.0.21", headless=("java-21-openjdk-amd64",)
    )
    java = tmp_path / "jvm" / "java-21-openjdk-amd64" / "bin" / "java"
    assert code == 1
    assert "NEXT STEP" not in out
    assert record.read_text(encoding="utf-8") == f"{java}\n"
    assert err.splitlines()[-2:] == [
        f"[install] ERROR: java: Via would run {java} (the JVM of the apt step's openjdk-21-jre-headless, "
        f"recorded in {record}), Java 21{NODRAW}; {NEEDS_X11}, and REQUIRE_FREEROUTING=1",
        ADVICE.format(jvm=tmp_path / "jvm"),
    ]


def test_of_2_jvms_of_the_21_that_cannot_draw_the_first_is_recorded(tmp_path):
    """2 JVMs of the 21 that run, neither with lib/libawt_xawt.so: the first in glob order is recorded and
    named, and the step stops."""
    code, out, err, calls, record = java_step(
        tmp_path,
        on_path="17.0.21",
        jvms={
            "java-21-openjdk-amd64": JVM_JAVA.replace("@VERSION@", "21.0.13"),
            "java-21-openjdk-arm64": JVM_JAVA.replace("@VERSION@", "21.0.4"),
        },
        headless=("java-21-openjdk-amd64", "java-21-openjdk-arm64"),
    )
    assert code == 1
    assert record.read_text(encoding="utf-8") == f"{tmp_path}/jvm/java-21-openjdk-amd64/bin/java\n"
    assert NODRAW in err


def test_of_2_jvms_of_the_21_the_first_that_can_draw_is_recorded(tmp_path):
    """2 JVMs of the 21 that both run; the first in glob order has no lib/libawt_xawt.so: the second,
    which has it, is recorded, and the step passes."""
    code, out, err, calls, record = java_step(
        tmp_path,
        on_path="17.0.21",
        jvms={
            "java-21-openjdk-amd64": JVM_JAVA.replace("@VERSION@", "21.0.13"),
            "java-21-openjdk-arm64": JVM_JAVA.replace("@VERSION@", "21.0.4"),
        },
        headless=("java-21-openjdk-amd64",),
    )
    assert code == 0, err
    assert record.read_text(encoding="utf-8") == f"{tmp_path}/jvm/java-21-openjdk-arm64/bin/java\n"
    assert out.splitlines()[-1] == "NEXT STEP"


# The first step (step_boot, from the container image's piece) looks for these 5 tools and the
# certificates file. curl and gpg are stand-ins of every test; git, make and cc are stood in here.
BOOT_TOOLS = {"git": "exit 0", "make": "exit 0", "cc": "exit 0"}
BOOT_INSTALL = "curl gnupg ca-certificates git make gcc libc6-dev"


def test_the_first_step_installs_nothing_when_every_tool_is_there(tmp_path):
    """GitHub's runner and the cloud environment have every tool and the certificates: no apt runs."""
    code, out, err, calls = run(tmp_path, BOOT_TOOLS, body="step_boot; echo NEXT STEP")
    assert (code, out, err, calls) == (0, "NEXT STEP\n", "", [])


def test_the_first_step_installs_the_boot_packages_where_1_is_missing(tmp_path):
    """No certificates file: 1 update, then 1 install of the 7 packages; the run goes on."""
    env = {"CA_BUNDLE": str(tmp_path / "no-bundle.crt")}
    code, out, err, calls = run(tmp_path, BOOT_TOOLS, env=env, body="step_boot; echo NEXT STEP")
    assert code == 0, err
    assert out.splitlines()[0] == f"[install] boot: ca-certificates missing; apt install {BOOT_INSTALL}"
    assert out.splitlines()[-1] == "NEXT STEP"
    apt = of(calls, "apt-get")
    assert apt[0] == "apt-get update -qq"
    assert apt[1].startswith("apt-get install -y --no-install-recommends ")
    assert apt[1].endswith(f" {BOOT_INSTALL}")
    assert len(apt) == 2


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("APT_DOWNLOAD_TRIES", "abc"),
        ("APT_DOWNLOAD_WAIT", "1m"),
        ("APT_DOWNLOAD_TIMEOUT", "0"),
        ("APT_UPDATE_TIMEOUT", "2m"),
    ],
)
def test_a_bad_value_stops_before_the_first_step_installs(tmp_path, name, value):
    """main's order on a bare Ubuntu (no certificates file): a typo in a bound, the passes or the wait
    stops the script with its 1 line before step_boot runs apt, not after it installed the boot packages."""
    env = {name: value, "CA_BUNDLE": str(tmp_path / "no-bundle.crt")}
    code, out, err, calls = run(tmp_path, BOOT_TOOLS, env=env, body="step_boot; step_apt")
    assert (code, out, calls) == (1, "", [])
    assert len(err.splitlines()) == 1
    assert err.startswith(f"[install] ERROR: {name}={value} is not a whole number of ")


@pytest.mark.parametrize(
    ("answer", "said"),
    [
        (
            update_says(E_LOCK, code=100),
            f"[install] ERROR: boot: `apt-get update` ended with exit code 100; apt said: {E_LOCK}",
        ),
        (
            f"""case "$*" in *install*) echo {shlex.quote(E_SOME)} >&2; exit 100 ;; esac""",
            "[install] ERROR: boot: the install of "
            f"{BOOT_INSTALL} ended with apt-get's exit code 100; apt said: {E_SOME}",
        ),
    ],
    ids=["update", "install"],
)
def test_a_failing_apt_in_the_first_step_stops_with_apts_own_line(tmp_path, answer, said):
    """The image's bare Ubuntu: apt's exit code stops the script, with 1 line that quotes apt's E: line,
    where a pipe's `|| true` let a failed install through to the tools' check."""
    env = {"CA_BUNDLE": str(tmp_path / "no-bundle.crt")}
    code, out, err, calls = run(
        tmp_path, {**BOOT_TOOLS, "apt-get": answer}, env=env, body="step_boot; echo NEXT STEP"
    )
    assert code == 1
    assert "NEXT STEP" not in out
    assert err.splitlines()[-1] == said


def test_sourcing_the_script_runs_no_step(tmp_path):
    code, out, err, calls = run(tmp_path, body="true")
    assert (code, out, err, calls) == (0, "", "", [])


GUARD_LINES = 'if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then\n  main "$@"\nfi\n'


def test_a_lost_guard_is_seen_and_stays_in_the_folder(tmp_path):
    """The script with its last line as it was before the guard (`main "$@"`), sourced the same way:
    main() runs, so the test above would fail on it. As root it runs the steps inside the folder; as
    another user it stops at "run as root". Either way no writer was refused a path outside."""
    text = INSTALL.read_text(encoding="utf-8")
    assert text.endswith(GUARD_LINES)
    env = folder(tmp_path)
    copy = tmp_path / "src" / "install.sh"
    copy.parent.mkdir()
    copy.write_text(text[: -len(GUARD_LINES)] + 'main "$@"\n', encoding="utf-8")
    proc = subprocess.run(
        [BASH, "-c", script(copy, "true")],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=60,
        check=False,
    )
    assert proc.stdout + proc.stderr != ""
    calls_of(tmp_path, expect=None)


def test_executing_the_script_runs_main(tmp_path):
    """`bash install.sh --check` reaches main, which hands over to `python3 tools/workcenter doctor`;
    the stand-in python3 ends with 7, and so does the script."""
    env = folder(tmp_path)
    proc = subprocess.run(
        [BASH, str(INSTALL), "--check"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 7
    assert calls_of(tmp_path, expect={"python3"}) == [f"python3 {ROOT}/tools/workcenter doctor"]


def test_the_script_read_from_standard_input_stops_with_a_line(tmp_path):
    """`bash -s < install.sh` (or a pipe into bash) gives the script no file: it says how to run it."""
    env = folder(tmp_path)
    proc = subprocess.run(
        [BASH, "-s"],
        input=INSTALL.read_text(encoding="utf-8"),
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=60,
        check=False,
    )
    assert (proc.returncode, proc.stdout) == (1, "")
    said = "[install] ERROR: install.sh runs as a file, not from standard input: sudo ./install.sh\n"
    assert proc.stderr == said
    assert calls_of(tmp_path, expect=set()) == []


def test_the_script_read_through_a_process_substitution_stops_with_a_line(tmp_path):
    """`bash <(curl ...)` gives the script a path under /dev/fd, which is no folder of the checkout: it
    says how to run it, and runs no step (the second review's S2-8). Run through the harness, so a lost
    stop stays in the folder."""
    env = folder(tmp_path)
    proc = subprocess.run(
        [BASH, "-c", f"{BASH} <(cat {INSTALL})"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=60,
        check=False,
    )
    assert (proc.returncode, proc.stdout) == (1, "")
    said = "[install] ERROR: install.sh runs as a file, not from standard input: sudo ./install.sh\n"
    assert proc.stderr == said
    calls_of(tmp_path, expect=set())


def test_a_link_in_another_folder_finds_the_checkout(tmp_path):
    """`bash <folder>/install.sh --check`, where the file is a link to the checkout's script: SRC_DIR is
    the checkout, not the link's folder."""
    env = folder(tmp_path)
    link = tmp_path / "elsewhere" / "install.sh"
    link.parent.mkdir()
    link.symlink_to(INSTALL)
    proc = subprocess.run(
        [BASH, str(link), "--check"], capture_output=True, text=True, env=env, cwd=tmp_path, timeout=60
    )
    assert proc.returncode == 7, proc.stderr
    assert calls_of(tmp_path, expect={"python3"}) == [f"python3 {ROOT}/tools/workcenter doctor"]


def test_sourcing_the_script_leaves_the_callers_shell_options(tmp_path):
    """`set -euo pipefail` is the script's own when it runs as a file; a shell that sources it keeps its
    options."""
    env = folder(tmp_path)
    proc = subprocess.run(
        [BASH, "-c", f'source {INSTALL}; echo "$-"; shopt -qo pipefail && echo pipefail || echo none'],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=60,
        check=False,
    )
    flags, pipefail = proc.stdout.splitlines()
    assert ("e" in flags, "u" in flags, pipefail) == (False, False, "none")
    calls_of(tmp_path, expect=set())


def test_main_runs_every_step_in_order_and_hands_over_to_the_doctor(tmp_path):
    """main() as it runs: each step replaced by 1 that logs its name, the root check by `true` in a copy.
    The 7 steps run in their order, the first step (step_boot, a bare Ubuntu's tools) before the apt
    step, and the run ends with `workcenter doctor` and its exit code."""
    text = INSTALL.read_text(encoding="utf-8")
    root_check = '[[ "$EUID" -eq 0 ]] || die "run as root (sudo ./install.sh)"'
    assert text.count(root_check) == 1
    copy = tmp_path / "src" / "install.sh"
    copy.parent.mkdir()
    copy.write_text(text.replace(root_check, "true"), encoding="utf-8")
    steps = [
        "step_boot",
        "step_apt",
        "step_freerouting",
        "step_java",
        "step_openems",
        "step_python",
        "step_link",
    ]
    others = ["step_java25", "step_freerouting2", "step_chip"]
    body = "\n".join(f'{s}() {{ log "ran {s}"; }}' for s in steps + others) + "\nmain"
    env = folder(tmp_path, {"python3": f"{DRAINS}exit 5"})
    proc = subprocess.run(
        [BASH, "-c", script(copy, body)],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=60,
        check=False,
    )
    ran = [line.removeprefix("[install] ran ") for line in proc.stdout.splitlines() if " ran " in line]
    assert ran == steps, proc.stderr
    assert proc.stdout.splitlines()[-1].startswith("[install] done in ")
    assert proc.returncode == 5
    assert calls_of(tmp_path, expect={"python3"}) == [f"python3 {copy.parent}/tools/workcenter doctor"]


@pytest.mark.parametrize(
    "body",
    [
        'sed -i "s/^/x/" "$VICTIM"',
        'awk \'BEGIN { print "x" > ENVIRON["VICTIM"] }\'',
        'find "$VICTIM" -delete',
        'echo x | tee "$VICTIM"',
        'mktemp -p "${VICTIM%/*}"',
        'rm -f "$STUB_DIR/../$VICTIM_REL"',
        'cp "$STUB_DIR/calls" "$STUB_DIR/../$VICTIM_REL"',
    ],
    ids=["sed -i", "awk >", "find -delete", "tee", "mktemp -p", "rm ..", "cp .."],
)
def test_the_fence_refuses_a_write_outside_the_folder(tmp_path, body):
    """The harness itself: every program on the closed PATH that can write is refused a path outside
    the test's folder, `..` included. The file outside is left as it was."""
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    victim = outside / "victim.txt"
    victim.write_text("line\n", encoding="utf-8")
    env = {**folder(tmp_path), "VICTIM": str(victim), "VICTIM_REL": f"{outside.name}/victim.txt"}
    proc = subprocess.run([BASH, "-c", body], capture_output=True, env=env, cwd=tmp_path, timeout=60)
    assert sorted(p.name for p in outside.iterdir()) == ["victim.txt"]
    assert victim.read_text(encoding="utf-8") == "line\n"
    assert proc.returncode != 0
    calls = (tmp_path / "calls").read_text(encoding="utf-8").splitlines()
    assert [c for c in calls if c.startswith("REFUSED")]


# The paths the script may name in its code: the 7 defaults on their own lines (CA_BUNDLE, the first
# step's certificates, since the container image's piece), and 2 it only reads.
DEFAULT_LINES = [
    'WC_ROOT="${WORKCENTER_ROOT:-/opt/workcenters/${WC_NAME}}"',
    'KICAD_KEYRING="${KICAD_KEYRING:-/etc/apt/keyrings/kicad-10.0-releases.gpg}"',
    'KICAD_SOURCES="${KICAD_SOURCES:-/etc/apt/sources.list.d/kicad-10.0-releases.sources}"',
    'WORKCENTER_LINK="${WORKCENTER_LINK:-/usr/local/bin/workcenter}"',
    'OS_RELEASE="${OS_RELEASE:-/etc/os-release}"',
    'JVM_DIR="${JVM_DIR:-/usr/lib/jvm}"',
    'CA_BUNDLE="${CA_BUNDLE:-/etc/ssl/certs/ca-certificates.crt}"',
    # apt's archives folder (Dir::Cache::Archives), which the watch of a download only reads.
    'APT_ARCHIVES="${APT_ARCHIVES:-/var/cache/apt/archives}"',
]
READ_ONLY = {"/dev/null", "/var/lib/dpkg/status"}
PATH_IN_CODE = re.compile(r"(?<![\w:/.$}~\]])/[A-Za-z0-9_.][A-Za-z0-9_.+-]*(?:/[A-Za-z0-9_.+-]+)*/?")


def literal_paths(text: str) -> list[tuple[str, str]]:
    """Each absolute path in a line of code (not a comment line, not a default's line) but READ_ONLY."""
    found = []
    for line in text.splitlines():
        if line.lstrip().startswith("#") or line in DEFAULT_LINES:
            continue
        found += [(path, line.strip()) for path in PATH_IN_CODE.findall(line) if path not in READ_ONLY]
    return found


# The variables a test points into its folder, and the locals the script builds from one of them (or from
# `mktemp`, under TMPDIR). A shell redirection writes with no program, so passes no fence: its target
# must start with 1 of these, or be /dev/null. A program called by a path (not by its name on the closed
# PATH) passes no fence either: its path must start with 1 of these too. Each assignment of a local of
# BUILT is held to the same rule, so that the name cannot carry another path.
MOVED = {"WC_ROOT", "KICAD_KEYRING", "KICAD_SOURCES", "WORKCENTER_LINK", "JVM_DIR"}
BUILT = {"dir", "root", "venv", "env", "stamp", "deb", "jar", "tgz", "kit", "errors", "shown", "py"}
# The download's 2 files of its own: what the watch saw of a pass, and every pass's progress lines.
BUILT |= {"watch", "passlog"}
INSIDE = re.compile(r'^"?\$\{?(' + "|".join(sorted(MOVED | BUILT)) + r")\b")
# What a local of BUILT may be set to besides a path under INSIDE: a name on the closed PATH, a temp file.
BUILT_ALSO = {'"python3"', '"$(mktemp)"'}
# Words after which the next word is a command.
STARTS = {"then", "do", "else", "elif", "if", "while", "until", "!", "exec", "time", "{", "}"}


def _skip_heredocs(text: str) -> list[str]:
    """The code's lines without the bodies of its here-documents, which are data, and without comments."""
    lines, kept, end = text.splitlines(), [], None
    for line in lines:
        if end is not None:
            if line.strip() == end:
                end = None
            continue
        if line.lstrip().startswith("#"):
            continue
        kept.append(line)
        found = re.search(r"(?<!<)<<-?\s*['\"]?(\w+)['\"]?(?!<)", line)
        if found and "<<<" not in line:
            end = found.group(1)
    return kept


def _closing(code: str, i: int, opening: str, closing: str) -> int:
    """The index just after the `closing` that matches the `opening` at code[i]."""
    depth, j = 0, i
    while j < len(code):
        if code.startswith(opening, j):
            depth += 1
            j += len(opening)
            continue
        if code.startswith(closing, j):
            depth -= 1
            j += len(closing)
            if depth == 0:
                return j
            continue
        j += 1
    return j


def unfenced_writes(text: str) -> list[str]:
    """Each place in the script's code that could write outside a test's folder without a fenced program:
    a redirection whose target is not under INSIDE (relative, `..`, the checkout, a path built from
    pieces), a program called by a path that is not under INSIDE, and an assignment of a local of BUILT
    that is not. A lexical scan: what it cannot see is listed in the docs' Left."""
    found: list[str] = []
    _scan("\n".join(_skip_heredocs(text)), found)
    return found


def _scan(code: str, found: list[str]) -> None:
    i, word, command, in_test, verb = 0, "", True, False, ""

    def end_word():
        """Judge the word just read: an assignment, a command word, or a word of `for` or `read`."""
        nonlocal word, command, in_test, verb
        w, word = word, ""
        if not w:
            return
        if in_test:
            in_test = w != "]]"
            return
        name = re.match(r"^(\w+)\+?=", w)
        if name:
            # `local a=... b=...` and `VAR=... program`: the next word may still be the command
            value = w[name.end() :]
            if name.group(1) in BUILT and not (INSIDE.match(value) or value in BUILT_ALSO):
                found.append(f"assignment {w}")
            return
        if verb in ("for", "read") and w in BUILT:
            found.append(f"assignment by {verb} of {w}")
        if not command:
            return
        if w == "[[":
            in_test, command = True, False
        elif w in STARTS or w in ("local", "export", "declare"):
            verb = w
        else:
            bare = w.lstrip('"')
            if w not in (".", '"$@"') and bare.startswith(("/", ".", "~", "$")) and not INSIDE.match(w):
                found.append(f"program {w}")
            verb, command = w, False

    while i < len(code):
        c = code[i]
        if code.startswith("\\\n", i):
            i += 2
            continue
        if c == "\\":
            word += code[i : i + 2]
            i += 2
            continue
        if c == "'":
            j = code.index("'", i + 1) + 1
            word += code[i:j]
            i = j
            continue
        if c == '"':
            j = i + 1
            while code[j] != '"':
                if code[j] == "\\":
                    j += 2
                elif code.startswith("$((", j):
                    j = _closing(code, j + 1, "((", "))")
                elif code.startswith("$(", j):
                    k = _closing(code, j + 1, "(", ")")
                    _scan(code[j + 2 : k - 1], found)
                    j = k
                elif code.startswith("${", j):
                    j = _closing(code, j + 1, "{", "}")
                else:
                    j += 1
            word += code[i : j + 1]
            i = j + 1
            continue
        if code.startswith("$((", i) or (not word and code.startswith("((", i)):
            j = _closing(code, i + (1 if c == "$" else 0), "((", "))")
            word += code[i:j]
            i = j
            continue
        if code.startswith("$(", i) or code.startswith("<(", i) or code.startswith(">(", i):
            j = _closing(code, i + 1, "(", ")")
            if c == ">":
                found.append(f"redirection {code[i:j]}")
            _scan(code[i + 2 : j - 1], found)
            word += code[i:j]
            i = j
            continue
        if code.startswith("${", i):
            j = _closing(code, i + 1, "{", "}")
            word += code[i:j]
            i = j
            continue
        if c == "(" and word.endswith("="):
            j = _closing(code, i, "(", ")")
            word += code[i:j]
            i = j
            continue
        if c == "#" and not word:
            i = code.find("\n", i) if "\n" in code[i:] else len(code)
            continue
        if c == ">" and not in_test:
            # `>`, `>>`, `>|`, `&>`, `N>`: a write; `>&N` duplicates a descriptor
            if word.isdigit() or word == "&":
                word = ""
            else:
                end_word()
            j = i + 1
            while j < len(code) and code[j] in ">|":
                j += 1
            while j < len(code) and code[j] in " \t":
                j += 1
            if code.startswith(">(", j - 1) or code.startswith("(", j):
                found.append(f"redirection {code[i : j + 1]}")
            k = j
            while k < len(code) and code[k] not in " \t\n;|&)<>":
                if code[k] in "\"'":
                    k = code.index(code[k], k + 1)
                k += 1
            target = code[j:k]
            # `>&N`, `>&-` and `>&"$fd"` (a descriptor bash chose, `exec {fd}>&1`) copy or close a
            # descriptor: no write to a path.
            dup = re.match(r'&(?:[0-9-]|"\$\{?\w+\}?"|\$\{?\w+\}?)', code[j:])
            if dup:
                k = j + dup.end()
            elif target != "/dev/null" and not INSIDE.match(target):
                found.append(f"redirection > {target}")
            i = k
            continue
        if c in " \t":
            end_word()
            i += 1
            continue
        if c in "\n;|&(){}" and not in_test:
            end_word()
            command, verb = True, ""
            i += 1
            continue
        if c in "\n;|&(){}":
            end_word()
            i += 1
            continue
        word += c
        i += 1
    end_word()


def test_the_path_scan_sees_a_write_the_fence_cannot():
    """A redirection, or a program off the closed PATH, passes no fence: the scan must see its path,
    on a line with a default's `:-/` too."""
    for line, path in [
        ("  rm -rf /var/lib/apt/lists/partial", "/var/lib/apt/lists/partial"),
        ("  sed -i 's/x/y/' /root/.bashrc", "/root/.bashrc"),
        ("  cp x /usr/share/kicad/x", "/usr/share/kicad/x"),
        ("  printf x > /etc/apt/apt.conf.d/99wc  # ${X:-/}", "/etc/apt/apt.conf.d/99wc"),
        ('  X="${X:-/etc/x}"', "/etc/x"),
    ]:
        assert [p for p, _ in literal_paths(line)] == [path], line
    assert literal_paths("  echo x 2>/dev/null; awk '$0 != \"/var/lib/dpkg/status\"'") == []


def test_the_write_scan_sees_a_redirection_or_a_program_outside_the_moved_paths():
    """A redirection to a path that is not under a moved variable (relative, `..`, the checkout, a path
    built from pieces: the 3 lines of the second review's S2-1 wrote outside the folder with every test
    passing), a program called by such a path, and a local of BUILT given another path."""
    for line, seen in [
        ("  printf 'x\\n' >> ../escape-rel.txt", "redirection > ../escape-rel.txt"),
        (
            "  printf x >> ../../../../../../etc/apt/apt.conf.d/99wc",
            "redirection > ../../../../../../etc/apt/apt.conf.d/99wc",
        ),
        ("  printf 'x\\n' >> \"${SRC_DIR}/escape-src.txt\"", 'redirection > "${SRC_DIR}/escape-src.txt"'),
        ('  printf x >> "/""etc/apt/apt.conf.d/99wc"', 'redirection > "/""etc/apt/apt.conf.d/99wc"'),
        ("  printf x >> ~/.bashrc", "redirection > ~/.bashrc"),
        ('  out="$(printf x 2> ../y)"', "redirection > ../y"),
        ('  "${SRC_DIR}/tools/workcenter" doctor', 'program "${SRC_DIR}/tools/workcenter"'),
        ('  local dir="$SRC_DIR"', 'assignment dir="$SRC_DIR"'),
        ("  for dir in /etc; do :; done", "assignment by for of dir"),
    ]:
        assert unfenced_writes(line) == [seen], line
    for line in [
        '  cat "$errors" >&2; echo x 2>/dev/null',
        '  echo "$want" > "${dir}/.sha256"',
        '  rows="$(kicad_candidates 2> "$errors")" || rc=$?',
        '  HOME="${root}/home" "${root}/mm/bin/micromamba" create < /dev/null > /dev/null 2>&1',
        '  log "link: ${WORKCENTER_LINK} -> ${SRC_DIR}/tools/workcenter"',
        "  if ((try < KICAD_INDEX_TRIES)); then [[ a > b ]]; fi",
        '  cat > "$KICAD_SOURCES" <<EOF\nx > /etc/y\nEOF',
        "  exec {out}>&1; exec {out}>&-",
        '  exec {wake}< <(exec {keep}>&1 >&"$out"; exec timeout "$secs" "$@")',
    ]:
        assert unfenced_writes(line) == [], line


def test_no_literal_path_outside_the_folder_is_in_the_scripts_code():
    """The paths a lost guard would reach are read from the environment, each with its real default on
    its own line; any other absolute path in the code is /dev/null or /var/lib/dpkg/status."""
    text = INSTALL.read_text(encoding="utf-8")
    lines = text.splitlines()
    for line in DEFAULT_LINES:
        assert lines.count(line) == 1, line
    assert literal_paths(text) == []
    assert unfenced_writes(text) == []


def assigned(name: str, env: bool = True) -> int:
    pattern = rf'^{name}="\${{{name}:-(\d+)}}"$' if env else rf'^{name}="(\d+)"$'
    (value,) = re.findall(pattern, INSTALL.read_text(encoding="utf-8"), re.M)
    return int(value)


def test_a_persons_computer_has_no_total_bound_by_default():
    """APT_UPDATE_TIMEOUT and APT_DOWNLOAD_TIMEOUT default to empty: no bound unless set."""
    text = INSTALL.read_text(encoding="utf-8")
    for name in ("APT_UPDATE_TIMEOUT", "APT_DOWNLOAD_TIMEOUT"):
        assert re.findall(rf'^{name}="\$\{{{name}:-(.*)\}}"$', text, re.M) == [""], name


def ci_bounds(path: Path = WORKFLOW, job: str = "full") -> tuple[dict, int]:
    """The bounds a workflow's install sets, and its job's limit in s, both read from the workflow: the
    install step's command line (ci.yml's `full` job, nightly.yml's `verify` job), or the image build's
    `--build-arg`s, which the Dockerfile hands to install.sh (image.yml's `build` job)."""
    yaml = pytest.importorskip("yaml")
    steps = yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"][job]
    runs = [s.get("run", "") for s in steps["steps"]]
    (install,) = [r for r in runs if "./install.sh" in r or "docker build" in r]
    bounds = dict(re.findall(r"\b(APT_(?:UPDATE|DOWNLOAD)_TIMEOUT)=(\S+)", install))
    return bounds, int(steps["timeout-minutes"]) * 60


# Every workflow that runs install.sh on a runner: CI's full job, the nightly run and the image build.
INSTALLING = {
    "ci.yml": (WORKFLOW, "full"),
    "nightly.yml": (WORKFLOW.parent / "nightly.yml", "verify"),
    "image.yml": (WORKFLOW.parent / "image.yml", "build"),
}


@pytest.mark.parametrize("name", list(INSTALLING))
def test_the_worst_case_of_the_apt_step_fits_the_jobs_limit(name):
    """Each workflow that runs install.sh sets CI's 2 bounds, and its own job's limit is read from it
    (ci.yml 30 minutes, nightly.yml 45, image.yml 60), so a change of either without the other fails
    here. The newest passing run of 2026-11-18 (job 134941364976; log
    lines 2, 169, 352, 710, 823, 843 and 933) used 9 s before install.sh (16:10:05.85 to 16:10:14.58),
    27 s to unpack and set up (16:12:18.72 to 16:12:45.28), 28 s for the steps after apt (to 16:13:13.37)
    and 670 s for `make verify` (16:13:13.86 to 16:24:23.84): of the job's 1800 s (timeout-minutes: 30),
    1800 - 9 - 27 - 28 - 670 = 1066 s are left for the key, the updates, the waits and the download.
    The key fetch runs on every fresh runner (the second review's S2-5): each of its 2 addresses is tried
    while curl's retry timer is below KICAD_KEY_TIMEOUT (--retry-max-time), each try lasts at most
    KICAD_KEY_TIMEOUT (--max-time), and with --retry 3 curl waits 1, 2, then 4 s (curl 8.5.0's manual,
    --retry and --retry-max-time): at most 20 + 4 + 20 = 44 s an address, 88 s for both.
    88 + 3 x 120 + 2 x 20 + 570 = 1058 s. The nightly run and the image build are held to the same 734 s
    of other steps; neither has a passing run of its own measured (the image build runs no
    `make verify`, but builds, checks and pushes)."""
    bounds, limit = ci_bounds(*INSTALLING[name])
    assert bounds == CI
    tries, wait = assigned("KICAD_INDEX_TRIES"), assigned("KICAD_INDEX_WAIT")
    update, download = int(bounds["APT_UPDATE_TIMEOUT"]), int(bounds["APT_DOWNLOAD_TIMEOUT"])
    key = 2 * (2 * assigned("KICAD_KEY_TIMEOUT", env=False) + 4)
    assert key + tries * update + (tries - 1) * wait + download <= limit - 9 - 27 - 28 - 670


def test_one_silent_file_fits_the_download_bound():
    """apt gives a silent server APT_FILE_TIMEOUT s, APT_FILE_RETRIES + 1 times: that must end within
    the download's bound CI sets, so that apt names the file (Err:) before the bound cuts it."""
    retries, timeout = assigned("APT_FILE_RETRIES", env=False), assigned("APT_FILE_TIMEOUT", env=False)
    assert (retries + 1) * timeout < int(ci_bounds()[0]["APT_DOWNLOAD_TIMEOUT"])


def test_the_step_holds_no_bare_bound():
    """Every wait and bound of the apt step is a named variable, the key fetch's included (it counts in
    the worst case above). Its `--retry 3` and `--connect-timeout 20` are curl's own, as before."""
    text = INSTALL.read_text(encoding="utf-8")
    step = text[text.index("\nkicad10_present() {") : text.index("\nstep_freerouting() {")]
    assert re.findall(r"(?<![-\w])(?:sleep|timeout) [0-9]", step) == []
    assert re.findall(r"(?:Retries|Timeout)=[0-9]", step) == []
    assert re.findall(r"--(?:retry-)?max-time [0-9]", step) == []


def test_the_script_parses_and_shellcheck_is_clean():
    proc = subprocess.run(["bash", "-n", str(INSTALL)], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
    proc = subprocess.run(["shellcheck", str(INSTALL)], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout


ANCHORS = "test_each_mutation_of_the_list_changes_1_place_of_the_script"


def test_each_mutation_of_the_list_changes_1_place_of_the_script():
    """tests/install_mutations.py: an edit of the step that moves an anchor fixes it in the same commit.
    In a mutant's copy this test fails on its own (the old text is gone), so TEST deselects it: else
    every mutant would count as caught."""
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
    assert f"--deselect tests/test_install_apt.py::{ANCHORS}" in found["TEST"]
