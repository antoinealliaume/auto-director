import { createHash } from 'node:crypto';
import { mkdir, writeFile, readFile, copyFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { unzipSync } from 'fflate';

const digest = 'c5d98189f41d7b11983069eb3ff780d8457f2256124cd8026f2ff568c2db8797';
const sources = [
  'https://slime-atlas-v3-unique.onrender.com/slime-atlas.bundle.zip',
  'https://slime-atlas-full-production.up.railway.app/slime-atlas.bundle.zip',
];
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
let archive;

for (const source of sources) {
  try {
    const response = await fetch(source, { signal: AbortSignal.timeout(120000) });
    if (!response.ok || (response.headers.get('content-type') || '').includes('text/html')) {
      await response.body?.cancel();
      continue;
    }
    const chunks = [];
    let total = 0;
    for await (const chunk of response.body) {
      total += chunk.byteLength;
      if (total > 64 * 1024 * 1024) throw new Error('Slime bundle exceeds transfer limit');
      chunks.push(Buffer.from(chunk));
    }
    const bytes = Buffer.concat(chunks);
    if (sha(bytes) !== digest) throw new Error('Slime bundle checksum mismatch');
    archive = bytes;
    console.log('Slime Atlas V3 bundle fetched from', new URL(source).host);
    break;
  } catch (error) {
    console.log('Slime Atlas source unavailable:', error.message);
  }
}

if (!archive) throw new Error('Unable to fetch Slime Atlas V3 bundle');

const allowed = /^(assets\.sha256\.json|catalog\.json|index\.html|math\.js|style\.css|viewer\.js|models\/s\d{3}\.glb|previews\/s\d{3}-[0-4]\.jpg)$/;
let expanded = 0;
const files = unzipSync(new Uint8Array(archive), {
  filter(file) {
    if (!allowed.test(file.name)) throw new Error('Unexpected file in Slime Atlas bundle: ' + file.name);
    expanded += file.originalSize;
    if (expanded > 160 * 1024 * 1024) throw new Error('Expanded Slime Atlas bundle exceeds limit');
    return true;
  }
});

if (Object.keys(files).length !== 582) throw new Error('Unexpected Slime Atlas file count: ' + Object.keys(files).length);

for (const [name, bytes] of Object.entries(files)) {
  const destination = join('public', name);
  await mkdir(dirname(destination), { recursive: true });
  await writeFile(destination, bytes);
}

await writeFile('public/slime-atlas.bundle.zip', archive);
console.log('Slime Atlas V3 installed:', Object.keys(files).length, 'files');

// The archive contains models/textures; the versioned V4 viewer always wins.
for (const name of ['index.html','viewer.js','vfx.js','math.js']) {
  await copyFile(join('v4',name),join('public',name));
}
const hashes = {};
for (const name of [...Object.keys(files).filter(n=>n!=='assets.sha256.json'),'vfx.js']) {
  hashes[name] = sha(await readFile(join('public',name)));
}
await writeFile('public/assets.sha256.json',JSON.stringify(hashes,null,2));
await writeFile('public/version.json',JSON.stringify({version:4,engine:'no-added-objects',species:96,build:'2026-09-24-v4.0.4'}));
console.log('Slime Atlas V4 installed: added objects removed');
