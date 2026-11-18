// The page's script: the theme button, the copy button and the agents' strip. effects.js holds the
// rest of the motion, and the page reads the same without either.

(() => {
  const root = document.documentElement;
  const metas = document.querySelectorAll('meta[name="theme-color"]');

  const toggle = document.querySelector("[data-theme-toggle]");
  const show = () => {
    const dark = root.classList.contains("dark");
    if (toggle) toggle.setAttribute("aria-pressed", String(dark));
  };
  show();
  if (toggle) {
    toggle.addEventListener("click", () => {
      const dark = !root.classList.contains("dark");
      // The swap is instant: no transition paints the old colours over the new.
      root.classList.add("theme-switching");
      root.classList.toggle("dark", dark);
      for (const m of metas) m.content = dark ? "#1b1917" : "#fbfaf7";
      try {
        localStorage.setItem("theme", dark ? "dark" : "light");
      } catch {}
      show();
      requestAnimationFrame(() => requestAnimationFrame(() => root.classList.remove("theme-switching")));
    });
  }

  // Without a stored choice the page follows the system while it is open.
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (e) => {
    let stored = null;
    try {
      stored = localStorage.getItem("theme");
    } catch {}
    if (stored) return;
    root.classList.toggle("dark", e.matches);
    show();
  });

  // A form (site/forms.py) sends its fields to its function and shows the answer in place: the
  // thank-you line whose id its data-form names, or the function's error under the fields.
  for (const form of document.querySelectorAll("[data-form]")) {
    const done = document.getElementById(form.dataset.form);
    const error = form.querySelector("[data-form-error]");
    const button = form.querySelector('button[type="submit"]');
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      button.disabled = true;
      error.hidden = true;
      let answer = null;
      try {
        const response = await fetch(form.action, {
          method: "POST",
          body: new FormData(form),
          headers: { accept: "application/json" },
        });
        answer = await response.json();
      } catch {}
      button.disabled = false;
      if (answer?.ok) {
        form.hidden = true;
        done.dataset.shown = "";
        done.focus();
        return;
      }
      error.textContent = answer?.error || "That didn't go through. Could you try again?";
      error.hidden = false;
    });
  }

  // A link to a form puts the cursor in its first field. The jump to the form's id alone would leave
  // the focus on the page.
  for (const link of document.querySelectorAll('a[href^="#"]')) {
    const form = document.getElementById(link.getAttribute("href").slice(1));
    const field = form?.tagName === "FORM" && form.querySelector("input, textarea");
    if (!field) continue;
    link.addEventListener("click", (e) => {
      e.preventDefault();
      field.focus();
    });
  }

  // The news bar: the newest posts (blog/news.json, from site/blog.py) run along the bottom of the
  // screen, and the button to the community stays at its right. The posts rest under a pointer or the
  // focus; a reader who asks for reduced motion scrolls them by hand. No file, no bar.
  if (!root.dataset.shot) {
    fetch("/blog/news.json")
      .then((r) => (r.ok ? r.json() : null))
      .then((news) => {
        const items = news?.items || [];
        if (!items.length) return;
        const list = document.createElement("ul");
        list.className = "ticker-items";
        const add = (repeat) => {
          for (const item of items) {
            // A post is a link; one of the owner's lines is a link only where it names one.
            const li = document.createElement("li");
            const words = document.createElement(item.href ? "a" : "span");
            if (item.href) words.href = item.href;
            words.textContent = item.text;
            if (repeat) {
              li.setAttribute("aria-hidden", "true");
              if (item.href) words.tabIndex = -1;
            }
            li.append(words);
            list.append(li);
          }
        };
        add(false);
        const view = document.createElement("div");
        view.className = "ticker-view";
        const track = document.createElement("div");
        track.className = "ticker-track";
        track.append(list);
        view.append(track);
        const join = document.createElement("a");
        join.className = "btn btn-primary";
        join.href = "https://discord.reagent-systems.com";
        join.textContent = "Join the community";
        const bar = document.createElement("aside");
        bar.className = "ticker";
        bar.setAttribute("aria-label", "News");
        bar.append(view, join);
        document.body.append(bar);
        root.classList.add("has-ticker");
        // The track holds the list twice and moves by one list's width, so the second takes the first's
        // place unseen. One list is at least as wide as the screen, or a gap would show at the loop.
        for (let i = 0; i < 12 && list.scrollWidth < Math.max(view.clientWidth, screen.width); i++) add(true);
        const copy = list.cloneNode(true);
        copy.setAttribute("aria-hidden", "true");
        for (const a of copy.querySelectorAll("a")) a.tabIndex = -1;
        track.append(copy);
        // 60 px a second, whatever the list's length.
        track.style.setProperty("--ticker-time", `${Math.round(list.scrollWidth / 60)}s`);
      })
      .catch(() => {});
  }

  for (const button of document.querySelectorAll("[data-copy]")) {
    button.addEventListener("click", async () => {
      const pre = (button.closest("[data-copyable]") || button.parentElement).querySelector("pre");
      // The commands without their prompts, 1 per line.
      const text = pre.textContent
        .split("\n")
        .map((line) => line.replace(/^\$ /, ""))
        .join("\n");
      try {
        await navigator.clipboard.writeText(text);
      } catch {
        return;
      }
      button.setAttribute("data-copied", "");
      setTimeout(() => button.removeAttribute("data-copied"), 1500);
    });
  }

  // The agents' strip drifts sideways, a copy's width in 80 s, as 2 copies side by side: passing the
  // first copy's width puts it back at the start unseen. It rests while a mouse is over it, a finger
  // is on it or focus is in it, and while it is off screen. A mouse drags it, a finger or a trackpad
  // swipes it, and the arrow keys move it once focused. A reader who asked for less motion, and a
  // capture, get 1 still copy that scrolls the same ways.
  const SECONDS = 80;
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches || Boolean(root.dataset.shot);
  for (const strip of document.querySelectorAll("[data-strip]")) {
    const list = strip.querySelector("ul");
    if (!list) continue;
    if (!still) {
      const copy = list.cloneNode(true);
      copy.setAttribute("aria-hidden", "true");
      strip.append(copy);
    }
    const width = () => list.getBoundingClientRect().width;
    let resting = false;
    let visible = false;
    let frame = 0;
    let last = 0;
    let pos = strip.scrollLeft;

    const tick = (now) => {
      const dt = last ? Math.min(now - last, 100) : 0;
      last = now;
      // Someone else moved it (a swipe, a drag, the keys): follow them rather than fight.
      if (Math.abs(strip.scrollLeft - pos) > 1.5) pos = strip.scrollLeft;
      pos += (width() / SECONDS) * (dt / 1000);
      if (pos >= width()) pos -= width();
      strip.scrollLeft = pos;
      frame = requestAnimationFrame(tick);
    };
    const drift = () => {
      const moving = !still && visible && !resting;
      if (moving && !frame) {
        last = 0;
        pos = strip.scrollLeft;
        frame = requestAnimationFrame(tick);
      } else if (!moving && frame) {
        cancelAnimationFrame(frame);
        frame = 0;
      }
    };
    new IntersectionObserver(([entry]) => {
      visible = Boolean(entry && entry.isIntersecting);
      drift();
    }).observe(strip);
    const rest = (on) => () => {
      resting = on;
      drift();
    };
    strip.addEventListener("pointerenter", rest(true));
    strip.addEventListener("pointerleave", rest(false));
    strip.addEventListener("focusin", rest(true));
    strip.addEventListener("focusout", rest(false));
    strip.addEventListener("touchstart", rest(true), { passive: true });
    strip.addEventListener("touchend", () => setTimeout(rest(false), 1200), { passive: true });

    // A mouse drags it; past either end it comes round again.
    let from = null;
    let start = 0;
    strip.addEventListener("pointerdown", (e) => {
      if (e.pointerType !== "mouse" || e.button !== 0) return;
      from = e.clientX;
      start = strip.scrollLeft;
      strip.setPointerCapture(e.pointerId);
      strip.dataset.dragging = "";
    });
    strip.addEventListener("pointermove", (e) => {
      if (from === null) return;
      let x = start - (e.clientX - from);
      if (!still) x = ((x % width()) + width()) % width();
      strip.scrollLeft = x;
    });
    const drop = () => {
      from = null;
      delete strip.dataset.dragging;
    };
    strip.addEventListener("pointerup", drop);
    strip.addEventListener("pointercancel", drop);

    strip.addEventListener("keydown", (e) => {
      const step = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
      if (!step) return;
      e.preventDefault();
      strip.scrollBy({ left: step * 104, behavior: still ? "auto" : "smooth" });
    });
  }
})();
