// The explorer's board in 3D. site/example.js loads this module when a reader picks 3D, and hands
// it the same drawing the flat view shows (board.svg, which site/examples.py writes from the board's
// own file). Every colour is read from that drawing's own CSS, so the 2 views match. The copper
// layers are stacked as the board is, drawn 1.6 mm thick, and a slider pulls them apart. A drag
// turns the board, a pinch or Ctrl and the wheel zoom, a pad names its part, and a click follows a
// net. three.js 0.170.0 draws it (vendor/, MIT license). It draws only when something changes.
import * as THREE from "./vendor/three-0.170.0.module.min.js";

const THICK = 1.6; // mm, the board as drawn
const HL = "oklch(0.98 0.03 95)"; // a followed net: site.css's .board.focus .hl
const NEAR = "oklch(0.97 0.02 85)"; // a pointed-at part: site.css's .board .part.near-part .p
const DIM = 0.85; // how far a net not followed fades toward the background (the flat view: 0.12 opacity)

// Any CSS colour, as a three.js colour: a 1-pixel canvas paints it and reads it back in sRGB.
const paint = Object.assign(document.createElement("canvas"), { width: 1, height: 1 }).getContext("2d", {
  willReadFrequently: true,
});
function colour(css) {
  paint.clearRect(0, 0, 1, 1);
  paint.fillStyle = "#000";
  paint.fillStyle = css;
  paint.fillRect(0, 0, 1, 1);
  const [r, g, b] = paint.getImageData(0, 0, 1, 1).data;
  return new THREE.Color().setRGB(r / 255, g / 255, b / 255, THREE.SRGBColorSpace);
}

// Triangles in the board's plane, each vertex tagged with the item it draws (a net, a pad).
class Flat {
  constructor() {
    this.p = [];
    this.tag = [];
  }
  tri(ax, az, bx, bz, cx, cz, t) {
    this.p.push(ax, 0, az, bx, 0, bz, cx, 0, cz);
    this.tag.push(t, t, t);
  }
  fan(points, t) {
    for (let i = 1; i + 1 < points.length; i++) {
      const [a, b, c] = [points[0], points[i], points[i + 1]];
      this.tri(a[0], a[1], b[0], b[1], c[0], c[1], t);
    }
  }
  disc(x, z, r, t, sides = 10) {
    const ring = [];
    for (let i = 0; i < sides; i++) ring.push([x + r * Math.cos((i / sides) * 2 * Math.PI), z + r * Math.sin((i / sides) * 2 * Math.PI)]);
    this.fan(ring, t);
  }
  // A straight piece of track: a band as wide as the track, round at both ends when `round`.
  band(ax, az, bx, bz, half, t, round) {
    const dx = bx - ax;
    const dz = bz - az;
    const len = Math.hypot(dx, dz);
    if (len > 1e-6) {
      const nx = (-dz / len) * half;
      const nz = (dx / len) * half;
      this.tri(ax + nx, az + nz, bx + nx, bz + nz, bx - nx, bz - nz, t);
      this.tri(ax + nx, az + nz, bx - nx, bz - nz, ax - nx, az - nz, t);
    }
    if (round) {
      this.disc(ax, az, half, t, 8);
      this.disc(bx, bz, half, t, 8);
    }
  }
  // Earcut's triangles of a polygon that may have notches (a pour's filled polygon).
  polygon(points, t) {
    const contour = points.map(([x, z]) => new THREE.Vector2(x, z));
    for (const [a, b, c] of THREE.ShapeUtils.triangulateShape(contour, [])) {
      this.tri(points[a][0], points[a][1], points[b][0], points[b][1], points[c][0], points[c][1], t);
    }
  }
  mesh(paintOf, material) {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(this.p), 3));
    const tags = Int32Array.from(this.tag);
    const colours = new Float32Array(tags.length * 3);
    geometry.setAttribute("color", new THREE.BufferAttribute(colours, 3));
    const m = new THREE.Mesh(geometry, material);
    m.userData = { tags, paintOf };
    recolour(m, (t) => paintOf(t));
    return m;
  }
}

function recolour(m, colourOf) {
  const { tags } = m.userData;
  const attr = m.geometry.getAttribute("color");
  let last = null;
  let c = null;
  for (let i = 0; i < tags.length; i++) {
    if (tags[i] !== last) {
      last = tags[i];
      c = colourOf(last);
    }
    attr.array[i * 3] = c.r;
    attr.array[i * 3 + 1] = c.g;
    attr.array[i * 3 + 2] = c.b;
  }
  attr.needsUpdate = true;
}

const numbers = (s) => (s.match(/-?\d*\.?\d+(?:e-?\d+)?/gi) || []).map(Number);

export function mount(box, svg, info) {
  const view = box.querySelector("[data-view]");
  const style = (el, prop) => (el ? getComputedStyle(el)[prop] : "");
  const background = colour(getComputedStyle(view).backgroundColor);
  const hl = colour(HL);
  const near = colour(NEAR);
  const dim = (c) => c.clone().lerp(background, DIM);

  // ---- the drawing, read --------------------------------------------------------------------
  const vb = svg.viewBox.baseVal;
  const ox = vb.x + vb.width / 2;
  const oz = vb.y + vb.height / 2;
  const size = Math.max(vb.width, vb.height);
  const at = (x, y) => [x - ox, y - oz];
  const loopsOf = (d) =>
    d
      .split("M")
      .slice(1)
      .map((part) => {
        const n = numbers(part);
        const loop = [];
        for (let i = 0; i + 1 < n.length; i += 2) loop.push(at(n[i], n[i + 1]));
        return loop;
      })
      .filter((loop) => loop.length >= 3);

  const nets = [];
  const netId = new Map();
  const idOf = (name) => {
    if (!netId.has(name)) {
      netId.set(name, nets.length);
      nets.push({ name, segments: 0, vias: 0, pads: 0, layers: new Set() });
    }
    return netId.get(name);
  };

  // The copper layers, top to bottom, in the toolbar's order.
  const layers = [...box.querySelectorAll("button[data-layer]")]
    .map((b) => b.dataset.layer)
    .filter((name) => name !== "refs" && svg.querySelector(`[data-layer="${name}"]`));
  for (const el of svg.querySelectorAll("[data-layer]")) if (!layers.includes(el.dataset.layer)) layers.push(el.dataset.layer);
  if (!layers.includes("F.Cu")) layers.unshift("F.Cu");
  if (!layers.includes("B.Cu")) layers.push("B.Cu");
  const rank = (name) => (name === "F.Cu" ? -1 : name === "B.Cu" ? 99 : Number(name.replace(/\D/g, "")) || 50);
  layers.sort((a, b) => rank(a) - rank(b));

  // ---- the scene ------------------------------------------------------------------------------
  const scene = new THREE.Scene();
  const basic = (opts) => new THREE.MeshBasicMaterial({ side: THREE.DoubleSide, ...opts });
  const edge = svg.querySelector(".edge");
  const boardFill = colour(style(edge, "fill"));
  const boardLine = colour(style(edge, "stroke"));

  // The board's outline: the largest loop, with the others as openings.
  const loops = edge ? loopsOf(edge.getAttribute("d")) : [];
  loops.sort((a, b) => Math.abs(THREE.ShapeUtils.area(b.map((p) => new THREE.Vector2(...p)))) - Math.abs(THREE.ShapeUtils.area(a.map((p) => new THREE.Vector2(...p)))));
  const shape = new THREE.Shape((loops[0] || []).map(([x, z]) => new THREE.Vector2(x, z)));
  for (const loop of loops.slice(1)) shape.holes.push(new THREE.Path(loop.map(([x, z]) => new THREE.Vector2(x, z))));

  // The board, whole: a slab with its sides a shade darker, so its edge reads in depth.
  const slabGeometry = new THREE.ExtrudeGeometry(shape, { depth: THICK, bevelEnabled: false, curveSegments: 1 });
  slabGeometry.rotateX(Math.PI / 2);
  slabGeometry.translate(0, THICK / 2, 0);
  const slab = new THREE.Mesh(slabGeometry, [basic({ color: boardFill }), basic({ color: boardFill.clone().multiplyScalar(0.62) })]);
  scene.add(slab);

  // The outline's gold line, as bands 0.25 mm wide, as the flat view strokes it.
  const outline = new Flat();
  for (const loop of loops) for (let i = 0; i < loop.length; i++) {
    const [a, b] = [loop[i], loop[(i + 1) % loop.length]];
    outline.band(a[0], a[1], b[0], b[1], 0.125, 0, false);
  }
  const outlineMaterial = basic({ vertexColors: true });

  // A layer: a sheet of board under its copper, the outline, its pours, its tracks, and on the
  // outer layers the pads. Each is a mesh of its own, in a group at the layer's height.
  const groups = new Map();
  const pickable = [];
  const recolourable = [];
  for (const name of layers) {
    const g = new THREE.Group();
    g.userData.name = name;
    const side = name === "B.Cu" ? -1 : 1;
    const sheetGeometry = new THREE.ShapeGeometry(shape, 1);
    sheetGeometry.rotateX(Math.PI / 2);
    const sheet = new THREE.Mesh(sheetGeometry, basic({ color: boardFill, transparent: true, opacity: 0.94, depthWrite: false }));
    sheet.userData.sheet = "plate";
    g.add(sheet);
    const line = outline.mesh(() => boardLine, outlineMaterial);
    line.position.y = side * 0.01;
    line.userData.sheet = "line";
    g.add(line);

    const probe = svg.querySelector(`.tracks[data-layer="${name}"] path`);
    const copper = colour(probe ? style(probe, "stroke") : style(box.querySelector(`button[data-layer="${name}"] i`), "backgroundColor"));
    const pours = new Flat();
    for (const p of svg.querySelectorAll(`.pour[data-layer="${name}"]`)) {
      const id = idOf(p.dataset.net || "");
      for (const loop of loopsOf(p.getAttribute("d"))) pours.polygon(loop, id);
    }
    if (pours.p.length) {
      const m = pours.mesh(() => copper, basic({ vertexColors: true, transparent: true, opacity: 0.22, depthWrite: false }));
      m.position.y = side * 0.02;
      m.userData.kind = "pour";
      m.userData.base = () => copper;
      g.add(m);
      pickable.push(m);
      recolourable.push(m);
    }
    const tracks = new Flat();
    for (const path of svg.querySelectorAll(`.tracks[data-layer="${name}"] path`)) {
      const id = idOf(path.dataset.net || "");
      nets[id].segments += Number(path.dataset.n || 0);
      nets[id].layers.add(name);
      const half = Number(path.getAttribute("stroke-width")) / 2;
      const n = numbers(path.getAttribute("d"));
      for (let i = 0; i + 3 < n.length; i += 4) {
        const [ax, az] = at(n[i], n[i + 1]);
        const [bx, bz] = at(n[i + 2], n[i + 3]);
        tracks.band(ax, az, bx, bz, half, id, true);
      }
    }
    if (tracks.p.length) {
      const m = tracks.mesh(() => copper, basic({ vertexColors: true }));
      m.position.y = side * 0.035;
      m.userData.kind = "track";
      m.userData.base = () => copper;
      g.add(m);
      pickable.push(m);
      recolourable.push(m);
    }
    groups.set(name, g);
    scene.add(g);
  }

  // Pads, on the outer layers: a part's pads on its side, a through-hole pad on both, and its hole.
  const padInfo = [];
  const parts = [];
  const front = colour(style(svg.querySelector('.part[data-side="front"] .p'), "fill") || "oklch(0.83 0.12 85)");
  const back = colour(style(svg.querySelector('.part[data-side="back"] .p'), "fill") || "oklch(0.72 0.09 250)");
  const through = colour(style(svg.querySelector(".part .th"), "fill") || "oklch(0.83 0.12 85)");
  const holeColour = colour(style(svg.querySelector(".part .hole"), "fill") || "oklch(0.12 0.01 250)");
  const pads = { "F.Cu": new Flat(), "B.Cu": new Flat() };
  const holes = { "F.Cu": new Flat(), "B.Cu": new Flat() };
  const barrels = [];
  const outlineOf = (el) => {
    const turn = numbers(el.getAttribute("transform") || "");
    const a = ((turn[0] || 0) * Math.PI) / 180;
    const [rx0, ry0] = [turn[1] || 0, turn[2] || 0];
    const spin = ([x, y]) => (turn.length ? [rx0 + (x - rx0) * Math.cos(a) - (y - ry0) * Math.sin(a), ry0 + (x - rx0) * Math.sin(a) + (y - ry0) * Math.cos(a)] : [x, y]);
    if (el.tagName === "circle") {
      const [cx, cy, r] = ["cx", "cy", "r"].map((k) => Number(el.getAttribute(k)));
      const ring = [];
      for (let i = 0; i < 16; i++) ring.push([cx + r * Math.cos((i / 16) * 2 * Math.PI), cy + r * Math.sin((i / 16) * 2 * Math.PI)]);
      return ring.map((p) => at(...p));
    }
    const [x, y, w, h] = ["x", "y", "width", "height"].map((k) => Number(el.getAttribute(k)));
    const r = Math.min(Number(el.getAttribute("rx") || 0), w / 2, h / 2);
    const pts = [];
    if (r > 0) {
      const corners = [[x + w - r, y + r, -Math.PI / 2], [x + w - r, y + h - r, 0], [x + r, y + h - r, Math.PI / 2], [x + r, y + r, Math.PI]];
      for (const [cx, cy, start] of corners) for (let i = 0; i <= 4; i++) pts.push([cx + r * Math.cos(start + (i / 4) * (Math.PI / 2)), cy + r * Math.sin(start + (i / 4) * (Math.PI / 2))]);
    } else pts.push([x, y], [x + w, y], [x + w, y + h], [x, y + h]);
    return pts.map((p) => at(...spin(p)));
  };
  for (const part of svg.querySelectorAll(".part")) {
    const index = parts.length;
    parts.push({ ref: part.dataset.ref, value: part.dataset.value, side: part.dataset.side, pads: [] });
    for (const el of part.querySelectorAll(".p, .th")) {
      const id = padInfo.length;
      const net = el.dataset.net ? idOf(el.dataset.net) : -1;
      if (net >= 0) nets[net].pads += 1;
      const th = el.classList.contains("th");
      padInfo.push({ part: index, pad: el.dataset.pad || "", net, th, colour: th ? through : part.dataset.side === "back" ? back : front });
      parts[index].pads.push(id);
      const shapeOf = outlineOf(el);
      const sides = th ? ["F.Cu", "B.Cu"] : [part.dataset.side === "back" ? "B.Cu" : "F.Cu"];
      for (const s of sides) pads[s].fan(shapeOf, id);
      if (th) {
        const [cx, cz] = shapeOf.reduce((s, p) => [s[0] + p[0] / shapeOf.length, s[1] + p[1] / shapeOf.length], [0, 0]);
        barrels.push({ x: cx, z: cz, pad: id });
      }
    }
    for (const el of part.querySelectorAll(".hole")) {
      const [x, z] = at(Number(el.getAttribute("cx")), Number(el.getAttribute("cy")));
      const r = Number(el.getAttribute("r"));
      for (const s of ["F.Cu", "B.Cu"]) holes[s].disc(x, z, r, 0, 16);
      const b = barrels.findLast((b) => Math.hypot(b.x - x, b.z - z) < 1e-3 + r) || null;
      if (b) b.r = r;
    }
  }
  const padColour = (id) => padInfo[id].colour;
  for (const s of ["F.Cu", "B.Cu"]) {
    const side = s === "B.Cu" ? -1 : 1;
    if (pads[s].p.length) {
      const m = pads[s].mesh(padColour, basic({ vertexColors: true }));
      m.position.y = side * 0.05;
      m.userData.kind = "pad";
      groups.get(s).add(m);
      pickable.push(m);
      recolourable.push(m);
    }
    if (holes[s].p.length) {
      const m = holes[s].mesh(() => holeColour, basic({ vertexColors: true }));
      m.position.y = side * 0.065;
      m.userData.hole = true;
      groups.get(s).add(m);
    }
  }

  // Vias and the through-hole pads' barrels: a cylinder each from the top layer to the bottom one.
  const via = colour(style(svg.querySelector(".vias circle"), "fill") || "oklch(0.82 0.08 85)");
  const vias = [...svg.querySelectorAll(".vias circle")].map((c) => {
    const net = idOf(c.dataset.net || "");
    nets[net].vias += 1;
    const [x, z] = at(Number(c.getAttribute("cx")), Number(c.getAttribute("cy")));
    return { x, z, r: Number(c.getAttribute("r")), net };
  });
  const cylinder = new THREE.CylinderGeometry(1, 1, 1, 12, 1, false);
  const viaMesh = new THREE.InstancedMesh(cylinder, basic({}), Math.max(vias.length, 1));
  viaMesh.count = vias.length;
  viaMesh.userData.kind = "via";
  const barrelMesh = new THREE.InstancedMesh(cylinder, basic({}), Math.max(barrels.length, 1));
  barrelMesh.count = barrels.length;
  barrelMesh.userData.kind = "barrel";
  scene.add(viaMesh, barrelMesh);
  pickable.push(viaMesh, barrelMesh);
  const paintInstances = (focus) => {
    vias.forEach((v, i) => viaMesh.setColorAt(i, focus < 0 ? via : v.net === focus ? hl : dim(via)));
    barrels.forEach((b, i) => {
      const n = padInfo[b.pad].net;
      barrelMesh.setColorAt(i, focus < 0 ? through : n === focus ? hl : dim(through));
    });
    for (const m of [viaMesh, barrelMesh]) if (m.instanceColor) m.instanceColor.needsUpdate = true;
  };

  // ---- the stack, apart or together ----------------------------------------------------------
  let apart = 0;
  const spanOf = (e) => THICK + e * Math.max(0, Math.max(THICK * 10, size * 0.45) - THICK);
  const place = () => {
    const span = spanOf(apart);
    const step = layers.length > 1 ? span / (layers.length - 1) : 0;
    layers.forEach((name, i) => {
      const g = groups.get(name);
      g.position.y = span / 2 - i * step;
      // Together, the slab is the board, its outline drawn on its top and its bottom; apart, each
      // layer floats on a sheet of board of its own, with its outline.
      const outer = i === 0 || i === layers.length - 1;
      for (const child of g.children) {
        if (child.userData.sheet === "plate") child.visible = apart > 0.002;
        else if (child.userData.sheet === "line") child.visible = apart > 0.002 || outer;
      }
    });
    slab.visible = apart <= 0.002;
    const m = new THREE.Matrix4();
    vias.forEach((v, i) => viaMesh.setMatrixAt(i, m.makeScale(v.r, span + 0.04, v.r).setPosition(v.x, 0, v.z)));
    barrels.forEach((b, i) => barrelMesh.setMatrixAt(i, m.makeScale(b.r || 0.4, span + 0.02, b.r || 0.4).setPosition(b.x, 0, b.z)));
    viaMesh.instanceMatrix.needsUpdate = true;
    barrelMesh.instanceMatrix.needsUpdate = true;
    viaMesh.computeBoundingSphere();
    barrelMesh.computeBoundingSphere();
    draw();
  };

  // ---- the camera: it turns round the board's middle -----------------------------------------
  const canvas = document.createElement("canvas");
  canvas.className = "ex-3d";
  canvas.tabIndex = 0;
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", "The board in 3D. Drag or use the arrow keys to turn it, and + and - to zoom.");
  canvas.style.setProperty("--ar", String(Math.min(2, Math.max(1.2, vb.width / vb.height))));
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setClearColor(0x000000, 0);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  const camera = new THREE.PerspectiveCamera(35, 1.6, size / 200, size * 40);
  const target = new THREE.Vector3();
  const HOME = { turn: -0.45, tilt: 0.95, distance: size * 1.7 };
  let orbit = { ...HOME };
  const aim = () => {
    const { turn, tilt, distance } = orbit;
    camera.position.set(target.x + distance * Math.sin(tilt) * Math.sin(turn), target.y + distance * Math.cos(tilt), target.z + distance * Math.sin(tilt) * Math.cos(turn));
    camera.lookAt(target);
    draw();
  };
  let queued = false;
  function draw() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => {
      queued = false;
      renderer.render(scene, camera);
    });
  }
  const fit = () => {
    const w = view.clientWidth;
    const h = canvas.clientHeight || w / 1.6;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    draw();
  };
  const zoom = (factor) => {
    orbit.distance = Math.min(size * 6, Math.max(size * 0.15, orbit.distance / factor));
    aim();
  };

  // ---- pointing, dragging, picking -----------------------------------------------------------
  const ray = new THREE.Raycaster();
  const shown = (o) => {
    for (let p = o; p; p = p.parent) if (!p.visible) return false;
    return true;
  };
  const hit = (e, only) => {
    const r = canvas.getBoundingClientRect();
    ray.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), camera);
    for (const h of ray.intersectObjects(only || pickable, false)) {
      if (!shown(h.object)) continue;
      const k = h.object.userData.kind;
      if (k === "via") return { net: vias[h.instanceId].net };
      if (k === "barrel") return { pad: barrels[h.instanceId].pad, net: padInfo[barrels[h.instanceId].pad].net };
      const tag = h.object.userData.tags[h.face.a];
      if (k === "pad") return { pad: tag, net: padInfo[tag].net };
      return { net: tag };
    }
    return null;
  };
  let focus = -1;
  let nearPart = -1;
  const hint = "You can drag to turn it, pinch or hold Ctrl and scroll to zoom, and slide the layers apart.";
  const paintAll = () => {
    for (const m of recolourable) {
      if (m.userData.kind === "pad") {
        recolour(m, (id) => {
          const p = padInfo[id];
          if (focus >= 0) return p.net === focus ? hl : dim(p.colour);
          return p.part === nearPart ? near : p.colour;
        });
      } else {
        const base = m.userData.base();
        recolour(m, (net) => (focus < 0 ? base : net === focus ? (m.userData.kind === "pour" ? base.clone().lerp(hl, 0.5) : hl) : dim(base)));
      }
    }
    paintInstances(focus);
    draw();
  };
  const follow = (net) => {
    focus = net >= 0 && net !== focus ? net : -1;
    nearPart = -1;
    paintAll();
    if (focus < 0) {
      info.textContent = hint;
      return;
    }
    const n = nets[focus];
    const where = n.layers.size ? ` on ${[...n.layers].join(", ")}` : "";
    info.textContent = `${n.name}: ${n.segments} track segments${where}, ${n.vias} vias, ${n.pads} pads. Click it again, or elsewhere, to let it go.`;
  };

  const pointers = new Map();
  let moved = 0;
  let pinch = 0;
  canvas.addEventListener("pointerdown", (e) => {
    canvas.setPointerCapture(e.pointerId);
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    moved = 0;
    if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      pinch = Math.hypot(a.x - b.x, a.y - b.y);
    }
  });
  canvas.addEventListener("pointermove", (e) => {
    const was = pointers.get(e.pointerId);
    if (!was) {
      // Pointing: a pad names its part.
      if (focus >= 0 || e.pointerType !== "mouse") return;
      const h = hit(e, recolourable.filter((m) => m.userData.kind === "pad").concat(barrelMesh));
      const part = h && h.pad !== undefined ? padInfo[h.pad].part : -1;
      if (part !== nearPart) {
        nearPart = part;
        paintAll();
        if (part < 0) info.textContent = hint;
        else {
          const p = parts[part];
          const pad = padInfo[h.pad];
          const net = pad.net >= 0 ? ` on ${nets[pad.net].name}` : "";
          info.textContent = `${p.ref}: ${p.value}, on the ${p.side}${pad.pad ? `, pad ${pad.pad}${net}` : ""}`;
        }
      }
      return;
    }
    const dx = e.clientX - was.x;
    const dy = e.clientY - was.y;
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    moved += Math.abs(dx) + Math.abs(dy);
    if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      const d = Math.hypot(a.x - b.x, a.y - b.y);
      if (pinch) zoom(d / pinch);
      pinch = d;
      return;
    }
    if (e.shiftKey || e.buttons === 2) {
      // Shift or the right button slides the board across the view.
      const k = orbit.distance / canvas.clientHeight;
      const right = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 0);
      const up = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 1);
      target.addScaledVector(right, -dx * k).addScaledVector(up, dy * k);
    } else {
      orbit.turn -= dx * 0.008;
      orbit.tilt = Math.min(Math.PI - 0.05, Math.max(0.05, orbit.tilt - dy * 0.008));
    }
    aim();
  });
  const lift = (e) => {
    const was = pointers.get(e.pointerId);
    pointers.delete(e.pointerId);
    if (pointers.size < 2) pinch = 0;
    if (was && moved < 5 && e.type === "pointerup") {
      const h = hit(e);
      follow(h ? h.net : -1);
    }
  };
  canvas.addEventListener("pointerup", lift);
  canvas.addEventListener("pointercancel", lift);
  canvas.addEventListener("contextmenu", (e) => e.preventDefault());
  canvas.addEventListener(
    "wheel",
    (e) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      zoom(Math.exp(-e.deltaY * 0.01));
    },
    { passive: false },
  );
  canvas.addEventListener("keydown", (e) => {
    const step = { ArrowLeft: [0.15, 0], ArrowRight: [-0.15, 0], ArrowUp: [0, -0.12], ArrowDown: [0, 0.12] }[e.key];
    if (step) {
      e.preventDefault();
      orbit.turn += step[0];
      orbit.tilt = Math.min(Math.PI - 0.05, Math.max(0.05, orbit.tilt + step[1]));
      aim();
    } else if (e.key === "+" || e.key === "=") zoom(1.25);
    else if (e.key === "-") zoom(0.8);
  });

  // ---- the toolbar: the layers' buttons, the zoom and a slider for the layers -------------------
  const sync = () => {
    const on = (name) => box.querySelector(`button[data-layer="${name}"]`)?.getAttribute("aria-pressed") !== "false";
    for (const [name, g] of groups) for (const child of g.children) if (!child.userData.sheet && !child.userData.hole && child.userData.kind !== "pad") child.visible = on(name);
    for (const s of ["F.Cu", "B.Cu"]) {
      const pad = groups.get(s).children.find((c) => c.userData.kind === "pad");
      if (pad) pad.visible = on(s);
      const hole = groups.get(s).children.find((c) => c.userData.hole);
      if (hole) hole.visible = on("F.Cu") || on("B.Cu");
    }
    barrelMesh.visible = on("F.Cu") || on("B.Cu");
    draw();
  };
  for (const b of box.querySelectorAll("button[data-layer]")) b.addEventListener("click", () => active && sync());
  for (const b of box.querySelectorAll("[data-zoom]")) {
    b.addEventListener("click", () => {
      if (!active) return;
      if (b.dataset.zoom === "in") zoom(1.6);
      else if (b.dataset.zoom === "out") zoom(1 / 1.6);
      else {
        orbit = { ...HOME };
        target.set(0, 0, 0);
        aim();
      }
    });
  }
  const slider = document.createElement("label");
  slider.className = "ex-apart";
  slider.hidden = true;
  slider.innerHTML = '<span>Layers apart</span><input type="range" min="0" max="1" step="0.01" value="0">';
  const range = slider.querySelector("input");
  range.addEventListener("input", () => {
    apart = Number(range.value);
    place();
  });
  box.querySelector(".ex-tools").append(slider);

  // ---- in and out of 3D -----------------------------------------------------------------------
  let active = false;
  const resize = new ResizeObserver(() => active && fit());
  resize.observe(view);
  const names = box.querySelector('button[data-layer="refs"]');
  place();
  paintAll();
  aim();
  return {
    enter() {
      active = true;
      svg.style.display = "none";
      if (!canvas.isConnected) view.append(canvas);
      canvas.hidden = false;
      slider.hidden = false;
      if (names) names.hidden = true;
      info.textContent = hint;
      fit();
      sync();
      // The layers part a little the first time, so the stack shows; still, for reduced motion.
      if (!range.dataset.opened) {
        range.dataset.opened = "";
        const to = 0.5;
        if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
          range.value = String(to);
          apart = to;
          place();
        } else {
          const t0 = performance.now();
          const step = (now) => {
            const k = Math.min(1, (now - t0) / 900);
            apart = to * (1 - (1 - k) ** 3);
            range.value = String(apart);
            place();
            if (k < 1) requestAnimationFrame(step);
          };
          requestAnimationFrame(step);
        }
      }
    },
    leave(hint2d) {
      active = false;
      canvas.hidden = true;
      slider.hidden = true;
      svg.style.display = "";
      if (names) names.hidden = false;
      focus = -1;
      nearPart = -1;
      paintAll();
      info.textContent = hint2d;
    },
  };
}
