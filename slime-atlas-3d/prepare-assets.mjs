import { createHash } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { unzipSync } from 'fflate';

const digest = '4f2fb2f35ea5d3088f34a6f7a0ffecddb6b58be4bc4996e4383493f271a4d378';
const sources = [
  'https://slime-atlas-v2-production.up.railway.app/slime-atlas.bundle.zip',
  'https://sdmntpritalynorth.oaiusercontent.com/files/00000000-8f3c-8246-b3bb-1a4fec50ff6d/raw?se=2026-09-23T21%3A00%3A53Z&sp=r&sv=2026-02-06&sr=b&scid=88b0b7c8-bd0d-57d1-bdbc-4092e3328500&skoid=1d6acb5b-b3f4-43ec-a5ec-b05c4a7708c8&sktid=a48cca56-e6da-484e-a814-9c849652bcb3&skt=2026-09-23T05%3A36%3A25Z&ske=2026-09-24T05%3A36%3A25Z&sks=b&skv=2026-02-06&sig=tZ5luTBQVrJf1ohpyd4p%2BneAkkJ3iTMetQ8zUG188LU%3D'
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
    console.log('Slime Atlas bundle fetched from', new URL(source).host);
    break;
  } catch (error) {
    console.log('Slime Atlas source unavailable:', error.message);
  }
}

if (!archive) throw new Error('Unable to fetch Slime Atlas V2 bundle');

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
console.log('Slime Atlas V2 installed:', Object.keys(files).length, 'files');
