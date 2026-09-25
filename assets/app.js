import * as THREE from 'three';
import { OrbitControls } from 'three/addons/OrbitControls.js';

const $ = (id) => document.getElementById(id);
const palette = ['#d5ec9e', '#6ec4b0', '#e8b989', '#84afe2', '#d09fc6', '#d7d185', '#87c6d5', '#da9784'];
const preferred = ['jr-east', 'jr-west', 'jr-central', 'tokyo-metro', 'toei', 'tokyu', 'odakyu', 'keio', 'seibu'];
const regions = {
  japan: { center: [137.5, 37.5], span: 1920, name: 'Japan 日本' },
  tokyo: { center: [139.72, 35.69], span: 90, name: 'Tokyo 東京' },
  kansai: { center: [135.5, 34.8], span: 150, name: 'Kansai 関西' },
  kyushu: { center: [130.8, 32.75], span: 410, name: 'Kyushu 九州' },
  hokkaido: { center: [142.3, 43.3], span: 520, name: 'Hokkaido 北海道' },
};
let renderer, scene, camera, controls, manifest, selectedOperator = null, selectedLine = null;
let tilted = false, animation = null, activeBounds = null, pointerStart = null;
const datasets = new Map(), visualizations = new Map(), stationMeshes = [];
const raycaster = new THREE.Raycaster(), pointer = new THREE.Vector2();
const project = ([lon, lat]) => new THREE.Vector3((lon - 137) * 90, 0, -(lat - 37) * 111.2);
const number = (n) => n.toLocaleString('en-US');
const name = (record) => record.name.en || record.name.ja;
function lineColor(line) {
  if (/^#[0-9a-f]{6}$/i.test(line.colour || '')) return line.colour;
  // Keep fallback colors stable when the manifest changes.
  let hash = 0;
  for (const character of line.id) hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  return palette[hash % palette.length];
}
function element(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}
function bilingualLabel(record) {
  const label = element('span', 'bilingual-name');
  for (const language of ['ja', 'en']) {
    const text = record.name[language];
    if (!text || (language === 'en' && text === record.name.ja)) continue;
    const translation = element('span', 'name-translation', text);
    translation.lang = language;
    label.append(translation);
  }
  return label;
}
async function readJSON(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  return response.json();
}
function makeGeometry(points) {
  return new THREE.BufferGeometry().setFromPoints(points);
}
function initScene() {
  const host = $('viewport');
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setClearColor('#101b22');
  host.append(renderer.domElement);
  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(40, 1, 0.1, 20000);
  camera.position.set(0, 2600, 0.01);
  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.12;
  controls.screenSpacePanning = true;
  controls.minDistance = 3;
  controls.maxDistance = 6500;
  controls.maxPolarAngle = Math.PI * 0.42;
  controls.mouseButtons = { LEFT: THREE.MOUSE.PAN, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.ROTATE };
  controls.touches = { ONE: THREE.TOUCH.PAN, TWO: THREE.TOUCH.DOLLY_ROTATE };
  controls.addEventListener('start', () => { animation = null; $('tooltip').hidden = true; });
  controls.addEventListener('change', () => {
    const isTilted = controls.getPolarAngle() > 0.1;
    if (tilted !== isTilted && !animation) updateViewButtons(isTilted);
  });
  const grid = [];
  for (let lon = 122; lon <= 150; lon += 2) grid.push(project([lon, 23]), project([lon, 48]));
  for (let lat = 24; lat <= 48; lat += 2) grid.push(project([122, lat]), project([150, lat]));
  const gridLines = new THREE.LineSegments(makeGeometry(grid), new THREE.LineBasicMaterial({ color: '#23353d', transparent: true, opacity: 0.4 }));
  gridLines.position.y = -1;
  scene.add(gridLines);
  new ResizeObserver(() => {
    const width = host.clientWidth, height = host.clientHeight;
    renderer.setSize(width, height);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  }).observe(host);
  renderer.domElement.addEventListener('pointerdown', (e) => { pointerStart = [e.clientX, e.clientY]; });
  renderer.domElement.addEventListener('pointermove', hoverStation);
  renderer.domElement.addEventListener('pointerleave', () => { $('tooltip').hidden = true; });
  renderer.domElement.addEventListener('pointerup', (e) => {
    if (e.button !== 0 || !pointerStart || Math.hypot(e.clientX - pointerStart[0], e.clientY - pointerStart[1]) > 5) return;
    const hit = pickStation(e);
    if (hit) showStation(hit);
  });
  renderer.domElement.addEventListener('webglcontextlost', (e) => {
    e.preventDefault();
    showError('The map’s graphics context was interrupted. Reload to restore the atlas.');
  });
  renderer.setAnimationLoop(() => {
    if (animation) {
      const t = Math.min((performance.now() - animation.start) / animation.duration, 1);
      const eased = 1 - Math.pow(1 - t, 3);
      camera.position.lerpVectors(animation.fromCamera, animation.toCamera, eased);
      controls.target.lerpVectors(animation.fromTarget, animation.toTarget, eased);
      if (t === 1) animation = null;
    }
    controls.update();
    const distance = camera.position.distanceTo(controls.target);
    for (const [id, view] of visualizations) {
      for (const item of view.lines) item.points.visible = (!selectedOperator ? distance < 450 : id === selectedOperator) && (!selectedLine || selectedLine === item.line.id);
    }
    renderer.render(scene, camera);
  });
}
function moveTo(center, distance) {
  const offset = tilted ? new THREE.Vector3(0, distance * 0.77, distance * 0.64) : new THREE.Vector3(0, distance, 0.001);
  animation = {
    start: performance.now(), duration: matchMedia('(prefers-reduced-motion: reduce)').matches ? 1 : 850,
    fromCamera: camera.position.clone(), fromTarget: controls.target.clone(), toTarget: center.clone(), toCamera: center.clone().add(offset),
  };
}
function fit(bounds) {
  activeBounds = bounds.clone();
  const size = bounds.getSize(new THREE.Vector3());
  const span = Math.max(size.z, size.x / camera.aspect, 4);
  moveTo(bounds.getCenter(new THREE.Vector3()), span / (2 * Math.tan(THREE.MathUtils.degToRad(20))) * 1.45);
}
function region(id) {
  const area = regions[id];
  const center = project(area.center);
  fit(new THREE.Box3(center.clone().add(new THREE.Vector3(-area.span * 0.42, 0, -area.span / 2)), center.clone().add(new THREE.Vector3(area.span * 0.42, 0, area.span / 2))));
  $('map-title').textContent = area.name;
  document.querySelectorAll('[data-region]').forEach((button) => button.classList.toggle('active', button.dataset.region === id));
}
function updateViewButtons(value) {
  tilted = value;
  $('flat').classList.toggle('active', !value);
  $('tilt').classList.toggle('active', value);
  $('flat').setAttribute('aria-pressed', String(!value));
  $('tilt').setAttribute('aria-pressed', String(value));
}
async function addCoastline() {
  const data = await readJSON('assets/japan.geojson');
  const outline = [];
  for (const feature of data.features) {
    const polygons = feature.geometry.type === 'Polygon' ? [feature.geometry.coordinates] : feature.geometry.coordinates;
    for (const polygon of polygons) {
      const rings = polygon.map((ring) => ring.map((coord) => { const p = project(coord); return new THREE.Vector2(p.x, -p.z); }));
      const shape = new THREE.Shape(rings[0]);
      for (const hole of rings.slice(1)) shape.holes.push(new THREE.Path(hole));
      const geometry = new THREE.ShapeGeometry(shape);
      geometry.rotateX(-Math.PI / 2);
      const mesh = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ color: '#192a31', side: THREE.DoubleSide }));
      mesh.position.y = -0.5;
      scene.add(mesh);
      for (const ring of polygon) for (let i = 1; i < ring.length; i++) outline.push(project(ring[i - 1]), project(ring[i]));
    }
  }
  const coast = new THREE.LineSegments(makeGeometry(outline), new THREE.LineBasicMaterial({ color: '#3a535a', transparent: true, opacity: 0.65 }));
  coast.position.y = -0.2;
  scene.add(coast);
}
function addOperator(data, color) {
  const stationById = new Map(data.stations.map((s) => [s.id, s]));
  const view = { lines: [], bounds: new THREE.Box3(), color };
  for (const line of data.lines) {
    const vertices = [];
    for (const segment of line.segments) {
      for (let i = 1; i < segment.geometry.length; i++) vertices.push(project(segment.geometry[i - 1]), project(segment.geometry[i]));
    }
    if (!vertices.length) continue;
    const geometry = makeGeometry(vertices);
    geometry.computeBoundingBox();
    const material = new THREE.LineBasicMaterial({ color: lineColor(line), transparent: true, opacity: 0.95, depthTest: false });
    const tracks = new THREE.LineSegments(geometry, material);
    tracks.renderOrder = 2;
    scene.add(tracks);
    const stations = [...new Set(line.routes.flat())].map((id) => stationById.get(id)).filter(Boolean);
    const points = new THREE.Points(makeGeometry(stations.map((s) => project(s.point))), new THREE.PointsMaterial({ color: '#edf5d8', size: 4, sizeAttenuation: false, transparent: true, opacity: 0.9, depthTest: false }));
    points.renderOrder = 3;
    points.userData = { stations, operator: data.operator, line };
    points.visible = false;
    stationMeshes.push(points);
    scene.add(points);
    view.lines.push({ tracks, points, line, stations });
    view.bounds.union(geometry.boundingBox);
  }
  visualizations.set(data.operator.id, view);
}
function renderOperators() {
  const query = $('search').value.trim().toLowerCase();
  const matches = manifest.shards.filter((s) => `${s.name.en || ''} ${s.name.ja} ${s.operator}`.toLowerCase().includes(query));
  matches.sort((a, b) => {
    const ai = preferred.indexOf(a.operator), bi = preferred.indexOf(b.operator);
    return (ai < 0 ? 999 : ai) - (bi < 0 ? 999 : bi) || name(a).localeCompare(name(b));
  });
  $('operators').replaceChildren();
  $('result-count').textContent = `${matches.length} OPERATORS`;
  for (const shard of matches) {
    const button = element('button', 'operator');
    const swatch = element('span', 'swatch');
    swatch.style.background = visualizations.get(shard.operator)?.color || palette[manifest.shards.indexOf(shard) % palette.length];
    const colors = [...new Set((datasets.get(shard.operator)?.lines || []).map(lineColor))];
    if (colors.length) swatch.style.background = `linear-gradient(to bottom, ${colors.map((color, i) => `${color} ${i / colors.length * 100}% ${(i + 1) / colors.length * 100}%`).join(', ')})`;
    const names = element('span', 'names');
    names.append(bilingualLabel(shard), element('small', '', `${shard.lines} lines`));
    button.append(swatch, names, element('span', 'arrow', '↗'));
    button.addEventListener('click', () => selectOperator(shard.operator));
    $('operators').append(button);
  }
  if (!matches.length) $('operators').append(element('p', 'empty', 'No operators found. Try a Japanese name or operator ID.'));
}
function applySelection() {
  for (const [id, view] of visualizations) {
    for (const item of view.lines) {
      const active = (!selectedOperator || id === selectedOperator) && (!selectedLine || item.line.id === selectedLine);
      item.tracks.material.opacity = active ? 0.95 : 0.08;
      item.tracks.renderOrder = active ? 2 : 1;
    }
  }
  $('station-card').hidden = true;
  $('tooltip').hidden = true;
}
function selectOperator(id) {
  if (!datasets.has(id)) return;
  selectedOperator = id;
  selectedLine = null;
  $('operators').hidden = true;
  $('details').hidden = false;
  $('search').closest('label').hidden = true;
  document.querySelector('.list-heading').hidden = true;
  document.querySelector('.explore-heading').hidden = true;
  renderDetails();
  applySelection();
  const view = visualizations.get(id);
  if (!view.bounds.isEmpty()) fit(view.bounds);
  $('map-title').replaceChildren(bilingualLabel(datasets.get(id).operator));
  document.querySelectorAll('[data-region]').forEach((b) => b.classList.remove('active'));
}
function renderDetails() {
  const data = datasets.get(selectedOperator), target = $('detail-content');
  const heading = element('h3');
  heading.append(bilingualLabel(data.operator));
  target.replaceChildren(heading, element('p', 'detail-sub', `${data.lines.length} lines · ${number(data.stations.length)} station records`));
  const link = element('a', 'api-button', 'Operator JSON ↗');
  link.href = `v0/operators/${selectedOperator}.json`;
  link.target = '_blank'; link.rel = 'noopener';
  target.append(link);
  for (const line of data.lines) {
    const button = element('button', `line-button${selectedLine === line.id ? ' active' : ''}`);
    button.setAttribute('aria-pressed', String(selectedLine === line.id));
    button.style.setProperty('--line-color', lineColor(line));
    const swatch = element('span', 'line-swatch');
    swatch.setAttribute('aria-hidden', 'true');
    button.append(swatch, bilingualLabel(line), element('small', '', `${number(line.km)} km`));
    button.addEventListener('click', () => {
      selectedLine = selectedLine === line.id ? null : line.id;
      const view = visualizations.get(selectedOperator);
      const item = view.lines.find((v) => v.line.id === selectedLine);
      fit(item ? item.tracks.geometry.boundingBox : view.bounds);
      applySelection();
      renderDetails();
    });
    target.append(button);
    if (selectedLine === line.id) {
      const list = element('div', 'station-list');
      list.style.setProperty('--line-color', lineColor(line));
      const lookup = new Map(data.stations.map((s) => [s.id, s]));
      for (const [index, route] of line.routes.entries()) {
        if (line.routes.length > 1) list.append(element('p', 'detail-sub', `Section ${index + 1}`));
        for (const id of route) {
          const station = lookup.get(id);
          if (!station) { list.append(element('p', 'detail-sub', 'Track junction')); continue; }
          const stationButton = element('button', 'station-button');
          const marker = element('span', 'station-marker', '○');
          marker.setAttribute('aria-hidden', 'true');
          stationButton.append(marker, bilingualLabel(station));
          stationButton.addEventListener('click', () => {
            showStation({ station, operator: data.operator, line });
            moveTo(project(station.point), 18);
          });
          list.append(stationButton);
        }
      }
      target.append(list);
    }
  }
  target.append(element('p', 'detail-sub', 'Distances estimated from track geometry. Registered lines may differ from passenger service names.'));
}
function clearSelection() {
  selectedOperator = selectedLine = null;
  $('details').hidden = true;
  $('operators').hidden = false;
  $('search').closest('label').hidden = false;
  document.querySelector('.list-heading').hidden = false;
  document.querySelector('.explore-heading').hidden = false;
  applySelection();
}
function pickStation(event) {
  const rect = renderer.domElement.getBoundingClientRect();
  pointer.set((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1);
  raycaster.setFromCamera(pointer, camera);
  raycaster.params.Points.threshold = camera.position.distanceTo(controls.target) * Math.tan(THREE.MathUtils.degToRad(20)) / rect.height * 14;
  const hits = raycaster.intersectObjects(stationMeshes.filter((p) => p.visible));
  if (!hits.length) return null;
  const hit = hits.sort((a, b) => a.distanceToRay - b.distanceToRay)[0];
  const { stations, operator, line } = hit.object.userData;
  return { station: stations[hit.index], operator, line };
}
function hoverStation(event) {
  if (event.buttons) return;
  const hit = pickStation(event), tip = $('tooltip');
  tip.hidden = !hit;
  renderer.domElement.style.cursor = hit ? 'pointer' : 'grab';
  if (hit) {
    const rect = renderer.domElement.getBoundingClientRect();
    tip.replaceChildren(bilingualLabel(hit.station));
    tip.style.left = `${Math.max(8, Math.min(event.clientX - rect.left + 14, rect.width - tip.offsetWidth - 8))}px`;
    tip.style.top = `${Math.max(8, event.clientY - rect.top - 38)}px`;
  }
}
function showStation({ station, operator, line }) {
  const card = $('station-card');
  card.style.setProperty('--line-color', lineColor(line));
  card.replaceChildren(element('div', 'eyebrow', 'STATION · 駅'), element('h3', '', name(station)), element('p', '', `${name(operator)} · ${name(line)}`), element('p', '', `${station.point[1].toFixed(5)}° N, ${station.point[0].toFixed(5)}° E`), element('p', '', `Station ${station.id} · Group ${station.group}`));
  card.querySelector('h3').replaceChildren(bilingualLabel(station));
  const context = card.querySelector('p');
  context.className = 'station-context';
  context.replaceChildren(bilingualLabel(operator), bilingualLabel(line));
  const close = element('button', '', '×'); close.setAttribute('aria-label', 'Close station details');
  close.onclick = () => { card.hidden = true; };
  card.append(close);
  card.hidden = false;
}
function showError(message) {
  const panel = $('loading');
  panel.hidden = false;
  panel.replaceChildren(element('p', '', 'The atlas couldn’t load'), element('small', '', message));
  const retry = element('button', 'error-retry', 'Reload atlas');
  retry.onclick = () => location.reload();
  panel.append(retry);
  $('load-status').textContent = 'Map unavailable · JSON data remains accessible';
}
async function start() {
  try {
    initScene();
    manifest = await readJSON('v0/manifest.json');
    $('operator-count').textContent = number(manifest.shards.length);
    $('line-count').textContent = number(manifest.shards.reduce((sum, s) => sum + s.lines, 0));
    $('station-count').textContent = number(manifest.shards.reduce((sum, s) => sum + s.stations, 0));
    const coastline = addCoastline().catch((error) => { console.warn('Coastline unavailable', error); return false; });
    let completed = 0, next = 0;
    const failures = [];
    // Bound concurrency so the public static host is not hit with 177 simultaneous requests.
    await Promise.all(Array.from({ length: 8 }, async () => {
      while (next < manifest.shards.length) {
        const index = next++, shard = manifest.shards[index];
        try {
          const data = await readJSON(`v0/${shard.path}`);
          datasets.set(shard.operator, data);
          addOperator(data, palette[index % palette.length]);
        } catch (error) { failures.push(shard.operator); console.warn(error); }
        completed++;
        $('progress').textContent = `${completed} / ${manifest.shards.length} operators`;
      }
    }));
    const coastResult = await coastline;
    if (!datasets.size) throw new Error('Railway files are unavailable. Check your connection and try again.');
    renderOperators();
    $('load-status').textContent = failures.length ? `${datasets.size} operators loaded · ${failures.length} unavailable — reload to retry` : `${number(manifest.shards.length)} operators · N02-25 dataset`;
    if (coastResult === false) $('load-status').textContent += ' · Coastline unavailable';
    $('loading').hidden = true;
    region('japan');
  } catch (error) { console.error(error); showError(error.message); }
}
$('search').addEventListener('input', () => { if (manifest) renderOperators(); });
$('back').onclick = () => { clearSelection(); region('japan'); };
document.querySelectorAll('[data-region]').forEach((button) => button.onclick = () => { if (!controls) return; clearSelection(); region(button.dataset.region); });
for (const [id, value] of [['flat', false], ['tilt', true]]) $(id).onclick = () => { if (!controls) return; updateViewButtons(value); moveTo(controls.target, camera.position.distanceTo(controls.target)); };
$('zoom-in').onclick = () => { if (controls) moveTo(controls.target, Math.max(3, camera.position.distanceTo(controls.target) * 0.6)); };
$('zoom-out').onclick = () => { if (controls) moveTo(controls.target, Math.min(6500, camera.position.distanceTo(controls.target) / 0.6)); };
$('reset').onclick = () => { if (activeBounds) fit(activeBounds); };
$('about-open').onclick = (event) => { event.preventDefault(); $('about').showModal(); };
$('about-close').onclick = () => $('about').close();
$('about').addEventListener('click', (event) => { if (event.target === $('about')) { const r = $('about').getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) $('about').close(); } });
document.addEventListener('keydown', (event) => {
  if (event.key === '/' && !['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName) && !$('about').open) {
    event.preventDefault(); if (selectedOperator) clearSelection(); $('search').focus();
  }
});
start();
