"""Write the blog from its posts in blog/: a page for each post, the list of posts, and their feed.

    python3 site/blog.py            # from the repository's root
    python3 site/blog.py --check    # exit 1 when a written file is not what this script writes

A post is a Markdown file `blog/YYYY-MM-DD-<slug>.md`, as the blog-post skill writes it. It starts
with its fields between 2 `---` lines: `title`, `date` and `tags`, and, where it wants them,
`description` (else its first paragraph) and `image` (a picture the site serves, as
`/examples/herald/card.png`; else the site's own card, `og.png`). The script writes:

- `site/blog/<slug>.html`, the post at `/blog/<slug>`: the site's header and footer, the post, the
  posts before and after it, and the way back into the site: the boards, the checks, the start;
- `site/blog.html`, the list of posts at `/blog`, the newest first;
- `site/blog/feed.xml`, the posts as an RSS feed, its addresses from the site's (`build.sh`);
- `site/blog/news.json`, the newest posts for the news bar along the bottom of each page
  (`site.js`).

Each post's page carries its share card (Open Graph and X's tags) and its record for search
engines (a BlogPosting in JSON-LD), all on the line `build.sh` fills with the site's address.

The Markdown is what a post needs: `##` and `###` headings, paragraphs, lists, quotes, fenced code,
a picture alone on its line (`![alt](/path "caption")`), and `code`, **bold**, *italic* and links
in a line. A link that starts with `/` names a page of the site (`/examples/herald`); a link with
no scheme names a file in the repository, shown on GitHub; any other is left as it is. A link to
the site or the repository that names nothing stops the script.
"""

# ruff: noqa: E501 - the page's templates are HTML, with its lines as long as the site's pages'.
from __future__ import annotations

import argparse
import html
import json
import posixpath
import re
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from email.utils import format_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
POSTS = ROOT / "blog"
OUT = SITE / "blog"
sys.path.insert(0, str(SITE))

from forms import subscribe  # noqa: E402
from frame import REPO, shell  # noqa: E402

SCRIPTS = ["vendor/motion-14.6.0.js", "site.js", "effects.js"]
NAMED = re.compile(r"(\d{4}-\d{2}-\d{2})-([a-z0-9]+(?:-[a-z0-9]+)*)\.md")
CARD = ("og.png", 1280, 640, "The Via wordmark and the headline Circuit Boards From AI, beside the routed board of Herald")
BLOG = "Via blog"
ABOUT = "We're making Via better every day! Subscribe to keep up to date with our progress."
# The owner's words of 2026-11-17 to the reader, at the head of the blog and after each post.
HEADLINE = "We're making Via better every day!"
# The news bar runs the newest posts along the bottom of each page that loads site.js.
NEWS = 6
# The owner's lines of 2026-11-18, each after a post on the news bar, a link where it has one.
QUIPS = (
    ("Only Cool Kids Allowed!", None),
    ("Building Tomorrow Today!", None),
    ("We have a dog", None),
    ("Check out our community!", "https://discord.reagent-systems.com"),
    ("Free inference found here!", None),
)


def message(up: str) -> str:
    """The owner's message under the headline: the first "here" is the subscribe form under it
    (site/forms.py), the second the feedback page. `up` leads back to the site's root."""
    return (
        'Subscribe <a class="link" href="#subscribe">here</a> to keep up to date with our progress. '
        f'Give us suggestions <a class="link" href="{up}feedback.html">here</a>!'
    )
ARROW = '<svg class="arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg>'


class PostError(ValueError):
    """A post this script cannot write: a missing field, a bad name, a link to nothing."""


@dataclass
class Post:
    source: Path
    slug: str
    day: date
    title: str
    tags: list[str]
    description: str
    image: str
    body: str


# ---------------------------------------------------------------- reading


def fields(text: str, source: Path) -> tuple[dict[str, str], str]:
    """A post's fields, from between its 2 `---` lines, and the Markdown after them."""
    if not text.startswith("---\n") or "\n---\n" not in text[3:]:
        raise PostError(f"{source.name}: a post starts with its fields between 2 --- lines")
    end = text.index("\n---\n", 3)
    found = {}
    for line in text[4:end].splitlines():
        key, colon, value = line.partition(":")
        if colon:
            found[key.strip()] = value.strip().strip("\"'")
    return found, text[end + 5 :]


def plain(text: str) -> str:
    """A line of Markdown as plain text: links by their words, marks taken off."""
    text = re.sub(r"!?\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return re.sub(r"[`*]", "", text)


def first_paragraph(body: str) -> str:
    for chunk in re.split(r"\n\s*\n", body.strip()):
        if chunk and not re.match(r"#|```|!\[|[-*] |\d+\. |>", chunk.lstrip()):
            return " ".join(line.strip() for line in chunk.splitlines())
    return ""


def summary(text: str, most: int = 200) -> str:
    """The text whole if it fits in `most` characters, else its sentences that do."""
    if len(text) <= most:
        return text
    cut = text[:most]
    end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    return cut[: end + 1] if end > 0 else cut.rsplit(" ", 1)[0] + " …"


def read(source: Path) -> Post:
    named = NAMED.fullmatch(source.name)
    if not named:
        raise PostError(f"{source.name}: a post is named YYYY-MM-DD-<slug>.md, the slug in lower case")
    found, body = fields(source.read_text(encoding="utf-8"), source)
    for key in ("title", "date", "tags"):
        if not found.get(key):
            raise PostError(f"{source.name}: the field {key} is missing")
    if found["date"] != named.group(1):
        raise PostError(f"{source.name}: the date {found['date']} is not the one in its name")
    tags = [t.strip() for t in found["tags"].strip("[]").split(",") if t.strip()]
    description = found.get("description") or summary(plain(first_paragraph(body)))
    return Post(
        source=source,
        slug=named.group(2),
        day=date.fromisoformat(found["date"]),
        title=found["title"],
        tags=tags,
        description=description,
        image=found.get("image", ""),
        body=body,
    )


def posts() -> list[Post]:
    """Every post, the newest first."""
    found = [read(p) for p in sorted(POSTS.glob("*.md")) if p.name != "README.md"]
    slugs = [p.slug for p in found]
    for slug in slugs:
        if slugs.count(slug) > 1:
            raise PostError(f"2 posts have the slug {slug}: each post's address is its own")
    return sorted(found, key=lambda p: (p.day, p.slug), reverse=True)


# ---------------------------------------------------------------- Markdown


def href(target: str, up: str) -> str:
    """Where a post's link leads, read from the page at `up` below the site's root."""
    target = html.unescape(target)
    if re.match(r"[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
        return target
    path, _, fragment = target.partition("#")
    fragment = f"#{fragment}" if fragment else ""
    if target.startswith("/"):
        page = path.strip("/")
        if not page:
            return f"{up}index.html{fragment}" if fragment else (up or "./")
        if (SITE / page).is_file():
            return f"{up}{page}{fragment}"
        if (SITE / f"{page}.html").is_file():
            return f"{up}{page}.html{fragment}"
        raise PostError(f"{target}: the site has no such page")
    rel = posixpath.normpath(path)
    if rel.startswith("..") or not (ROOT / rel).exists():
        raise PostError(f"{target}: the repository has no such file")
    kind = "tree" if (ROOT / rel).is_dir() else "blob"
    return f"{REPO}/{kind}/main/{rel}{fragment}"


def marks(text: str) -> str:
    """`code`, **bold** and *italic*; the rest escaped."""
    out = []
    for part in re.split(r"(`[^`]+`)", text):
        if len(part) > 1 and part[0] == part[-1] == "`":
            out.append(f"<code>{html.escape(part[1:-1], quote=False)}</code>")
            continue
        part = html.escape(part, quote=False)
        part = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", part)
        part = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", part)
        out.append(part)
    return "".join(out)


def inline(text: str, up: str) -> str:
    """A line of Markdown as HTML: its links first, so a link's words may hold `code`."""
    links: list[str] = []

    def keep(m: re.Match) -> str:
        links.append(f'<a class="link" href="{html.escape(href(m.group(2), up))}">{marks(m.group(1))}</a>')
        return f"\x00{len(links) - 1}\x00"

    text = re.sub(r"(?<!!)\[([^\]]+)\]\(([^)\s]+)\)", keep, text)
    return re.sub(r"\x00(\d+)\x00", lambda m: links[int(m.group(1))], marks(text))


def anchor(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", plain(text).lower()).strip("-")


def png_size(path: Path) -> tuple[int, int] | None:
    data = path.read_bytes()[:24]
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def picture(alt: str, src: str, caption: str, up: str) -> str:
    """A picture alone on its line: a file the site serves, at its own size."""
    if not src.startswith("/") or not (SITE / src.strip("/")).is_file():
        raise PostError(f"{src}: a post's picture is a file the site serves, named from its root")
    size = png_size(SITE / src.strip("/"))
    dims = f' width="{size[0]}" height="{size[1]}"' if size else ""
    shown = f"<figcaption>{inline(caption, up)}</figcaption>" if caption else ""
    return f'<figure class="post-figure"><img src="{up}{src.strip("/")}"{dims} loading="lazy" decoding="async" alt="{html.escape(alt)}">{shown}</figure>'


LIST = re.compile(r"([-*]|\d+\.) +(.*)")
PICTURE = re.compile(r'!\[([^\]]*)\]\(([^)\s]+)(?: +"([^"]*)")?\)')


def render(body: str, up: str) -> str:
    """A post's Markdown as HTML, block by block."""
    lines = body.strip("\n").splitlines()
    out: list[str] = []
    i = 0

    def starts_block(line: str) -> bool:
        return bool(re.match(r"#{1,3} |```|> ?|([-*]|\d+\.) ", line)) or bool(PICTURE.fullmatch(line.strip()))

    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
        elif line.startswith("```"):
            language = line[3:].strip()
            i += 1
            code = []
            while i < len(lines) and not lines[i].startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1
            label = f' data-language="{html.escape(language)}"' if language else ""
            out.append(f"<pre{label}><code>{html.escape(chr(10).join(code), quote=False)}</code></pre>")
        elif m := re.match(r"(#{1,3}) +(.*)", line):
            level = 3 if len(m.group(1)) == 3 else 2
            out.append(f'<h{level} id="{anchor(m.group(2))}">{inline(m.group(2), up)}</h{level}>')
            i += 1
        elif m := PICTURE.fullmatch(line.strip()):
            out.append(picture(m.group(1), m.group(2), m.group(3) or "", up))
            i += 1
        elif line.startswith(">"):
            quoted = []
            while i < len(lines) and lines[i].startswith(">"):
                quoted.append(lines[i][1:].strip())
                i += 1
            out.append(f"<blockquote><p>{inline(' '.join(quoted), up)}</p></blockquote>")
        elif m := LIST.match(line):
            tag = "ol" if m.group(1)[0].isdigit() else "ul"
            items: list[str] = []
            while i < len(lines) and (LIST.match(lines[i]) or (items and lines[i].startswith("  ") and lines[i].strip())):
                item = LIST.match(lines[i])
                if item:
                    items.append(item.group(2).strip())
                else:
                    items[-1] += " " + lines[i].strip()
                i += 1
            out.append(f"<{tag}>" + "".join(f"<li>{inline(item, up)}</li>" for item in items) + f"</{tag}>")
        else:
            words = []
            while i < len(lines) and lines[i].strip() and not (words and starts_block(lines[i])):
                words.append(lines[i].strip())
                i += 1
            out.append(f"<p>{inline(' '.join(words), up)}</p>")
    return "\n".join(out)


# ---------------------------------------------------------------- pages


def shown(day: date) -> str:
    return f"{day.day} {day.strftime('%B')} {day.year}"


def card(post: Post) -> tuple[str, int, int, str]:
    """The post's share card: its own picture, or the site's."""
    if not post.image:
        return CARD
    src = post.image.strip("/")
    size = png_size(SITE / src) if (SITE / src).is_file() else None
    if not size:
        raise PostError(f"{post.source.name}: its image {post.image} is not a PNG the site serves")
    return src, size[0], size[1], post.title


def share(kind: str, title: str, description: str, canonical: str, image: tuple[str, int, int, str], extra: str = "") -> str:
    """The share card's tags and the page's record, on 1 line: build.sh fills %ORIGIN% on it, or
    drops it whole from a build with no address."""
    src, width, height, alt = image
    tags = [
        f'<meta property="og:type" content="{kind}">',
        '<meta property="og:site_name" content="Via">',
        f'<meta property="og:title" content="{html.escape(title)}">',
        f'<meta property="og:description" content="{html.escape(description)}">',
        f'<meta property="og:url" content="%ORIGIN%/{canonical}">',
        f'<meta property="og:image" content="%ORIGIN%/{src}">',
        '<meta property="og:image:type" content="image/png">',
        f'<meta property="og:image:width" content="{width}">',
        f'<meta property="og:image:height" content="{height}">',
        f'<meta property="og:image:alt" content="{html.escape(alt)}">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:image" content="%ORIGIN%/{src}">',
        f'<meta name="twitter:image:alt" content="{html.escape(alt)}">',
        f'<link rel="alternate" type="application/rss+xml" title="{BLOG}" href="%ORIGIN%/blog/feed.xml">',
    ]
    return "".join(tags) + extra


def post_page(post: Post, newer: Post | None, older: Post | None) -> str:
    up = "../"
    canonical = f"blog/{post.slug}"
    image = card(post)
    record = {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": post.title,
        "description": post.description,
        "datePublished": post.day.isoformat(),
        "dateModified": post.day.isoformat(),
        "keywords": post.tags,
        "image": f"%ORIGIN%/{image[0]}",
        "url": f"%ORIGIN%/{canonical}",
        "mainEntityOfPage": f"%ORIGIN%/{canonical}",
        "isPartOf": {"@type": "Blog", "name": BLOG, "url": "%ORIGIN%/blog"},
        "author": {"@type": "Organization", "name": "Via", "url": "%ORIGIN%/"},
        "publisher": {
            "@type": "Organization",
            "name": "Via",
            "url": "%ORIGIN%/",
            "logo": {"@type": "ImageObject", "url": "%ORIGIN%/apple-touch-icon.png"},
        },
    }
    extra = f'<meta property="article:published_time" content="{post.day.isoformat()}">'
    extra += "".join(f'<meta property="article:tag" content="{html.escape(t)}">' for t in post.tags)
    extra += '<script type="application/ld+json">' + json.dumps(record, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/") + "</script>"
    tags = "".join(f"<li>{html.escape(t)}</li>" for t in post.tags)
    around = []
    if older:
        around.append(f'<a class="older" href="{older.slug}.html"><span>Older post</span>{html.escape(older.title)}</a>')
    around.append(f'<a class="all" href="{up}blog.html"><span>Blog</span>All posts</a>')
    if newer:
        around.append(f'<a class="newer" href="{newer.slug}.html"><span>Newer post</span>{html.escape(newer.title)}</a>')
    body = f"""      <article class="section post" aria-labelledby="post-title">
        <div class="wrap">
          <header class="post-head" data-reveal data-stagger>
            <p class="eyebrow"><a class="crumb" href="{up}blog.html">Blog</a> · <time datetime="{post.day.isoformat()}">{shown(post.day)}</time></p>
            <h1 class="title post-title" id="post-title">{html.escape(post.title)}</h1>
            <ul class="chips" aria-label="Tags">{tags}</ul>
          </header>
          <div class="prose">
{render(post.body, up)}
          </div>
        </div>
      </article>

      <section class="section band post-after" aria-labelledby="after-title">
        <div class="wrap">
          <div class="head" data-reveal data-stagger>
            <p class="eyebrow">Via</p>
            <h2 class="title" id="after-title">{HEADLINE}</h2>
            <p class="lede message">{message(up)}</p>
{subscribe(f"/{canonical}", "            ")}
          </div>
          <div class="actions" data-reveal>
            <a class="btn btn-primary" href="{up}index.html#run">Get started</a>
            <a class="btn btn-quiet" href="{up}examples.html">See the example boards {ARROW}</a>
            <a class="btn btn-quiet" href="{up}index.html#gates">See the four checks {ARROW}</a>
          </div>
          <nav class="post-nav" aria-label="More posts" data-reveal>{"".join(around)}</nav>
        </div>
      </section>"""
    return shell(
        f"{post.title} · {BLOG}",
        post.description,
        canonical,
        up,
        body,
        SCRIPTS,
        share("article", post.title, post.description, canonical, image, extra),
    )


def index_page(found: list[Post]) -> str:
    items = []
    for post in found:
        tags = "".join(f"<li>{html.escape(t)}</li>" for t in post.tags)
        items.append(
            f'<li><a class="post-card" href="blog/{post.slug}.html"><time datetime="{post.day.isoformat()}">{shown(post.day)}</time>'
            f"<h2>{html.escape(post.title)}</h2><p>{html.escape(post.description)}</p>"
            f'<ul class="chips" aria-label="Tags">{tags}</ul></a></li>'
        )
    listed = "\n".join(f"            {item}" for item in items) or '            <li class="none">There are no posts.</li>'
    body = f"""      <section class="section" aria-labelledby="blog-title">
        <div class="wrap">
          <div class="head" data-reveal data-stagger>
            <p class="eyebrow">Blog</p>
            <h1 class="title" id="blog-title">{HEADLINE}</h1>
            <p class="lede message">{message("")}</p>
{subscribe("/blog", "            ")}
          </div>
          <ol class="posts" data-reveal data-stagger>
{listed}
          </ol>
        </div>
      </section>"""
    return shell(BLOG, ABOUT, "blog", "", body, SCRIPTS, share("website", BLOG, ABOUT, "blog", CARD))


def feed(found: list[Post]) -> str:
    """The posts as RSS 2.0, the newest first. Its addresses wait for build.sh's %ORIGIN%."""

    def stamp(day: date) -> str:
        return format_datetime(datetime(day.year, day.month, day.day, tzinfo=UTC))

    items = []
    for post in found:
        categories = "".join(f"\n      <category>{html.escape(t)}</category>" for t in post.tags)
        items.append(
            f"""    <item>
      <title>{html.escape(post.title)}</title>
      <link>%ORIGIN%/blog/{post.slug}</link>
      <guid isPermaLink="true">%ORIGIN%/blog/{post.slug}</guid>
      <pubDate>{stamp(post.day)}</pubDate>{categories}
      <description>{html.escape(post.description)}</description>
    </item>"""
        )
    built = f"\n    <lastBuildDate>{stamp(found[0].day)}</lastBuildDate>" if found else ""
    return f"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{BLOG}</title>
    <link>%ORIGIN%/blog</link>
    <atom:link href="%ORIGIN%/blog/feed.xml" rel="self" type="application/rss+xml"/>
    <description>{html.escape(ABOUT)}</description>
    <language>en</language>{built}
{chr(10).join(items)}
  </channel>
</rss>
"""


def news(found: list[Post]) -> str:
    """The newest posts as the news bar reads them, each its words and its address on the site, with
    the owner's lines between them. Lines left over after the last post follow it."""
    items = []
    posts_shown = found[:NEWS]
    for i in range(max(len(posts_shown), len(QUIPS))):
        if i < len(posts_shown):
            items.append({"text": f"New post: {posts_shown[i].title}", "href": f"/blog/{posts_shown[i].slug}"})
        if i < len(QUIPS):
            words, link = QUIPS[i]
            items.append({"text": words, **({"href": link} if link else {})})
    return json.dumps({"items": items}, ensure_ascii=False, indent=1) + "\n"


def pages() -> dict[Path, str]:
    """Every file this script writes, with its text."""
    found = posts()
    written = {SITE / "blog.html": index_page(found), OUT / "feed.xml": feed(found), OUT / "news.json": news(found)}
    for i, post in enumerate(found):
        newer = found[i - 1] if i > 0 else None
        older = found[i + 1] if i + 1 < len(found) else None
        written[OUT / f"{post.slug}.html"] = post_page(post, newer, older)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 when a written file differs from the committed one")
    args = parser.parse_args()
    try:
        written = pages()
    except PostError as error:
        print(f"site/blog.py: {error}", file=sys.stderr)
        return 1
    # A post taken out of blog/ takes its page with it.
    stale = [p for p in OUT.glob("*.html") if p not in written] if OUT.is_dir() else []
    if args.check:
        wrong = [p for p, text in written.items() if not p.is_file() or p.read_text(encoding="utf-8") != text]
        for p in wrong:
            print(f"{p.relative_to(ROOT)}: not what site/blog.py writes; run it again", file=sys.stderr)
        for p in stale:
            print(f"{p.relative_to(ROOT)}: no post in blog/ writes it; run site/blog.py again", file=sys.stderr)
        return 1 if wrong or stale else 0
    for p in stale:
        p.unlink()
        print(f"{p.relative_to(ROOT)}: removed, its post is gone")
    for path, text in written.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"{path.relative_to(ROOT)}: {len(text) // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
