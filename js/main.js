import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

const $ = (s) => document.querySelector(s);
const load = $('#loading');
const prog = $('#progress');
const err = $('#error');
const setProgress = (pct, text) => {
  const p = Math.max(0, Math.min(100, Math.round(pct)));
  prog.textContent = `${text} ${p}%`;
};
setProgress(2, 'Engine');

window.addEventListener('error', (e) => {
  if (!err.textContent) fail(`JavaScript error: ${e.message || 'unknown error'}`);
});
window.addEventListener('unhandledrejection', (e) => {
  console.error(e.reason);
});

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x91a8b7);
scene.fog = new THREE.Fog(0x91a8b7, 180, 900);

const camera = new THREE.PerspectiveCamera(62, innerWidth / innerHeight, 0.08, 1600);
const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
renderer.setPixelRatio(Math.min(devicePixelRatio, 1.35));
renderer.setSize(innerWidth, innerHeight);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
document.body.prepend(renderer.domElement);
setProgress(5, 'Engine');

scene.add(new THREE.HemisphereLight(0xddeeff, 0x59634b, 2.0));
const sun = new THREE.DirectionalLight(0xffffff, 2.2);
sun.position.set(80, 130, 40);
sun.castShadow = true;
sun.shadow.mapSize.set(1024, 1024);
scene.add(sun);

let hero = null, mixer = null, clips = {}, state = 'IDLE', groundMeshes = [];
let vy = 0, grounded = false, yaw = 0, pitch = .32, camDist = 5.3;
let joy = { x: 0, y: 0, power: 0 }, keys = {};
const ray = new THREE.Raycaster();
const clock = new THREE.Clock();
const gltf = new GLTFLoader();

function fail(message) {
  console.error(message);
  err.style.display = 'block';
  err.textContent = message;
  load.style.display = 'none';
}

function parseGLB(buffer, base) {
  return new Promise((resolve, reject) => gltf.parse(buffer, base, resolve, reject));
}

function loadDirectGLB(url, startPct, endPct, label) {
  return new Promise((resolve, reject) => {
    // A cache-busting query avoids Android/Chromium reusing a stale GLB after a rebuild.
    const freshUrl = `${url}?v=${Date.now()}`;
    gltf.load(
      freshUrl,
      resolve,
      (e) => {
        if (e.total) setProgress(startPct + (e.loaded / e.total) * (endPct - startPct), `Loading ${label}`);
        else setProgress(startPct, `Loading ${label}`);
      },
      (e) => reject(new Error(`${label} tidak ditemukan / gagal dibaca: ${url}. ${e?.message || e || ''}`))
    );
  });
}

async function loadPackedGLB(url, label, startPct, endPct) {
  setProgress(startPct, `Checking ${label}`);
  const manifestUrl = `${url}.parts.json`;
  let manifestResponse;
  try {
    manifestResponse = await fetch(`${manifestUrl}?t=${Date.now()}`, { cache: 'no-store' });
  } catch (e) {
    throw new Error(`Tidak bisa mengakses ${manifestUrl}: ${e.message}`);
  }

  if (!manifestResponse.ok) {
    return loadDirectGLB(url, startPct, endPct, label);
  }

  const manifest = await manifestResponse.json();
  if (!Array.isArray(manifest.parts) || !manifest.parts.length) {
    throw new Error(`Manifest ${label} kosong/rusak: ${manifestUrl}`);
  }

  const base = url.slice(0, url.lastIndexOf('/') + 1);
  const buffers = [];
  let total = 0;
  // v2 manifests contain the SHA-256-derived cacheKey of the actual GLB.
  // If an old manifest is encountered we still force revalidation with Date.now().
  const cacheKey = manifest.cacheKey || `${manifest.totalBytes || 0}-${Date.now()}`;

  for (let i = 0; i < manifest.parts.length; i++) {
    const pct = startPct + ((i + 0.15) / manifest.parts.length) * (endPct - startPct);
    setProgress(pct, `Loading ${label} ${i + 1}/${manifest.parts.length}`);
    const partUrl = `${base}${manifest.parts[i]}?v=${encodeURIComponent(cacheKey)}`;
    const response = await fetch(partUrl, { cache: 'no-store' });
    if (!response.ok) throw new Error(`${label}: ${manifest.parts[i]} HTTP ${response.status}`);
    const buffer = await response.arrayBuffer();
    buffers.push(buffer);
    total += buffer.byteLength;
  }

  if (manifest.totalBytes && total !== manifest.totalBytes) {
    throw new Error(`${label}: ukuran chunk tidak cocok (${total} != ${manifest.totalBytes})`);
  }

  setProgress(endPct - 2, `Joining ${label}`);
  const merged = new Uint8Array(total);
  let offset = 0;
  for (const buffer of buffers) {
    merged.set(new Uint8Array(buffer), offset);
    offset += buffer.byteLength;
  }
  const parsed = await parseGLB(merged.buffer, base);
  setProgress(endPct, `${label} ready`);
  return parsed;
}

async function boot() {
  try {
    setProgress(7, 'Preparing assets');
    const map = await loadPackedGLB('assets/map/map.glb', 'map', 8, 68);
    scene.add(map.scene);
    map.scene.traverse((o) => {
      if (o.isMesh) {
        o.receiveShadow = true;
        groundMeshes.push(o);
      }
    });

    const ch = await loadPackedGLB('assets/character/character_rigged.glb', 'character', 70, 94);
    hero = ch.scene;
    scene.add(hero);
    hero.traverse((o) => {
      if (o.isMesh) {
        o.castShadow = true;
        o.frustumCulled = true;
      }
    });

    mixer = new THREE.AnimationMixer(hero);
    for (const c of ch.animations) clips[c.name.toUpperCase()] = mixer.clipAction(c);
    setAnim('IDLE');
    spawn();
    setProgress(100, 'Ready');
    requestAnimationFrame(() => { load.style.display = 'none'; });
  } catch (e) {
    fail(
      'Asset game belum siap. Repo harus memiliki map.glb / map.glb.parts.json dan character_rigged.glb. ' +
      'Jika memakai GitHub Pages, jalankan workflow Build & Deploy yang disertakan. Detail: ' + e.message
    );
  }
}
boot();

function setAnim(n) {
  if (state === n && clips[n]) return;
  const next = clips[n] || clips.IDLE;
  if (!next) return;
  Object.values(clips).forEach((a) => { if (a !== next) a.fadeOut(.18); });
  next.reset().fadeIn(.18).play();
  state = n;
}

function groundAt(p) {
  ray.set(new THREE.Vector3(p.x, p.y + 6, p.z), new THREE.Vector3(0, -1, 0));
  const h = ray.intersectObjects(groundMeshes, true);
  return h.length ? h[0].point.y : null;
}

function spawn() {
  if (!hero || !groundMeshes.length) return;
  const mapBox = new THREE.Box3();
  for (const obj of groundMeshes) mapBox.expandByObject(obj);
  hero.position.set((mapBox.min.x + mapBox.max.x) / 2, mapBox.max.y + 10, (mapBox.min.z + mapBox.max.z) / 2);
  let y = groundAt(hero.position);
  if (y == null) {
    hero.position.set(0, mapBox.max.y + 10, 0);
    y = groundAt(hero.position);
  }
  if (y != null) hero.position.y = y;
}

function update(dt) {
  if (!hero) return;
  let ix = joy.x, iy = joy.y;
  if (keys.KeyW) iy = 1;
  if (keys.KeyS) iy = -1;
  if (keys.KeyA) ix = -1;
  if (keys.KeyD) ix = 1;
  let power = Math.min(1, Math.hypot(ix, iy));
  if (keys.ShiftLeft && power) power = 1;

  const f = new THREE.Vector3(-Math.sin(yaw), 0, -Math.cos(yaw));
  const r = new THREE.Vector3(Math.cos(yaw), 0, -Math.sin(yaw));
  const dir = f.multiplyScalar(iy).add(r.multiplyScalar(ix));
  if (dir.lengthSq()) dir.normalize();
  const speed = power > .65 ? 6.1 : power > .12 ? 2.8 : 0;

  if (speed) {
    hero.position.addScaledVector(dir, speed * dt);
    const target = Math.atan2(dir.x, dir.z);
    const d = Math.atan2(Math.sin(target - hero.rotation.y), Math.cos(target - hero.rotation.y));
    hero.rotation.y += d * Math.min(1, dt * 10);
  }

  vy -= 18 * dt;
  hero.position.y += vy * dt;
  const gy = groundAt(hero.position);
  grounded = gy != null && hero.position.y <= gy + .18 && vy <= 0;
  if (grounded) { hero.position.y = gy; vy = 0; }

  if (!grounded) setAnim(vy > .3 ? 'JUMP_START' : 'JUMP_AIR');
  else if (state === 'JUMP_AIR' || state === 'JUMP_START') setAnim('JUMP_LAND');
  else setAnim(speed ? (power > .65 ? 'RUN' : 'WALK') : 'IDLE');

  mixer?.update(dt);
  const target = hero.position.clone().add(new THREE.Vector3(0, 1.55, 0));
  const cp = new THREE.Vector3(
    Math.sin(yaw) * Math.cos(pitch) * camDist,
    Math.sin(pitch) * camDist + 1.0,
    Math.cos(yaw) * Math.cos(pitch) * camDist
  ).add(target);
  camera.position.lerp(cp, 1 - Math.exp(-10 * dt));
  camera.lookAt(target);
}

function jump() {
  if (hero && grounded) {
    vy = 7.2;
    grounded = false;
    setAnim('JUMP_START');
  }
}

function loop() {
  requestAnimationFrame(loop);
  const dt = Math.min(.033, clock.getDelta());
  update(dt);
  renderer.render(scene, camera);
}
loop();

addEventListener('resize', () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});
addEventListener('keydown', (e) => { keys[e.code] = 1; if (e.code === 'Space') jump(); });
addEventListener('keyup', (e) => keys[e.code] = 0);

const jb = $('#joy'), kn = jb.querySelector('i');
let jid = null;
function jmove(e) {
  const b = jb.getBoundingClientRect();
  const x = e.clientX - (b.left + b.width / 2), y = e.clientY - (b.top + b.height / 2);
  const m = Math.min(48, Math.hypot(x, y)), a = Math.atan2(y, x);
  const dx = Math.cos(a) * m, dy = Math.sin(a) * m;
  kn.style.transform = `translate(${dx}px,${dy}px)`;
  joy = { x: dx / 48, y: -dy / 48, power: m / 48 };
}
jb.onpointerdown = (e) => { jid = e.pointerId; jb.setPointerCapture(jid); jmove(e); };
jb.onpointermove = (e) => { if (e.pointerId === jid) jmove(e); };
jb.onpointerup = jb.onpointercancel = (e) => {
  if (e.pointerId === jid) {
    jid = null; joy = { x: 0, y: 0, power: 0 }; kn.style.transform = 'translate(0,0)';
  }
};

$('#jump').onpointerdown = (e) => { e.stopPropagation(); jump(); };
let cid = null, last = null;
renderer.domElement.onpointerdown = (e) => {
  if (e.clientX < innerWidth * .32) return;
  cid = e.pointerId; last = [e.clientX, e.clientY]; renderer.domElement.setPointerCapture(cid);
};
renderer.domElement.onpointermove = (e) => {
  if (e.pointerId !== cid) return;
  const dx = e.clientX - last[0], dy = e.clientY - last[1];
  yaw -= dx * .005;
  pitch = THREE.MathUtils.clamp(pitch + dy * .004, -.3, 1.05);
  last = [e.clientX, e.clientY];
};
renderer.domElement.onpointerup = renderer.domElement.onpointercancel = (e) => { if (e.pointerId === cid) cid = null; };

$('#fs').onclick = async () => {
  try {
    if (!document.fullscreenElement) await document.documentElement.requestFullscreen();
    else await document.exitFullscreen();
    try { await screen.orientation?.lock?.('landscape'); } catch {}
  } catch {}
};
