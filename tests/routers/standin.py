"""A stand-in router for tests/test_routers.py: it is called as Java is, `java -jar <jar> -de <dsn> -do
<ses> ...`, and does what its "jar" says. The jar is a JSON file:

    {"ses": "<session text>" or null, "log": "<printed>", "exit": 0, "sleep": 0, "record": "<path>"}

- `record`: a JSON line is appended per call: the arguments, DISPLAY, the folder it ran in, the
  DSN's text and whether a `.rules` file stands beside the DSN. A test reads what Via
  handed the router from it.
- `sleep`: seconds to wait before anything else, in a child process, as Java under xvfb-run is.
- `log` is printed; `ses`, when not null, is written where -do says; then it exits with `exit`.

`java -version` prints the version in STANDIN_JAVA_VERSION (default 21.0.13) as OpenJDK does, on
standard error. It routes nothing: every output is the one its jar names.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if argv[:1] == ["-version"]:
        version = os.environ.get("STANDIN_JAVA_VERSION", "21.0.13")
        print(f'openjdk version "{version}" 2026-10-24', file=sys.stderr)
        return 0
    args = dict(zip(argv[::1], argv[1::1], strict=False))
    plan = json.loads(Path(args["-jar"]).read_text(encoding="utf-8"))
    if plan.get("sleep"):
        # A child that holds the output, as Java does under xvfb-run: stopping this process alone
        # would leave it running.
        subprocess.run(
            [sys.executable, "-c", f"import time; time.sleep({float(plan['sleep'])})"], check=False
        )
    dsn = Path(args["-de"])
    if plan.get("record"):
        entry = {
            "argv": argv,
            "display": os.environ.get("DISPLAY"),
            "cwd": os.getcwd(),
            "dsn_path": str(dsn),
            "dsn": dsn.read_text(encoding="utf-8"),
            # FreeRouting 2.5.0 reads a <board>.rules beside the DSN when none is named.
            "rules_beside": dsn.with_suffix(".rules").exists(),
        }
        with open(plan["record"], "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    print(plan.get("log", ""))
    if plan.get("ses") is not None:
        Path(args["-do"]).write_text(plan["ses"], encoding="utf-8")
    return int(plan.get("exit", 0))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
