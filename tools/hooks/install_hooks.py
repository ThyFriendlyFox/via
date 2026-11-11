#!/usr/bin/env python3
"""Install the workcenter's agent hooks into a Claude Code settings file (user-wide by default).

The repository's own `.claude/settings.json` only loads in a session opened inside this repository.
A board session opened elsewhere (a project with the workcenter beside it, a session rooted above
both) runs without the no-`cd` hook (M35) and without the hook that refuses a test edited by a
script (M61, M119). Writing the user's settings is the user's call, so nothing runs this
automatically: run it once by hand to enable both hooks everywhere, and `workcenter doctor` reports
whether each is there.

    python3 tools/hooks/install_hooks.py                      # ~/.claude/settings.json
    python3 tools/hooks/install_hooks.py --settings PATH      # another settings file

Merges: existing settings and hooks are kept, each hook is added once, and a run that finds it
already there changes nothing. Prints one line for each hook saying what it did.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Each hook's name as the doctor and this command print it, and its file.
HOOKS = {"no-cd hook": HERE / "no_cd.py", "test hook": HERE / "no_script_test_edits.py"}


def has_hook(settings: dict, hook: Path) -> bool:
    """True when a PreToolUse hook on Bash already runs the file `hook`."""
    for entry in settings.get("hooks", {}).get("PreToolUse", []):
        for item in entry.get("hooks", []):
            if hook.name in item.get("command", ""):
                return True
    return False


def install(path: Path, hook: Path) -> bool:
    """Add 1 hook to the settings file at `path`. Returns True when the file changed."""
    settings = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    if has_hook(settings, hook):
        return False
    entry = {"matcher": "Bash", "hooks": [{"type": "command", "command": f'python3 "{hook}"', "timeout": 10}]}
    settings.setdefault("hooks", {}).setdefault("PreToolUse", []).append(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--settings", type=Path, default=Path.home() / ".claude" / "settings.json")
    args = ap.parse_args(argv)
    for name, hook in HOOKS.items():
        changed = install(args.settings, hook)
        print(f"hooks: {name} {'added to' if changed else 'already in'} {args.settings}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
