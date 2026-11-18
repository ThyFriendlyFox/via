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
   JVM_DIR, HOME and TMPDIR all point into the test's folder, and the folder is the working directory.
   A lost guard runs main() there.
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
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "install.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
SAMPLES = ROOT / "tests" / "samples" / "install"
BASH = "/bin/bash"
# A person's computer has no total bound; CI sets these 2 in its install step (the workflow file, held to
# them by test_the_worst_case_of_the_apt_step_fits_the_jobs_limit).
CI = {"APT_UPDATE_TIMEOUT": "120", "APT_DOWNLOAD_TIMEOUT": "600"}

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
LATER = (
    "[install] No package was installed. A package source did not serve a file this time: "
    "run the script again later; apt keeps the files it has downloaded."
)
CUT = (
    "[install] No package was installed. Run the script again now: apt keeps the files it has downloaded "
    "and goes on from them. On a slow line, set APT_DOWNLOAD_TIMEOUT to more seconds."
)

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
READERS = ["basename", "cat", "dirname", "grep", "head", "seq", "tail"]

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
STEP |= {"install", "mv", "chmod", "rm", "touch", "mktemp", "tee"}


def real(name: str) -> str:
    found = shutil.which(name, path="/usr/bin:/bin")
    assert found, name
    return found


def folder(tmp_path: Path, answers: dict | None = None) -> dict:
    """Make the stand-ins, the readers and the folder's files; return the environment of a run."""
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
    jvm = tmp_path / "jvm" / "lib"
    jvm.mkdir(parents=True)
    (jvm / "libawt_xawt.so").write_text("", encoding="utf-8")
    (tmp_path / "tmp").mkdir()
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
    assert updates(calls) == ["apt-get update -qq"]
    assert of(calls, "sleep") == []
    assert of(calls, "apt-cache") == ["apt-cache policy kicad kicad-symbols kicad-footprints kicad-templates"]
    download, install = installs(calls)
    assert "--download-only" in download and "--download-only" not in install
    assert download.startswith("apt-get install ") and "-o Acquire::http::Timeout=60" in download
    assert "-o APT::Get::Download=false" in install
    assert of(calls, "timeout") == []
    # the key was fetched and checked, and the sources file names the source
    assert (tmp_path / "keyrings" / "kicad-10.0-releases.gpg").read_text(encoding="utf-8") == "a key\n"
    sources = tmp_path / "sources.list.d" / "kicad-10.0-releases.sources"
    assert "Suites: noble" in sources.read_text(encoding="utf-8")
    # progress stays visible
    assert "[apt] Get:172 https://ppa.launchpadcontent.net/" in out
    assert "[apt] Setting up kicad (10.0.8~ubuntu24.04.1) ..." in out
    assert out.splitlines()[-1] == "[install] apt: done; kicad-cli 10.0.8"


def test_the_bounds_ci_sets_run_the_update_and_the_download_under_timeout(tmp_path):
    """APT_UPDATE_TIMEOUT=120 and APT_DOWNLOAD_TIMEOUT=600, as CI's install step sets them: the update
    and the download run under `timeout`; the install from the downloaded files does not."""
    code, out, err, calls = run(tmp_path, env=CI)
    assert code == 0, err
    bounded = of(calls, "timeout")
    assert bounded[0] == "timeout 120 apt-get update -qq"
    assert bounded[1].startswith("timeout 600 apt-get install -y --no-install-recommends --download-only ")
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
        said = "[install] ERROR: apt: the download ended with apt-get's exit code 124; apt said: nothing"
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
    """With CI's bound of 120 s on 1 update, `timeout` ends with 124 when it is reached."""
    answer = '[[ "$*" == *update* ]] && exit 124; shift; exec "$@"'
    code, _, err, calls = run(tmp_path, {"timeout": answer}, env=CI)
    assert code == 1
    assert of(calls, "timeout")[0] == "timeout 120 apt-get update -qq"
    assert len(of(calls, "timeout")) == 3
    stop = (
        "[install] ERROR: apt: the index of KiCad 10's package source did not arrive in 3 tries: "
        f"{SOURCE}; apt said: nothing: apt-get update did not end within 120 s (APT_UPDATE_TIMEOUT)"
    )
    assert err.splitlines()[-2:] == [stop, AGAIN]
    assert installs(calls) == []


def test_another_sources_warning_is_not_kicads(tmp_path):
    """A 503 of another source's index is apt's and the user's business: KiCad's index is there."""
    other = (
        "W: Failed to fetch http://azure.archive.ubuntu.com/ubuntu/dists/noble/InRelease"
        "  503  Service Unavailable"
    )
    code, _, err, calls = run(tmp_path, {"apt-get": update_says(other)})
    assert code == 0, err
    assert len(updates(calls)) == 1


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
    code, _, err, calls = run(
        tmp_path,
        {"apt-get": update_says(E_RELEASE, N_SECURE, N_MANPAGE, code=100)},
        env={"OS_RELEASE": str(bookworm)},
    )
    assert code == 1
    assert len(updates(calls)) == 1 and of(calls, "sleep") == []
    sources = tmp_path / "sources.list.d" / "kicad-10.0-releases.sources"
    assert not sources.exists()
    assert err.splitlines()[-2:] == [
        "[install] ERROR: apt: the index of KiCad 10's package source did not arrive in 1 try: "
        f"{URL} bookworm; apt said: {E_RELEASE}",
        f"[install] KiCad 10's package source serves no release for bookworm ({bookworm}); install.sh is for "
        f"Ubuntu 24.04 (noble). {sources} was removed, so apt works as before. This run installed no KiCad.",
    ]


def test_another_sources_missing_release_is_quoted_and_not_blamed_on_kicads(tmp_path):
    """apt ends with 100 because another source has no Release file; no line names KiCad's source. The
    stop quotes apt's last E: line (not its last line, an N: line), tries again as for any cause it
    does not know, and leaves KiCad's sources file, which is not at fault."""
    e_other = "E: The repository 'http://dl.example.org/tool noble Release' does not have a Release file."
    code, _, err, calls = run(tmp_path, {"apt-get": update_says(e_other, N_SECURE, N_MANPAGE, code=100)})
    assert code == 1
    assert len(updates(calls)) == 3
    assert (tmp_path / "sources.list.d" / "kicad-10.0-releases.sources").exists()
    assert err.splitlines()[-2:] == [
        "[install] ERROR: apt: the index of KiCad 10's package source did not arrive in 3 tries: "
        f"{SOURCE}; apt said: exit code 100: {e_other}",
        f"{NONE} Fix what apt said, then run the script again.",
    ]


def test_a_second_key_for_the_source_stops_at_once_and_names_the_other_file(tmp_path):
    """Another .sources file names the source with another key (add-apt-repository's): apt ends with
    100 and E: Conflicting values. 1 try; the other file is named, the script's own is removed."""
    other = tmp_path / "sources.list.d" / "kicad-ubuntu-kicad-10_0-releases-noble.sources"
    other.parent.mkdir()
    other.write_text(f"Types: deb\nURIs: {URL}/\nSuites: noble\n", encoding="utf-8")
    code, _, err, calls = run(tmp_path, {"apt-get": update_says(E_SIGNED, E_LIST, code=100)})
    assert code == 1
    assert len(updates(calls)) == 1 and of(calls, "sleep") == []
    ours = tmp_path / "sources.list.d" / "kicad-10.0-releases.sources"
    assert not ours.exists() and other.exists()
    assert err.splitlines()[-2:] == [
        "[install] ERROR: apt: the index of KiCad 10's package source did not arrive in 1 try: "
        f"{SOURCE}; apt said: {E_SIGNED}",
        f"[install] Another file names KiCad 10's package source with another key: {other}. {ours} was "
        "removed, so apt works as before. Remove the other file, then run the script again. "
        "This run installed no KiCad.",
    ]


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
    assert err.splitlines()[-2:] == [
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
    """apt-get ends with 100 and its E: lines (job 134906707485 at 15:44:22): exit 1, no install, no
    later step; with a bound or without."""
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
    within = ", within its bound of 600 s" if bounds else ""
    stop = (
        f"[install] ERROR: apt: the download ended with apt-get's exit code 100{within}; apt said: {E_FETCH}"
    )
    assert err.splitlines()[-2:] == [stop, LATER]
    assert "NEXT STEP" not in out
    assert of(calls, "kicad-cli") == ["kicad-cli version"]


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
        f"[install] ERROR: apt: the download ended with apt-get's exit code {rc}; apt said: nothing",
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
    stop = "[install] ERROR: apt: the download did not end within 9 s (APT_DOWNLOAD_TIMEOUT); apt said: "
    stop += "nothing"
    assert err.splitlines()[-2:] == [stop, CUT]


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
    assert err.splitlines()[-2:] == [
        "[install] ERROR: apt: the download did not end within 600 s (APT_DOWNLOAD_TIMEOUT); "
        f"apt said: {err_line}",
        CUT,
    ]


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


def test_main_runs_every_step_in_order_and_hands_over_to_the_doctor(tmp_path):
    """main() as it runs: each step replaced by 1 that logs its name, the root check by `true` in a copy.
    The 5 steps run in their order, and the run ends with `workcenter doctor` and its exit code."""
    text = INSTALL.read_text(encoding="utf-8")
    root_check = '[[ "$EUID" -eq 0 ]] || die "run as root (sudo ./install.sh)"'
    assert text.count(root_check) == 1
    copy = tmp_path / "src" / "install.sh"
    copy.parent.mkdir()
    copy.write_text(text.replace(root_check, "true"), encoding="utf-8")
    steps = ["step_apt", "step_freerouting", "step_openems", "step_python", "step_link"]
    others = ["step_java25", "step_freerouting2", "step_chip"]
    body = "\n".join(f'{s}() {{ log "ran {s}"; }}' for s in steps + others) + "\nmain"
    env = folder(tmp_path, {"python3": "exit 5"})
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


# The paths the script may name in its code: the 6 defaults on their own lines, and 2 it only reads.
DEFAULT_LINES = [
    'WC_ROOT="${WORKCENTER_ROOT:-/opt/workcenters/${WC_NAME}}"',
    'KICAD_KEYRING="${KICAD_KEYRING:-/etc/apt/keyrings/kicad-10.0-releases.gpg}"',
    'KICAD_SOURCES="${KICAD_SOURCES:-/etc/apt/sources.list.d/kicad-10.0-releases.sources}"',
    'WORKCENTER_LINK="${WORKCENTER_LINK:-/usr/local/bin/workcenter}"',
    'OS_RELEASE="${OS_RELEASE:-/etc/os-release}"',
    'JVM_DIR="${JVM_DIR:-/usr/lib/jvm}"',
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


def test_no_literal_path_outside_the_folder_is_in_the_scripts_code():
    """The paths a lost guard would reach are read from the environment, each with its real default on
    its own line; any other absolute path in the code is /dev/null or /var/lib/dpkg/status."""
    text = INSTALL.read_text(encoding="utf-8")
    lines = text.splitlines()
    for line in DEFAULT_LINES:
        assert lines.count(line) == 1, line
    assert literal_paths(text) == []


def assigned(name: str, env: bool = True) -> int:
    pattern = rf'^{name}="\${{{name}:-(\d+)}}"$' if env else rf'^{name}="(\d+)"$'
    (value,) = re.findall(pattern, INSTALL.read_text(encoding="utf-8"), re.M)
    return int(value)


def test_a_persons_computer_has_no_total_bound_by_default():
    """APT_UPDATE_TIMEOUT and APT_DOWNLOAD_TIMEOUT default to empty: no bound unless set."""
    text = INSTALL.read_text(encoding="utf-8")
    for name in ("APT_UPDATE_TIMEOUT", "APT_DOWNLOAD_TIMEOUT"):
        assert re.findall(rf'^{name}="\$\{{{name}:-(.*)\}}"$', text, re.M) == [""], name


def ci_bounds() -> tuple[dict, int]:
    """The bounds CI's install step sets, and the `full` job's limit in s, both read from ci.yml."""
    yaml = pytest.importorskip("yaml")
    full = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["full"]
    (install,) = [s["run"] for s in full["steps"] if "./install.sh" in s.get("run", "")]
    bounds = dict(re.findall(r"\b(APT_(?:UPDATE|DOWNLOAD)_TIMEOUT)=(\S+)", install))
    return bounds, int(full["timeout-minutes"]) * 60


def test_the_worst_case_of_the_apt_step_fits_the_jobs_limit():
    """The 2 bounds CI sets and the `full` job's limit are read from .github/workflows/ci.yml, so a change
    of either without the other fails here. The newest passing run of 2026-11-18 (job 134941364976; log
    lines 2, 169, 352, 710, 823, 843 and 933) used 9 s before install.sh (16:10:05.85 to 16:10:14.58),
    27 s to unpack and set up (16:12:18.72 to 16:12:45.28), 28 s for the steps after apt (to 16:13:13.37)
    and 670 s for `make verify` (16:13:13.86 to 16:24:23.84): of the job's 1800 s (timeout-minutes: 30),
    1800 - 9 - 27 - 28 - 670 = 1066 s are left for the updates, the waits and the download.
    3 x 120 + 2 x 20 + 600 = 1000 s."""
    bounds, limit = ci_bounds()
    assert bounds == CI
    tries, wait = assigned("KICAD_INDEX_TRIES"), assigned("KICAD_INDEX_WAIT")
    update, download = int(bounds["APT_UPDATE_TIMEOUT"]), int(bounds["APT_DOWNLOAD_TIMEOUT"])
    assert tries * update + (tries - 1) * wait + download <= limit - 9 - 27 - 28 - 670


def test_one_silent_file_fits_the_download_bound():
    """apt gives a silent server APT_FILE_TIMEOUT s, APT_FILE_RETRIES + 1 times: that must end within
    the download's bound CI sets, so that apt names the file (Err:) before the bound cuts it."""
    retries, timeout = assigned("APT_FILE_RETRIES", env=False), assigned("APT_FILE_TIMEOUT", env=False)
    assert (retries + 1) * timeout < int(ci_bounds()[0]["APT_DOWNLOAD_TIMEOUT"])


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
