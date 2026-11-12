// Write Herald's 3D model for the site, site/showcase/herald.glb, from its routed board.
//
//   KICAD10_3DMODEL_DIR=<KiCad's 3D bodies> node site/showcase/make_glb.mjs <node_modules>
//
// <node_modules> holds three@0.186.1 and @gltf-transform/cli@4.5.1 (npm install --prefix <dir> ...),
// and Playwright's Chromium is installed. The steps:
//   1. kicad-cli exports the board as VRML, in metres, with every part: KiCad's own bodies and the
//      project's (models/*.wrl). Its GLB export reads STEP bodies only and leaves the project's out.
//   2. three.js, in Chromium, reads the VRML, turns the board Y up, centres it, gives each surface a
//      PBR material of its colour, and writes a GLB (12.6 MB).
//   3. gltf-transform joins, welds, simplifies and meshopt-compresses it (0.6 MB). GPU instancing is
//      off: with it, each quantized instance lost its scale.
import { execFileSync } from "node:child_process";
import { createServer } from "node:http";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..", "..");
const modules = resolve(process.argv[2] || "node_modules");
const bodies = process.env.KICAD10_3DMODEL_DIR;
if (!bodies) throw new Error("set KICAD10_3DMODEL_DIR to a folder of KiCad's 3D bodies (site/media/README.md)");
const board = join(root, "examples/fire-alarm-communicator/v0.1/herald.kicad_pcb");
const out = join(root, "site/showcase/herald.glb");
const work = mkdtempSync(join(tmpdir(), "herald-glb-"));

execFileSync("kicad-cli", ["pcb", "export", "vrml", "-D", `KICAD10_3DMODEL_DIR=${bodies}`, "--units", "m", "-f", "-o", join(work, "herald.wrl"), board], { stdio: "inherit" });

const page = `<!doctype html><meta charset="utf-8">
<script type="importmap">{"imports":{"three":"/three/build/three.module.js","three/addons/":"/three/examples/jsm/"}}</script>
<script type="module">
import * as THREE from "three";
import { VRMLLoader } from "three/addons/loaders/VRMLLoader.js";
import { GLTFExporter } from "three/addons/exporters/GLTFExporter.js";
window.convert = async () => {
  const scene = await new VRMLLoader().loadAsync("/herald.wrl");
  const root = new THREE.Group();
  root.add(scene);
  scene.rotation.x = -Math.PI / 2;
  root.updateMatrixWorld(true);
  scene.position.sub(new THREE.Box3().setFromObject(root).getCenter(new THREE.Vector3()));
  root.updateMatrixWorld(true);
  root.traverse((o) => {
    if (o.isMesh) o.material = new THREE.MeshStandardMaterial({ color: o.material.color.clone(), roughness: 0.55, metalness: 0.05, side: THREE.DoubleSide });
  });
  const bytes = new Uint8Array(await new GLTFExporter().parseAsync(root, { binary: true }));
  let s = "";
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
};
window.ready = true;
</script>`;

const types = { ".js": "text/javascript", ".html": "text/html", ".wrl": "model/vrml" };
const server = createServer((req, res) => {
  const path = req.url.split("?")[0];
  const file = path === "/" ? null : path.startsWith("/three/") ? join(modules, path) : join(work, path);
  try {
    const body = file ? readFileSync(file) : page;
    res.writeHead(200, { "content-type": file ? types[file.slice(file.lastIndexOf("."))] || "application/octet-stream" : "text/html" });
    res.end(body);
  } catch {
    res.writeHead(404).end();
  }
});
await new Promise((ok) => server.listen(0, "127.0.0.1", ok));
const { chromium } = createRequire(import.meta.url)("playwright");
const browser = await chromium.launch();
const tab = await browser.newPage();
await tab.goto(`http://127.0.0.1:${server.address().port}/`);
await tab.waitForFunction(() => window.ready === true);
writeFileSync(join(work, "herald-raw.glb"), Buffer.from(await tab.evaluate(() => window.convert()), "base64"));
await browser.close();
server.close();

execFileSync(join(modules, ".bin", "gltf-transform"), ["optimize", join(work, "herald-raw.glb"), out, "--compress", "meshopt", "--instance", "false", "--texture-compress", "false"], { stdio: "inherit" });
console.log(`${out}: written`);
