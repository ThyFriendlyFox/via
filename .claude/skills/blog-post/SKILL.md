---
name: Blog Post
description: Writes a public blog post from the devlog, the changelog and the shipped roadmap items.
---

# Blog Post

Writes a public blog post about recent work. The devlog is the source.
The post is the devlog retold for a reader who does not work on the
project.

## Install

Copy this folder into the repo's skill directory (`.claude/skills/
blog-post/` for Claude Code) so `/blog-post` invokes it. In this
repository posts live in `blog/`, and `site/blog.py` makes each one a
page of the site at `/blog/<slug>`. In another repo, adjust the output
path below to where it keeps posts (`blog/`, `posts/`, or the site repo).

## Inputs

1. `DEVLOG.md` — the entries since the last post. The story.
2. `CHANGELOG.md` — the released versions in the window. The facts.
3. `ROADMAP.md` Shipped table — the promises and their evidence.
4. `docs/USE-CASES.md` — the reader's problems. Every post connects
   the work to at least one use case.

## Steps

1. Read the devlog entries since the last post. Find the one change a
   reader cares about most. That is the post's subject. One post, one
   subject.
2. Write the title: under 60 characters, names the change, no pun
   unless the human asked for puns.
3. Write the post by `docs/WEBSITE-WRITING.md` (the owner's rules for
   the website), 300–800 words:
   - **Open** with what changed for the reader, in 2 sentences.
   - **Show** it: one concrete example from a use case — commands,
     screenshots, or output. Real evidence from the shipped item.
   - **Tell** the story: what broke, what we learned, from the devlog.
     Failures stay in. Readers trust a log that admits the broken week.
   - **Close** with what is next: the top of the ROADMAP queue, stated
     as intent, not promise.
4. Save to `blog/YYYY-MM-DD-<slug>.md` with frontmatter: `title`,
   `date`, `tags`, and `description` or `image` where the first
   paragraph or the site's card does not fit. A link that starts with
   `/` names a page of the site (`/examples/herald`); a link with no
   scheme names a file in the repo.
5. Run `python3 site/blog.py`: it writes the post's page, the list of
   posts and the feed, and stops at a link that names nothing.
6. Add one devlog entry: "Published post: <title>."
7. Do not publish beyond the repo without the human's go-ahead: the
   post goes live when it reaches `main`.

## A post about an example board

The owner's ask of 2026-11-18: each example board has a post, written as
an electrical engineer who knows the theory, the science and the papers
behind the device, explains them to a reader who is a little technical:
"hey, this is a project, and how we came to make it". `docs/STYLE.md`
website rule 10 holds it.

1. Speak as "we", Team Reagent. Say once that an AI agent designed the
   board with Via from our brief. Invent no personal story: the brief,
   the owner's asks in the devlog and the rounds in the files are the
   story.
2. Open with what the device is and why we made it. Put the board's
   `card.png` alone on its line after that.
3. Give 2 to 4 sections of science, each on 1 idea the device depends on:
   how it works, the paper, standard or book it comes from (authors,
   title, venue, year), and how the board uses it. Build each idea from
   the ground up with its number, in plain words, with no staged scene
   or made-up comparison. Cite only a work that says what the post says; leave a doubtful
   one out.
4. Tell how the design went, from the example's README, TIMELINE.md,
   LOOP.md, the devlog and `MISTAKES.md`, numbers copied from the files.
5. End with what is open, then 1 or 2 sentences of intent.
6. 900 to 1300 words. Name the file `blog/YYYY-MM-DD-<board>-<words>.md`
   and set `image` to the board's card.

## Checks

- Every claim in the post traces to a devlog entry, changelog line, or
  shipped-item evidence. No claim without a source.
- No marketing words. Run the docs/STYLE.md rules over the draft.
- The website writing rules (`docs/WEBSITE-WRITING.md`): contractions,
  1 idea in a sentence, none of its ban list, and its checklist read
  before the post is shown.
- A reader who has never seen the project understands the opening
  2 sentences.
- The post names version numbers and dates as digits.
