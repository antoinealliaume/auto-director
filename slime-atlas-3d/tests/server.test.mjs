import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import http from 'node:http';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const projectDir = dirname(dirname(fileURLToPath(import.meta.url)));

function request(port, path) {
  return new Promise((resolve, reject) => {
    const req = http.request({ host: '127.0.0.1', port, path }, (res) => {
      let body = '';
      res.setEncoding('utf8');
      res.on('data', (chunk) => {
        body += chunk;
      });
      res.on('end', () => resolve({ statusCode: res.statusCode, body }));
    });
    req.on('error', reject);
    req.end();
  });
}

function waitForListening(child) {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('server did not start')), 5000);
    child.once('exit', (code) => {
      clearTimeout(timeout);
      reject(new Error(`server exited before listening (${code})`));
    });
    child.stdout.on('data', (chunk) => {
      if (chunk.toString().includes('Slime Atlas listening on port')) {
        clearTimeout(timeout);
        resolve();
      }
    });
  });
}

test('malformed percent escapes return 400 without crashing the server', async () => {
  const port = 20000 + (process.pid % 20000);
  const child = spawn(process.execPath, [join(projectDir, 'server.js')], {
    cwd: projectDir,
    env: { ...process.env, PORT: String(port) },
    stdio: ['ignore', 'pipe', 'pipe']
  });

  try {
    await waitForListening(child);
    const malformed = await request(port, '/%');
    assert.equal(malformed.statusCode, 400);

    const healthy = await request(port, '/');
    assert.equal(healthy.statusCode, 200);
    assert.equal(child.exitCode, null);
  } finally {
    child.kill();
  }
});
