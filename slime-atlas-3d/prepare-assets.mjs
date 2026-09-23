import { createHash } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { unzipSync } from 'fflate';

const digest = 'c5d98189f41d7b11983069eb3ff780d8457f2256124cd8026f2ff568c2db8797';
const sources = [
  'https://slime-atlas-full-production.up.railway.app/slime-atlas.bundle.zip',
  'https://sdmntprukwest.oaiusercontent.com/files/00000000-438c-8243-b289-5fef6e41988d/raw?se=2026-09-23T21%3A36%3A49Z&sp=r&sv=2026-02-06&sr=b&scid=637b06c3-3f75-5765-9019-343800671bfb&skoid=1d6acb5b-b3f4-43ec-a5ec-b05c4a7708c8&sktid=a48cca56-e6da-484e-a814-9c849652bcb3&skt=2026-09-23T21%3A01%3A18Z&ske=2026-09-24T21%3A01%3A18Z&sks=b&skv=2026-02-06&sig=WyuqbWVU00jJ2aeUne/ywplxTDYVYad8gWUU3iPLv8U%3D'
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
