// POST /api/subscribe: keeps a reader's email address in the project's private Blob store,
// `via-forms`, under subscribers/. The rules are in _forms.js.
import { put } from "@vercel/blob";
import { receive, subscription } from "./_forms.js";

const keep = (pathname, body) =>
  put(pathname, body, { access: "private", contentType: "application/json", addRandomSuffix: false, allowOverwrite: true });

export default {
  fetch: (request) => receive(request, subscription, keep, "subscribed"),
};
