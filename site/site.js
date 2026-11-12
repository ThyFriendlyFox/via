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
