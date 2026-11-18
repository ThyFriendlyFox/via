"""The container image: 1 Dockerfile that runs install.sh, its content tag, the workflow that builds it,
CI's full job that runs inside it when the registry holds it, and a run as a user id with no home.

No Docker daemon answers on the machines these tests were written on, and GitHub Actions does not run
here: the Dockerfile and both workflows are held by their parsed text, and the 1 real build test skips
by the tool's name where `docker info` fails. The real build is the `image` workflow's job.
"""

from __future__ import annotations

import hashlib
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
    assert "REQUIRE_FREEROUTING=1 ./install.sh" in run
    assert "rm -rf /var/lib/apt/lists/*" in run and "apt-get clean" in run
    own = re.compile(r"apt-get install|apt install|dpkg -i|pip3? install|python3? -m pip|snap install")
    assert [r for r in runs() if own.search(r)] == []


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
    assert set(on["push"]["paths"]) == watched and on["push"]["branches"] == ["main"]
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
    # Only the build arguments that name the build; the toolchain is the Dockerfile's text alone.
    assert set(re.findall(r"--build-arg (\w+)=", build)) == {"TOOLCHAIN_TAG", "WORKCENTER_REVISION"}


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
    assert [s["run"] for s in install] == ["sudo env REQUIRE_FREEROUTING=1 ./install.sh", "make verify"]
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
