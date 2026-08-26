/**
 * 測試橋接器：讓 Python 測試能執行真正的前端 JS 模組。
 *
 * payload 來自真實的 Step 23 API 回應（`api.dispatch`），因此沒有任何 fixture
 * 檔案，也不會與 API 產生漂移。
 *
 * 用法：
 *   node web/tests/run_render.mjs <payload.json>
 *   node web/tests/run_render.mjs --error <kind> [detail.json]
 *   node web/tests/run_render.mjs --players <players.json> [requestedId]
 *   node web/tests/run_render.mjs --bootstrap <players.json> <payload.json> [requestedId]
 */

import { readFileSync } from 'node:fs';
import { buildErrorViewModel, buildViewModel } from '../render.js';
import {
  loadPlayers,
  playerEndpointUrl,
  playerListItems,
  playersEndpointUrl,
  resolvePlayerId,
} from '../app.js';

const args = process.argv.slice(2);
const read = (path) => JSON.parse(readFileSync(path, 'utf8'));
const emit = (value) => process.stdout.write(JSON.stringify(value, null, 0));

if (args[0] === '--error') {
  const kind = args[1];
  const detail = args[2] ? read(args[2]) : null;
  emit(buildErrorViewModel(kind, detail));
} else if (args[0] === '--players') {
  // 純函式層：清單映射與 player id 解析，完全不需要 DOM
  const players = read(args[1]);
  const requestedId = args[2] || null;
  emit({
    items: playerListItems(players),
    resolvedPlayerId: resolvePlayerId(players, requestedId),
    resolvedWithoutRequest: resolvePlayerId(players, null),
    resolvedWithUnknownRequest: resolvePlayerId(players, 'no-such-player'),
    playersEndpoint: playersEndpointUrl('http://127.0.0.1:8000'),
    playerEndpoints: playerListItems(players).map((i) =>
      playerEndpointUrl('http://127.0.0.1:8000', i.playerId)
    ),
  });
} else if (args[0] === '--bootstrap') {
  // 用注入的 fetch 走一次「取清單 → 取該球員資料」，記錄實際請求的 URL
  const players = read(args[1]);
  const payload = read(args[2]);
  const requestedId = args[3] || null;
  const requested = [];
  const fetchImpl = async (url) => {
    requested.push(url);
    if (url.endsWith('/api/players')) {
      return { status: 200, json: async () => players };
    }
    return { status: 200, json: async () => payload };
  };
  const base = 'http://127.0.0.1:8000';
  const list = await loadPlayers(base, fetchImpl);
  const activePlayerId = resolvePlayerId(list.body, requestedId);
  const detail = await fetchImpl(playerEndpointUrl(base, activePlayerId));
  const body = await detail.json();
  emit({
    requestedUrls: requested,
    listStatus: list.status,
    activePlayerId,
    detailStatus: detail.status,
    // 用真正的 render.js 建 view model，證明選到的球員資料能正常呈現
    viewModelPlayerName: buildViewModel(body).header.playerName.text,
  });
} else {
  emit(buildViewModel(read(args[0])));
}
