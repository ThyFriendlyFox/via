// An example's page: the board in 3D that a drag turns, and the board explorer. Both work without
// Motion; a reader who asked for less motion gets a turntable that stands still until it is dragged.

(() => {
  const root = document.documentElement;
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches || Boolean(root.dataset.shot);

  // ---- the turntable: 36 of KiCad's views, 10 degrees apart, side by side in 1 picture ------------
  for (const table of document.querySelectorAll("[data-turntable]")) {
    const frames = Number(table.dataset.frames);
    const columns = Number(table.dataset.columns);
    const rows = Math.ceil(frames / columns);
    const sheet = table.querySelector(".tt-frames");
    sheet.style.backgroundSize = `${columns * 100}% ${rows * 100}%`;
    let at = 0;
    const show = (n) => {
      at = ((Math.round(n) % frames) + frames) % frames;
      const col = at % columns;
      const row = Math.floor(at / columns);
      sheet.style.backgroundPosition = `${(col / (columns - 1)) * 100}% ${(row / (rows - 1)) * 100}%`;
    };
    show(0);

    // It turns by itself, a view every 150 ms, while it is on screen and nobody holds it.
    let held = false;
    let visible = false;
    let timer = 0;
    const spin = () => {
      const turning = !still && visible && !held;
      if (turning && !timer) timer = setInterval(() => show(at + 1), 150);
      else if (!turning && timer) {
        clearInterval(timer);
        timer = 0;
      }
    };
    new IntersectionObserver(([e]) => {
      visible = Boolean(e && e.isIntersecting);
      spin();
    }).observe(table);

    // A drag turns it: 12 px a view.
    let from = null;
    let start = 0;
    table.addEventListener("pointerdown", (e) => {
      from = e.clientX;
      start = at;
      held = true;
      spin();
      table.setPointerCapture(e.pointerId);
      table.dataset.dragging = "";
    });
    table.addEventListener("pointermove", (e) => {
      if (from !== null) show(start - (e.clientX - from) / 12);
    });
    const drop = () => {
      from = null;
      delete table.dataset.dragging;
    };
    table.addEventListener("pointerup", drop);
    table.addEventListener("pointercancel", drop);
    table.addEventListener("pointerleave", () => {
      if (from === null) {
        held = false;
        spin();
      }
    });
    table.addEventListener("keydown", (e) => {
      const step = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
      if (!step) return;
      e.preventDefault();
      held = true;
      spin();
      show(at + step);
    });
  }

  // ---- the explorer: the board drawn from its own file; layers, zoom, pan, a net, a part --------
  for (const box of document.querySelectorAll("[data-explorer]")) {
    const view = box.querySelector("[data-view]");
    const info = box.querySelector("[data-info]");
    const hint = info.textContent;
    fetch(box.dataset.src)
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(String(r.status)))))
      .then((text) => {
        view.innerHTML = text;
        explore(box, view.querySelector("svg"), info, hint);
      })
      .catch(() => {
        info.textContent = "The drawing did not load. The board is in the repository: open it in KiCad.";
      });
  }

  function explore(box, svg, info, hint) {
    const base = svg.viewBox.baseVal;
    const home = { x: base.x, y: base.y, w: base.width, h: base.height };
    let vb = { ...home };
    svg.style.aspectRatio = `${home.w} / ${home.h}`;
    const set = () => {
      svg.setAttribute("viewBox", `${vb.x} ${vb.y} ${vb.w} ${vb.h}`);
      svg.classList.toggle("near", vb.w < home.w / 3);
    };
    const zoomAt = (factor, cx, cy) => {
      const w = Math.min(home.w, Math.max(home.w / 30, vb.w / factor));
      const k = w / vb.w;
      vb = { x: cx - (cx - vb.x) * k, y: cy - (cy - vb.y) * k, w, h: vb.h * k };
      // The board stays in view.
      vb.x = Math.min(Math.max(vb.x, home.x - vb.w / 2), home.x + home.w - vb.w / 2);
      vb.y = Math.min(Math.max(vb.y, home.y - vb.h / 2), home.y + home.h - vb.h / 2);
      set();
    };
    const toBoard = (clientX, clientY) => {
      const r = svg.getBoundingClientRect();
      return { x: vb.x + ((clientX - r.left) / r.width) * vb.w, y: vb.y + ((clientY - r.top) / r.height) * vb.h };
    };
    const centre = () => ({ x: vb.x + vb.w / 2, y: vb.y + vb.h / 2 });

    for (const b of box.querySelectorAll("[data-zoom]")) {
      b.addEventListener("click", () => {
        const c = centre();
        if (b.dataset.zoom === "in") zoomAt(1.6, c.x, c.y);
        else if (b.dataset.zoom === "out") zoomAt(1 / 1.6, c.x, c.y);
        else {
          vb = { ...home };
          set();
        }
      });
    }
    // Ctrl and the wheel, or a trackpad's pinch, zoom; the wheel alone scrolls the page.
    svg.addEventListener(
      "wheel",
      (e) => {
        if (!e.ctrlKey && !e.metaKey) return;
        e.preventDefault();
        const p = toBoard(e.clientX, e.clientY);
        zoomAt(Math.exp(-e.deltaY * 0.01), p.x, p.y);
      },
      { passive: false },
    );
    svg.addEventListener("dblclick", (e) => {
      const p = toBoard(e.clientX, e.clientY);
      zoomAt(2, p.x, p.y);
    });

    // A drag moves the board; 2 fingers pinch it. A press that does not move is a click.
    const pointers = new Map();
    let moved = 0;
    let pinch = 0;
    svg.addEventListener("pointerdown", (e) => {
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      svg.setPointerCapture(e.pointerId);
      moved = 0;
      if (pointers.size === 2) {
        const [a, b] = [...pointers.values()];
        pinch = Math.hypot(a.x - b.x, a.y - b.y);
      }
    });
    svg.addEventListener("pointermove", (e) => {
      const last = pointers.get(e.pointerId);
      if (!last) return;
      const r = svg.getBoundingClientRect();
      if (pointers.size === 1) {
        const dx = e.clientX - last.x;
        const dy = e.clientY - last.y;
        moved += Math.abs(dx) + Math.abs(dy);
        vb.x -= (dx / r.width) * vb.w;
        vb.y -= (dy / r.height) * vb.h;
        set();
      }
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pointers.size === 2) {
        const [a, b] = [...pointers.values()];
        const d = Math.hypot(a.x - b.x, a.y - b.y);
        const p = toBoard((a.x + b.x) / 2, (a.y + b.y) / 2);
        if (pinch) zoomAt(d / pinch, p.x, p.y);
        pinch = d;
        moved += 10;
      }
    });
    const lift = (e) => {
      pointers.delete(e.pointerId);
      if (pointers.size < 2) pinch = 0;
    };
    svg.addEventListener("pointerup", (e) => {
      if (moved < 4 && pointers.size === 1) pick(e.target);
      lift(e);
    });
    svg.addEventListener("pointercancel", lift);

    // Layers on and off.
    for (const b of box.querySelectorAll("button[data-layer]")) {
      const layer = b.dataset.layer;
      if (layer !== "refs" && !svg.querySelector(`[data-layer="${layer}"]`)) {
        b.hidden = true;
        continue;
      }
      const apply = () => svg.classList.toggle(`off-${layer.replace(".", "")}`, b.getAttribute("aria-pressed") !== "true");
      apply();
      b.addEventListener("click", () => {
        b.setAttribute("aria-pressed", String(b.getAttribute("aria-pressed") !== "true"));
        apply();
      });
    }

    // A net, followed: every track, via, pad and pour on it.
    let net = "";
    const pick = (target) => {
      const on = target.closest("[data-net]");
      for (const el of svg.querySelectorAll(".hl")) el.classList.remove("hl");
      const next = on && on.dataset.net !== net ? on.dataset.net : "";
      net = next;
      svg.classList.toggle("focus", Boolean(net));
      if (!net) {
        info.textContent = hint;
        return;
      }
      const found = svg.querySelectorAll(`[data-net="${CSS.escape(net)}"]`);
      let segments = 0;
      let vias = 0;
      let pads = 0;
      const layers = new Set();
      for (const el of found) {
        el.classList.add("hl");
        if (el.dataset.n) {
          segments += Number(el.dataset.n);
          layers.add(el.closest("[data-layer]").dataset.layer);
        } else if (el.closest(".vias")) vias += 1;
        else if (el.closest(".part")) pads += 1;
      }
      const where = layers.size ? ` on ${[...layers].join(", ")}` : "";
      info.textContent = `${net}: ${segments} track segments${where}, ${vias} vias, ${pads} pads. Click it again, or elsewhere, to let it go.`;
    };

    // A part, named when a pad is pointed at.
    svg.addEventListener("pointerover", (e) => {
      if (net) return;
      const part = e.target.closest(".part");
      for (const el of svg.querySelectorAll(".part.near-part")) el.classList.remove("near-part");
      if (!part) {
        info.textContent = hint;
        return;
      }
      part.classList.add("near-part");
      const pad = e.target.closest("[data-pad]");
      const d = part.dataset;
      const where = pad ? `, pad ${pad.dataset.pad}${pad.dataset.net ? ` on ${pad.dataset.net}` : ""}` : "";
      info.textContent = `${d.ref}: ${d.value}, on the ${d.side}${where}`;
    });
    set();
  }
})();
