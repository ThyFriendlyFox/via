"""The site's frame: the head, the header and the footer every written page shares.

site/examples.py and site/blog.py write their pages in it, so a page they write reads as the site's
own: the same menu, the same footer, and the same theme before the first paint.
"""

# ruff: noqa: E501 - the frame is HTML, with its lines as long as the site's pages'.
from __future__ import annotations

import html

REPO = "https://github.com/ThyFriendlyFox/via"


GH_PATH = (
    "M8 0c4.42 0 8 3.58 8 8a8.013 8.013 0 0 1-5.45 7.59c-.4.08-.55-.17-.55-.38 0-.27.01-1.13.01-2.2 0-.75-.25-1.23-.54-1.48 "
    "1.78-.2 3.65-.88 3.65-3.95 0-.88-.31-1.59-.82-2.15.08-.2.36-1.02-.08-2.12 0 0-.67-.22-2.2.82-.64-.18-1.32-.27-2-.27-.68 "
    "0-1.36.09-2 .27-1.53-1.03-2.2-.82-2.2-.82-.44 1.1-.16 1.92-.08 2.12-.51.56-.82 1.28-.82 2.15 0 3.06 1.86 3.75 3.64 "
    "3.95-.23.2-.44.55-.51 1.07-.46.21-1.61.55-2.33-.66-.15-.24-.6-.83-1.23-.82-.67.01-.27.38.01.53.34.19.73.9.82 1.13.16.45.68 "
    "1.31 2.69.94 0 .67.01 1.3.01 1.49 0 .21-.15.45-.55.38A7.995 7.995 0 0 1 0 8c0-4.42 3.58-8 8-8Z"
)
LOGO = (
    '<svg class="logo" data-logo viewBox="283 202 394 136" fill="currentColor" stroke="currentColor" stroke-width="12" '
    'stroke-linejoin="round" aria-hidden="true"><path class="lg-letter" d="m378.4252 269.28348-44.566925-60.472458h-44.566925'
    'l89.13385 120.9449z"/><path class="lg-pad" d="M389.88452 208.81102h39.46457v33.10237h-39.46457z"/><path class="lg-letter" '
    'd="M464.09186 210.2441h39.46457v120.94487h-39.46457z"/><path class="lg-letter" d="m581.5748 269.28348 44.566895 60.472443'
    'h44.566956l-89.13385-120.9449z"/><path class="lg-pad" d="M570.1155 329.75592h-39.46454v-33.102386h39.46454z"/><g fill="none">'
    '<path class="lg-trace" d="M409.6168 241.91339v57.606293h-31.181091"/><path class="lg-trace" d="M503.55643 270.71652h46.834625'
    'v25.952759"/><path class="lg-trace" d="M570.1155 313.2047h18.233643v-13.669281h15.498657"/><path class="lg-trace" '
    'd="M429.3491 225.3622h17.37146v45.354324h17.368683"/></g></svg>'
)


def shell(
    title: str, description: str, canonical: str, up: str, body: str, scripts: list[str], head: str = ""
) -> str:
    """A page in the site's frame: its head, its header and its footer. `up` leads back to the site's root.
    `head` is more of the head, after the canonical link: a post's share tags. A line of it that names
    %ORIGIN% goes from a build without an address (build.sh), so it holds all such tags on 1 line."""
    script_tags = "\n".join(f'    <script src="{up}{s}" defer></script>' for s in scripts)
    more = "".join(f"\n    {line}" for line in head.splitlines() if line)
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{html.escape(title)}</title>
    <meta name="description" content="{html.escape(description)}">
    <link rel="canonical" href="%ORIGIN%/{canonical}">{more}
    <link rel="icon" href="{up}favicon-32.png" sizes="32x32" type="image/png">
    <link rel="icon" href="{up}favicon.svg" type="image/svg+xml">
    <link rel="apple-touch-icon" href="{up}apple-touch-icon.png">
    <link rel="preload" href="{up}fonts/inter-latin-wght-normal.woff2" as="font" type="font/woff2" crossorigin>
    <link rel="stylesheet" href="{up}site.css">
    <meta name="theme-color" content="#fbfaf7" media="(prefers-color-scheme: light)">
    <meta name="theme-color" content="#1b1917" media="(prefers-color-scheme: dark)">
    <!-- Before first paint: the theme the address asks for, else the stored one, else the system's;
         and `motion` unless the reader asked for reduced motion or the page is a capture. -->
    <script>
      (() => {{
        const root = document.documentElement;
        const asked = new URLSearchParams(location.search);
        let stored = asked.get("theme");
        try {{
          stored = stored || localStorage.getItem("theme");
        }} catch {{}}
        const dark = stored ? stored === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
        root.classList.toggle("dark", dark);
        if (stored) for (const m of document.querySelectorAll('meta[name="theme-color"]')) m.content = dark ? "#1b1917" : "#fbfaf7";
        if (asked.get("shot")) root.dataset.shot = asked.get("shot");
        if (!asked.get("shot") && !matchMedia("(prefers-reduced-motion: reduce)").matches) {{
          root.classList.add("motion");
          setTimeout(() => root.dataset.motionReady || root.classList.remove("motion"), 3000);
        }}
      }})();
    </script>
{script_tags}
    <script>
      window.va = window.va || function () {{ (window.vaq = window.vaq || []).push(arguments); }};
    </script>
    <script defer src="/_vercel/insights/script.js"></script>
  </head>
  <body>
    <a class="skip" href="#main">Skip to content</a>

    <header class="site-header">
      <div class="progress" data-progress aria-hidden="true"></div>
      <div class="wrap">
        <a class="brand" href="{up or "./"}" aria-label="Via, home">
          {LOGO}
        </a>
        <nav class="site-nav" aria-label="Site">
          <ul>
            <li><a href="{up}index.html#herald">Example</a></li>
            <li><a href="{up}examples.html">Boards</a></li>
            <li><a href="{up}index.html#gates">Checks</a></li>
            <li><a href="{up}index.html#run">Get started</a></li>
            <li><a href="{up}blog.html">Blog</a></li>
            <li><a href="https://discord.reagent-systems.com">Community</a></li>
          </ul>
        </nav>
        <div class="header-end">
          <button class="icon-btn" type="button" data-theme-toggle aria-pressed="false" aria-label="Dark theme">
            <svg class="moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20.2 14.6A8.4 8.4 0 1 1 9.4 3.8a6.6 6.6 0 0 0 10.8 10.8Z"/></svg>
            <svg class="sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/></svg>
          </button>
          <a class="gh-pill" href="{REPO}" aria-label="Via on GitHub">
            <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="{GH_PATH}"/></svg>
            <span>GitHub</span>
          </a>
        </div>
      </div>
    </header>

    <main id="main" tabindex="-1">
{body}
    </main>

    <footer class="site-footer">
      <div class="wrap">
        <div class="row">
          <p class="brand"><a href="{up or "./"}" aria-label="Via, home">{LOGO.replace(" data-logo", "")}</a></p>
          <nav aria-label="Footer">
            <ul>
              <li><a href="{up}blog.html">Blog</a></li>
              <li><a href="{up}feedback.html">Feedback</a></li>
              <li><a href="https://discord.reagent-systems.com">Community</a></li>
              <li><a href="{REPO}">GitHub</a></li>
              <li><a href="{REPO}/blob/main/WORKCENTER.md">Contract</a></li>
              <li><a href="{REPO}/blob/main/ee-agent-kit/STATUS.md">Status</a></li>
              <li><a href="{REPO}/blob/main/ee-agent-kit/ROADMAP.md">Roadmap</a></li>
              <li><a href="{REPO}/blob/main/LICENSE">MIT License</a></li>
            </ul>
          </nav>
        </div>
        <p class="small">Via is built under the MIT License.</p>
        <p class="small made"><a href="https://reagent-systems.com">Made by Team Reagent for Builders</a></p>
      </div>
    </footer>

  </body>
</html>
"""
