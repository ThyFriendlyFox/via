"""CI's install path keeps more than 1 host for Ubuntu's archive, asks the fastest first, and gives up a
silent one (tools/ci/apt_archive.sh).

Run 44402154007 (2026-11-18) and run 44432768560 (2026-11-19) of CI's `full` job took the install path,
and apt's download from us-east-2.ec2.archive.ubuntu.com crawled to the bound of 570 s. The image builds
of the same hours asked archive.ubuntu.com and downloaded 377 files in 41 s. So the step turned the
regional mirror into archive.ubuntu.com. Then run 44477966021 (2026-11-19, 07:14 UTC, on Azure) turned
azure.archive.ubuntu.com into archive.ubuntu.com, and `apt-get update` did not end within 120 s in 3
tries: that day each of the 2 hosts was the slow one once. Now the mirror list keeps both, a probe of a
few seconds ranks them by bytes a second, and a CI-only apt configuration gives up a silent host so that
apt's mirror method asks the next.

Each stand-in folder below is a layout GitHub's ubuntu-24.04 runner images are shown to hold, from the
actions/runner-images repository read at commit fbb26cb (2026-11-18):
- images/ubuntu/scripts/build/configure-apt-sources.sh since f2f9183 (2026-11-17): on Ubuntu 24.04,
  /etc/apt/sources.list.d/ubuntu.sources names `mirror+file:/etc/apt/apt-mirrors.txt`, and the list's
  first line is the cloud's mirror (azure.archive.ubuntu.com, or us-east-2.ec2.archive.ubuntu.com on
  AWS) at priority 1, then https://archive.ubuntu.com/ubuntu/ at 2, https://security.ubuntu.com/ubuntu/
  at 3.
- the same script at 9b75b60 (2026-11-11), the one before AWS was named: it writes the Azure line
  whatever the cloud, and its sed knows only azure.archive, archive and security, so an EC2 host that
  cloud-init wrote stays in ubuntu.sources itself.
- images/ubuntu/scripts/build/configure-apt.sh and scripts/tests/Apt.Tests.ps1 at fbb26cb: 24.04 on
  arm64 is served by ports.ubuntu.com/ubuntu-ports, named in ubuntu.sources, with no mirror list.
The regional forms of each host are cloud-init's (canonical/cloud-init config/cloud.cfg.tmpl at
40336875, `package_mirrors`): `%(ec2_region)s.ec2.archive.ubuntu.com`, `%(region)s.clouds.archive...`,
and the same under ports.ubuntu.com/ubuntu-ports.

How apt uses the list (apt-transport-mirror(1) of noble's apt 2.8.4, "Fallback order for mirrors"): the
lowest `priority` is asked first, and when a file fails on 1 mirror the next is asked. apt 2.8.3's
apt-pkg/acquire-worker.cc (HandleFailure) first spends Acquire::Retries on the same mirror, then takes
the next; methods/basehttp.cc sets the http timeout to 30 s unless Acquire::http::Timeout says otherwise.

No test asks a real host. Every run puts 2 stand-ins first on PATH: the probe (APT_ARCHIVE_PROBE) answers
from a table the test writes, and `curl` records its arguments and answers nothing; a run that reached
the stand-in curl when it was given the stand-in probe fails. The script never needs /etc in a test:
each test gives it a folder of its own. The 1 test that names the real /etc/apt runs the script as a
user id that cannot write there.
"""

from __future__ import annotations

import hashlib
import os
import platform
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "ci" / "apt_archive.sh"
FLOWS = ROOT / ".github" / "workflows"
PREFIX = "[apt-archive]"
OFF = "CI_APT_UBUNTU_ARCHIVE"
CALL = "sudo env APT_ARCHIVE_CI=1 bash tools/ci/apt_archive.sh /etc/apt"

KEY = "Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg"
PARTS = "Components: main universe restricted multiverse"

# The architecture the script reads from `uname -m`, as apt names it.
ARCH = {"x86_64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine(), "")
PACKAGES = f"dists/noble/main/binary-{ARCH}/Packages.gz"
CONF = "apt.conf.d/80apt-archive-ci"
CONF_TEXT = (
    "// Written by tools/ci/apt_archive.sh, on CI's install path only (APT_ARCHIVE_CI=1).\n"
    "// A file whose host sends nothing for 15 s gets 0 more tries there; apt's mirror method\n"
    "// asks the next host of the mirror list for it. apt's own defaults are 30 s and 3 more tries.\n"
    "// It holds for every source: a source of 1 host gets 1 try.\n"
    'Acquire::http::Timeout "15";\n'
    'Acquire::https::Timeout "15";\n'
    'Acquire::Retries "0";\n'
)


def deb822(main: str, security: str) -> str:
    """ubuntu.sources as cloud-init's templates/sources.list.ubuntu.deb822.tmpl writes it for noble."""
    return (
        "## Ubuntu distribution repository\n#\n# See sources.list(5) for more details.\n\n"
        f"Types: deb\nURIs: {main}\nSuites: noble noble-updates noble-backports\n{PARTS}\n{KEY}\n\n"
        f"Types: deb\nURIs: {security}\nSuites: noble-security\n{PARTS}\n{KEY}\n"
    )


LIST = "mirror+file:/etc/apt/apt-mirrors.txt"


def mirrors(first: str, archive: int = 2, security: int = 3, own: int = 1) -> str:
    """apt-mirrors.txt as configure-apt-sources.sh (f2f9183) writes it: tab, then the priority."""
    return (
        f"{first}\tpriority:{own}\n"
        f"https://archive.ubuntu.com/ubuntu/\tpriority:{archive}\n"
        f"https://security.ubuntu.com/ubuntu/\tpriority:{security}\n"
    )


EC2 = "http://us-east-2.ec2.archive.ubuntu.com/ubuntu/"
AZURE = "http://azure.archive.ubuntu.com/ubuntu/"
ARCHIVE = "https://archive.ubuntu.com/ubuntu/"
SECURITY = "https://security.ubuntu.com/ubuntu/"
PPA_LIST = "deb https://ppa.launchpadcontent.net/kicad/kicad-10.0-releases/ubuntu noble main\n"
KICAD_SOURCES = (
    "Types: deb\nURIs: https://ppa.launchpadcontent.net/kicad/kicad-10.0-releases/ubuntu\n"
    "Suites: noble\nComponents: main\nSigned-By: /etc/apt/keyrings/kicad-10.0-releases.gpg\n"
)
DOCKER = (
    "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.gpg] "
    "https://download.docker.com/linux/ubuntu noble stable\n"
)

FAST = "206 1048576 0.500000"
SLOW = "206 300000 5.000000"


def layout(tmp_path: Path, files: dict[str, str]) -> Path:
    apt = tmp_path / "apt"
    (apt / "sources.list.d").mkdir(parents=True)
    for name, text in files.items():
        (apt / name).write_text(text, encoding="utf-8")
    return apt


def snapshot(apt: Path) -> dict[str, str]:
    return {
        p.relative_to(apt).as_posix(): p.read_text(encoding="utf-8") for p in apt.rglob("*") if p.is_file()
    }


PROBE = """#!/bin/bash
# The probe's stand-in: answers for a host from the table "measures", as curl's -w would.
here="$(dirname "$0")"
printf '%s\\n' "$1" >> "$here/calls"
host="${1#*://}"; host="${host%%/*}"; host="${host%%:*}"
m="$(awk -v h="$host" '$1 == h { sub(/^[^ ]+ /, ""); print; exit }' "$here/measures")"
if [[ -z "$m" ]]; then printf '000 0 0.000000'; exit 7; fi
if [[ "$m" == sleep\\ * ]]; then exec sleep "${m#sleep }"; fi
printf '%s' "$m"
"""

CURL = """#!/bin/bash
# curl's stand-in: records its arguments and reaches no host.
printf '%s\\n' "$*" >> "$(dirname "$0")/curl-calls"
# A test that writes curl-sleep makes it hang, as a name lookup that blocks would.
if [[ -f "$(dirname "$0")/curl-sleep" ]]; then exec sleep "$(cat "$(dirname "$0")/curl-sleep")"; fi
printf '000 0 0.000000'
exit 7
"""


def standins(tmp: Path, measures: dict[str, str]) -> Path:
    bin_ = tmp / "standin"
    bin_.mkdir(exist_ok=True)
    (bin_ / "measures").write_text("".join(f"{h} {m}\n" for h, m in measures.items()), encoding="utf-8")
    for name, text in (("probe", PROBE), ("curl", CURL)):
        (bin_ / name).write_text(text, encoding="utf-8")
        (bin_ / name).chmod(0o755)
    return bin_


def run(
    *args: str,
    tmp: Path,
    env: dict | None = None,
    measures: dict[str, str] | None = None,
    probe: bool = True,
) -> subprocess.CompletedProcess:
    bin_ = standins(tmp, measures or {})
    base = {"PATH": f"{bin_}:/usr/bin:/bin", "LC_ALL": "C", "TMPDIR": str(tmp)}
    if probe:
        base["APT_ARCHIVE_PROBE"] = str(bin_ / "probe")
    ran = subprocess.run(
        ["bash", str(SCRIPT), *args], env={**base, **(env or {})}, capture_output=True, text=True, timeout=60
    )
    if probe:
        assert not (bin_ / "curl-calls").exists(), "the run reached curl although the probe was a stand-in"
    return ran


def probed(tmp: Path) -> list[str]:
    calls = tmp / "standin" / "calls"
    return calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []


def lines(ran: subprocess.CompletedProcess) -> list[str]:
    return ran.stdout.splitlines()


def none_line(apt: Path) -> str:
    return f"{PREFIX} no regional or cloud mirror of Ubuntu's archive in {apt}; changed nothing"


def answered(uri: str, measure: str) -> str:
    _, got, secs = measure.split()
    return f"{PREFIX} probe {uri}: {got} bytes in {secs} s, {int(int(got) / float(secs))} bytes/s"


def silent(uri: str, why: str = "HTTP 000, 0 bytes") -> str:
    return f"{PREFIX} probe {uri}: no answer ({why}); it goes last"


def order(apt: Path, *uris: str) -> str:
    """The line of the order chosen. It names what the order rests on, a sample of 1 MiB: in run
    44506767788 the first host sent its MiB at 2468910 bytes/s and the download at 48.3 kB/s."""
    asks = ", then ".join(uris)
    return f"{PREFIX} {apt}/apt-mirrors.txt: apt asks {asks}: the fastest in a 1 MiB sample first"


def kept(apt: Path, *uris: str) -> str:
    return (
        f"{PREFIX} {apt}/apt-mirrors.txt: no host answered the probe; apt asks in the runner's order: "
        + ", then ".join(uris)
    )


def conf_line(apt: Path) -> str:
    return (
        f"{PREFIX} {apt}/{CONF}: a file whose host is silent for 15 s gets 0 more tries there, then apt "
        "asks the next host (Acquire::http::Timeout 15, Acquire::https::Timeout 15, Acquire::Retries 0)"
    )


def runner(tmp_path: Path, first: str) -> Path:
    """The layout of f2f9183's script: ubuntu.sources names the list, the list names 3 hosts."""
    return layout(
        tmp_path, {"sources.list.d/ubuntu.sources": deb822(LIST, LIST), "apt-mirrors.txt": mirrors(first)}
    )


# ---------------------------------------------------------------- the list keeps every host, ranked


def test_the_azure_list_keeps_every_host_and_the_fastest_goes_first(tmp_path):
    """The layout of run 44477966021, with Azure's mirror slow and security silent: the list keeps all 3
    hosts, archive.ubuntu.com goes first, the silent host last."""
    apt = runner(tmp_path, AZURE)
    before = snapshot(apt)
    measures = {"azure.archive.ubuntu.com": SLOW, "archive.ubuntu.com": FAST}
    ran = run(str(apt), tmp=tmp_path, measures=measures)
    assert ran.returncode == 0, ran.stderr
    assert lines(ran) == [
        answered(AZURE, SLOW),
        answered(ARCHIVE, FAST),
        silent(SECURITY),
        order(apt, ARCHIVE, AZURE, SECURITY),
        conf_line(apt),
    ]
    after = snapshot(apt)
    assert after["apt-mirrors.txt"] == mirrors(AZURE, own=2, archive=1, security=3)
    assert after["sources.list.d/ubuntu.sources"] == before["sources.list.d/ubuntu.sources"]
    assert after[CONF] == CONF_TEXT
    assert sorted(probed(tmp_path)) == sorted(u + PACKAGES for u in (AZURE, ARCHIVE, SECURITY))


def test_the_ec2_list_keeps_its_order_when_the_ec2_host_is_fastest(tmp_path):
    """The layout of runs 44402154007 and 44432768560 on a day the regional mirror is fast: its list stays
    as the runner wrote it, and the step says why."""
    apt = runner(tmp_path, EC2)
    measures = {
        "us-east-2.ec2.archive.ubuntu.com": FAST,
        "archive.ubuntu.com": SLOW,
        "security.ubuntu.com": SLOW,
    }
    ran = run(str(apt), tmp=tmp_path, measures=measures)
    assert ran.returncode == 0, ran.stderr
    assert lines(ran) == [
        answered(EC2, FAST),
        answered(ARCHIVE, SLOW),
        answered(SECURITY, SLOW),
        order(apt, EC2, ARCHIVE, SECURITY),
        conf_line(apt),
    ]
    assert snapshot(apt)["apt-mirrors.txt"] == mirrors(EC2)


def test_a_host_that_does_not_answer_goes_last_and_stays_in_the_list(tmp_path):
    apt = runner(tmp_path, EC2)
    measures = {"us-east-2.ec2.archive.ubuntu.com": "503 0 0.100000", "archive.ubuntu.com": SLOW}
    measures["security.ubuntu.com"] = FAST
    ran = run(str(apt), tmp=tmp_path, measures=measures)
    assert ran.returncode == 0, ran.stderr
    assert lines(ran) == [
        silent(EC2, "HTTP 503, 0 bytes"),
        answered(ARCHIVE, SLOW),
        answered(SECURITY, FAST),
        order(apt, SECURITY, ARCHIVE, EC2),
        conf_line(apt),
    ]
    assert snapshot(apt)["apt-mirrors.txt"] == mirrors(EC2, own=3, archive=2, security=1)


def test_no_answer_at_all_keeps_the_runners_order_and_says_so(tmp_path):
    apt = runner(tmp_path, AZURE)
    ran = run(str(apt), tmp=tmp_path)
    assert ran.returncode == 0, ran.stderr
    assert lines(ran) == [
        silent(AZURE),
        silent(ARCHIVE),
        silent(SECURITY),
        kept(apt, AZURE, ARCHIVE, SECURITY),
        conf_line(apt),
    ]
    assert snapshot(apt)["apt-mirrors.txt"] == mirrors(AZURE)


@pytest.mark.parametrize(
    "lst, said",
    [
        (
            f"{AZURE}\tpriority:1\n{ARCHIVE}\tpriority:1\n{SECURITY}\tpriority:3\n",
            f"by the runner's priorities: {AZURE} and {ARCHIVE} in random order, then {SECURITY}",
        ),
        (f"{AZURE}\n{ARCHIVE}\n", f"by the runner's priorities: {AZURE} and {ARCHIVE} in random order"),
        (
            f"{AZURE}\tpriority:1\n{ARCHIVE}\n{SECURITY}\n",
            f"by the runner's priorities: {AZURE}, then {ARCHIVE} and {SECURITY} in random order",
        ),
        (
            f"{AZURE}\tpriority:5\n{ARCHIVE}\tpriority:5\n{SECURITY}\tpriority:5\n",
            f"by the runner's priorities: {AZURE}, {ARCHIVE} and {SECURITY} in random order",
        ),
        (
            f"{AZURE}\tpriority:30\n{ARCHIVE}\tpriority:10\n{SECURITY}\tpriority:20\n",
            f"in the runner's order: {ARCHIVE}, then {SECURITY}, then {AZURE}",
        ),
    ],
    ids=["2 tie", "none", "1 then none", "all tie", "10 20 30"],
)
def test_no_answer_names_no_order_apt_takes_at_random_and_keeps_the_list(tmp_path, lst, said):
    """apt-transport-mirror(1), "Fallback order for mirrors": hosts of 1 priority, or of none, are asked
    in random order (apt 2.8.3's methods/mirror.cc sorts by priority, then by a random seed). With no
    answer the list stays byte for byte, priorities other than 1 to n included."""
    apt = layout(tmp_path, {"sources.list.d/ubuntu.sources": deb822(LIST, LIST), "apt-mirrors.txt": lst})
    ran = run(str(apt), tmp=tmp_path)
    assert ran.returncode == 0, ran.stderr
    assert lines(ran)[-2:] == [
        f"{PREFIX} {apt}/apt-mirrors.txt: no host answered the probe; apt asks {said}",
        conf_line(apt),
    ]
    assert (apt / "apt-mirrors.txt").read_bytes() == lst.encode()


def assigned(name: str) -> int:
    """A constant the script assigns once, as `NAME=<digits>`."""
    (value,) = re.findall(rf"^{name}=([0-9]+)$", SCRIPT.read_text(encoding="utf-8"), re.M)
    return int(value)


def test_the_probe_fits_the_margin_the_jobs_limit_leaves():
    """tests/test_install_apt.py (test_the_worst_case_of_the_apt_step_fits_the_jobs_limit) counts the
    worst case of install.sh's apt step at 1058 s of the 1066 s the `full` job's newest passing run left
    (job 134941364976): 8 s are left for this step. Its probe ends at PROBE_BOUND s, `timeout` kills it
    1 s later, and the rest of the step needs well under 1 s (on this machine 4.63 s in all with a probe
    of 4.51 s, 2026-11-19): at most PROBE_BOUND + 2 s of the 8."""
    assert assigned("PROBE_SECONDS") < assigned("PROBE_BOUND")
    assert assigned("PROBE_BOUND") + 2 <= 1066 - 1058


def update_bound() -> int:
    """APT_UPDATE_TIMEOUT as CI's install step sets it: the bound of 1 try of install.sh's update."""
    (value,) = set(re.findall(r"APT_UPDATE_TIMEOUT=([0-9]+)", (FLOWS / "ci.yml").read_text(encoding="utf-8")))
    return int(value)


def test_a_silent_first_host_costs_at_most_the_updates_bound():
    """apt fetches the files of 1 host one after another: 1 queue per scheme and host, 1 worker per
    queue (apt 2.8.3's apt-pkg/acquire.cc, QueueName and Queue::Startup). The runner's ubuntu.sources
    sends 4 suites through the list (deb822 above), so `apt-get update` puts 4 InRelease files on the
    first host. A host that accepts the connection and then sends nothing costs 2 timeouts per try
    (methods/basehttp.cc, RUN_HEADERS_IO_ERROR: the item fails at the 2nd). A retry first waits 1, 2,
    4 s (apt-pkg/acquire-worker.cc, HandleFailure). With apt's defaults (30 s, 3 retries) that is
    4 x (4 x 60 + 7) = 988 s, and with 15 s and 1 retry 4 x (2 x 30 + 1) = 244 s. CI bounds 1 try of
    the update at 120 s. This is an upper bound: a retry's wait can overlap another file's fetch."""
    timeout, retries = assigned("TIMEOUT"), assigned("RETRIES")
    files = sum(len(s.split()) for s in re.findall(r"^Suites: (.*)$", deb822(LIST, LIST), re.M))
    assert files == 4
    per_file = (retries + 1) * 2 * timeout + sum(2**k for k in range(retries))
    assert files * per_file <= update_bound(), (files, per_file, update_bound())


def test_a_probe_past_its_bound_is_no_answer_and_the_step_ends_within_the_bound(tmp_path):
    """Each probe has 3 s (curl's --max-time) and is ended at 4 s; the probes run side by side, so the
    step's probe takes at most 5 s whatever the hosts do."""
    apt = runner(tmp_path, AZURE)
    measures = {
        "azure.archive.ubuntu.com": FAST,
        "archive.ubuntu.com": "sleep 30",
        "security.ubuntu.com": "sleep 30",
    }
    began = time.monotonic()
    ran = run(str(apt), tmp=tmp_path, measures=measures)
    took = time.monotonic() - began
    assert ran.returncode == 0, ran.stderr
    assert took < 8, took
    assert lines(ran) == [
        answered(AZURE, FAST),
        silent(ARCHIVE, "nothing within 4 s"),
        silent(SECURITY, "nothing within 4 s"),
        order(apt, AZURE, ARCHIVE, SECURITY),
        conf_line(apt),
    ]


def test_an_answer_the_probe_cannot_read_is_no_answer(tmp_path):
    apt = runner(tmp_path, AZURE)
    measures = {"azure.archive.ubuntu.com": "garbage", "archive.ubuntu.com": "206 0 1.000000"}
    measures["security.ubuntu.com"] = FAST
    ran = run(str(apt), tmp=tmp_path, measures=measures)
    assert ran.returncode == 0, ran.stderr
    assert lines(ran)[:3] == [
        silent(AZURE, "unreadable: garbage"),
        silent(ARCHIVE, "HTTP 206, 0 bytes"),
        answered(SECURITY, FAST),
    ]
    assert lines(ran)[3] == order(apt, SECURITY, AZURE, ARCHIVE)


def test_the_default_probe_asks_curl_for_the_first_mebibyte_within_3_s(tmp_path):
    """With no stand-in probe the script runs curl: here the stand-in curl, which reaches no host."""
    apt = runner(tmp_path, AZURE)
    ran = run(str(apt), tmp=tmp_path, probe=False)
    assert ran.returncode == 0, ran.stderr
    calls = (tmp_path / "standin" / "curl-calls").read_text(encoding="utf-8").splitlines()
    expect = "-sS -o /dev/null -r 0-1048575 --connect-timeout 3 --max-time 3 "
    expect += "-w %{http_code} %{size_download} %{time_total} -- "
    assert sorted(calls) == sorted(expect + u + PACKAGES for u in (AZURE, ARCHIVE, SECURITY))
    assert lines(ran)[3] == kept(apt, AZURE, ARCHIVE, SECURITY)


def test_a_curl_that_hangs_is_ended_at_the_bound(tmp_path):
    """curl's own --max-time does not bound everything: a name lookup that blocks is bounded only by
    `timeout`. A stand-in curl that sleeps 30 s is ended at 4 s and killed 1 s later."""
    apt = runner(tmp_path, AZURE)
    (tmp_path / "standin").mkdir()
    (tmp_path / "standin" / "curl-sleep").write_text("30\n", encoding="utf-8")
    began = time.monotonic()
    ran = run(str(apt), tmp=tmp_path, probe=False)
    took = time.monotonic() - began
    assert ran.returncode == 0, ran.stderr
    assert took < 8, took
    assert lines(ran)[:3] == [silent(u, "nothing within 4 s") for u in (AZURE, ARCHIVE, SECURITY)]


def test_the_probe_file_follows_the_suite_and_the_ports_host(tmp_path):
    """The suite is the first one with no `-` of a source that names the list; the path is the host's."""
    ports = "http://ports.ubuntu.com/ubuntu-ports/"
    regional = "http://us-east-2.ec2.ports.ubuntu.com/ubuntu-ports/"
    text = deb822(LIST, LIST).replace("noble noble-updates", "noble-updates jammy noble")
    lst = f"{regional}\tpriority:1\n{ports}\tpriority:2\n"
    apt = layout(tmp_path, {"sources.list.d/ubuntu.sources": text, "apt-mirrors.txt": lst})
    ran = run(str(apt), tmp=tmp_path)
    assert ran.returncode == 0, ran.stderr
    path = f"dists/jammy/main/binary-{ARCH}/Packages.gz"
    assert sorted(probed(tmp_path)) == sorted([regional + path, ports + path])


def test_the_apt_configuration_is_written_only_where_a_list_is_used(tmp_path):
    apt = runner(tmp_path, AZURE)
    (apt / "apt.conf.d").mkdir()
    (apt / "apt.conf.d" / CONF.split("/")[1]).write_text("old\n", encoding="utf-8")
    assert run(str(apt), tmp=tmp_path).returncode == 0
    assert snapshot(apt)[CONF] == CONF_TEXT
    plain = tmp_path / "plain"
    plain.mkdir()
    apt = layout(plain, {"sources.list.d/ubuntu.sources": deb822(ARCHIVE, SECURITY)})
    ran = run(str(apt), tmp=tmp_path)
    assert lines(ran) == [none_line(apt)]
    assert not (apt / "apt.conf.d").exists()


# ---------------------------------------------------------------- a host named in a source file


def test_the_ec2_host_left_in_ubuntu_sources_goes_into_the_list(tmp_path):
    """9b75b60's script on AWS: the EC2 host stays in the deb822 file, security goes through the list,
    whose first line is Azure's. The source now names the list too, and the list gains the EC2 host,
    after the hosts it had."""
    apt = layout(
        tmp_path, {"sources.list.d/ubuntu.sources": deb822(EC2, LIST), "apt-mirrors.txt": mirrors(AZURE)}
    )
    ran = run(str(apt), tmp=tmp_path)
    assert ran.returncode == 0, ran.stderr
    assert lines(ran) == [
        f"{PREFIX} {apt}/sources.list.d/ubuntu.sources: us-east-2.ec2.archive.ubuntu.com -> {LIST}",
        f"{PREFIX} {apt}/apt-mirrors.txt: added {EC2}",
        silent(AZURE),
        silent(ARCHIVE),
        silent(SECURITY),
        silent(EC2),
        kept(apt, AZURE, ARCHIVE, SECURITY, EC2),
        conf_line(apt),
    ]
    after = snapshot(apt)
    assert after["sources.list.d/ubuntu.sources"] == deb822(LIST, LIST)
    assert after["apt-mirrors.txt"] == mirrors(AZURE) + f"{EC2}\tpriority:4\n"


def test_a_country_mirror_in_a_one_line_file_gets_ubuntus_own_archive_beside_it(tmp_path):
    """No mirror list: the script writes 1 with the mirror first and Ubuntu's own archive second, and
    the mirror's lines name it. security.ubuntu.com, named by itself, stays."""
    text = "deb http://us.archive.ubuntu.com/ubuntu/ noble main restricted\n"
    text += "deb-src http://us.archive.ubuntu.com/ubuntu/ noble main restricted\n"
    text += "deb http://security.ubuntu.com/ubuntu noble-security main\n"
    apt = layout(tmp_path, {"sources.list": text})
    measures = {"archive.ubuntu.com": FAST, "us.archive.ubuntu.com": SLOW}
    ran = run(str(apt), tmp=tmp_path, measures=measures)
    assert ran.returncode == 0, ran.stderr
    own = "http://archive.ubuntu.com/ubuntu/"
    assert lines(ran) == [
        f"{PREFIX} {apt}/sources.list: us.archive.ubuntu.com -> {LIST}",
        f"{PREFIX} {apt}/apt-mirrors.txt: added http://us.archive.ubuntu.com/ubuntu/, {own}",
        answered("http://us.archive.ubuntu.com/ubuntu/", SLOW),
        answered(own, FAST),
        order(apt, own, "http://us.archive.ubuntu.com/ubuntu/"),
        conf_line(apt),
    ]
    after = snapshot(apt)
    assert after["sources.list"] == text.replace("http://us.archive.ubuntu.com/ubuntu/", LIST)
    assert (
        after["apt-mirrors.txt"] == f"http://us.archive.ubuntu.com/ubuntu/\tpriority:2\n{own}\tpriority:1\n"
    )


def test_a_clouds_host_and_https_keep_their_scheme_and_path_in_the_list(tmp_path):
    text = "deb https://us-east-2.ec2.archive.ubuntu.com/ubuntu noble main\n"
    text += "deb https://us-west-2.clouds.archive.ubuntu.com/ubuntu/ noble-updates main\n"
    apt = layout(tmp_path, {"sources.list.d/cloud.list": text})
    ran = run(str(apt), tmp=tmp_path)
    assert ran.returncode == 0, ran.stderr
    assert lines(ran)[:2] == [
        f"{PREFIX} {apt}/sources.list.d/cloud.list: us-east-2.ec2.archive.ubuntu.com, "
        f"us-west-2.clouds.archive.ubuntu.com -> {LIST}",
        f"{PREFIX} {apt}/apt-mirrors.txt: added https://us-east-2.ec2.archive.ubuntu.com/ubuntu/, "
        "https://us-west-2.clouds.archive.ubuntu.com/ubuntu/, https://archive.ubuntu.com/ubuntu/",
    ]
    after = snapshot(apt)
    assert after["sources.list.d/cloud.list"] == f"deb {LIST} noble main\ndeb {LIST} noble-updates main\n"
    assert after["apt-mirrors.txt"] == (
        "https://us-east-2.ec2.archive.ubuntu.com/ubuntu/\tpriority:1\n"
        "https://us-west-2.clouds.archive.ubuntu.com/ubuntu/\tpriority:2\n"
        "https://archive.ubuntu.com/ubuntu/\tpriority:3\n"
    )


def test_the_line_names_only_the_hosts_it_changed(tmp_path):
    """A host that only begins like a mirror (x.archive.ubuntu.com.cn) stays, and the line does not
    name it. A host with a port is named and changed, and keeps its port in the list; Ubuntu's own
    archive is added once."""
    text = "deb http://my.archive.ubuntu.com.cn/ubuntu noble main\n"
    text += "deb http://de.archive.ubuntu.com/ubuntu noble main\n"
    text += "# deb http://nl.archive.ubuntu.com/ubuntu noble main\n"
    text += "deb http://fr.archive.ubuntu.com:80/ubuntu noble main\n"
    apt = layout(tmp_path, {"sources.list.d/mixed.list": text})
    ran = run(str(apt), tmp=tmp_path)
    assert ran.returncode == 0, ran.stderr
    assert lines(ran)[:2] == [
        f"{PREFIX} {apt}/sources.list.d/mixed.list: de.archive.ubuntu.com, fr.archive.ubuntu.com -> {LIST}",
        f"{PREFIX} {apt}/apt-mirrors.txt: added http://de.archive.ubuntu.com/ubuntu/, "
        "http://fr.archive.ubuntu.com:80/ubuntu/, http://archive.ubuntu.com/ubuntu/",
    ]
    assert snapshot(apt)["sources.list.d/mixed.list"] == (
        "deb http://my.archive.ubuntu.com.cn/ubuntu noble main\n"
        f"deb {LIST} noble main\n"
        "# deb http://nl.archive.ubuntu.com/ubuntu noble main\n"
        f"deb {LIST} noble main\n"
    )


@pytest.mark.parametrize(
    "files",
    [
        {
            "sources.list": "deb http://de.archive.ubuntu.com/ubuntu noble main\nURIs: http://nl.archive.ubuntu.com\n"
        },
        {
            "sources.list.d/ubuntu.sources": deb822(
                "http://us-east-2.ec2.ports.ubuntu.com/ubuntu-ports/", LIST
            ),
            "apt-mirrors.txt": mirrors(EC2),
        },
    ],
    ids=["2 direct hosts", "a direct host and the list"],
)
def test_hosts_of_different_paths_are_a_layout_it_does_not_know(tmp_path, files):
    """1 list serves 1 path of the archive: hosts of /ubuntu/ and of / or /ubuntu-ports/ cannot share it."""
    apt = layout(tmp_path, files)
    before = snapshot(apt)
    ran = run(str(apt), tmp=tmp_path)
    assert ran.returncode == 0, ran.stderr
    (line,) = lines(ran)
    assert line.startswith(f"{PREFIX} the hosts of Ubuntu's archive in {apt} name different paths (")
    assert line.endswith("): a layout this script does not know; changed nothing")
    assert snapshot(apt) == before
    assert probed(tmp_path) == []


def test_ubuntus_own_archive_already_changes_nothing(tmp_path):
    """This machine's layout (Ubuntu 24.04's own ubuntu.sources), beside a mirror list no source names."""
    apt = layout(
        tmp_path,
        {
            "sources.list.d/ubuntu.sources": deb822(
                "http://archive.ubuntu.com/ubuntu/", "http://security.ubuntu.com/ubuntu/"
            ),
            "apt-mirrors.txt": mirrors("http://archive.ubuntu.com/ubuntu/"),
        },
    )
    before = snapshot(apt)
    ran = run(str(apt), tmp=tmp_path)
    assert ran.returncode == 0, ran.stderr
    assert lines(ran) == [none_line(apt)]
    assert snapshot(apt) == before
    assert probed(tmp_path) == []


def test_an_arm_machines_ports_host_stays_and_its_regional_form_gets_it_beside(tmp_path):
    ports = "http://ports.ubuntu.com/ubuntu-ports/"
    apt = layout(tmp_path, {"sources.list.d/ubuntu.sources": deb822(ports, ports)})
    ran = run(str(apt), tmp=tmp_path)
    assert ran.returncode == 0 and lines(ran) == [none_line(apt)], ran.stdout + ran.stderr
    regional = tmp_path / "regional"
    regional.mkdir()
    ec2 = "http://us-east-2.ec2.ports.ubuntu.com/ubuntu-ports/"
    apt = layout(regional, {"sources.list.d/ubuntu.sources": deb822(ec2, ports)})
    ran = run(str(apt), tmp=tmp_path, measures={"ports.ubuntu.com": FAST})
    assert ran.returncode == 0, ran.stderr
    assert lines(ran) == [
        f"{PREFIX} {apt}/sources.list.d/ubuntu.sources: us-east-2.ec2.ports.ubuntu.com -> {LIST}",
        f"{PREFIX} {apt}/apt-mirrors.txt: added {ec2}, {ports}",
        silent(ec2),
        answered(ports, FAST),
        order(apt, ports, ec2),
        conf_line(apt),
    ]
    after = snapshot(apt)
    assert after["sources.list.d/ubuntu.sources"] == deb822(LIST, ports)
    assert after["apt-mirrors.txt"] == f"{ec2}\tpriority:2\n{ports}\tpriority:1\n"


def test_security_a_ppa_and_a_third_party_stay_as_they_are(tmp_path):
    """Beside the list, every other source is left byte for byte, comments with a mirror's name
    included."""
    comment = "# deb http://us-east-2.ec2.archive.ubuntu.com/ubuntu/ noble main\n"
    apt = layout(
        tmp_path,
        {
            "apt-mirrors.txt": mirrors(EC2),
            "sources.list": comment + "deb http://security.ubuntu.com/ubuntu/ noble-security main\n",
            "sources.list.d/kicad.list": PPA_LIST,
            "sources.list.d/kicad-10.0-releases.sources": KICAD_SOURCES,
            "sources.list.d/docker.list": DOCKER,
            "sources.list.d/ubuntu.sources": deb822(LIST, LIST),
        },
    )
    before = snapshot(apt)
    ran = run(str(apt), tmp=tmp_path, measures={"archive.ubuntu.com": FAST})
    assert ran.returncode == 0, ran.stderr
    assert lines(ran)[-2:] == [order(apt, ARCHIVE, EC2, SECURITY), conf_line(apt)]
    after = snapshot(apt)
    assert {k for k in after if before.get(k) != after[k]} == {"apt-mirrors.txt", CONF}
    assert not any("ppa." in u or "docker" in u for u in probed(tmp_path))


def test_a_second_run_with_the_same_measures_changes_nothing(tmp_path):
    apt = layout(
        tmp_path, {"sources.list.d/ubuntu.sources": deb822(EC2, LIST), "apt-mirrors.txt": mirrors(EC2)}
    )
    measures = {"archive.ubuntu.com": FAST, "security.ubuntu.com": SLOW}
    first = run(str(apt), tmp=tmp_path, measures=measures)
    assert first.returncode == 0, first.stdout + first.stderr
    once = snapshot(apt)
    assert once["apt-mirrors.txt"] == mirrors(EC2, own=3, archive=1, security=2)
    second = run(str(apt), tmp=tmp_path, measures=measures)
    assert second.returncode == 0, second.stderr
    assert snapshot(apt) == once
    assert lines(second)[-2:] == [order(apt, ARCHIVE, SECURITY, EC2), conf_line(apt)]


def test_a_folder_with_no_source_file_says_so_and_makes_none(tmp_path):
    apt = layout(tmp_path, {})
    ran = run(str(apt), tmp=tmp_path)
    assert ran.returncode == 0, ran.stderr
    assert lines(ran) == [
        f"{PREFIX} no apt source file in {apt}: a layout this script does not know; changed nothing"
    ]
    assert snapshot(apt) == {}


@pytest.mark.parametrize(
    "uri",
    [
        "mirror+file:/etc/apt/other-mirrors.txt",
        "mirror://mirrors.ubuntu.com/mirrors.txt",
        "mirror+https://x.example/m",
    ],
)
def test_a_mirror_list_it_does_not_know_says_so_and_changes_nothing(tmp_path, uri):
    """A layout no runner image is shown to hold: nothing changes, not even the file it knows."""
    apt = layout(
        tmp_path,
        {"sources.list.d/ubuntu.sources": deb822(EC2, uri), "apt-mirrors.txt": mirrors(EC2)},
    )
    before = snapshot(apt)
    ran = run(str(apt), tmp=tmp_path)
    assert ran.returncode == 0, ran.stderr
    assert lines(ran) == [
        f"{PREFIX} {apt}/sources.list.d/ubuntu.sources names {uri}, a mirror list this script does not know; "
        "changed nothing"
    ]
    assert snapshot(apt) == before
    assert probed(tmp_path) == []


@pytest.mark.parametrize("tail", [" priority:1", " priority:1\tarch:amd64", "  "])
def test_a_list_line_with_a_blank_before_its_first_tab_changes_nothing(tmp_path, tail):
    """apt's mirror method ends the URI at the first tab (apt 2.8.3's methods/mirror.cc, the list's
    reading: `line.find('\\t')`, else the whole line is the URI). A line `<uri> priority:1` is then 1
    URI with no priority, asked last; the step must not name it first. No runner image is shown to
    write such a line: the step calls it a layout it does not know."""
    lst = f"{AZURE}{tail}\n{ARCHIVE}\tpriority:2\n"
    apt = layout(tmp_path, {"sources.list.d/ubuntu.sources": deb822(LIST, LIST), "apt-mirrors.txt": lst})
    before = snapshot(apt)
    ran = run(str(apt), tmp=tmp_path, measures={"azure.archive.ubuntu.com": FAST})
    assert ran.returncode == 0, ran.stderr
    uri = AZURE + tail.split("\t")[0]
    assert lines(ran) == [
        f"{PREFIX} {apt}/apt-mirrors.txt: a line has a blank before its first tab ({uri}),"
        " and apt reads all of that as the URI: a layout this script does not know; changed nothing"
    ]
    assert snapshot(apt) == before
    assert probed(tmp_path) == []


def test_the_known_mirror_list_named_but_absent_changes_nothing(tmp_path):
    apt = layout(tmp_path, {"sources.list.d/ubuntu.sources": deb822(EC2, LIST)})
    before = snapshot(apt)
    ran = run(str(apt), tmp=tmp_path)
    assert ran.returncode == 0, ran.stderr
    assert lines(ran) == [
        f"{PREFIX} {apt}/sources.list.d/ubuntu.sources names {LIST}, and {apt}/apt-mirrors.txt is absent: "
        "a layout this script does not know; changed nothing"
    ]
    assert snapshot(apt) == before


def test_the_folder_comes_from_apt_dir_and_a_missing_folder_stops(tmp_path):
    apt = runner(tmp_path, AZURE)
    ran = run(env={"APT_DIR": str(apt)}, tmp=tmp_path, measures={"archive.ubuntu.com": FAST})
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert lines(ran)[-2:] == [order(apt, ARCHIVE, AZURE, SECURITY), conf_line(apt)]
    ran = run(str(tmp_path / "nope"), tmp=tmp_path)
    assert ran.returncode == 2 and ran.stdout == ""
    assert ran.stderr.strip() == f"{PREFIX} no folder {tmp_path / 'nope'}; changed nothing"


def test_a_changed_file_keeps_its_mode(tmp_path):
    apt = runner(tmp_path, EC2)
    (apt / "apt-mirrors.txt").chmod(0o644)
    assert run(str(apt), tmp=tmp_path, measures={"archive.ubuntu.com": FAST}).returncode == 0
    assert snapshot(apt)["apt-mirrors.txt"] == mirrors(EC2, own=2, archive=1, security=3)
    assert (apt / "apt-mirrors.txt").stat().st_mode & 0o777 == 0o644
    assert (apt / CONF).stat().st_mode & 0o777 == 0o644


# ---------------------------------------------------------------- after a slow download pass
# install.sh's watch ends a download pass too slow to finish and runs APT_SLOW_PASS_COMMAND with the
# hosts of that pass, the most files first. CI names `--slow` of this script: the first of them that the
# list holds goes last, so that the next pass asks another host first. install.sh runs the same command
# between 2 tries of its update, after a try its bound ended, with the hosts of the mirror list's sources
# that had not answered, in the list's order.

ECTWO = "us-east-2.ec2.archive.ubuntu.com"
PPA_HOST = "ppa.launchpadcontent.net"


def slow_line(apt: Path, host: str, *uris: str) -> str:
    return (
        f"{PREFIX} {apt}/apt-mirrors.txt: {host} was too slow (a download pass too slow to finish, or an "
        "update try its bound ended); "
        f"apt asks {', then '.join(uris)}"
    )


def test_the_host_of_a_slow_pass_goes_last_and_the_others_keep_their_order(tmp_path):
    """The list of run 44506767788 after its ranking (us-east-2.ec2 1, security 2, archive 3), and that
    run's hosts as install.sh names them (us-east-2.ec2: 45 Get lines; the PPA: 4, and no line in the
    list). us-east-2.ec2 goes last; nothing is probed and no other file changes. A second slow pass, on
    security.ubuntu.com, sends it last in turn."""
    apt = layout(
        tmp_path,
        {
            "sources.list.d/ubuntu.sources": deb822(LIST, LIST),
            "apt-mirrors.txt": mirrors(EC2, own=1, archive=3, security=2),
        },
    )
    before = snapshot(apt)
    ran = run("--slow", ECTWO, PPA_HOST, tmp=tmp_path, env={"APT_DIR": str(apt)})
    assert ran.returncode == 0, ran.stderr
    assert lines(ran) == [slow_line(apt, ECTWO, SECURITY, ARCHIVE, EC2)]
    after = snapshot(apt)
    assert after.pop("apt-mirrors.txt") == mirrors(EC2, own=3, archive=2, security=1)
    assert after == {k: v for k, v in before.items() if k != "apt-mirrors.txt"}
    assert probed(tmp_path) == []
    ran = run("--slow", "security.ubuntu.com", tmp=tmp_path, env={"APT_DIR": str(apt)})
    assert lines(ran) == [slow_line(apt, "security.ubuntu.com", ARCHIVE, EC2, SECURITY)]
    assert snapshot(apt)["apt-mirrors.txt"] == mirrors(EC2, own=2, archive=1, security=3)


def test_of_2_named_hosts_the_list_holds_the_first_named_goes_last(tmp_path):
    """install.sh names the hosts of the slow pass, the most files first: in CI e.g. us-east-2.ec2, the
    PPA and security. The list holds 2 of them; the first named, us-east-2.ec2, goes last, and security
    keeps its place."""
    apt = layout(
        tmp_path,
        {
            "sources.list.d/ubuntu.sources": deb822(LIST, LIST),
            "apt-mirrors.txt": mirrors(EC2, own=1, archive=3, security=2),
        },
    )
    ran = run("--slow", ECTWO, PPA_HOST, "security.ubuntu.com", tmp=tmp_path, env={"APT_DIR": str(apt)})
    assert ran.returncode == 0, ran.stderr
    assert lines(ran) == [slow_line(apt, ECTWO, SECURITY, ARCHIVE, EC2)]
    assert snapshot(apt)["apt-mirrors.txt"] == mirrors(EC2, own=3, archive=2, security=1)


def test_a_slow_pass_on_the_host_already_last_leaves_the_file_untouched(tmp_path):
    """A second slow pass on the host the first one sent last changes no byte, so the file is not
    written again: its time of change stays."""
    apt = layout(
        tmp_path,
        {
            "sources.list.d/ubuntu.sources": deb822(LIST, LIST),
            "apt-mirrors.txt": mirrors(EC2, own=1, archive=3, security=2),
        },
    )
    run("--slow", ECTWO, tmp=tmp_path, env={"APT_DIR": str(apt)})
    listed = apt / "apt-mirrors.txt"
    written = listed.read_text()
    os.utime(listed, (1_000_000_000, 1_000_000_000))
    ran = run("--slow", ECTWO, tmp=tmp_path, env={"APT_DIR": str(apt)})
    assert ran.returncode == 0, ran.stderr
    assert lines(ran) == [slow_line(apt, ECTWO, SECURITY, ARCHIVE, EC2)]
    assert listed.read_text() == written
    assert listed.stat().st_mtime == 1_000_000_000


def test_a_list_with_comments_keeps_them_and_a_line_without_priority_gets_one(tmp_path):
    lst = f"# the runner's\n{EC2}\tpriority:1\n{ARCHIVE}\n{SECURITY}\tpriority:2\n"
    apt = layout(tmp_path, {"sources.list.d/ubuntu.sources": deb822(LIST, LIST), "apt-mirrors.txt": lst})
    ran = run("--slow", ECTWO, tmp=tmp_path, env={"APT_DIR": str(apt)})
    assert ran.returncode == 0, ran.stderr
    assert lines(ran) == [slow_line(apt, ECTWO, SECURITY, ARCHIVE, EC2)]
    assert (apt / "apt-mirrors.txt").read_text() == (
        f"# the runner's\n{EC2}\tpriority:3\n{ARCHIVE}\tpriority:2\n{SECURITY}\tpriority:1\n"
    )


@pytest.mark.parametrize(
    ("args", "files", "said"),
    [
        (
            ["--slow", PPA_HOST],
            {"apt-mirrors.txt": mirrors(EC2)},
            "{apt}/apt-mirrors.txt holds none of the hosts of the slow pass (ppa.launchpadcontent.net); "
            "changed nothing",
        ),
        (
            ["--slow"],
            {"apt-mirrors.txt": mirrors(EC2)},
            "{apt}/apt-mirrors.txt holds none of the hosts of the slow pass (none named); changed nothing",
        ),
        (
            ["--slow", ECTWO],
            {},
            "{apt}/apt-mirrors.txt is absent: no mirror list to reorder after a slow pass; changed nothing",
        ),
    ],
    ids=["a host the list does not hold", "no host", "no list"],
)
def test_a_slow_pass_the_list_cannot_answer_changes_nothing(tmp_path, args, files, said):
    """A person's computer with 1 host, or a runner whose step was off: 1 line, exit 0, nothing changed.
    install.sh goes on with its next pass either way."""
    apt = layout(tmp_path, {"sources.list.d/ubuntu.sources": deb822(EC2, SECURITY), **files})
    before = snapshot(apt)
    ran = run(*args, tmp=tmp_path, env={"APT_DIR": str(apt)})
    assert ran.returncode == 0, ran.stderr
    assert lines(ran) == [f"{PREFIX} " + said.format(apt=apt)]
    assert snapshot(apt) == before


# ---------------------------------------------------------------- the refusal on the real /etc/apt

SETPRIV = shutil.which("setpriv")
UID = 12345


def unprivileged(argv: list[str], env: dict[str, str]) -> subprocess.CompletedProcess:
    """argv as a user id that cannot write /etc/apt: this one when it is not root, else user id 12345
    with no groups through setpriv."""
    if os.geteuid() != 0:
        return subprocess.run(argv, env=env, capture_output=True, text=True, timeout=60)
    cmd = [SETPRIV, "--reuid", str(UID), "--regid", str(UID), "--clear-groups", "env", "-i"]
    cmd += [f"{k}={v}" for k, v in env.items()] + argv
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60)


def tree(path: Path) -> dict[str, str]:
    found = {}
    for p in sorted(path.rglob("*")):
        if p.is_file() and os.access(p, os.R_OK):
            found[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
    return found


@pytest.mark.skipif(
    os.geteuid() == 0 and SETPRIV is None,
    reason="setpriv: as root, the refusal is judged only as another user id",
)
def test_the_real_etc_apt_is_refused_unless_ci_says_so(tmp_path):
    """The script runs as a user id that cannot write /etc/apt, checked first, so a lost refusal fails
    this test and writes nothing. The script's text is handed to bash on its command line (no file of
    this checkout needs to be readable by that user). /etc/apt, by its own name or by a link to it,
    with no variable, is refused with exit 2; so is the default folder; CI's variable set to another
    value than 1 is no permission. The refusal comes before the probe: a curl that answers nothing is
    first on PATH, and it is not called."""
    real = Path("/etc/apt")
    if not real.is_dir():
        pytest.skip("this machine has no /etc/apt")
    # The link's folder must be one that user id may enter, or realpath cannot follow it.
    shared = Path(tempfile.mkdtemp(prefix="apt-archive-test-", dir="/tmp"))
    try:
        shared.chmod(0o755)
        bin_ = standins(shared, {})
        bin_.chmod(0o777)
        env = {"PATH": f"{bin_}:/usr/bin:/bin", "LC_ALL": "C", "TMPDIR": "/tmp"}
        probe = unprivileged(["bash", "-c", 'test -w /etc/apt || test -w "$(realpath /etc/apt)"'], env)
        assert probe.returncode == 1, "the user id of this test can write /etc/apt: the refusal is not judged"
        link = shared / "apt-link"
        link.symlink_to(real)
        text = SCRIPT.read_text(encoding="utf-8")
        before = tree(real)
        seen = {}
        for name, args, extra in [
            ("named", [str(real)], {}),
            ("linked", [str(link)], {}),
            ("by APT_DIR", [], {"APT_DIR": str(real)}),
            ("default", [], {}),
            ("not 1", [str(real)], {"APT_ARCHIVE_CI": "yes"}),
            ("after a slow pass", ["--slow", "us-east-2.ec2.archive.ubuntu.com"], {}),
        ]:
            ran = unprivileged(["bash", "-c", text, "apt_archive.sh", *args], {**env, **extra})
            seen[name] = (ran.returncode, ran.stdout, ran.stderr.strip())
        curled = (bin_ / "curl-calls").exists()
    finally:
        shutil.rmtree(shared)
    refused = (
        f"{PREFIX} refused: {real} is this machine's own apt folder; CI says it may change it with "
        "APT_ARCHIVE_CI=1 (.github/workflows/ci.yml); changed nothing"
    )
    assert seen == {name: (2, "", refused) for name in seen}
    assert tree(real) == before
    assert not curled


# ---------------------------------------------------------------- the workflows


def flow(name: str) -> dict:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load((FLOWS / name).read_text(encoding="utf-8"))


def archive_steps(job: dict) -> list[tuple[int, dict]]:
    """The steps that rank the hosts (the install step names the script too, for its `--slow` mode)."""
    return [
        (i, s) for i, s in enumerate(job["steps"]) if "tools/ci/apt_archive.sh /etc/apt" in s.get("run", "")
    ]


def install_index(job: dict) -> int:
    (i,) = [i for i, s in enumerate(job["steps"]) if "./install.sh" in s.get("run", "")]
    return i


def test_ci_calls_the_script_on_the_install_path_only_right_before_install_sh():
    job = flow("ci.yml")["jobs"]["full"]
    ((i, step),) = archive_steps(job)
    assert i == install_index(job) - 1
    assert step["if"] == "steps.where.outputs.where == 'install'"
    assert job["steps"][i + 1]["if"] == step["if"]
    assert step["env"] == {"ENABLED": f"${{{{ vars.{OFF} }}}}"}
    assert [x.strip() for x in step["run"].splitlines()].count(CALL) == 1
    image_path = [s for s in job["steps"] if s.get("if") == "steps.where.outputs.where == 'image'"]
    assert image_path and all("apt_archive" not in s.get("run", "") for s in image_path)
    others = [name for name, j in flow("ci.yml")["jobs"].items() if name != "full" and archive_steps(j)]
    assert others == []
    assert "apt_archive" not in (FLOWS / "image.yml").read_text(encoding="utf-8")


def test_the_step_is_named_for_what_it_does_now():
    """The step keeps the hosts and ranks them by a sample of 1 MiB: its name says so, and no more, in
    both workflows. Its 15 s silence rule holds for `apt-get update` only (install.sh's download passes
    its own per-file bounds on apt's command line, which win), so the name no longer promises it."""
    ((_, ours),) = archive_steps(flow("ci.yml")["jobs"]["full"])
    assert ours["name"] == "Rank the hosts of Ubuntu's archive by a 1 MiB sample, fastest first"


def test_the_nightly_run_calls_the_same_step_right_before_install_sh():
    """The nightly run has 1 path, install.sh: its step has no `if`, and is ci.yml's in all else. Its
    `id` names it to the issue's step (tools/ci/nightly_issue.py), which tells the step that failed."""
    job = flow("nightly.yml")["jobs"]["verify"]
    ((i, step),) = archive_steps(job)
    assert i == install_index(job) - 1 and "if" not in step
    assert step["id"] == "archive"
    ((_, ours),) = archive_steps(flow("ci.yml")["jobs"]["full"])
    assert {k: v for k, v in ours.items() if k != "if"} == {k: v for k, v in step.items() if k != "id"}


@pytest.mark.parametrize("value", ["", "1", "0", "no"])
def test_the_step_runs_the_script_under_sudo_unless_the_variable_is_0(tmp_path, value):
    """The step's script runs here under `bash -e` with a closed PATH: `sudo` is a stand-in that writes
    its arguments and runs nothing. `0` turns it off with 1 line that names the variable; anything
    else, unset included, runs it."""
    ((_, step),) = archive_steps(flow("ci.yml")["jobs"]["full"])
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    calls = tmp_path / "calls"
    (bin_ / "sudo").write_text(f'#!/bin/bash\nprintf "%s\\n" "$*" >> {calls}\n', encoding="utf-8")
    (bin_ / "sudo").chmod(0o755)
    env = {"PATH": str(bin_), "ENABLED": value}
    ran = subprocess.run(["/bin/bash", "-e", "-c", step["run"]], env=env, capture_output=True, text=True)
    assert ran.returncode == 0, ran.stderr
    said = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
    if value == "0":
        assert said == []
        assert ran.stdout.splitlines() == [
            f"{PREFIX} off: the repository variable {OFF} is 0; apt keeps the runner's mirror"
        ]
    else:
        assert said == [CALL.removeprefix("sudo ")]


HOOK = "env APT_ARCHIVE_CI=1 bash tools/ci/apt_archive.sh --slow"


def install_step(name: str, job: str) -> dict:
    (step,) = [s for s in flow(name)["jobs"][job]["steps"] if "./install.sh" in s.get("run", "")]
    return step


@pytest.mark.parametrize("value", ["", "1", "0"])
def test_the_install_step_names_the_slow_mode_unless_the_variable_is_0(tmp_path, value):
    """install.sh's APT_SLOW_PASS_COMMAND is this script's `--slow`, passed through `sudo env` (sudo
    drops a variable set before it) with APT_ARCHIVE_CI=1, which lets it change /etc/apt. With
    CI_APT_UBUNTU_ARCHIVE=0 the list stays the runner's: the variable is empty, and install.sh runs no
    command. The step runs here with a stand-in sudo that writes each argument on a line of its own. The
    nightly run's install step is the same."""
    step = install_step("ci.yml", "full")
    assert step["env"] == {"ENABLED": f"${{{{ vars.{OFF} }}}}"}
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    calls = tmp_path / "calls"
    (bin_ / "sudo").write_text(f'#!/bin/bash\nprintf "%s\\n" "$@" >> {calls}\n', encoding="utf-8")
    (bin_ / "sudo").chmod(0o755)
    env = {"PATH": str(bin_), "ENABLED": value}
    ran = subprocess.run(["/bin/bash", "-e", "-c", step["run"]], env=env, capture_output=True, text=True)
    assert ran.returncode == 0, ran.stderr
    hook = "" if value == "0" else HOOK
    assert calls.read_text(encoding="utf-8").splitlines() == [
        "env",
        "REQUIRE_FREEROUTING=1",
        "APT_UPDATE_TIMEOUT=120",
        "APT_DOWNLOAD_TIMEOUT=570",
        f"APT_SLOW_PASS_COMMAND={hook}",
        "./install.sh",
    ]
    nightly = install_step("nightly.yml", "verify")
    assert (nightly["run"], nightly["env"]) == (step["run"], step["env"])


def test_the_variable_the_step_sets_is_the_one_the_script_reads():
    text = SCRIPT.read_text(encoding="utf-8")
    assert '[ "${APT_ARCHIVE_CI:-}" != 1 ]' in text


# ---------------------------------------------------------------- lint


def test_shellcheck_reads_the_script_as_the_lint_does():
    """The Makefile's lint line and verify.sh's lint step name the script, and shellcheck passes on it."""
    for path in (ROOT / "Makefile", ROOT / "verify" / "verify.sh"):
        (line,) = [
            x
            for x in path.read_text(encoding="utf-8").splitlines()
            if x.strip().startswith("shellcheck install.sh")
        ]
        assert "tools/ci/apt_archive.sh" in line.split(), path
    if shutil.which("shellcheck") is None:
        pytest.skip("shellcheck is not on PATH")
    ran = subprocess.run(["shellcheck", str(SCRIPT)], capture_output=True, text=True)
    assert ran.returncode == 0, ran.stdout
