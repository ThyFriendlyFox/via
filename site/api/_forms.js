// The rules the site's 2 forms share: what each field may hold, the file each form keeps, and the
// answer each request gets. subscribe.js and feedback.js give the file to the Blob store; the tests
// (tests/test_forms.py) give it to a store of their own. Vercel makes no function of a file in api/
// whose name starts with "_".

export const MOST = { email: 254, message: 5000 };
export const NOT_SENT = "That didn't send. Try again.";
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const text = (form, name) => {
  const value = form.get(name);
  return typeof value === "string" ? value.trim() : "";
};

export const isEmail = (value) => value.length <= MOST.email && EMAIL.test(value);

// The page that sent the form. A browser without the page's script goes back to it: a path on this
// site only, never another host.
export function from(form) {
  const path = text(form, "from");
  return /^\/(?!\/)[A-Za-z0-9/_.-]*$/.test(path) ? path : "/";
}

async function sha256(value) {
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(bytes), (b) => b.toString(16).padStart(2, "0")).join("");
}

// 1 file for each address, named by its hash: the same address twice is 1 file.
export async function subscription(form, now) {
  const email = text(form, "email");
  if (!isEmail(email)) return { error: "Enter an email address." };
  return {
    pathname: `subscribers/${await sha256(email.toLowerCase())}.json`,
    record: { email, page: from(form), at: now.toISOString() },
  };
}

// 1 file for each suggestion, named by its time and 8 random characters.
export async function suggestion(form, now) {
  const message = text(form, "message");
  const email = text(form, "email");
  if (!message) return { error: "Write a suggestion." };
  if (message.length > MOST.message) return { error: `Keep the suggestion under ${MOST.message.toLocaleString("en-US")} characters.` };
  if (email && !isEmail(email)) return { error: "Enter an email address, or leave that field empty." };
  return {
    pathname: `feedback/${now.toISOString().replace(/[:.]/g, "-")}-${crypto.randomUUID().slice(0, 8)}.json`,
    record: { message, email: email || null, page: from(form), at: now.toISOString() },
  };
}

// A form posted from a page of another site is refused.
function ours(request) {
  const origin = request.headers.get("origin");
  if (!origin) return true;
  let host;
  try {
    host = new URL(origin).host;
  } catch {
    return false;
  }
  return [request.headers.get("x-forwarded-host"), request.headers.get("host"), new URL(request.url).host].includes(host);
}

// The page's script asks for JSON and shows the answer in place. A browser without it posts the
// form and goes back to the page, at the element whose id is `done`.
export async function receive(request, read, keep, done) {
  if (request.method !== "POST") {
    return new Response("Send the form with POST.\n", { status: 405, headers: { allow: "POST" } });
  }
  const script = (request.headers.get("accept") || "").includes("application/json");
  const refuse = (status, error) =>
    script
      ? Response.json({ ok: false, error }, { status })
      : new Response(`${error}\n`, { status, headers: { "content-type": "text/plain; charset=utf-8" } });
  if (!ours(request)) return refuse(403, "Send the form from the site.");
  let form;
  try {
    form = await request.formData();
  } catch {
    return refuse(400, NOT_SENT);
  }
  const sent = () =>
    script ? Response.json({ ok: true }) : new Response(null, { status: 303, headers: { location: `${from(form)}#${done}` } });
  // A person never sees the field "website"; a program that fills each field fills it too.
  if (text(form, "website")) return sent();
  const kept = await read(form, new Date());
  if (kept.error) return refuse(400, kept.error);
  try {
    await keep(kept.pathname, `${JSON.stringify(kept.record, null, 2)}\n`);
  } catch (error) {
    console.error(`${kept.pathname}: ${error.message}`);
    return refuse(500, NOT_SENT);
  }
  return sent();
}
