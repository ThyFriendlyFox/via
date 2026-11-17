# Blog posts

Each post is a Markdown file named `YYYY-MM-DD-<slug>.md`. The `blog-post` skill
(`.claude/skills/blog-post/SKILL.md`) writes one from the devlog, and `site/blog.py`
makes it a page of the site at `/blog/<slug>`, with the list of posts at `/blog` and an
RSS feed. `site/README.md`, "A new post", says what a post holds and how to build it.

A post reaches the site when it reaches `main`.
