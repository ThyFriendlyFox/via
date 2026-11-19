#!/usr/bin/env python3
"""image — Via's container image: its name, its content tag, the record of its build, and
where CI's full job runs.

The content tag names a toolchain by the files that define it (TOOLCHAIN_FILES): the sha256 of each
file's bytes as git stores them, written as `sha256sum` writes its lines, in a fixed order, and the
sha256 of those lines. By hand, in a checkout: `sha256sum Dockerfile install.sh requirements.txt |
sha256sum`; the tag is `tc-` and its first 16 digits. 2 machines that hold 1 commit get 1 tag.

    image.py tag [--repo R] [--rev REV] [--json] [--owner O] [--github-output]
    image.py decide --base B [--repo R] --owner O [--enabled V] [--github-output]
    image.py record --out FILE [--src DIR] [--expect-tag T] [--revision R]   (the Dockerfile's last step)
    image.py check [--src DIR] [--record FILE]                                (CI, inside the image)
    image.py show [--json]                                                    (the record of this image)

`decide` prints `where=image` and the image by digest when the registry gives the image of this
commit's tag, else `where=install`; both with the reason. Exit code 0 for either answer, 1 when a
record or a check is refused, 2 for misuse. Standard library only, as the CLI.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

REGISTRY = "ghcr.io"
NAME = "via"
# The files that define the toolchain, in the order their sums are written. requirements.txt is 1 of
# them: an image of a tag holds the Python packages of that tag's requirements.txt and no other.
TOOLCHAIN_FILES = ("Dockerfile", "install.sh", "requirements.txt")
RECORD = Path("/opt/workcenters/ee/image.json")
SRC = Path(__file__).resolve().parents[1]
DISABLE = "CI_FULL_IN_IMAGE"

Reader = Callable[[str], bytes]


class Absent(Exception):
    """A toolchain file is not where the tag reads it."""


class Refused(Exception):
    """A record or a check that does not hold."""


# ---------------------------------------------------------------- the content tag


def from_git(repo: Path, rev: str) -> Reader:
    """Each file's bytes as git stores them at `rev`: line endings as committed, whatever the checkout."""

    def read(path: str) -> bytes:
        shown = subprocess.run(
            ["git", "-C", str(repo), "cat-file", "blob", f"{rev}:{path}"], capture_output=True
        )
        if shown.returncode != 0:
            raise Absent(f"{path} is not in {rev}")
        return shown.stdout

    return read


def from_disk(root: Path) -> Reader:
    """Each file's bytes as they are on disk: the Dockerfile's build reads these (it holds no .git)."""

    def read(path: str) -> bytes:
        file = Path(root) / path
        if not file.is_file():
            raise Absent(f"{path} is not in {root}")
        return file.read_bytes()

    return read


def sums(read: Reader) -> dict[str, str]:
    return {path: hashlib.sha256(read(path)).hexdigest() for path in TOOLCHAIN_FILES}


def manifest(read: Reader) -> str:
    """The lines `sha256sum` prints for the toolchain files, in TOOLCHAIN_FILES' order."""
    return "".join(f"{digest}  {path}\n" for path, digest in sums(read).items())


def content_tag(read: Reader) -> str:
    return "tc-" + hashlib.sha256(manifest(read).encode("utf-8")).hexdigest()[:16]


def image_name(owner: str) -> str:
    """The registry's name of the image: the owner in lower case, as GitHub's container registry page
    writes it."""
    return f"{REGISTRY}/{owner.lower()}/{NAME}"


# ---------------------------------------------------------------- where CI's full job runs


def changed_files(repo: Path, base: str, head: str) -> list[str] | None:
    """The toolchain files whose stored bytes differ between the 2 commits; None where the base cannot
    be read (no base, or a commit this checkout does not hold)."""
    if not base:
        return None
    if subprocess.run(["git", "-C", str(repo), "cat-file", "-e", f"{base}^{{commit}}"]).returncode != 0:
        return None
    old, new = from_git(repo, base), from_git(repo, head)
    changed = []
    for path in TOOLCHAIN_FILES:
        try:
            before = old(path)
        except Absent:
            before = None
        if before != new(path):
            changed.append(path)
    return changed


def pull(ref: str) -> tuple[bool, str]:
    """`docker pull` of 1 image: (True, the image by digest) or (False, the registry's last line)."""
    try:
        got = subprocess.run(["docker", "pull", "--quiet", ref], capture_output=True, text=True, timeout=900)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"docker pull did not end: {exc}"
    if got.returncode != 0:
        said = (got.stderr or got.stdout).strip().splitlines()
        return False, said[-1] if said else f"docker pull exit code {got.returncode}"
    shown = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{index .RepoDigests 0}}", ref],
        capture_output=True,
        text=True,
    )
    digest = shown.stdout.strip()
    if shown.returncode != 0 or "@sha256:" not in digest:
        return False, f"the image pulled has no digest: {shown.stderr.strip() or digest}"
    return True, digest


def decide(
    enabled: str,
    tag: str | None,
    changed: list[str] | None,
    pull: Callable[[str], tuple[bool, str]],
    owner: str,
    unread: str = "",
) -> dict[str, str]:
    """Where the full job runs: in the image of this commit's tag when the registry gives it, else by
    install.sh as before. `changed` is None where no base could be read. The image holds node, so the
    whole suite runs there: no other path of the change moves the job."""

    def install(reason: str) -> dict[str, str]:
        return {"where": "install", "image": "", "reason": reason}

    if enabled.strip() == "0":
        return install(f"the repository variable {DISABLE} is 0")
    if tag is None:
        return install(f"the toolchain's files cannot be read at this commit: {unread or 'absent'}")
    if changed:
        return install(f"this change edits {', '.join(changed)}: the install path is their test")
    ref = f"{image_name(owner)}:{tag}"
    ok, said = pull(ref)
    if not ok:
        return install(f"the registry gave no {ref}: {said}")
    return {"where": "image", "image": said, "reason": f"the registry holds {ref} ({said.split('@', 1)[1]})"}


# ---------------------------------------------------------------- the build's record


def judge_doctor(payload: dict, machine: str) -> list[str]:
    """What keeps an image from being published: a doctor that fails, and each engine the image is for
    that doctor does not find. openEMS is asked of the amd64 image alone: install.sh fetches Debian's
    amd64 packages of it. node is asked of both: doctor's row is advisory (a board needs none), but CI
    runs Via's own tests in the image, and 3 of their files run node."""
    problems = [f"doctor: {payload.get('status')}"] if payload.get("status") == "fail" else []
    # `requirements`: the venv holds requirements.txt's pins, the file whose sum is in the tag.
    wanted = [
        "kicad-cli",
        "ngspice",
        "python",
        "java",
        "freerouting",
        "venv",
        "requirements",
        "xvfb",
        "symbols",
        "node",
    ]
    if machine == "x86_64":
        wanted.append("openems")
    checks = payload.get("checks", {})
    problems += [f"{name}: not ok in the image" for name in wanted if not checks.get(name, {}).get("ok")]
    return problems


def versions(payload: dict) -> dict[str, str]:
    checks = payload.get("checks", {})
    jar = Path(checks.get("freerouting", {}).get("path", "")).resolve().name
    found = re.fullmatch(r"freerouting-(.+)\.jar", jar)
    return {
        "kicad": checks.get("kicad-cli", {}).get("version") or "",
        "ngspice": checks.get("ngspice", {}).get("version") or "",
        "java": checks.get("java", {}).get("version") or "",
        "python": checks.get("python", {}).get("version") or "",
        "freerouting": found.group(1) if found else "",
        "openems": checks.get("openems", {}).get("version") or "",
        "node": checks.get("node", {}).get("version") or "",
    }


def record(src: Path, out: Path, expect: str, revision: str, payload: dict, machine: str) -> dict:
    """The image's record: its tag from the files it was built from, the commit, each file's sum and the
    tools' versions as doctor read them. Refused, and nothing written, on another tag than the workflow
    named or on a doctor that does not pass."""
    read = from_disk(src)
    tag = content_tag(read)
    if expect and expect != tag:
        raise Refused(f"the files in the image make {tag}; the workflow named {expect}")
    problems = judge_doctor(payload, machine)
    if problems:
        raise Refused("; ".join(problems))
    rec = {
        "tag": tag,
        "revision": revision,
        "machine": machine,
        "files": sums(read),
        "versions": versions(payload),
        "doctor": payload.get("status", ""),
    }
    Path(out).write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    return rec


def read_record(rec_path: Path) -> dict:
    """An image's record, or Refused naming the file and why it is not one."""

    def refuse(why: str) -> Refused:
        return Refused(f"{rec_path}: not a record ({why})")

    try:
        rec = json.loads(Path(rec_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise refuse(f"unreadable: {exc}") from None
    except json.JSONDecodeError as exc:
        raise refuse(f"no JSON: {exc}") from None
    if not isinstance(rec, dict):
        raise refuse(f"a JSON {type(rec).__name__}, not an object")
    if not isinstance(rec.get("files", {}), dict):
        raise refuse(f"its files are a JSON {type(rec['files']).__name__}, not an object")
    return rec


def check(src: Path, rec_path: Path) -> list[str]:
    """Each toolchain file of the checkout whose bytes are not those the image was built from."""
    rec = read_record(rec_path)
    have = sums(from_disk(src))
    built = rec.get("files", {})
    return [
        f"{p}: the image was built from sha256 {built.get(p)}, the checkout holds {have[p]}"
        for p in TOOLCHAIN_FILES
        if built.get(p) != have[p]
    ]


def doctor_payload(src: Path) -> dict:
    ran = subprocess.run(
        [sys.executable, str(src / "tools" / "workcenter"), "doctor", "--json"],
        capture_output=True,
        text=True,
    )
    try:
        return json.loads(ran.stdout)
    except json.JSONDecodeError:
        return {"status": "fail", "checks": {}, "said": ran.stderr.strip()[-400:]}


# ---------------------------------------------------------------- the command


def github_output(pairs: dict[str, str]) -> None:
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
        for key, value in pairs.items():
            out.write(f"{key}={value}\n")


def tag_of(repo: Path, rev: str) -> dict:
    read = from_git(repo, rev)
    return {"tag": content_tag(read), "rev": rev, "files": sums(read)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="image.py", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("tag", help="the content tag of a commit's toolchain files")
    p.add_argument("--repo", type=Path, default=SRC)
    p.add_argument("--rev", default="HEAD")
    p.add_argument("--owner", help="also print the image's name under this owner")
    p.add_argument("--json", action="store_true")
    p.add_argument("--github-output", action="store_true", help="append tag= and image= to $GITHUB_OUTPUT")
    p = sub.add_parser(
        "decide", help="where CI's full job runs: the image of this commit's tag, or install.sh"
    )
    p.add_argument("--repo", type=Path, default=Path.cwd())
    p.add_argument("--base", required=True, help="the commit the change starts from; empty: none")
    p.add_argument("--head", default="HEAD")
    p.add_argument("--owner", required=True)
    p.add_argument("--enabled", default="", help=f"the value of the repository variable {DISABLE}")
    p.add_argument("--github-output", action="store_true")
    p = sub.add_parser("record", help="write the image's record; refused on a doctor that does not pass")
    p.add_argument("--out", type=Path, default=RECORD)
    p.add_argument("--src", type=Path, default=SRC)
    p.add_argument("--expect-tag", default="")
    p.add_argument("--revision", default="")
    p = sub.add_parser("check", help="the checkout's toolchain files against those the image was built from")
    p.add_argument("--src", type=Path, default=Path.cwd())
    p.add_argument("--record", type=Path, default=RECORD)
    p = sub.add_parser("show", help="the record of the image this runs in")
    p.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if getattr(args, "github_output", False) and not os.environ.get("GITHUB_OUTPUT"):
        print("image.py: --github-output needs $GITHUB_OUTPUT, the file GitHub reads", file=sys.stderr)
        return 2

    if args.cmd == "tag":
        try:
            said = tag_of(args.repo, args.rev)
        except Absent as exc:
            print(f"image.py: {exc}", file=sys.stderr)
            return 1
        if args.owner:
            said["image"] = image_name(args.owner)
        if args.github_output:
            github_output({"tag": said["tag"], **({"image": said["image"]} if args.owner else {})})
        if args.json:
            print(json.dumps(said, indent=2))
        else:
            print(said["tag"])
            for path, digest in said["files"].items():
                print(f"  {digest}  {path}")
        return 0

    if args.cmd == "decide":
        tag, unread = None, ""
        try:
            tag = tag_of(args.repo, args.head)["tag"]
            changed = changed_files(args.repo, args.base, args.head)
        except Absent as exc:
            changed, unread = None, str(exc)
        d = decide(args.enabled, tag, changed, pull, args.owner, unread)
        print(f"where: {d['where']}: {d['reason']}")
        if args.github_output:
            github_output(d)
        return 0

    if args.cmd == "record":
        try:
            rec = record(
                args.src,
                args.out,
                args.expect_tag,
                args.revision,
                doctor_payload(args.src),
                platform.machine(),
            )
        except (Refused, Absent) as exc:
            print(f"image.py: record refused: {exc}", file=sys.stderr)
            return 1
        print(f"image {rec['tag']} ({rec['machine']}) at {args.out}")
        for tool, version in rec["versions"].items():
            print(f"  {tool:12} {version or 'absent'}")
        return 0

    if args.cmd == "check":
        if not args.record.is_file():
            print(f"image.py: no record at {args.record}: this is not Via's image", file=sys.stderr)
            return 1
        try:
            problems = check(args.src, args.record)
        except (Refused, Absent) as exc:
            print(f"image.py: {exc}", file=sys.stderr)
            return 1
        for line in problems:
            print(f"FAIL image: {line}")
        if not problems:
            print(f"image: the checkout's {', '.join(TOOLCHAIN_FILES)} are those the image was built from")
        return 1 if problems else 0

    if not RECORD.is_file():
        print(f"image.py: no record at {RECORD}: this is not Via's image", file=sys.stderr)
        return 1
    try:
        print(json.dumps(read_record(RECORD), indent=2))
    except Refused as exc:
        print(f"image.py: {exc}", file=sys.stderr)
        return 1
    return 0


def register(sub, cli) -> None:
    """Add `image` to Via's parser."""
    p = sub.add_parser(
        "image",
        help="the content tag of Via's toolchain files at a commit, and the record of the "
        "image this runs in when there is one; runs no engine",
    )
    p.add_argument("--rev", default="HEAD", help="the commit (default HEAD)")
    p.set_defaults(run=lambda a: cmd_image(a, cli))


def cmd_image(args, cli) -> int:
    try:
        said = tag_of(cli.SRC_DIR, args.rev)
    except Absent as exc:
        said = {"tag": None, "rev": args.rev, "files": {}, "not_judged": f"{exc} (no git checkout?)"}
    said["image"] = image_name("<owner>")
    try:
        said["installed"] = read_record(RECORD) if RECORD.is_file() else None
    except Refused as exc:
        print(f"workcenter image: {exc}", file=sys.stderr)
        return 1
    if getattr(args, "json", False):
        print(json.dumps(said, indent=2))
        return 0
    if said["tag"]:
        print(f"toolchain tag {said['tag']} at {args.rev}: {said['image']}:{said['tag']}")
        for path, digest in said["files"].items():
            print(f"  {digest}  {path}")
    else:
        print(f"toolchain tag not judged: {said['not_judged']}")
    inst = said["installed"]
    if inst:
        built = inst.get("revision") or "an unnamed commit"
        print(f"this image: {inst.get('tag')} built at {built} ({inst.get('machine')})")
        for tool, version in dict(inst.get("versions") or {}).items():
            print(f"  {tool:12} {version or 'absent'}")
    else:
        print(f"this is not Via's image: no record at {RECORD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
