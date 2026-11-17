// POST /api/feedback: keeps a reader's suggestion in the project's private Blob store, `via-forms`,
// under feedback/. The rules are in _forms.js.
import { put } from "@vercel/blob";
import { receive, suggestion } from "./_forms.js";

const keep = (pathname, body) =>
  put(pathname, body, { access: "private", contentType: "application/json", addRandomSuffix: false });

export default {
  fetch: (request) => receive(request, suggestion, keep, "sent"),
};
