#!/usr/bin/env node
/** i18n 门禁：JSX/TS 中的中文必须只活在 i18n.ts 与 samples.ts（字典区）。
 *  用法：pnpm i18n:lint（CI 可接）。注释行豁免，用户数据与引擎原文不在源码字面量中。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

const ROOT = new URL('.', import.meta.url).pathname + '../src';
const CJK = /[\u4e00-\u9fff]/;
const ALLOW_FILES = new Set(['i18n.ts', 'samples.ts']);

function* walk(dir) {
  for (const e of readdirSync(dir)) {
    const p = join(dir, e);
    if (statSync(p).isDirectory()) yield* walk(p);
    else if (/\.(tsx?|ts)$/.test(e)) yield p;
  }
}

let bad = 0;
for (const file of walk(ROOT)) {
  const name = file.split('/').pop();
  if (ALLOW_FILES.has(name)) continue;
  for (const [i, line] of readFileSync(file, 'utf8').split('\n').entries()) {
    const s = line.trim();
    if (!s || s.startsWith('//') || s.startsWith('*') || s.startsWith('/*') || s.startsWith('import')) continue;
    if (/^(中|EN)$/.test(s)) continue; // 语言专名（分段选择器），中英模式共用
    if (CJK.test(s)) {
      console.log(`${name}:${i + 1}: ${s.slice(0, 80)}`);
      bad++;
    }
  }
}

// t('key') 引用的 key 必须在字典两边都存在（跳过字典自身，避免定义行误报）
const dictSrc = readFileSync(join(ROOT, 'i18n.ts'), 'utf8');
const zhKeys = new Set([...dictSrc.matchAll(/^\s{4}(\w+):/gm)].map((m) => m[1]));
const used = new Set();
for (const file of walk(ROOT)) {
  if (ALLOW_FILES.has(file.split('/').pop())) continue;
  const src = readFileSync(file, 'utf8');
  for (const m of src.matchAll(/\bt\(\s*['"]([\w]+)['"]/g)) used.add(m[1]);
  for (const m of src.matchAll(/label:\s*['"]([\w]+)['"]/g)) used.add(m[1]);
}
for (const k of used) {
  if (!zhKeys.has(k)) {
    console.log(`missing key: t('${k}')`);
    bad++;
  }
}
if (bad > 0) {
  console.log(`\ni18n-lint: ${bad} problem(s)`);
  process.exit(1);
}
console.log('i18n-lint: clean');
