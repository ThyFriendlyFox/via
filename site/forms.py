"""The site's forms: the subscribe form under the blog's message, and the feedback page.

    python3 site/forms.py          # write site/feedback.html
    python3 site/forms.py --check  # exit 1 when site/feedback.html is not what this writes

site/blog.py puts `subscribe(page)` under the owner's message. Each form posts to a function in
`site/api/` (`subscribe.js`, `feedback.js`), which keeps what the reader sends in the project's
private Blob store, `via-forms`. The field names here are the ones `site/api/_forms.js` reads.
site.js sends a form and shows the answer in place. Without site.js, the browser posts the form,
and the function sends the reader back to the page, at the form's thank-you line.
"""

# ruff: noqa: E501 - the page's templates are HTML, with its lines as long as the site's pages'.
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
sys.path.insert(0, str(SITE))

from frame import shell  # noqa: E402

SCRIPTS = ["vendor/motion-14.6.0.js", "site.js", "effects.js"]
FEEDBACK = SITE / "feedback.html"
# A person never sees this field, and _forms.js drops a form that fills it.
TRAP = '<p class="trap" aria-hidden="true"><label>Website <input name="website" tabindex="-1" autocomplete="off"></label></p>'


def subscribe(page: str, indent: str) -> str:
    """The subscribe form for the page at the site's path `page` (`/blog`), each line at `indent`."""
    lines = [
        '<form class="form subscribe" id="subscribe" action="/api/subscribe" method="post" data-form="subscribed">',
        '  <label class="sr-only" for="subscribe-email">Email</label>',
        '  <div class="form-row">',
        '    <input id="subscribe-email" name="email" type="email" autocomplete="email" maxlength="254" placeholder="Email" required>',
        '    <button class="btn btn-primary" type="submit">Subscribe</button>',
        "  </div>",
        f"  {TRAP}",
        f'  <input type="hidden" name="from" value="{page}">',
        '  <p class="form-error" data-form-error role="alert" hidden></p>',
        "</form>",
        '<p class="form-done" id="subscribed" tabindex="-1">Thank you. You are subscribed.</p>',
    ]
    return "\n".join(indent + line for line in lines)


def feedback_page() -> str:
    body = f"""      <section class="section" aria-labelledby="feedback-title">
        <div class="wrap">
          <div class="head" data-reveal data-stagger>
            <p class="eyebrow">Feedback</p>
            <h1 class="title" id="feedback-title">Give us suggestions</h1>
          </div>
          <form class="form feedback" id="feedback" action="/api/feedback" method="post" data-form="sent">
            <label for="feedback-message">Suggestion</label>
            <textarea id="feedback-message" name="message" rows="8" maxlength="5000" required></textarea>
            <label for="feedback-email">Email <span>(optional)</span></label>
            <input id="feedback-email" name="email" type="email" autocomplete="email" maxlength="254">
            {TRAP}
            <input type="hidden" name="from" value="/feedback">
            <p class="form-error" data-form-error role="alert" hidden></p>
            <button class="btn btn-primary" type="submit">Send</button>
          </form>
          <p class="form-done" id="sent" tabindex="-1">Thank you. We got your suggestion.</p>
        </div>
      </section>"""
    return shell("Feedback · Via", "Give us suggestions for Via.", "feedback", "", body, SCRIPTS)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 when feedback.html differs from what this writes")
    args = parser.parse_args()
    text = feedback_page()
    if args.check:
        if FEEDBACK.is_file() and FEEDBACK.read_text(encoding="utf-8") == text:
            return 0
        print(f"{FEEDBACK.relative_to(ROOT)}: not what site/forms.py writes; run it again", file=sys.stderr)
        return 1
    FEEDBACK.write_text(text, encoding="utf-8")
    print(f"{FEEDBACK.relative_to(ROOT)}: {len(text) // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
