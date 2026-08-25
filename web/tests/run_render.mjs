/**
 * 測試橋接器：讀一份 payload JSON，用 web/render.js 建出 view model，印成 JSON。
 *
 * 由 tests/test_frontend.py 呼叫。payload 來自真實的 Step 23 API 回應
 * （`api.dispatch`），因此沒有任何 fixture 檔案，也不會與 API 產生漂移。
 *
 * 用法：
 *   node web/tests/run_render.mjs <payload.json> [--error <kind> <detail.json>]
 */

import { readFileSync } from 'node:fs';
import { buildErrorViewModel, buildViewModel } from '../render.js';

const args = process.argv.slice(2);

if (args[0] === '--error') {
  const kind = args[1];
  const detail = args[2] ? JSON.parse(readFileSync(args[2], 'utf8')) : null;
  process.stdout.write(
    JSON.stringify(buildErrorViewModel(kind, detail), null, 0)
  );
} else {
  const payload = JSON.parse(readFileSync(args[0], 'utf8'));
  process.stdout.write(JSON.stringify(buildViewModel(payload), null, 0));
}
