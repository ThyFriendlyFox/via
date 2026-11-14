// The pages' motion, with Motion (motion.dev, vendor/). A page reads the same without it: every
// element starts where it ends, and the head's script adds `motion` to <html> only when the reader
// has not asked for reduced motion. This file removes it again if Motion did not load.

(() => {
  const root = document.documentElement;
  root.dataset.motionReady = "1";

  // ---- the example's parts, a label every 3 s: works with or without Motion ---------------------
  const M = window.Motion;
  const moving = root.classList.contains("motion") && M;
  if (root.classList.contains("motion") && !M) root.classList.remove("motion");
  const tour = document.querySelector("[data-tour]");
  const partsData = document.getElementById("herald-parts");
  if (tour && partsData) {
    const { groups, parts } = JSON.parse(partsData.textContent);
    const NS = "http://www.w3.org/2000/svg";
    const STEP = 3000;
    const ease = [0.2, 0, 0, 1];
    const face = tour.querySelector("[data-face]");
    const svg = face.querySelector("svg");
    const lists = { left: tour.querySelector('[data-cards="left"]'), right: tour.querySelector('[data-cards="right"]') };
    const leaders = tour.querySelector("[data-leaders]");
    const groupOf = {};
    groups.forEach((g, i) => g.p.forEach((ref) => (groupOf[ref] = i)));
    const middle = svg.viewBox.baseVal.x + svg.viewBox.baseVal.width / 2;
    const body = (ref) => svg.querySelector(`.body[data-ref="${ref}"]`);
    let at = 0;
    let order = [];
    let shown = 0;
    let seen = false;
    let timer = 0;

    // A part's label: what the page's data holds on it, the rows it has and no others.
    function card(ref, n) {
      const p = parts[ref];
      const el = document.createElement("article");
      el.className = "part-card is-waiting";
      el.dataset.ref = ref;
      // Stacked under the board, the labels come in their turn's order, top to bottom.
      el.style.order = n;
      if (p.dp) {
        el.classList.add("has-sheet");
        const sheet = document.createElement("a");
        sheet.className = "part-sheet";
        sheet.href = p.ds;
        sheet.target = "_blank";
        sheet.rel = "noopener";
        const img = document.createElement("img");
        img.src = p.dp[0];
        img.width = p.dp[1];
        img.height = p.dp[2];
        img.loading = "lazy";
        img.alt = `The first page of the ${ref} datasheet`;
        sheet.append(img);
        el.append(sheet);
      }
      const text = document.createElement("div");
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
      const row = (label, value) => {
        if (!value) return;
        const div = document.createElement("div");
        const dt = document.createElement("dt");
        const dd = document.createElement("dd");
        dt.textContent = label;
        dd.textContent = value;
        div.append(dt, dd);
        rows.append(div);
      };
      row("Nets", p.n);
      row("The problem it answers", p.r);
      row("Why this part", p.w);
      row("Its terminals", p.c);
      if (p.s) row("Simulated", p.s.slice(0, 2).join("\n") + (p.s.length > 2 ? `\nand ${p.s.length - 2} more decks` : ""));
      text.append(head, what, rows);
      if (p.ds) {
        const link = document.createElement("a");
        link.className = "part-ds";
        link.href = p.ds;
        link.target = "_blank";
        link.rel = "noopener";
        link.textContent = "Datasheet";
        text.append(link);
      }
      el.append(text);
      return el;
    }

    // A leader in 2 segments: a diagonal from the part, then a break to a horizontal into its label,
    // where the labels stand beside the board. Under the board the numbers pair them instead.
    function lead(fresh) {
      const s = tour.getBoundingClientRect();
      const f = face.getBoundingClientRect();
      leaders.setAttribute("viewBox", `0 0 ${s.width} ${s.height}`);
      leaders.replaceChildren();
      for (const el of tour.querySelectorAll(".part-card:not(.is-waiting)")) {
        const c = el.getBoundingClientRect();
        const onLeft = c.right <= f.left + 2;
        if (!onLeft && c.left < f.right - 2) continue;
        const r = body(el.dataset.ref).getBoundingClientRect();
        const px = r.left + r.width / 2 - s.left;
        const py = r.top + r.height / 2 - s.top;
        const ay = c.top + 21 - s.top;
        const ax = (onLeft ? c.right + 4 : c.left - 4) - s.left;
        const room = Math.max(Math.abs(ax - px) - 24, 0);
        const ex = px + (onLeft ? -1 : 1) * Math.min(Math.abs(ay - py), room);
        const path = document.createElementNS(NS, "path");
        path.setAttribute("d", `M${px} ${py} L${ex} ${ay} L${ax} ${ay}`);
        path.setAttribute("pathLength", "1");
        const dot = document.createElementNS(NS, "circle");
        dot.setAttribute("cx", px);
        dot.setAttribute("cy", py);
        dot.setAttribute("r", 2.5);
        leaders.append(path, dot);
        if (fresh === el.dataset.ref && moving) {
          M.animate(path, { pathLength: [0, 1] }, { duration: 0.6, ease });
          M.animate(dot, { opacity: [0, 1] }, { duration: 0.3 });
        }
      }
    }

    // A group's labels go in place at once, unseen, so none moves when the next appears: each to the
    // side of the board its part sits on, at most half to a side, each side from the top down.
    function place(i) {
      at = (i + groups.length) % groups.length;
      shown = 0;
      for (const el of svg.querySelectorAll(".body.on")) el.classList.remove("on");
      for (const el of svg.querySelectorAll(".part-tag")) el.remove();
      leaders.replaceChildren();
      const placed = groups[at].p.map((ref, k) => {
        const b = body(ref).getBBox();
        return { ref, n: k + 1, x: b.x + b.width / 2, y: b.y + b.height / 2 };
      });
      const half = Math.ceil(placed.length / 2);
      const left = placed.filter((p) => p.x < middle).sort((u, v) => u.x - v.x);
      const right = placed.filter((p) => p.x >= middle).sort((u, v) => v.x - u.x);
      while (left.length > half) right.push(left.pop());
      while (right.length > half) left.push(right.pop());
      left.sort((u, v) => u.y - v.y);
      right.sort((u, v) => u.y - v.y);
      lists.left.replaceChildren(...left.map((p) => card(p.ref, p.n)));
      lists.right.replaceChildren(...right.map((p) => card(p.ref, p.n)));
      order = placed;
    }

    // The next label of the group: its card, its part lit, its number on the board, its leader.
    function reveal(animated) {
      const p = order[shown];
      shown += 1;
      const el = tour.querySelector(`.part-card[data-ref="${p.ref}"]`);
      el.classList.remove("is-waiting");
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
      lead(animated ? p.ref : null);
      if (animated && moving) {
        M.animate(el, { opacity: [0, 1], y: [8, 0] }, { duration: 0.45, ease });
        M.animate(tag, { scale: [0, 1] }, { duration: 0.35 });
      }
    }

    function tick() {
      if (shown >= order.length) place(at + 1);
      reveal(true);
      schedule();
    }

    // The labels turn by themselves while the board is in view and the page is shown.
    function schedule() {
      clearTimeout(timer);
      if (seen && !document.hidden) timer = setTimeout(tick, STEP);
    }

    // A click on a part shows its group whole; the next group follows 3 s later.
    svg.addEventListener("click", (e) => {
      const hit = e.target.closest(".body");
      if (!hit) return;
      place(groupOf[hit.dataset.ref]);
      while (shown < order.length) reveal(false);
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
    new ResizeObserver(() => lead(null)).observe(tour);
    place(0);
    reveal(false);
  }

  // ---- the board in 3D: the viewer and the model load only as the reader nears them --------------
  // The page loads with KiCad's picture alone. 600 px before the picture comes into view, the
  // viewer (model-viewer, 1 MB) and the model (0.6 MB) load, and the model takes the picture's place.
  // Without WebGL, or if either fails to load, the picture stays.
  const board3d = document.querySelector("[data-board3d]");
  if (board3d && "IntersectionObserver" in window) {
    const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const script = (src) =>
      new Promise((resolve, reject) => {
        const s = document.createElement("script");
        s.src = src;
        s.onload = resolve;
        s.onerror = reject;
        document.head.append(s);
      });
    const near = new IntersectionObserver(
      (entries) => {
        if (!entries.some((e) => e.isIntersecting)) return;
        near.disconnect();
        script(board3d.dataset.viewerSrc)
          .then(() => customElements.whenDefined("model-viewer"))
          .then(() => {
            // The model's meshes are meshopt-compressed; model-viewer turns its decoder on from here.
            customElements.get("model-viewer").meshoptDecoderLocation = board3d.dataset.decoderSrc;
            const viewer = document.createElement("model-viewer");
            const settings = {
              src: board3d.dataset.src,
              alt: "Herald in 3D, to turn with a finger or the pointer",
              "camera-controls": "",
              "camera-orbit": "0deg 50deg 78%",
              "touch-action": "pan-y",
              "interaction-prompt": "none",
              "environment-image": "neutral",
              exposure: "1.05",
              "shadow-intensity": "0.7",
              loading: "eager",
            };
            if (!still) Object.assign(settings, { "auto-rotate": "", "auto-rotate-delay": "0", "rotation-per-second": "12deg" });
            for (const [name, value] of Object.entries(settings)) viewer.setAttribute(name, value);
            viewer.addEventListener("load", () => board3d.classList.add("is-live"), { once: true });
            board3d.append(viewer);
          })
          .catch(() => {});
      },
      { rootMargin: "600px 0px" },
    );
    near.observe(board3d);
  }

  if (!moving) return;
  const { animate, inView, scroll, stagger } = M;
  const ease = [0.2, 0, 0, 1];

  // ---- the logo: its pads land, then its traces are drawn --------------------------------------
  for (const logo of document.querySelectorAll("[data-logo]")) {
    animate(logo.querySelectorAll(".lg-pad, .lg-letter"), { opacity: [0, 1], scale: [0.7, 1] }, { delay: stagger(0.06), duration: 0.45, ease });
    animate(logo.querySelectorAll(".lg-trace"), { pathLength: [0, 1] }, { delay: stagger(0.12, { startDelay: 0.25 }), duration: 0.6, ease });
  }

  // ---- the hero's wordmark is built the way a board is: sketched, its corners set, its copper ----
  //      laid, its traces run; then the sketch and the points go, and the mark is as logo.svg draws it
  const build = document.querySelector("[data-build]");
  if (build) {
    const sketch = build.querySelectorAll(".wm-sketch");
    const points = build.querySelectorAll(".wm-pt");
    const sequence = [
      [sketch, { opacity: [0, 1], pathLength: [0, 1] }, { duration: 0.8, delay: stagger(0.12), ease, at: 0.15 }],
      [points, { opacity: [0, 1], scale: [0, 1] }, { duration: 0.3, delay: stagger(0.03), at: 0.45 }],
      [build.querySelectorAll(".wm-cu"), { opacity: [0, 1], scale: [0.96, 1] }, { duration: 0.5, delay: stagger(0.09), ease, at: 1.45 }],
      [build.querySelectorAll(".wm-tr"), { opacity: [0, 1], pathLength: [0, 1] }, { duration: 0.6, delay: stagger(0.12), ease, at: 2.0 }],
      [points, { opacity: 0 }, { duration: 0.4, at: 2.3 }],
      [sketch, { opacity: 0 }, { duration: 0.5, at: 2.5 }],
    ];
    const paper = document.querySelector(".wm-paper");
    if (paper) sequence.unshift([paper, { opacity: [0, 1] }, { duration: 0.6, at: 0 }]);
    animate(sequence);
  }

  // ---- a drawing draws itself when it comes into view: site.css times each stroke ---------------
  inView(".draw", (el) => el.classList.add("drawn"), { amount: 0.35 });

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
