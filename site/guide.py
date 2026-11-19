"""The guide: how to use Via, step by step, in plain English, at /guide.

    python3 site/guide.py          # write site/guide.html
    python3 site/guide.py --check  # exit 1 when site/guide.html is not what this writes

The home page's left card leads here (the owner's ask, 2026-11-19: "a card directly opposite that
links to how to use VIA step-by-step in simple plain English"). Every command and every claim is
the repository's own: README.md ("Quick start", "Where it runs"), environment/README.md and
tests/boards/README.md. The words follow ee-agent-kit/docs/WEBSITE-WRITING.md.
"""

# ruff: noqa: E501 - the page's templates are HTML, with its lines as long as the site's pages'.
from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
sys.path.insert(0, str(SITE))

from frame import REPO, shell  # noqa: E402

SCRIPTS = ["vendor/motion-14.6.0.js", "site.js", "effects.js"]
GUIDE = SITE / "guide.html"
COPY = """<button class="copy" type="button" data-copy aria-label="Copy the commands">
                <svg class="todo" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h8"/></svg>
                <svg class="done" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>
              </button>"""


def commands(*lines: str) -> str:
    """A box of commands with the home page's copy button: it copies them without their prompts."""
    text = "\n".join(f'<span class="prompt">$ </span>{html.escape(line, quote=False)}' for line in lines)
    return f"""<div class="guide-cmd" data-copyable>
              <pre>{text}</pre>
              {COPY}
            </div>"""


# Each step: its id, its heading and its body. The headings say what the step is, not what to do.
STEPS = (
    (
        "where",
        "Where Via runs",
        f"""<p>Via runs on Ubuntu 24.04. If that's your computer, you can go straight to step 2.</p>
            <p>On Windows or a Mac, the way in today is a Claude Code cloud environment. It's a Linux machine in the cloud that you use from your browser, and our setup script installs Via on it. <a class="link" href="{REPO}/blob/main/environment/README.md">The environment's settings</a> are in the repository. We're also making a Docker image, but it isn't public yet.</p>""",
    ),
    (
        "install",
        "Installing the tools",
        f"""<p>One script installs the tools Via uses, including KiCad 10, ngspice, Java 21 and FreeRouting. It adds system packages, so it asks for sudo.</p>
            {commands("git clone https://github.com/ThyFriendlyFox/via.git && cd via", "sudo ./install.sh")}
            <p>On a cloud environment, the setup script does this step for you.</p>""",
    ),
    (
        "doctor",
        "Checking the install",
        f"""<p><code>workcenter doctor</code> lists each tool Via needs and whether it found it. When nothing's missing, you're ready.</p>
            {commands("workcenter doctor")}""",
    ),
    (
        "checks",
        "A first run of the checks",
        f"""<p>Every board goes through 4 checks, in order.</p>
            <ul>
              <li>ERC checks the schematic's wiring.</li>
              <li>DRC checks the board's copper and spacing, and that the board matches the schematic.</li>
              <li>The simulation runs the circuit and holds its numbers to their limits.</li>
              <li>The export writes the files a board maker needs.</li>
            </ul>
            <p>Our small test board passes all 4, so it shows you what a pass looks like. The last line says GREEN.</p>
            {commands("workcenter gates tests/boards/pass-first-design")}
            <p>A copy of it has 1 track moved too close to a pad, so you can see a failure too. After a failure, <code>workcenter next</code> names the fix.</p>
            {commands("workcenter gates tests/boards/fail-drc-clearance", "workcenter next tests/boards/fail-drc-clearance")}""",
    ),
    (
        "new",
        "Starting your own board",
        f"""<p><code>workcenter new</code> makes a folder for your board, and we keep it outside Via's own folder. It starts with a design file from our template and an empty parts list.</p>
            {commands("workcenter new ~/my-board")}""",
    ),
    (
        "describe",
        "Telling your agent what you want",
        """<p>Next, you describe the board to your AI agent in your own words. A good description says what the board does, how it gets power and what it connects to. We use Claude Code, and another agent can start from <code>AGENTS.md</code>.</p>
            <p>The agent writes the design as a Python file, following Via's board-design skill. A skill is a written procedure that comes with Via. There's one for each job, from designing a board to pricing its parts.</p>""",
    ),
    (
        "next",
        "One step at a time",
        f"""<p>At any point, <code>workcenter next</code> names the one next step. It says what to do, which command to run, why, and what to read. Your agent runs it, fixes what it finds and asks again, until nothing's left.</p>
            {commands("workcenter next ~/my-board")}""",
    ),
    (
        "order",
        "The files you order with",
        f"""<p>When your board passes all 4 checks, the files a board maker asks for are in <code>build/fab</code>. They're the Gerbers, the drill files, the parts list and a PDF of the schematic.</p>
            {commands("workcenter gates ~/my-board")}
            <p>Board makers like JLCPCB and PCBWay take the Gerbers and the drill files when you order.</p>""",
    ),
)


def guide_page() -> str:
    steps = "\n".join(
        f"""            <h2 id="{key}"><span class="guide-n" aria-hidden="true">{n}</span> {heading}</h2>
            {body}"""
        for n, (key, heading, body) in enumerate(STEPS, 1)
    )
    body = f"""      <article class="section post guide" aria-labelledby="guide-title">
        <div class="wrap">
          <header class="post-head" data-reveal data-stagger>
            <p class="eyebrow">Guide</p>
            <h1 class="title post-title" id="guide-title">How to use Via, step by step</h1>
            <p class="lede">Here's the whole path from an idea to the files a board maker needs, in plain English. Your AI agent does most of the typing, and Via's checks tell it what's wrong until the board passes.</p>
          </header>
          <div class="prose">
{steps}
            <p>We're still early, and there's no release yet. If a step doesn't work for you, we'd like to hear about it on <a class="link" href="feedback.html">the feedback page</a> or in <a class="link" href="https://discord.reagent-systems.com">our Discord</a>.</p>
          </div>
        </div>
      </article>"""
    return shell(
        "How to use Via, step by step · Via",
        "How to use Via, step by step, from installing the tools to the files a board maker needs.",
        "guide",
        "",
        body,
        SCRIPTS,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check", action="store_true", help="exit 1 when guide.html differs from what this writes"
    )
    args = parser.parse_args()
    text = guide_page()
    if args.check:
        if GUIDE.is_file() and GUIDE.read_text(encoding="utf-8") == text:
            return 0
        print(f"{GUIDE.relative_to(ROOT)}: not what site/guide.py writes; run it again", file=sys.stderr)
        return 1
    GUIDE.write_text(text, encoding="utf-8")
    print(f"{GUIDE.relative_to(ROOT)}: {len(text) // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
