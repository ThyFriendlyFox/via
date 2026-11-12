// The page's motion, with Motion (motion.dev, vendor/). The page reads the same without it: every
// element starts where it ends, and the head's script adds `motion` to <html> only when the reader
// has not asked for reduced motion. This file removes it again if Motion did not load.

(() => {
  const root = document.documentElement;
  root.dataset.motionReady = "1";

  // ---- the example's parts, a few at a time, each labelled: works with or without Motion --------
  const M = window.Motion;
  const moving = root.classList.contains("motion") && M;
  if (root.classList.contains("motion") && !M) root.classList.remove("motion");
  const tour = document.querySelector("[data-tour]");
  const partsData = document.getElementById("herald-parts");
  if (tour && partsData) {
    const { groups, parts } = JSON.parse(partsData.textContent);
    const NS = "http://www.w3.org/2000/svg";
    const face = tour.querySelector("[data-face]");
    const svg = face.querySelector("svg");
    const lists = { left: tour.querySelector('[data-cards="left"]'), right: tour.querySelector('[data-cards="right"]') };
    const leaders = tour.querySelector("[data-leaders]");
    const title = tour.querySelector("[data-tour-title]");
    const count = tour.querySelector("[data-tour-count]");
    const play = tour.querySelector("[data-tour-play]");
    const total = Object.keys(parts).length;
    const first = [];
    const groupOf = {};
    let before = 0;
    groups.forEach((g, i) => {
      first[i] = before;
      before += g.p.length;
      for (const ref of g.p) groupOf[ref] = i;
    });
    const middle = svg.viewBox.baseVal.x + svg.viewBox.baseVal.width / 2;
    const body = (ref) => svg.querySelector(`.body[data-ref="${ref}"]`);
    let at = 0;
    let playing = Boolean(moving); // the labels turn by themselves only where motion is welcome
    let hovered = false;
    let seen = false;
    let timer = 0;

    // A part's label: what the page's data holds on it, the rows it has and no others.
    function card(ref, n) {
      const p = parts[ref];
      const el = document.createElement("article");
      el.className = "part-card";
      el.dataset.ref = ref;
      const head = document.createElement("header");
      const num = document.createElement("span");
      num.className = "part-n";
      num.textContent = n;
      const name = document.createElement("b");
      name.textContent = ref;
      const value = document.createElement("span");
      value.className = "part-v";
      value.textContent = p.v;
      head.append(num, name, value);
      const what = document.createElement("p");
      what.className = "part-d";
      what.textContent = [p.d, p.fp].filter(Boolean).join(" · ");
      const rows = document.createElement("dl");
      const row = (label, text) => {
        if (!text) return;
        const div = document.createElement("div");
        const dt = document.createElement("dt");
        const dd = document.createElement("dd");
        dt.textContent = label;
        dd.textContent = text;
        div.append(dt, dd);
        rows.append(div);
      };
      row("Nets", p.n);
      row("The problem it answers", p.r);
      row("Why this part", p.w);
      row("Its terminals", p.c);
      if (p.s) row("Simulated", p.s.slice(0, 2).join("\n") + (p.s.length > 2 ? `\nand ${p.s.length - 2} more decks` : ""));
      el.append(head, what, rows);
      if (p.ds) {
        const link = document.createElement("a");
        link.className = "part-ds";
        link.href = p.ds;
        link.target = "_blank";
        link.rel = "noopener";
        link.textContent = "Datasheet";
        el.append(link);
      }
      return el;
    }

    // A leader from each part to its label, where the labels stand beside the board.
    function lead(animated) {
      const s = tour.getBoundingClientRect();
      const f = face.getBoundingClientRect();
      leaders.setAttribute("viewBox", `0 0 ${s.width} ${s.height}`);
      leaders.replaceChildren();
      for (const el of tour.querySelectorAll(".part-card")) {
        const c = el.getBoundingClientRect();
        const onLeft = c.right <= f.left + 2;
        if (!onLeft && c.left < f.right - 2) continue; // stacked under the board: the numbers pair them
        const r = body(el.dataset.ref).getBoundingClientRect();
        const px = r.left + r.width / 2 - s.left;
        const py = r.top + r.height / 2 - s.top;
        const ay = c.top + 20 - s.top;
        const ax = (onLeft ? c.right + 4 : c.left - 4) - s.left;
        const ex = (onLeft ? f.left - 12 : f.right + 12) - s.left;
        const path = document.createElementNS(NS, "path");
        path.setAttribute("d", `M${px} ${py} L${ex} ${ay} L${ax} ${ay}`);
        path.setAttribute("pathLength", "1");
        const dot = document.createElementNS(NS, "circle");
        dot.setAttribute("cx", px);
        dot.setAttribute("cy", py);
        dot.setAttribute("r", 2.5);
        leaders.append(path, dot);
      }
      if (animated && moving) {
        M.animate(leaders.querySelectorAll("path"), { pathLength: [0, 1] }, { delay: M.stagger(0.08, { startDelay: 0.1 }), duration: 0.55, ease: [0.2, 0, 0, 1] });
      }
    }

    function schedule() {
      clearTimeout(timer);
      if (playing && seen && !hovered && !document.hidden) timer = setTimeout(() => show(at + 1, true), 6500);
    }

    function show(i, animated) {
      at = (i + groups.length) % groups.length;
      const g = groups[at];
      title.textContent = g.t;
      count.textContent = `parts ${first[at] + 1} to ${first[at] + g.p.length} of ${total}`;
      for (const el of svg.querySelectorAll(".body.on")) el.classList.remove("on");
      for (const el of svg.querySelectorAll(".part-tag")) el.remove();
      // Each part's label goes to the side of the board it sits on, at most half of them to a side,
      // and each side in the parts' order from the top, so no 2 leaders cross.
      const placed = g.p.map((ref) => {
        const b = body(ref).getBBox();
        return { ref, x: b.x + b.width / 2, y: b.y + b.height / 2 };
      });
      const half = Math.ceil(placed.length / 2);
      const left = placed.filter((p) => p.x < middle).sort((u, v) => u.x - v.x);
      const right = placed.filter((p) => p.x >= middle).sort((u, v) => v.x - u.x);
      while (left.length > half) right.push(left.pop());
      while (right.length > half) left.push(right.pop());
      left.sort((u, v) => u.y - v.y);
      right.sort((u, v) => u.y - v.y);
      [...left, ...right].forEach((p, k) => (p.n = k + 1));
      lists.left.replaceChildren(...left.map((p) => card(p.ref, p.n)));
      lists.right.replaceChildren(...right.map((p) => card(p.ref, p.n)));
      for (const p of placed) {
        body(p.ref).classList.add("on");
        const tag = document.createElementNS(NS, "g");
        tag.setAttribute("class", "part-tag");
        const c = document.createElementNS(NS, "circle");
        c.setAttribute("cx", p.x);
        c.setAttribute("cy", p.y);
        c.setAttribute("r", 1.5);
        const t = document.createElementNS(NS, "text");
        t.setAttribute("x", p.x);
        t.setAttribute("y", p.y + 0.68);
        t.textContent = p.n;
        tag.append(c, t);
        svg.append(tag);
      }
      lead(animated);
      if (animated && moving) {
        M.animate(tour.querySelectorAll(".part-card"), { opacity: [0, 1], y: [8, 0] }, { delay: M.stagger(0.08), duration: 0.4, ease: [0.2, 0, 0, 1] });
        M.animate(svg.querySelectorAll(".part-tag"), { scale: [0, 1] }, { delay: M.stagger(0.08), duration: 0.35 });
      }
      schedule();
    }

    function setPlaying(on) {
      playing = on;
      play.textContent = on ? "Pause" : "Play";
      // A screen reader hears each new group only when the reader turns the labels, not every 6.5 s.
      title.parentElement.setAttribute("aria-live", on ? "off" : "polite");
      schedule();
    }

    tour.querySelector("[data-tour-prev]").addEventListener("click", () => show(at - 1, true));
    tour.querySelector("[data-tour-next]").addEventListener("click", () => show(at + 1, true));
    play.addEventListener("click", () => setPlaying(!playing));
    svg.addEventListener("click", (e) => {
      const hit = e.target.closest(".body");
      if (!hit) return;
      setPlaying(false);
      show(groupOf[hit.dataset.ref], true);
    });
    tour.addEventListener("pointerenter", (e) => {
      if (e.pointerType !== "mouse") return;
      hovered = true;
      schedule();
    });
    tour.addEventListener("pointerleave", (e) => {
      if (e.pointerType !== "mouse") return;
      hovered = false;
      schedule();
    });
    document.addEventListener("visibilitychange", schedule);
    new IntersectionObserver(
      (entries) => {
        seen = entries.some((e) => e.isIntersecting);
        schedule();
      },
      { threshold: 0.35 },
    ).observe(tour);
    new ResizeObserver(() => lead(false)).observe(tour);
    setPlaying(playing);
    show(0, false);
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

  // ---- the example's copper sweeps in a layer at a time: the back, the inner layer, the front ---
  const copper = [...document.querySelectorAll("[data-face] [data-copper]")];
  if (copper.length) {
    const hidden = "inset(0% 100% 0% 0%)";
    for (const layer of copper) layer.style.clipPath = hidden;
    inView(
      "[data-face]",
      () => {
        animate(copper, { clipPath: [hidden, "inset(0% 0% 0% 0%)"] }, { delay: stagger(0.35), duration: 1.3, ease });
      },
      { amount: 0.3 },
    );
  }

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
