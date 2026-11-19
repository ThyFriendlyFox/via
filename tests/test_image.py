"""The container image: 1 Dockerfile that runs install.sh, its content tag, the workflow that builds it,
CI's full job that runs inside it when the registry holds it, and a run as a user id with no home.

No Docker daemon answers on the machines these tests were written on, and GitHub Actions does not run
here: the Dockerfile and both workflows are held by their parsed text, and the 1 real build test skips
by the tool's name where `docker info` fails. The real build is the `image` workflow's job.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import image  # noqa: E402

DOCKERFILE = ROOT / "Dockerfile"
IMAGE_FLOW = ROOT / ".github" / "workflows" / "image.yml"
CI_FLOW = ROOT / ".github" / "workflows" / "ci.yml"
RELEASE_FLOW = ROOT / ".github" / "workflows" / "release.yml"
FIXTURE = ROOT / "tests" / "boards" / "pass-rc-divider"


# ---------------------------------------------------------------- the Dockerfile, by its instructions


def instructions(text: str) -> list[tuple[str, str]]:
    """The Dockerfile's instructions as (KEYWORD, arguments), each continuation line joined and each
    comment left out, as Docker's reference (Format, Parser directives) reads them."""
    out: list[tuple[str, str]] = []
    pending = ""
    for line in text.splitlines():
        if not pending and (not line.strip() or line.lstrip().startswith("#")):
            continue
        if pending and line.lstrip().startswith("#"):
            continue
        if line.rstrip().endswith("\\"):
            pending += line.rstrip()[:-1] + " "
            continue
        whole = pending + line
        pending = ""
        word, _, rest = whole.strip().partition(" ")
        out.append((word.upper(), rest.strip()))
    return out


def dockerfile() -> list[tuple[str, str]]:
    return instructions(DOCKERFILE.read_text(encoding="utf-8"))


def runs() -> list[str]:
    return [args for word, args in dockerfile() if word == "RUN"]


def test_the_parser_joins_continuations_and_leaves_comments_out():
    text = "# a comment\nFROM x\nRUN a \\\n  # inside\n  && b\nENV K=v\n"
    assert instructions(text) == [("FROM", "x"), ("RUN", "a    && b"), ("ENV", "K=v")]


def test_the_image_starts_from_ubuntu_24_04_alone():
    """Ubuntu 24.04 is the release install.sh is written for (its header) and CI's runner
    (`runs-on: ubuntu-24.04`)."""
    assert [args for word, args in dockerfile() if word == "FROM"] == ["ubuntu:24.04"]


def test_the_toolchain_is_installed_by_install_sh_alone_and_its_apt_lists_go_in_the_same_layer():
    """1 RUN runs install.sh as CI does (REQUIRE_FREEROUTING=1); the apt lists and caches it made are
    removed in that RUN, so no layer keeps them. No RUN installs a package of its own."""
    installing = [r for r in runs() if "./install.sh" in r]
    assert len(installing) == 1
    (run,) = installing
    # As CI does, with the 2 bounds the build is given (none unless the image workflow passes them).
    assert re.match(r"REQUIRE_FREEROUTING=1 (APT_\w+_TIMEOUT=\"\$APT_\w+_TIMEOUT\" )*\./install\.sh ", run)
    assert "rm -rf /var/lib/apt/lists/*" in run and "apt-get clean" in run
    own = re.compile(r"apt-get install|apt install|dpkg -i|pip3? install|python3? -m pip|snap install")
    assert [r for r in runs() if own.search(r)] == []


def test_the_install_line_hands_install_sh_the_2_bounds_of_build_arguments_that_default_to_none():
    """The image workflow passes CI's 2 bounds as build arguments; the Dockerfile declares them with
    empty defaults before the install's RUN and hands them to install.sh there, so a person's own
    `docker build .` has no bound (install.sh reads an empty value as none)."""
    words = dockerfile()
    install = next(i for i, (w, a) in enumerate(words) if w == "RUN" and "./install.sh" in a)
    for name in ("APT_UPDATE_TIMEOUT", "APT_DOWNLOAD_TIMEOUT"):
        declared = [i for i, (w, a) in enumerate(words) if w == "ARG" and a.split("=")[0] == name]
        assert len(declared) == 1 and declared[0] < install, name
        assert words[declared[0]][1] == f"{name}=", name
        assert f'{name}="${name}"' in words[install][1], name
    assert words[install][1].startswith(
        'REQUIRE_FREEROUTING=1 APT_UPDATE_TIMEOUT="$APT_UPDATE_TIMEOUT" '
        'APT_DOWNLOAD_TIMEOUT="$APT_DOWNLOAD_TIMEOUT" ./install.sh'
    )


def test_the_last_step_runs_doctor_and_records_the_versions_and_home_comes_after_it():
    """The last RUN runs `workcenter doctor` and `tools/image.py record`, which fails the build on a
    doctor that does not pass. HOME is set after it, to a folder any user id may write (KiCad stops
    with `Environment variable HOME is empty`), so the build's own doctor writes nothing into it."""
    words = [w for w, _ in dockerfile()]
    last_run = max(i for i, w in enumerate(words) if w == "RUN")
    run = dockerfile()[last_run][1]
    assert "workcenter doctor" in run and "tools/image.py record" in run
    assert run.index("workcenter doctor") < run.index("tools/image.py record")
    assert "install -d -m 1777 /home/workcenter /work" in run
    homes = [i for i, (w, a) in enumerate(dockerfile()) if w == "ENV" and a.startswith("HOME=")]
    assert homes and min(homes) > last_run
    assert ("ENV", "HOME=/home/workcenter") in dockerfile()
    assert ("WORKDIR", "/work") in dockerfile()


def test_every_run_fails_the_build_when_any_of_its_commands_fails():
    """Promise 4 (no image whose doctor does not pass) rests on the last RUN's exit code: Docker's /bin/sh
    stops a RUN only where its commands are joined by `&&`. A `||`, a `;` or a pipe lets a failing doctor
    or a refused record through, so no RUN holds one, and none turns off the shell's exit code."""
    for run in runs():
        assert not re.search(r"\|\||;|(?<!\|)\|(?!\|)|set \+e", run), run
    last = runs()[-1]
    joined = [part.strip() for part in last.split("&&")]
    assert joined[0] == "HOME=/root workcenter doctor"
    assert joined[1].startswith("HOME=/root python3 tools/image.py record ")


def test_the_dockerfile_holds_no_secret_no_user_and_pipes_no_download_into_a_shell():
    """No ARG or ENV names a token, a password or a key; no line holds a GitHub token's prefix; no
    download is piped into a shell. No USER: CI and a user pass `--user`, and GitHub's Dockerfile
    support page says an image that runs on its runners runs as root."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    secretish = re.compile(r"TOKEN|PASSWORD|PASSWD|SECRET|API_?KEY|PRIVATE", re.I)
    named = [a.split("=")[0] for w, a in dockerfile() if w in ("ARG", "ENV")]
    assert [n for n in named if secretish.search(n)] == []
    assert not re.search(r"ghp_|github_pat_|gho_|ghs_", text)
    assert not re.search(r"(curl|wget)[^|\n]*\|\s*(ba|z)?sh\b", text)
    assert "USER" not in [w for w, _ in dockerfile()]


def test_install_sh_first_installs_what_a_bare_ubuntu_lacks_and_only_where_it_is_missing():
    """Canonical's ubuntu-base 24.04.5 tarball holds no curl, gpg, git, make or certificates (its file
    list; Docker Hub refused the official image's layer for its pull limit). The PPA step fetches its
    key with curl and gpg before any apt install, so install.sh's first step installs them, and git and
    make for `make verify`, a C compiler for `workcenter mutate`, where 1 is missing."""
    text = (ROOT / "install.sh").read_text(encoding="utf-8")
    boot = re.search(r"^BOOT_PACKAGES=\(([^)]*)\)", text, re.M)
    assert boot and boot.group(1).split() == [
        "curl",
        "gnupg",
        "ca-certificates",
        "git",
        "make",
        "gcc",
        "libc6-dev",
    ]
    body = text.split("\nstep_boot() {", 1)[1].split("\n}\n", 1)[0]
    assert 'command -v "$tool"' in body and "for tool in curl gpg git make cc; do" in body
    assert body.index("return") < body.index("apt-get update")
    main = text.split("\nmain() {", 1)[1]
    assert main.index("  step_boot\n") < main.index("  step_apt\n")


def test_the_build_context_leaves_out_git_and_build_outputs():
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    assert ".git" in ignored and "**/build" in ignored and "**/__pycache__" in ignored


# A path under examples/ or site/ in code: `"examples/..."`, `ROOT / "site"`, `Path("examples")`.
UNDER_LEFT_OUT = re.compile(
    r"""(?<![\w.-])(examples|site)/|/\s*["'](examples|site)["']|Path\(\s*["'](examples|site)["']"""
)
LOCAL_IMPORT = re.compile(r"^\s*(?:import|from)\s+(\w+)", re.M)


def called_by_the_runs() -> list[Path]:
    """The files the Dockerfile's RUN lines run: install.sh, the CLI (`workcenter doctor`), tools/image.py,
    and every module of tools/ they import, followed through their own imports."""
    joined = " ".join(runs())
    assert "./install.sh" in joined and "workcenter doctor" in joined and "tools/image.py record" in joined
    todo, seen = [ROOT / "tools" / "workcenter", ROOT / "tools" / "image.py"], set()
    while todo:
        file = todo.pop()
        if file in seen:
            continue
        seen.add(file)
        for name in LOCAL_IMPORT.findall(file.read_text(encoding="utf-8")):
            module = ROOT / "tools" / f"{name}.py"
            if module.is_file():
                todo.append(module)
    return [ROOT / "install.sh", *sorted(seen)]


def test_the_image_holds_no_example_board_and_no_site_and_nothing_it_runs_reads_them():
    """examples/ (376 MB of the working tree) and site/ (18 MB) are not in the build context, so the
    image holds the workcenter without the example boards and the site. Nothing the RUN lines run reads
    a path under them: not install.sh, not the CLI's doctor, not the record. image.py's NODE_PATHS
    names site/api/ for CI's choice of path on the checkout, outside the image, and the record, the
    check and the doctor's run do not read it."""
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    assert "examples" in ignored and "site" in ignored
    assert UNDER_LEFT_OUT.search('ROOT / "examples"') and UNDER_LEFT_OUT.search('"site/api/"')
    assert not UNDER_LEFT_OUT.search("--system-site-packages") and not UNDER_LEFT_OUT.search('"site",')
    allowed = {f'"{p}"' for p in image.NODE_PATHS}
    found = []
    for file in called_by_the_runs():
        for number, line in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
            code = line.strip()
            if code.startswith("#"):
                continue
            for word in allowed:
                code = code.replace(word, "")
            if UNDER_LEFT_OUT.search(code):
                found.append(f"{file.relative_to(ROOT)}:{number}: {line.strip()}")
    assert found == []
    for function in (image.record, image.check, image.doctor_payload, image.judge_doctor):
        assert "NODE_PATHS" not in inspect.getsource(function)


# ---------------------------------------------------------------- the content tag


def reader(files: dict[str, bytes]):
    return lambda path: files[path]


FIXED = {"Dockerfile": b"FROM a\n", "install.sh": b"echo b\n", "requirements.txt": b"c\n"}


def test_the_content_tag_of_fixed_inputs_is_the_sum_worked_out_by_hand():
    """By hand, in a folder holding the 3 files:
    printf 'FROM a\\n' | sha256sum   -> 20a51c1806196a27c0b6855656a7480447832e6a755ca8b4f0e582a41fa2534c
    printf 'echo b\\n' | sha256sum   -> 256931e5627bfa46347df35ae1c25649073ce5630975d0cdf9d301d32836a118
    printf 'c\\n' | sha256sum        -> a3a5e715f0cc574a73c3f9bebb6bc24f32ffd5b67b387244c2c909da779a1478
    sha256sum Dockerfile install.sh requirements.txt | sha256sum
                                    -> 7b247424ac84899d9bc291e076d11d9ae5ce774e5da5a79379b6d4efbbc7b93a
    The tag is `tc-` and the first 16 digits of the last sum."""
    assert image.manifest(reader(FIXED)) == (
        "20a51c1806196a27c0b6855656a7480447832e6a755ca8b4f0e582a41fa2534c  Dockerfile\n"
        "256931e5627bfa46347df35ae1c25649073ce5630975d0cdf9d301d32836a118  install.sh\n"
        "a3a5e715f0cc574a73c3f9bebb6bc24f32ffd5b67b387244c2c909da779a1478  requirements.txt\n"
    )
    assert image.content_tag(reader(FIXED)) == "tc-7b247424ac84899d"


def test_the_names_are_inside_the_sum_and_the_order_is_fixed():
    """The same 3 contents with Dockerfile's and install.sh's swapped: the manifest's lines are
    256931e5...a118  Dockerfile, 20a51c18...534c  install.sh, a3a5e715...1478  requirements.txt, whose
    sha256 is 856f5e5aa2ee8e959e6f29be2e4846852fa9ae9389e0da83cb88a4f3f3c6799c. A reader asked in any
    order gives the same tag: the files are read in TOOLCHAIN_FILES' order alone."""
    swapped = {**FIXED, "Dockerfile": FIXED["install.sh"], "install.sh": FIXED["Dockerfile"]}
    assert image.content_tag(reader(swapped)) == "tc-856f5e5aa2ee8e95"
    asked: list[str] = []
    image.content_tag(lambda p: asked.append(p) or FIXED[p])
    assert asked == ["Dockerfile", "install.sh", "requirements.txt"] == list(image.TOOLCHAIN_FILES)


def test_the_python_environment_of_an_image_is_the_one_of_its_tag():
    """Invariant: a run inside the image has the Python packages of the checkout's requirements.txt,
    because requirements.txt is 1 of the files the tag sums. A changed requirements.txt is another tag:
    printf 'c\\r\\n' | sha256sum -> ef1fac987a48... differs from a3a5e715...."""
    assert "requirements.txt" in image.TOOLCHAIN_FILES and "install.sh" in image.TOOLCHAIN_FILES
    changed = {**FIXED, "requirements.txt": b"c\r\n"}
    assert image.content_tag(reader(changed)) != image.content_tag(reader(FIXED))


def git(repo: Path, *args: str) -> str:
    ident = ["-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.autocrlf=false"]
    ran = subprocess.run(["git", "-C", str(repo), *ident, *args], capture_output=True, text=True, check=True)
    return ran.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    for name, data in FIXED.items():
        (r / name).write_bytes(data)
    git(r, "add", ".")
    git(r, "commit", "-q", "-m", "toolchain")
    return r


def test_the_tag_reads_the_bytes_git_stores_not_the_working_tree(repo):
    """From git at HEAD the tag is the hand-worked tc-7b247424ac84899d although the working tree's
    requirements.txt has a CR the commit does not; read from the disk, the CR moves it."""
    (repo / "requirements.txt").write_bytes(b"c\r\n")
    assert image.content_tag(image.from_git(repo, "HEAD")) == "tc-7b247424ac84899d"
    assert image.content_tag(image.from_disk(repo)) != "tc-7b247424ac84899d"


def test_a_toolchain_file_absent_at_the_commit_is_said_by_name(repo):
    git(repo, "rm", "-q", "install.sh")
    git(repo, "commit", "-q", "-m", "gone")
    with pytest.raises(image.Absent, match="install.sh is not in HEAD"):
        image.content_tag(image.from_git(repo, "HEAD"))


def test_the_command_prints_the_tag_of_the_commit_and_its_files(repo):
    ran = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "image.py"), "tag", "--repo", str(repo), "--json"],
        capture_output=True,
        text=True,
    )
    assert ran.returncode == 0, ran.stderr
    said = json.loads(ran.stdout)
    assert said["tag"] == "tc-7b247424ac84899d" and said["rev"] == "HEAD"
    assert said["files"]["install.sh"] == "256931e5627bfa46347df35ae1c25649073ce5630975d0cdf9d301d32836a118"


def test_workcenter_image_is_the_same_function_on_the_workcenters_own_checkout():
    ran = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "workcenter"), "image", "--json"],
        capture_output=True,
        text=True,
    )
    assert ran.returncode == 0, ran.stderr
    said = json.loads(ran.stdout)
    assert said["tag"] == image.content_tag(image.from_git(ROOT, "HEAD"))
    assert said["image"] == "ghcr.io/<owner>/ee-workcenter"


def test_the_image_name_is_the_owner_in_lower_case():
    """GitHub's container registry page writes the image's name in lower case (its workflow example
    changes every upper-case letter to lower case before the push)."""
    assert image.image_name("ThyFriendlyFox") == "ghcr.io/thyfriendlyfox/ee-workcenter"


# ---------------------------------------------------------------- where CI's full job runs


def pulled(digest: str):
    return lambda ref: (True, f"{ref.split(':')[0]}@{digest}")


def refused(said: str):
    return lambda ref: (False, said)


def test_the_full_job_runs_in_the_image_of_its_own_tag_when_the_registry_gives_it():
    seen: list[str] = []

    def pull(ref):
        seen.append(ref)
        return pulled("sha256:" + "a" * 64)(ref)

    d = image.decide("", "tc-7b247424ac84899d", [], pull, "ThyFriendlyFox")
    assert seen == ["ghcr.io/thyfriendlyfox/ee-workcenter:tc-7b247424ac84899d"]
    assert d["where"] == "image"
    assert d["image"] == "ghcr.io/thyfriendlyfox/ee-workcenter@sha256:" + "a" * 64
    assert d["reason"].startswith(
        "the registry holds ghcr.io/thyfriendlyfox/ee-workcenter:tc-7b247424ac84899d"
    )


def test_each_other_case_installs_as_today_and_says_why():
    never = refused("not asked")
    asked: list[str] = []

    def must_not_pull(ref):
        asked.append(ref)
        return never(ref)

    off = image.decide("0", "tc-x", [], must_not_pull, "o")
    assert off == {"where": "install", "image": "", "reason": "the repository variable CI_FULL_IN_IMAGE is 0"}
    edits = image.decide("", "tc-x", ["install.sh", "requirements.txt"], must_not_pull, "o")
    assert edits["where"] == "install" and edits["reason"] == (
        "this change edits install.sh, requirements.txt: the install path is their test"
    )
    assert asked == []
    missing = image.decide("", "tc-x", [], refused("manifest unknown"), "o")
    assert missing["where"] == "install"
    assert missing["reason"] == "the registry gave no ghcr.io/o/ee-workcenter:tc-x: manifest unknown"
    unread = image.decide("", None, None, must_not_pull, "o")
    assert unread["where"] == "install" and "toolchain's files" in unread["reason"]


def test_a_change_with_no_base_still_asks_the_registry():
    d = image.decide("", "tc-x", None, pulled("sha256:" + "b" * 64), "o")
    assert d["where"] == "image"


def test_the_changed_toolchain_files_are_read_from_git(repo):
    base = git(repo, "rev-parse", "HEAD")
    (repo / "requirements.txt").write_bytes(b"d\n")
    git(repo, "commit", "-q", "-am", "pin")
    assert image.changed_files(repo, base, "HEAD") == ["requirements.txt"]
    assert image.changed_files(repo, "", "HEAD") is None
    assert image.changed_files(repo, "0" * 40, "HEAD") is None


def test_decide_writes_where_image_and_reason_to_the_github_output(repo, tmp_path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setattr(image, "pull", refused("denied"))
    code = image.main(["decide", "--repo", str(repo), "--base", "", "--owner", "O", "--github-output"])
    assert code == 0
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines == [
        "where=install",
        "image=",
        "reason=the registry gave no ghcr.io/o/ee-workcenter:tc-7b247424ac84899d: denied",
    ]


def stub(folder: Path, name: str, body: str) -> None:
    folder.mkdir(exist_ok=True)
    (folder / name).write_text(f"#!/bin/bash\n{body}\n", encoding="utf-8")
    (folder / name).chmod(0o755)


def test_pull_takes_the_image_by_its_digest_alone(tmp_path, monkeypatch):
    """A stub `docker` on PATH: the pull succeeds, and `docker image inspect` prints what $SAID holds. An
    image with no repo digest (built here, never pushed) is not taken: CI must run the image the
    registry holds, by digest."""
    bin_ = tmp_path / "bin"
    stub(bin_, "docker", 'if [ "$1" = image ]; then echo "$SAID"; fi; exit 0')
    monkeypatch.setenv("PATH", f"{bin_}:{os.environ['PATH']}")
    digest = "ghcr.io/o/ee-workcenter@sha256:" + "c" * 64
    monkeypatch.setenv("SAID", digest)
    assert image.pull("ghcr.io/o/ee-workcenter:tc-x") == (True, digest)
    monkeypatch.setenv("SAID", "ghcr.io/o/ee-workcenter:tc-x")
    ok, said = image.pull("ghcr.io/o/ee-workcenter:tc-x")
    assert not ok and said == "the image pulled has no digest: ghcr.io/o/ee-workcenter:tc-x"


def test_every_test_that_needs_node_is_routed_to_the_install_path_by_the_files_it_reads():
    """The image holds no node, so on the image path the tests that run node skip. A change to a file
    they read goes to the install path, where they run. The files, read from the 2 tests: test_forms.py
    runs site/api/_forms.js (its API folder); test_lead.py parses ee-agent-kit/lead/workflows/*.js."""
    asking = sorted(
        f"tests/{p.name}"
        for p in (ROOT / "tests").glob("test_*.py")
        if re.search(r"""which\(["']node["']\)""", p.read_text(encoding="utf-8"))
    )
    assert asking == ["tests/test_forms.py", "tests/test_lead.py"]
    assert set(image.NODE_PATHS) == {*asking, "site/api/", "ee-agent-kit/lead/workflows/"}
    assert image.needs_node(["tools/fields.py", "site/api/_forms.js"]) == ["site/api/_forms.js"]
    assert image.needs_node(["ee-agent-kit/lead/workflows/user-round.js"]) != []
    assert image.needs_node(["site/index.html", "tests/test_image.py", "ee-agent-kit/lead/x.md"]) == []


def test_a_change_to_what_node_reads_runs_on_the_install_path():
    asked: list[str] = []
    d = image.decide(
        "", "tc-x", [], lambda r: asked.append(r) or (False, ""), "o", node=["site/api/_forms.js"]
    )
    assert asked == []
    assert d == {
        "where": "install",
        "image": "",
        "reason": "this change edits site/api/_forms.js: the tests that need node run on the install path "
        "(the image holds no node)",
    }


def test_the_image_path_says_the_node_tests_are_not_judged_there():
    """A change that touches nothing node reads: the reason names the tests the image path does not
    judge. With no base the files changed are not known, and the reason says so."""
    d = image.decide("", "tc-x", [], pulled("sha256:" + "d" * 64), "o", node=[])
    assert d["where"] == "image" and d["reason"].endswith(
        "; not judged there: the tests that need node (no node in the image); this change edits no file "
        "they read"
    )
    blind = image.decide("", "tc-x", None, pulled("sha256:" + "d" * 64), "o", node=None)
    assert blind["where"] == "image" and blind["reason"].endswith(
        "; not judged there: the tests that need node (no node in the image); no base says which files "
        "this change edits"
    )


def test_the_paths_a_change_edits_are_read_from_git(repo):
    base = git(repo, "rev-parse", "HEAD")
    (repo / "site" / "api").mkdir(parents=True)
    (repo / "site" / "api" / "_forms.js").write_text("x\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "forms")
    assert image.changed_paths(repo, base, "HEAD") == ["site/api/_forms.js"]
    assert image.changed_paths(repo, "", "HEAD") is None
    assert image.changed_paths(repo, "0" * 40, "HEAD") is None


# ---------------------------------------------------------------- the build's record and its check


def doctor(**over) -> dict:
    checks = {
        "kicad-cli": {"required": True, "ok": True, "version": "10.0.8"},
        "ngspice": {"required": True, "ok": True, "version": "42"},
        "python": {"required": True, "ok": True, "version": "3.12.3"},
        "java": {"required": False, "ok": True, "version": "21.0.9"},
        "freerouting": {"required": False, "ok": True, "path": "/x/freerouting.jar"},
        "venv": {"required": False, "ok": True},
        "xvfb": {"required": False, "ok": True},
        "symbols": {"required": False, "ok": True},
        "openems": {"required": False, "ok": True, "version": "v0.0.35"},
    }
    for name, ok in over.items():
        checks[name.replace("_", "-")]["ok"] = ok
    status = "fail" if any(c["required"] and not c["ok"] for c in checks.values()) else "ok"
    return {"status": status, "checks": checks}


def test_an_image_whose_doctor_does_not_pass_is_refused_by_name():
    assert image.judge_doctor(doctor(), "x86_64") == []
    assert image.judge_doctor(doctor(kicad_cli=False), "x86_64") == [
        "doctor: fail",
        "kicad-cli: not ok in the image",
    ]
    assert image.judge_doctor(doctor(freerouting=False), "aarch64") == ["freerouting: not ok in the image"]


def test_openems_is_asked_of_the_amd64_image_alone():
    """install.sh fetches openEMS as Debian's amd64 packages (`_amd64.deb`, its step_openems): on arm64
    the step warns and `workcenter fields` skips, so the arm64 image is not refused for it."""
    assert image.judge_doctor(doctor(openems=False), "x86_64") == ["openems: not ok in the image"]
    assert image.judge_doctor(doctor(openems=False), "aarch64") == []


def test_the_record_holds_the_tag_the_versions_and_the_files_and_refuses_another_tag(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    for name, data in FIXED.items():
        (src / name).write_bytes(data)
    jar = tmp_path / "freerouting-1.9.0.jar"
    jar.write_bytes(b"jar")
    (tmp_path / "freerouting.jar").symlink_to(jar)
    payload = doctor()
    payload["checks"]["freerouting"]["path"] = str(tmp_path / "freerouting.jar")
    out = tmp_path / "image.json"
    record = image.record(src, out, "", "abc123", payload, "x86_64")
    assert record["tag"] == "tc-7b247424ac84899d" and record["revision"] == "abc123"
    assert record["versions"] == {
        "kicad": "10.0.8",
        "ngspice": "42",
        "java": "21.0.9",
        "python": "3.12.3",
        "freerouting": "1.9.0",
        "openems": "v0.0.35",
    }
    assert record["files"]["requirements.txt"] == hashlib.sha256(b"c\n").hexdigest()
    assert json.loads(out.read_text(encoding="utf-8")) == record
    with pytest.raises(image.Refused, match="the workflow named tc-0000000000000000"):
        image.record(src, tmp_path / "other.json", "tc-0000000000000000", "abc123", payload, "x86_64")


def test_the_check_inside_ci_refuses_an_image_of_another_requirements_txt(tmp_path):
    src = tmp_path / "checkout"
    src.mkdir()
    for name, data in FIXED.items():
        (src / name).write_bytes(data)
    rec = tmp_path / "image.json"
    rec.write_text(
        json.dumps({"files": {n: hashlib.sha256(d).hexdigest() for n, d in FIXED.items()}}), encoding="utf-8"
    )
    assert image.check(src, rec) == []
    (src / "requirements.txt").write_bytes(b"d\n")
    was, now = hashlib.sha256(b"c\n").hexdigest(), hashlib.sha256(b"d\n").hexdigest()
    assert image.check(src, rec) == [
        f"requirements.txt: the image was built from sha256 {was}, the checkout holds {now}"
    ]


def image_cli(*argv: str, path: str | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, **({"PATH": path} if path else {})}
    return subprocess.run(
        [sys.executable, str(ROOT / "tools" / "image.py"), *argv], capture_output=True, text=True, env=env
    )


def fixed_tree(at: Path) -> Path:
    at.mkdir()
    for name, data in FIXED.items():
        (at / name).write_bytes(data)
    return at


def test_the_record_command_exits_1_and_writes_nothing_on_a_refused_record(tmp_path):
    """The Dockerfile's last RUN fails the build on this exit code alone (Promise 4). The tree holds the
    3 fixed files (tag tc-7b247424ac84899d, worked out above) and no tools/workcenter, so its doctor
    gives no JSON and is read as `doctor: fail`. Another tag is refused first; the right tag is then
    refused for the doctor."""
    src = fixed_tree(tmp_path / "src")
    out = tmp_path / "image.json"
    other = image_cli("record", "--src", str(src), "--out", str(out), "--expect-tag", "tc-0000000000000000")
    assert other.returncode == 1, other.stdout + other.stderr
    assert "record refused: the files in the image make tc-7b247424ac84899d" in other.stderr
    failed = image_cli("record", "--src", str(src), "--out", str(out), "--expect-tag", "tc-7b247424ac84899d")
    assert failed.returncode == 1, failed.stdout + failed.stderr
    assert "record refused: doctor: fail" in failed.stderr
    assert not out.exists()


def test_the_check_command_exits_1_on_files_the_image_was_not_built_from(tmp_path):
    """CI's image path runs `image.py check` under `bash -e`; its exit code is what stops `make verify`
    on an image of another requirements.txt."""
    src = fixed_tree(tmp_path / "src")
    rec = tmp_path / "image.json"
    rec.write_text(json.dumps({"files": {n: hashlib.sha256(d).hexdigest() for n, d in FIXED.items()}}))
    same = image_cli("check", "--src", str(src), "--record", str(rec))
    assert same.returncode == 0, same.stdout + same.stderr
    (src / "requirements.txt").write_bytes(b"d\n")
    moved = image_cli("check", "--src", str(src), "--record", str(rec))
    assert moved.returncode == 1 and moved.stdout.startswith("FAIL image: requirements.txt: "), moved.stdout


def test_a_record_that_is_not_one_is_refused_by_its_path_not_by_a_traceback(tmp_path):
    """An empty file, a JSON list, and a `files` that is not an object: each is 1 line naming the file and
    why, exit code 1, from `image.py check` and from `workcenter image`."""
    src = fixed_tree(tmp_path / "src")
    cases = {
        "empty.json": ("", "no JSON: Expecting value: line 1 column 1 (char 0)"),
        "list.json": ("[]", "a JSON list, not an object"),
        "files.json": ('{"files": ["x"]}', "its files are a JSON list, not an object"),
    }
    for name, (text, why) in cases.items():
        rec = tmp_path / name
        rec.write_text(text, encoding="utf-8")
        ran = image_cli("check", "--src", str(src), "--record", str(rec))
        assert ran.returncode == 1, (name, ran.stdout, ran.stderr)
        assert ran.stderr == f"image.py: {rec}: not a record ({why})\n", ran.stderr
        with pytest.raises(image.Refused, match=re.escape(f"{rec}: not a record ({why})")):
            image.read_record(rec)


def test_workcenter_image_refuses_a_record_that_is_not_one(tmp_path, monkeypatch, capsys):
    rec = tmp_path / "image.json"
    rec.write_text("", encoding="utf-8")
    monkeypatch.setattr(image, "RECORD", rec)
    cli = type("Cli", (), {"SRC_DIR": ROOT})
    code = image.cmd_image(type("Args", (), {"rev": "HEAD"})(), cli)
    assert code == 1
    said = capsys.readouterr()
    assert f"{rec}: not a record (no JSON: Expecting value" in said.err and "Traceback" not in said.err


# ---------------------------------------------------------------- the workflows, by their parsed text


def flow(path: Path) -> dict:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def run_lines(job: dict) -> str:
    return "\n".join(step.get("run", "") for step in job.get("steps", []))


def test_the_image_workflow_builds_on_a_pull_request_and_pushes_only_from_main_tags_the_week_and_by_hand():
    f = flow(IMAGE_FLOW)
    on = f[True]
    assert set(on) == {"pull_request", "push", "schedule", "workflow_dispatch"}
    watched = set(on["pull_request"]["paths"])
    assert set(image.TOOLCHAIN_FILES) <= watched
    assert {".dockerignore", ".github/workflows/image.yml", "tools/image.py"} <= watched
    # `main` is the image a user is told to run: every push to main builds it, so its workcenter code is
    # main's, not that of the last change to a toolchain file. No path filter on push.
    assert "paths" not in on["push"] and on["push"]["branches"] == ["main"]
    assert on["push"]["tags"] == ["v*.*.*"]
    assert len(on["schedule"]) == 1 and len(on["schedule"][0]["cron"].split()) == 5
    assert f["permissions"] == {"contents": "read"}
    jobs = f["jobs"]
    assert list(jobs) == ["build", "publish"]
    runners = sorted(i["runner"] for i in jobs["build"]["strategy"]["matrix"]["include"])
    assert runners == ["ubuntu-24.04", "ubuntu-24.04-arm"]
    for job in jobs.values():
        assert job["permissions"] == {"contents": "read", "packages": "write"}
    pushes = [s for s in jobs["build"]["steps"] if "docker push" in s.get("run", "")]
    assert len(pushes) == 1 and pushes[0]["if"] == "github.event_name != 'pull_request'"
    assert jobs["publish"]["needs"] == "build"
    assert jobs["publish"]["if"] == "github.event_name != 'pull_request'"
    text = IMAGE_FLOW.read_text(encoding="utf-8")
    assert re.findall(r"secrets\.\w+", text) == ["secrets.GITHUB_TOKEN"] * len(re.findall(r"secrets\.", text))


def test_the_image_workflow_tags_by_content_main_a_release_and_the_day_and_summarises_the_digest():
    jobs = flow(IMAGE_FLOW)["jobs"]
    build, publish = run_lines(jobs["build"]), run_lines(jobs["publish"])
    assert "tools/image.py tag" in build and "--build-arg TOOLCHAIN_TAG=" in build
    assert "workcenter gates ." in build and '--user "$(id -u):$(id -g)"' in build
    assert "docker buildx imagetools create" in publish
    for tag in (
        '"$IMAGE:$TAG"',
        '"$IMAGE:main"',
        '"$IMAGE:$GITHUB_REF_NAME"',
        '"$IMAGE:$TAG-$(date -u +%Y%m%d)"',
    ):
        assert tag in publish, tag
    assert "GITHUB_STEP_SUMMARY" in build and "GITHUB_STEP_SUMMARY" in publish
    # The build arguments that name the build, and CI's 2 bounds of install.sh's apt step (a person's
    # own `docker build .` passes none: no bound); the toolchain is the Dockerfile's text alone.
    assert set(re.findall(r"--build-arg (\w+)=", build)) == {
        "TOOLCHAIN_TAG",
        "WORKCENTER_REVISION",
        "APT_UPDATE_TIMEOUT",
        "APT_DOWNLOAD_TIMEOUT",
    }
    assert "--build-arg APT_UPDATE_TIMEOUT=120 --build-arg APT_DOWNLOAD_TIMEOUT=570" in build


def step_named(job: dict, start: str) -> dict:
    (step,) = [s for s in job["steps"] if s.get("name", "").startswith(start)]
    return step


def test_the_gates_step_fails_unless_every_file_written_is_the_runners_user(tmp_path):
    """The step runs here with stand-ins: `docker` (the gates write nothing), `find` that prints the
    owners $OWNERS names, and `id` whose `-un` prints $ME and ends with $ID_CODE. The step's logic is
    judged, not this machine's user list: GNU `id -un` for a user id with no passwd line prints the number
    and ends with 1 (coreutils v9.4 src/id.c, print_user), and the suite ran inside the image as such a
    user (CI run 44409635104). Promise 3: 1 owner, the runner's user, passes; another owner beside it
    fails, whether sort puts it before the runner's name or after (a step that keeps 1 owner fails 1
    of the 2); another owner alone fails; and an `id -un` that fails fails the step, even when the number it
    prints is the owner find prints."""
    step = step_named(flow(IMAGE_FLOW)["jobs"]["build"], "The gates on a fixture")
    bin_ = tmp_path / "bin"
    stub(bin_, "docker", "exit 0")
    stub(bin_, "find", 'printf "$OWNERS\\n"')
    stub(bin_, "id", 'if [ "$1" = -un ]; then echo "$ME"; exit "$ID_CODE"; fi; echo 1001')
    cases = {
        ("runner", "runner", 0): 0,
        ("runner\\nnobody-else", "runner", 0): 1,
        ("runner\\nzz-other", "runner", 0): 1,
        ("nobody-else", "runner", 0): 1,
        ("1001", "1001", 1): 1,
    }
    codes = {}
    for owners, me, id_code in cases:
        env = {
            **os.environ,
            "PATH": f"{bin_}:{os.environ['PATH']}",
            "TMPDIR": str(tmp_path),
            "OWNERS": owners,
            "ME": me,
            "ID_CODE": str(id_code),
        }
        env |= {"IMAGE": "i", "TAG": "t", "ARCH": "amd64"}
        ran = subprocess.run(
            ["bash", "-e", "-c", step["run"]], cwd=ROOT, env=env, capture_output=True, text=True
        )
        codes[(owners, me, id_code)] = ran.returncode
    assert codes == cases


def test_the_image_path_runs_make_verify_only_after_its_check_passes(tmp_path):
    """The image path's script runs here under `bash -e`, as the step runs it inside the image, with
    stubs: `python3` fails its `check` when $CHECK is 1, `make` leaves a mark. make verify runs only
    when the image's toolchain files are the checkout's."""
    run = step_named(full_job(), "Verify inside the image")["run"]
    script = re.search(r"bash -e -c '([^']*)'", run).group(1)
    bin_ = tmp_path / "bin"
    stub(bin_, "python3", 'if [ "$2" = check ]; then [ "$CHECK" = 0 ]; fi')
    stub(bin_, "make", 'touch "$MARK"')
    seen = {}
    for check in ("0", "1"):
        mark = tmp_path / f"made-{check}"
        env = {"PATH": f"{bin_}:/usr/bin:/bin", "CHECK": check, "MARK": str(mark), "IMAGE": "i"}
        ran = subprocess.run(["bash", "-e", "-c", script], env=env, capture_output=True, text=True)
        seen[check] = (ran.returncode == 0, mark.exists())
    assert seen == {"0": (True, True), "1": (False, False)}


def test_the_release_workflow_no_longer_builds_an_image_of_its_own():
    f = flow(RELEASE_FLOW)
    text = RELEASE_FLOW.read_text(encoding="utf-8")
    assert "docker" not in text and "packages" not in json.dumps(f.get("permissions", {}))


def full_job() -> dict:
    return flow(CI_FLOW)["jobs"]["full"]


def test_the_full_job_decides_its_path_then_runs_the_same_make_verify_on_either():
    job = full_job()
    assert job["permissions"] == {"contents": "read", "packages": "read"}
    steps = job["steps"]
    assert steps[0]["uses"] == "actions/checkout@v4" and steps[0]["with"] == {"fetch-depth": 2}
    where = steps[1]
    assert where["id"] == "where" and "tools/image.py decide" in where["run"]
    assert where["env"]["ENABLED"] == "${{ vars.CI_FULL_IN_IMAGE }}"
    install = [s for s in steps if s.get("if") == "steps.where.outputs.where == 'install'"]
    inside = [s for s in steps if s.get("if") == "steps.where.outputs.where == 'image'"]
    # The install path's line carries CI's 2 bounds (the install script's piece; its tests read them).
    bounded = "sudo env REQUIRE_FREEROUTING=1 APT_UPDATE_TIMEOUT=120 APT_DOWNLOAD_TIMEOUT=570 ./install.sh"
    assert [s["run"] for s in install] == [bounded, "make verify"]
    (run,) = inside
    assert '--user "$(id -u):$(id -g)"' in run["run"] and "tools/image.py check" in run["run"]
    assert run["run"].rstrip().endswith("make verify'")
    assert run["env"] == {"IMAGE": "${{ steps.where.outputs.image }}"}


def test_the_full_job_fails_unless_the_path_it_decided_ran_and_passed(tmp_path):
    """The last step runs here with each answer: green only when the decided path's verify step
    succeeded. A path that was skipped is not a pass, and no decision is a failure."""
    last = full_job()["steps"][-1]
    assert last["env"] == {
        "WHERE": "${{ steps.where.outputs.where }}",
        "INSTALLED": "${{ steps.verify.outcome }}",
        "IMAGED": "${{ steps.inside.outcome }}",
    }
    ids = {s.get("id") for s in full_job()["steps"]}
    assert {"verify", "inside"} <= ids
    script = tmp_path / "ran.sh"
    script.write_text(last["run"], encoding="utf-8")
    cases = {
        ("install", "success", "skipped"): 0,
        ("image", "skipped", "success"): 0,
        ("install", "skipped", "success"): 1,
        ("image", "success", "skipped"): 1,
        ("image", "skipped", "skipped"): 1,
        ("", "skipped", "skipped"): 1,
    }
    for (where, installed, imaged), code in cases.items():
        env = {**os.environ, "WHERE": where, "INSTALLED": installed, "IMAGED": imaged}
        ran = subprocess.run(["bash", "-e", str(script)], env=env, capture_output=True, text=True)
        assert ran.returncode == code, (where, installed, imaged, ran.stdout, ran.stderr)


# ---------------------------------------------------------------- real runs


def daemon() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


@pytest.mark.engine
@pytest.mark.skipif(not daemon(), reason="docker: no daemon answers `docker info`; the image workflow builds")
def test_the_image_builds_and_runs_the_gates_as_the_calling_user(tmp_path):
    tag = image.content_tag(image.from_disk(ROOT))
    name = f"ee-workcenter-test:{tag}"
    built = subprocess.run(
        ["docker", "build", "--build-arg", f"TOOLCHAIN_TAG={tag}", "-t", name, str(ROOT)],
        capture_output=True,
        text=True,
    )
    assert built.returncode == 0, built.stderr[-2000:]
    board = tmp_path / "board"
    shutil.copytree(FIXTURE, board)
    ran = subprocess.run(
        ["docker", "run", "--rm", "--user", f"{os.getuid()}:{os.getgid()}", "-v", f"{board}:/work", name]
        + ["workcenter", "gates", "."],
        capture_output=True,
        text=True,
    )
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert (board / "build" / "gates.json").stat().st_uid == os.getuid()


SETPRIV = shutil.which("setpriv")
UID = 12345


def as_uid(*argv: str, env: dict[str, str], stdin: bytes | None = None) -> subprocess.CompletedProcess:
    cmd = [SETPRIV, "--reuid", str(UID), "--regid", str(UID), "--clear-groups", "env", "-i"]
    cmd += [f"{k}={v}" for k, v in env.items()] + list(argv)
    return subprocess.run(cmd, input=stdin, capture_output=True)


@pytest.mark.engine
@pytest.mark.skipif(
    SETPRIV is None or os.geteuid() != 0 or shutil.which("kicad-cli") is None,
    reason="setpriv: another user id needs root and setpriv here, and kicad-cli to run",
)
def test_a_user_id_with_no_home_and_no_passwd_line_needs_the_home_the_image_sets():
    """What `docker run --user` gives the engines, without Docker: user id 12345, which has no line in
    /etc/passwd here. With no HOME, kicad-cli stops (`Environment variable HOME is empty`) and the CLI
    cannot start (Path.home()). With HOME a folder the user may write, as the image's
    /home/workcenter (mode 1777), the gates are GREEN and every file they write is the user's."""
    assert subprocess.run(["getent", "passwd", str(UID)], capture_output=True).returncode != 0
    path = {"PATH": "/usr/local/bin:/usr/bin:/bin"}
    made = as_uid("mktemp", "-d", "/tmp/wc-image-test-XXXXXX", env=path)
    assert made.returncode == 0, made.stderr
    top = made.stdout.decode().strip()
    try:
        tree = subprocess.run(
            ["tar", "-C", str(ROOT), "-c", "tools", "rules", "pdks", "templates", "WORKCENTER.md"],
            capture_output=True,
            check=True,
        ).stdout
        assert as_uid("tar", "-C", top, "-x", "-f", "-", env=path, stdin=tree).returncode == 0
        board = subprocess.run(["tar", "-C", str(FIXTURE), "-c", "."], capture_output=True, check=True).stdout
        assert as_uid("mkdir", f"{top}/board", f"{top}/home", env=path).returncode == 0
        assert as_uid("tar", "-C", f"{top}/board", "-x", "-f", "-", env=path, stdin=board).returncode == 0
        bare = as_uid("kicad-cli", "version", env=path)
        assert bare.returncode != 0 and b"HOME is empty" in bare.stdout + bare.stderr
        cli = as_uid(sys.executable, f"{top}/tools/workcenter", "doctor", env=path)
        assert cli.returncode != 0 and b"Path.home()" in cli.stderr
        home = {**path, "HOME": f"{top}/home"}
        gates = as_uid(sys.executable, f"{top}/tools/workcenter", "gates", f"{top}/board", env=home)
        assert gates.returncode == 0, gates.stdout + gates.stderr
        assert b"GREEN: rc_divider" in gates.stdout
        written = [p for p in Path(top, "board", "build").rglob("*")]
        assert written and {p.stat().st_uid for p in written} == {UID}
    finally:
        as_uid("rm", "-rf", top, env=path)
