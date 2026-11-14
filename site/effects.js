// The pages' motion, with Motion (motion.dev, vendor/). A page reads the same without it: every
// element starts where it ends, and the head's script adds `motion` to <html> only when the reader
// has not asked for reduced motion. This file removes it again if Motion did not load.

(() => {
  const root = document.documentElement;
  root.dataset.motionReady = "1";

  // ---- the example's parts: 4 labels at a time, 1 of them swapped for the next every 3 s --------
  //      works with or without Motion
  const M = window.Motion;
  const moving = root.classList.contains("motion") && M;
  if (root.classList.contains("motion") && !M) root.classList.remove("motion");
  const tour = document.querySelector("[data-tour]");
  const partsData = document.getElementById("herald-parts");
  if (tour && partsData) {
    const { groups, parts } = JSON.parse(partsData.textContent);
    const NS = "http://www.w3.org/2000/svg";
    const STEP = 3000;
    const GLIDE = 0.5; // s: a label that stays slides to its new place, its leader with it
    const ease = [0.2, 0, 0, 1];
    const face = tour.querySelector("[data-face]");
    const svg = face.querySelector("svg");
    const lists = { left: tour.querySelector('[data-cards="left"]'), right: tour.querySelector('[data-cards="right"]') };
    const leaders = tour.querySelector("[data-leaders]");
    const middle = svg.viewBox.baseVal.x + svg.viewBox.baseVal.width / 2;
    const body = (ref) => svg.querySelector(`.body[data-ref="${ref}"]`);

    // Each side's parts in the tour's order, a circuit at a time, with where each sits on the board.
    // A side holds 2 labels, numbered 1 and 2 on the left, 3 and 4 on the right: the sides take turns,
    // and the side's older label gives way to its next part, which takes the label's number.
    const queues = { left: [], right: [] };
    for (const g of groups) {
      for (const ref of g.p) {
        const b = body(ref).getBBox();
        const p = { ref, x: b.x + b.width / 2, y: b.y + b.height / 2 };
        queues[p.x < middle ? "left" : "right"].push(p);
      }
    }
    const where = {};
    for (const side of ["left", "right"]) queues[side].forEach((p, i) => (where[p.ref] = { side, i }));
    const shown = { left: [], right: [] }; // oldest first: { p, n, el, tag }
    const next = { left: 0, right: 0 };
    const FIRST = { left: 1, right: 3 };
    let turn = "left";
    let seen = false;
    let timer = 0;
    let busy = Promise.resolve();
    let sliding = false;

    // A part's label: what the page's data holds on it, the rows it has and no others.
    function card(ref, n) {
      const p = parts[ref];
      const el = document.createElement("article");
      el.className = "part-card";
      el.dataset.ref = ref;
      // Stacked under the board, the labels stand by their numbers, 1 to 4 (site.css); beside it, in
      // the order arrange() gives them.
      el.style.setProperty("--n", n);
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
    // A label on its way in or out has none.
    function lead(fresh) {
      const s = tour.getBoundingClientRect();
      const f = face.getBoundingClientRect();
      leaders.setAttribute("viewBox", `0 0 ${s.width} ${s.height}`);
      leaders.replaceChildren();
      for (const el of tour.querySelectorAll(".part-card:not([data-moving])")) {
        const c = el.getBoundingClientRect();
        const onLeft = c.right <= f.left + 2;
        if (!onLeft && c.left < f.right - 2) continue;
        const [[px, py], [ex, ay], [ax]] = route(el.dataset.ref, c.top, onLeft ? c.right : c.left, onLeft).map(
          ([x, y]) => [x - s.left, y - s.top],
        );
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

    // A part's number on the board, where its leader starts.
    function tag(p, n) {
      const g = document.createElementNS(NS, "g");
      g.setAttribute("class", "part-tag");
      const c = document.createElementNS(NS, "circle");
      c.setAttribute("cx", p.x);
      c.setAttribute("cy", p.y);
      c.setAttribute("r", 1.5);
      const t = document.createElementNS(NS, "text");
      t.setAttribute("x", p.x);
      t.setAttribute("y", p.y + 0.68);
      t.textContent = n;
      g.append(c, t);
      svg.append(g);
      return g;
    }

    // The leader from a part to the label whose top is at `top` and whose near edge is at `edge`, on
    // the page: from the part a diagonal, then level into the label.
    function route(ref, top, edge, onLeft) {
      const r = body(ref).getBoundingClientRect();
      const px = r.left + r.width / 2;
      const py = r.top + r.height / 2;
      const ay = top + 21;
      const ax = onLeft ? edge + 4 : edge - 4;
      const room = Math.max(Math.abs(ax - px) - 24, 0);
      const ex = px + (onLeft ? -1 : 1) * Math.min(Math.abs(ay - py), room);
      return [
        [px, py],
        [ex, ay],
        [ax, ay],
      ];
    }

    // Whether 2 leaders cross: a segment of one strictly across a segment of the other.
    function crosses(a, b) {
      const orient = (u, v, w) => (v[0] - u[0]) * (w[1] - u[1]) - (v[1] - u[1]) * (w[0] - u[0]);
      const across = (p, q, r, t) => orient(p, q, r) * orient(p, q, t) < 0 && orient(r, t, p) * orient(r, t, q) < 0;
      for (let i = 0; i < 2; i += 1) {
        for (let j = 0; j < 2; j += 1) if (across(a[i], a[i + 1], b[j], b[j + 1])) return true;
      }
      return false;
    }

    // The most a label stands beside the board: half the board's height less half the gap between
    // 2 labels, so a side's 2 always fit beside it and the board never moves. Stacked under the
    // board, a label is whole.
    function room() {
      if (getComputedStyle(leaders).display === "none") return 0;
      const gap = parseFloat(getComputedStyle(lists.left).rowGap) || 0;
      return (face.getBoundingClientRect().height - gap) / 2;
    }

    // A label taller than its room ends in an ellipsis where the room ends: the text there keeps the
    // lines that fit, and the rows under it, and the datasheet's link, are left out (its picture
    // still links it). Where no line of a row fits, the row goes and the text above it ends in "…".
    function fit(el, limit) {
      for (const x of el.querySelectorAll("[data-cut], [data-gone], [data-last]")) {
        delete x.dataset.cut;
        delete x.dataset.gone;
        delete x.dataset.last;
      }
      const box = el.getBoundingClientRect();
      if (!limit || box.height <= limit + 0.5) return;
      const bottom = box.top + limit - parseFloat(getComputedStyle(el).paddingBottom);
      const blocks = [...el.querySelectorAll(".part-d, dd, .part-ds")];
      const gone = (x) => ((x.matches("dd") ? x.parentElement : x).dataset.gone = "");
      for (let i = 0; i < blocks.length; i += 1) {
        const r = blocks[i].getBoundingClientRect();
        if (r.bottom <= bottom + 0.5) continue;
        blocks.slice(i + 1).forEach(gone);
        const line = parseFloat(getComputedStyle(blocks[i]).lineHeight) || r.height;
        const lines = blocks[i].matches(".part-ds") ? 0 : Math.floor((bottom - r.top) / line);
        if (lines >= 1) {
          blocks[i].dataset.cut = "";
          blocks[i].style.setProperty("--lines", lines);
        } else {
          gone(blocks[i]);
          if (i > 0) blocks[i - 1].dataset.last = "";
        }
        return;
      }
    }

    // A side's labels stand in the order of their parts from the top of the board down; where 2
    // parts sit side by side and their leaders would cross, the other way up. Under the board the
    // numbers order them instead (site.css).
    function arrange(side) {
      const items = [...shown[side]].sort((u, v) => u.p.y - v.p.y);
      lists[side].append(...items.map((s) => s.el));
      if (items.length !== 2 || getComputedStyle(leaders).display === "none") return;
      const [a, b] = items;
      const ra = a.el.getBoundingClientRect();
      const rb = b.el.getBoundingClientRect();
      const onLeft = side === "left";
      const edge = onLeft ? ra.right : ra.left;
      if (!crosses(route(a.p.ref, ra.top, edge, onLeft), route(b.p.ref, rb.top, edge, onLeft))) return;
      // The other way up the 2 labels fill the same height: b at the top, a below it by b's height.
      const under = ra.top + rb.height + (rb.top - ra.bottom);
      if (!crosses(route(b.p.ref, ra.top, edge, onLeft), route(a.p.ref, under, edge, onLeft))) lists[side].append(b.el, a.el);
    }

    // Part p takes the place of its side's older label: that label fades, the other one slides to
    // its new place with its leader, and p's label comes in, its leader drawn from its part.
    async function swap(p, animated) {
      const { side } = where[p.ref];
      const list = shown[side];
      if (list.some((s) => s.p.ref === p.ref)) return;
      const old = list.length >= 2 ? list.shift() : null;
      const n = old ? old.n : FIRST[side] + list.length;
      const motion = animated && moving;
      if (motion) sliding = true;
      if (old && motion) {
        old.el.dataset.moving = "";
        lead(null);
        await Promise.all([
          M.animate(old.el, { opacity: 0 }, { duration: 0.25 }),
          M.animate(old.tag, { opacity: 0 }, { duration: 0.25 }),
        ]);
      }
      const before = new Map([...tour.querySelectorAll(".part-card")].map((el) => [el, el.getBoundingClientRect().top]));
      const height = tour.getBoundingClientRect().height;
      if (old) {
        old.el.remove();
        old.tag.remove();
        body(old.p.ref).classList.remove("on");
      }
      const item = { p, n, el: card(p.ref, n), tag: tag(p, n) };
      body(p.ref).classList.add("on");
      list.push(item);
      lists[side].append(item.el);
      fit(item.el, room());
      arrange(side);
      if (!motion) {
        lead(null);
        return;
      }
      item.el.dataset.moving = "";
      for (const [el, top] of before) {
        if (!el.isConnected) continue;
        const dy = top - el.getBoundingClientRect().top;
        if (Math.abs(dy) > 0.5) M.animate(el, { y: [dy, 0] }, { duration: GLIDE, ease });
      }
      const now = tour.getBoundingClientRect().height;
      if (Math.abs(now - height) > 0.5) {
        M.animate(tour, { height: [`${height}px`, `${now}px`] }, { duration: GLIDE, ease }).then(() => (tour.style.height = ""));
      }
      M.animate(item.el, { opacity: [0, 1], y: [8, 0] }, { duration: 0.45, ease });
      M.animate(item.tag, { scale: [0, 1] }, { duration: 0.35 });
      // The leaders follow the labels as they slide; the new one is drawn once its label is still.
      const end = performance.now() + GLIDE * 1000;
      await new Promise((done) => {
        const frame = () => {
          lead(null);
          if (performance.now() < end) requestAnimationFrame(frame);
          else done();
        };
        requestAnimationFrame(frame);
      });
      delete item.el.dataset.moving;
      sliding = false;
      lead(p.ref);
    }

    // Once the stage has its size (its fonts, its pictures, a new width), each label is fitted to its
    // room and each side's order checked again, between swaps: a label's height decides where its
    // leader runs.
    function settle() {
      if (sliding) return;
      const limit = room();
      for (const el of tour.querySelectorAll(".part-card")) fit(el, limit);
      arrange("left");
      arrange("right");
      lead(null);
    }

    // One swap at a time: a click during a swap waits for it.
    function then(p, animated) {
      busy = busy.then(() => swap(p, animated)).catch(() => {});
      return busy;
    }

    // The side whose turn it is brings in its next part that is not already shown.
    function tick() {
      const side = turn;
      turn = side === "left" ? "right" : "left";
      const queue = queues[side];
      for (let k = 0; k < queue.length; k += 1) {
        const p = queue[next[side]];
        next[side] = (next[side] + 1) % queue.length;
        if (!shown[side].some((s) => s.p.ref === p.ref)) {
          then(p, true);
          break;
        }
      }
      schedule();
    }

    // The labels turn by themselves while the board is in view and the page is shown.
    function schedule() {
      clearTimeout(timer);
      if (seen && !document.hidden) timer = setTimeout(tick, STEP);
    }

    // A click on a part brings its label in at once, and its side goes on from there.
    svg.addEventListener("click", (e) => {
      const hit = e.target.closest(".body");
      if (!hit || !where[hit.dataset.ref]) return;
      const { side, i } = where[hit.dataset.ref];
      next[side] = (i + 1) % queues[side].length;
      turn = side === "left" ? "right" : "left";
      then(queues[side][i], true);
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
    new ResizeObserver(settle).observe(tour);
    window.addEventListener("load", settle);
    for (const side of ["left", "right"]) {
      for (const p of queues[side].slice(0, 2)) swap(p, false);
      next[side] = Math.min(2, queues[side].length) % Math.max(queues[side].length, 1);
    }
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
