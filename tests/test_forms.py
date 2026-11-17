"""The site's forms keep what a reader sends (site/forms.py, site/api/).

The subscribe form under the blog's message and the feedback page post to 2 functions, which keep
each form as a file in the project's private Blob store. These tests run the functions' rules
(`site/api/_forms.js`) in Node with a store of their own, and hold each page's form to the fields
the rules read. A field renamed on one side only loses every form a reader sends, with no error.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
API = SITE / "api"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node runs the forms' functions")

# 1 request to a function's rules: the store keeps each file in a list, or fails when asked to.
DRIVER = """
const { pathToFileURL } = await import("node:url");
const forms = await import(pathToFileURL(process.env.FORMS_API + "/_forms.js").href);
const c = JSON.parse(process.env.FORMS_CASE);
const kept = [];
const keep = async (pathname, body) => {
  if (c.fail) throw new Error("the store is down");
  kept.push({ pathname, record: JSON.parse(body) });
};
const init = { method: c.method, headers: { host: "via.computer", ...c.headers } };
if (c.method === "POST") init.body = new URLSearchParams(c.fields);
const [read, done] = c.form === "subscribe" ? [forms.subscription, "subscribed"] : [forms.suggestion, "sent"];
const request = new Request(`https://via.computer/api/${c.form}`, init);
const response = await forms.receive(request, read, keep, done);
const body = await response.text();
const location = response.headers.get("location");
console.log(JSON.stringify({ status: response.status, location, body, kept }));
"""


def send(
    form: str,
    fields: dict[str, str],
    *,
    script: bool = True,
    origin: str | None = "https://via.computer",
    method: str = "POST",
    fail: bool = False,
) -> dict:
    headers = {"accept": "application/json"} if script else {}
    if origin:
        headers["origin"] = origin
    case = {"form": form, "fields": fields, "headers": headers, "method": method, "fail": fail}
    proc = subprocess.run(
        [NODE, "--input-type=module", "-e", DRIVER],
        env={**os.environ, "FORMS_API": str(API), "FORMS_CASE": json.dumps(case)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    answer = json.loads(proc.stdout)
    if script and answer["body"]:
        answer["json"] = json.loads(answer["body"])
    return answer


def test_the_feedback_page_is_what_site_forms_writes():
    proc = subprocess.run(
        [sys.executable, str(SITE / "forms.py"), "--check"], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stderr


def test_each_form_posts_the_fields_its_function_reads():
    """Each page's form names its function, the fields `_forms.js` reads, the hidden field a person
    never fills, its own path for a browser without the script, and its thank-you line."""
    wanted = {
        "subscribe": ("subscribed", {"email", "website", "from"}),
        "feedback": ("sent", {"message", "email", "website", "from"}),
    }
    pages = [SITE / "feedback.html", SITE / "blog.html", *sorted((SITE / "blog").glob("*.html"))]
    seen = set()
    for page in pages:
        text = page.read_text(encoding="utf-8")
        path = "/" + re.search(r'<link rel="canonical" href="%ORIGIN%/([^"]*)">', text).group(1)
        (form,) = re.findall(r'<form [^>]*action="/api/(\w+)".*?</form>', text, re.S)
        done, names = wanted[form]
        whole = re.search(r"<form .*?</form>", text, re.S).group(0)
        assert f'data-form="{done}"' in whole and f'id="{done}"' in text, page.name
        assert set(re.findall(r'name="(\w+)"', whole)) == names, page.name
        assert f'<input type="hidden" name="from" value="{path}">' in whole, page.name
        assert re.search(r'<p class="trap" aria-hidden="true"><label>Website <input name="website"', whole)
        seen.add(form)
    assert seen == set(wanted)
    for form, (done, _) in wanted.items():
        rule = "subscription" if form == "subscribe" else "suggestion"
        code = (API / f"{form}.js").read_text(encoding="utf-8")
        assert f'receive(request, {rule}, keep, "{done}")' in code and 'access: "private"' in code


def test_the_functions_pin_their_one_dependency():
    package = json.loads((SITE / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((SITE / "package-lock.json").read_text(encoding="utf-8"))
    (version,) = package["dependencies"].values()
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), "a range lets a build take a version no test ran"
    assert lock["packages"]["node_modules/@vercel/blob"]["version"] == version


@needs_node
def test_a_subscription_keeps_1_file_for_each_address():
    first = send("subscribe", {"email": " Reader@Example.com ", "from": "/blog"})
    again = send("subscribe", {"email": "reader@example.com", "from": "/blog/herald-fire-alarm-communicator"})
    assert first["status"] == again["status"] == 200 and first["json"] == {"ok": True}
    (kept,) = first["kept"]
    assert re.fullmatch(r"subscribers/[0-9a-f]{64}\.json", kept["pathname"])
    assert again["kept"][0]["pathname"] == kept["pathname"]
    assert kept["record"]["email"] == "Reader@Example.com" and kept["record"]["page"] == "/blog"


@needs_node
def test_a_suggestion_keeps_its_words_and_an_email_only_when_given():
    alone = send("feedback", {"message": "Route the USB pairs first.", "from": "/feedback"})
    (kept,) = alone["kept"]
    assert re.fullmatch(r"feedback/\d{4}-\d\d-\d\dT[\d-]+Z-[0-9a-f]{8}\.json", kept["pathname"])
    assert kept["record"]["message"] == "Route the USB pairs first." and kept["record"]["email"] is None
    signed = send("feedback", {"message": "More boards.", "email": "a@example.com", "from": "/feedback"})
    assert signed["kept"][0]["record"]["email"] == "a@example.com"


@needs_node
def test_a_form_that_is_not_whole_keeps_nothing_and_says_why():
    for form, fields, error in (
        ("subscribe", {"email": "nope"}, "Enter an email address."),
        ("subscribe", {"email": "a@" + "b" * 250 + ".com"}, "Enter an email address."),
        ("feedback", {"message": "  "}, "Write a suggestion."),
        ("feedback", {"message": "x" * 5001}, "Write the suggestion in 5000 characters or fewer."),
        ("feedback", {"message": "Hi", "email": "nope"}, "Enter an email address, or leave the email empty."),
    ):
        answer = send(form, fields)
        assert (answer["status"], answer["json"], answer["kept"]) == (400, {"ok": False, "error": error}, [])


@needs_node
def test_a_browser_without_the_script_goes_back_to_the_thank_you_line():
    for given, back in (
        ("/blog", "/blog"),
        ("//elsewhere.example/x", "/"),
        ("https://elsewhere.example", "/"),
    ):
        answer = send("subscribe", {"email": "a@example.com", "from": given}, script=False)
        assert (answer["status"], answer["location"]) == (303, f"{back}#subscribed")
    answer = send("feedback", {"message": "Hi", "from": "/feedback"}, script=False)
    assert (answer["status"], answer["location"]) == (303, "/feedback#sent")
    refused = send("subscribe", {"email": "nope"}, script=False)
    assert (refused["status"], refused["body"]) == (400, "Enter an email address.\n")


@needs_node
def test_a_program_or_another_site_keeps_nothing():
    trapped = send("subscribe", {"email": "a@example.com", "website": "https://spam.example"})
    assert (trapped["status"], trapped["json"], trapped["kept"]) == (200, {"ok": True}, [])
    foreign = send("feedback", {"message": "Hi"}, origin="https://elsewhere.example")
    assert (foreign["status"], foreign["kept"]) == (403, [])
    assert send("subscribe", {}, method="GET", script=False)["status"] == 405


@needs_node
def test_a_store_that_fails_tells_the_reader_to_try_again():
    answer = send("subscribe", {"email": "a@example.com"}, fail=True)
    assert (answer["status"], answer["json"]) == (
        500,
        {"ok": False, "error": "The form did not send. Try again."},
    )
