// The page's motion, with Motion (motion.dev, vendor/). The page reads the same without it: every
// element starts where it ends, and the head's script adds `motion` to <html> only when the reader
// has not asked for reduced motion. This file removes it again if Motion did not load.

(() => {
  const root = document.documentElement;
  root.dataset.motionReady = "1";

  // ---- the mode knob: works with or without Motion --------------------------------------------
  const face = document.querySelector("[data-face]");
  const tabs = [...document.querySelectorAll("[data-mode]")];
  const readout = document.querySelector("[data-readout]");
  const M = window.Motion;
  const moving = root.classList.contains("motion") && M;
  if (root.classList.contains("motion") && !M) root.classList.remove("motion");

  const spring = { type: "spring", stiffness: 260, damping: 22 };

  function choose(tab, animated) {
    const d = tab.dataset;
    for (const t of tabs) {
      const on = t === tab;
      t.setAttribute("aria-selected", String(on));
      t.tabIndex = on ? 0 : -1;
    }
    if (readout) {
      for (const field of readout.querySelectorAll("[data-f]")) {
        field.textContent = d[field.dataset.f] || "";
      }
      readout.style.setProperty("--mode", d.color);
    }
    if (!face) return;
    face.style.setProperty("--mode", d.color);
    face.dataset.active = d.mode;
    // The knob's pointer turns to the LED of the mode; that LED lights in the mode's colour.
    const pointer = face.querySelector("[data-pointer]");
    const angle = Number(d.angle);
    if (pointer) {
      if (animated && moving) M.animate(pointer, { rotate: angle }, spring);
      else pointer.style.transform = `rotate(${angle}deg)`;
    }
    for (const led of face.querySelectorAll("[data-led]")) {
      const on = led.dataset.led === d.mode;
      led.classList.toggle("lit", on);
      if (animated && moving && on) M.animate(led, { scale: [0.6, 1.25, 1] }, { duration: 0.5 });
    }
    // The path the data takes for this mode, drawn from the port to the RP2040.
    for (const path of face.querySelectorAll("[data-route]")) {
      const on = path.dataset.route.split(" ").includes(d.mode);
      path.classList.toggle("on", on);
      if (animated && moving && on) {
        M.animate(path, { pathLength: [0, 1] }, { duration: 0.9, ease: [0.2, 0, 0, 1] });
      }
    }
    for (const part of face.querySelectorAll("[data-part]")) {
      const on = part.dataset.part.split(" ").includes(d.mode);
      part.classList.toggle("on", on);
    }
    if (animated && moving && readout) {
      M.animate(readout.querySelectorAll("[data-f]"), { opacity: [0, 1], y: [6, 0] }, { delay: M.stagger(0.04), duration: 0.35 });
    }
  }

  if (tabs.length) {
    tabs.forEach((tab, i) => {
      tab.addEventListener("click", () => choose(tab, true));
      tab.addEventListener("keydown", (e) => {
        const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
        if (!step) return;
        e.preventDefault();
        const next = tabs[(i + step + tabs.length) % tabs.length];
        next.focus();
        choose(next, true);
      });
    });
    choose(tabs.find((t) => t.getAttribute("aria-selected") === "true") || tabs[0], false);
  }

  // The front and the back of the board, one button.
  const flip = document.querySelector("[data-flip]");
  if (flip) {
    const card = document.querySelector(flip.getAttribute("aria-controls") && `#${flip.getAttribute("aria-controls")}`);
    flip.addEventListener("click", () => {
      const back = flip.getAttribute("aria-pressed") !== "true";
      flip.setAttribute("aria-pressed", String(back));
      if (!card) return;
      if (moving) {
        M.animate(card, { rotateY: back ? 180 : 0 }, { type: "spring", stiffness: 120, damping: 18 });
      } else {
        card.style.transform = back ? "rotateY(180deg)" : "";
      }
    });
  }

  if (!moving) return;
  const { animate, inView, scroll, stagger } = M;
  const ease = [0.2, 0, 0, 1];

  // ---- the logo: its pads land, then its traces are drawn --------------------------------------
  for (const logo of document.querySelectorAll("[data-logo]")) {
    animate(logo.querySelectorAll(".lg-pad, .lg-letter"), { opacity: [0, 1], scale: [0.7, 1] }, { delay: stagger(0.06), duration: 0.45, ease });
    animate(logo.querySelectorAll(".lg-trace"), { pathLength: [0, 1] }, { delay: stagger(0.12, { startDelay: 0.25 }), duration: 0.6, ease });
  }

  // ---- the hero's traces draw, then drift with the scroll -------------------------------------
  const traces = document.querySelector("[data-traces]");
  if (traces) {
    animate(traces.querySelectorAll("path"), { pathLength: [0, 1], opacity: [0, 1] }, { delay: stagger(0.05), duration: 1.4, ease });
    animate(traces.querySelectorAll("circle"), { scale: [0, 1], opacity: [0, 1] }, { delay: stagger(0.05, { startDelay: 0.8 }), duration: 0.4 });
    scroll(animate(traces, { y: [0, 120], opacity: [1, 0.2] }, { ease: "linear" }), { target: traces.closest("section"), offset: ["start start", "end start"] });
  }

  // ---- anything marked data-reveal rises in when it comes into view ---------------------------
  inView(
    "[data-reveal]",
    (el) => {
      if (el.matches("[data-stagger]")) {
        animate([...el.children], { opacity: [0, 1], y: [18, 0] }, { delay: stagger(0.07), duration: 0.6, ease });
      } else {
        animate(el, { opacity: [0, 1], y: [18, 0] }, { duration: 0.6, ease });
      }
    },
    { amount: 0.2 },
  );

  // ---- a run types out a line at a time when it comes into view -------------------------------
  inView(
    ".run pre",
    (pre) => {
      const lines = pre.querySelectorAll(".cmd, .out, .verdict");
      animate(lines, { opacity: [0, 1], x: [-6, 0] }, { delay: stagger(0.18), duration: 0.35, ease });
      const verdict = pre.querySelectorAll(".verdict");
      animate(verdict, { backgroundColor: ["oklch(0.6 0.15 150 / 0.25)", "oklch(0.6 0.15 150 / 0)"] }, { delay: lines.length * 0.18, duration: 1.2 });
    },
    { amount: 0.4 },
  );

  // ---- the board leans toward the pointer --------------------------------------------------------
  for (const tilt of document.querySelectorAll("[data-tilt]")) {
    const stage = tilt.parentElement;
    stage.addEventListener("pointermove", (e) => {
      const r = stage.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width - 0.5;
      const y = (e.clientY - r.top) / r.height - 0.5;
      animate(tilt, { rotateX: -y * 6, rotateY: x * 8 }, { type: "spring", stiffness: 150, damping: 20 });
    });
    stage.addEventListener("pointerleave", () => animate(tilt, { rotateX: 0, rotateY: 0 }, { type: "spring", stiffness: 120, damping: 16 }));
  }

  // ---- the 3D board rises and turns a little as it scrolls through ----------------------------
  for (const el of document.querySelectorAll("[data-parallax]")) {
    scroll(animate(el, { y: [40, -40], rotate: [-2, 2] }, { ease: "linear" }), { target: el, offset: ["start end", "end start"] });
  }

  // ---- the diagram: each node in turn, each arrow drawn --------------------------------------
  inView(
    ".flow",
    (flow) => {
      const steps = flow.querySelectorAll(".node, .hop");
      animate(steps, { opacity: [0, 1], y: [10, 0] }, { delay: stagger(0.12), duration: 0.45, ease });
    },
    { amount: 0.3 },
  );

  // ---- the progress line under the header follows the page ------------------------------------
  const bar = document.querySelector("[data-progress]");
  if (bar) scroll(animate(bar, { scaleX: [0, 1] }, { ease: "linear" }));
})();
