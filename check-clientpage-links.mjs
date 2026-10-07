import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { runInNewContext } from 'node:vm';
import { clientpageClients } from './clientpage-clients.js';

assert.equal(clientpageClients['서윤웰스'], 'sywells');
assert.equal(new Set(Object.values(clientpageClients)).size, Object.keys(clientpageClients).length);
for (const filename of ['full.html', 'playlist.html', 'lists.html']) {
  const html = readFileSync(new URL(filename, import.meta.url), 'utf8');
  assert.ok(html.includes('import { clientpageClients }'), filename);
  for (const [, script] of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)) {
    if (script.trim()) execFileSync(process.execPath, ['--input-type=module', '--check'], {
      input: script, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'],
    });
  }
}
const html = readFileSync(new URL('playlist.html', import.meta.url), 'utf8');
const start = html.indexOf('window.removeFromList =');
const handler = html.slice(start, html.indexOf('\nfunction render(){', start));
assert.ok(start >= 0 && handler.includes('Object.hasOwn(clientpageClients,state.list)'));
for (const name of Object.keys(clientpageClients)) {
  const window = {};
  runInNewContext(handler, {window, state: {list:name}, clientpageClients,
    confirm: () => {throw new Error('고객 추천 목록을 Firestore에서 삭제하려 함');}});
  await window.removeFromList({preventDefault(){},stopPropagation(){}}, 'example-program');
}
console.log('고객 6곳 추천 연결·스크립트 문법·공개 화면 삭제 차단 확인');
