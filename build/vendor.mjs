import { mkdir, copyFile } from 'node:fs/promises';
const root = new URL('../', import.meta.url);
await mkdir(new URL('assets/vendor/', root), { recursive: true });
for (const [source, target] of [
  ['build/three.module.min.js', 'three.module.js'],
  ['build/three.core.min.js', 'three.core.min.js'],
  ['examples/jsm/controls/OrbitControls.js', 'OrbitControls.js'],
  ['LICENSE', 'THREE-LICENSE.txt'],
]) await copyFile(new URL(`node_modules/three/${source}`, root), new URL(`assets/vendor/${target}`, root));
console.log('Vendored Three.js and OrbitControls for static hosting.');
