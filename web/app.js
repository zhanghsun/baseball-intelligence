/**
 * Step 24 Frontend — DOM 層。
 *
 * 職責只有兩件事：
 *   1. 透過 HTTP 呼叫 Step 23 的 API
 *   2. 把 render.js 產生的 view model 畫成 DOM
 *
 * 這裡沒有任何計算、排序、篩選或解讀。所有事實都來自 API。
 * 不讀 data/raw、不讀 data/processed，也不知道 backend 怎麼算出這些數字。
 */

import {
  NO_DATA,
  buildErrorViewModel,
  buildViewModel,
} from './render.js';

const DEFAULT_API_BASE = 'http://127.0.0.1:8000';
const PLAYERS_PATH = '/api/players';
const ORIGIN_RE = /^https?:\/\/[A-Za-z0-9.\-]+(:\d+)?$/;
const PLAYER_ID_RE = /^[a-z0-9-]+$/;

/** 允許用 ?api=http://host:port 覆寫，方便本機換 port。格式嚴格驗證。 */
function resolveApiBase() {
  const params = new URLSearchParams(window.location.search);
  const override = params.get('api');
  if (override && ORIGIN_RE.test(override)) return override.replace(/\/$/, '');
  return DEFAULT_API_BASE;
}

/** 允許用 ?player=<player_id> 深層連結到特定球員。格式嚴格驗證。 */
function resolveRequestedPlayerId() {
  const params = new URLSearchParams(window.location.search);
  const requested = params.get('player');
  return requested && PLAYER_ID_RE.test(requested) ? requested : null;
}

// ------------------------------------------------------- player registry（UI 層）

/**
 * `/api/players` 的球員清單 -> 選單項目。
 *
 * **順序完全照 API 給的順序**，沒有 sort。這裡只做欄位取用，不做任何計算。
 */
export function playerListItems(playersPayload) {
  const players = (playersPayload && playersPayload.players) || [];
  return players.map((p) => ({
    playerId: p.player_id,
    playerName: p.player_name,
    team: p.team,
    season: p.season,
    kindName: p.kind_name,
    label: `${p.player_name}（${p.team}）· ${p.season} ${p.kind_name}`,
  }));
}

/**
 * 決定要載入哪一位球員。
 *
 * 規則：`?player=` 指定且真的在清單裡就用它，否則用清單第一筆（registry 順序）。
 * 清單為空時回 null。**不猜測、不 fallback 到任何寫死的 id。**
 */
export function resolvePlayerId(playersPayload, requestedId) {
  const items = playerListItems(playersPayload);
  if (items.length === 0) return null;
  if (requestedId && items.some((i) => i.playerId === requestedId)) {
    return requestedId;
  }
  return items[0].playerId;
}

/** 組出某位球員的 product output 端點 URL。 */
export function playerEndpointUrl(apiBase, playerId) {
  return `${apiBase}/api/player/${playerId}`;
}

/** 組出球員清單端點 URL。 */
export function playersEndpointUrl(apiBase) {
  return `${apiBase}${PLAYERS_PATH}`;
}

// ---------------------------------------------------------------- DOM 工具

function el(tag, opts = {}, children = []) {
  const node = document.createElement(tag);
  if (opts.className) node.className = opts.className;
  if (opts.text !== undefined && opts.text !== null) node.textContent = String(opts.text);
  if (opts.title) node.title = opts.title;
  if (opts.attrs) {
    for (const [k, v] of Object.entries(opts.attrs)) {
      if (v !== null && v !== undefined) node.setAttribute(k, String(v));
    }
  }
  for (const child of children) {
    if (child) node.appendChild(child);
  }
  return node;
}

/**
 * 數值 cell -> DOM。
 * 缺值時顯示「尚無資料」／「無法計算」並附原因，絕不顯示 0 / undefined / NaN。
 */
function valueNode(cell, { big = false } = {}) {
  if (!cell || cell.isNull) {
    const reason = cell ? cell.reason : null;
    return el('span', { className: 'missing' }, [
      el('span', { className: 'missing-label', text: cell ? cell.text : NO_DATA }),
      reason ? el('span', { className: 'missing-reason', text: reason }) : null,
    ]);
  }
  const wrap = el('span', { className: big ? 'value value-big' : 'value' });
  wrap.appendChild(el('span', { className: 'value-main', text: cell.text }));
  if (cell.full) {
    wrap.appendChild(
      el('span', {
        className: 'value-full',
        text: cell.full,
        title: '完整精度（來自 API，未經四捨五入）',
      })
    );
  }
  return wrap;
}

function statusBadge(status, extraClass = '') {
  return el('span', {
    className: `badge badge-${status.value} ${extraClass}`.trim(),
    text: status.label,
    title: status.value,
  });
}

function kv(labelText, valueEl) {
  return el('div', { className: 'kv' }, [
    el('span', { className: 'kv-label', text: labelText }),
    el('span', { className: 'kv-value' }, [valueEl]),
  ]);
}

function note(text, className = 'note') {
  if (!text) return null;
  return el('p', { className, text });
}

function detailsBlock(summaryText, children, { className = 'details' } = {}) {
  const d = el('details', { className });
  d.appendChild(el('summary', { text: summaryText }));
  const body = el('div', { className: 'details-body' }, children);
  d.appendChild(body);
  return d;
}

function section(id, titleText, subtitleText, children) {
  return el('section', { className: 'card', attrs: { id } }, [
    el('header', { className: 'card-head' }, [
      el('h2', { text: titleText }),
      subtitleText ? el('p', { className: 'card-sub', text: subtitleText }) : null,
    ]),
    el('div', { className: 'card-body' }, children),
  ]);
}

// ---------------------------------------------------------------- A. header

function renderHeader(h) {
  const root = el('header', { className: 'page-head' });

  const idBlock = el('div', { className: 'identity' }, [
    el('h1', { text: h.playerName.text }),
    el('div', { className: 'identity-meta' }, [
      el('span', { text: `${h.season.text} ${h.kindName.text}` }),
      el('span', { className: 'dot', text: '·' }),
      el('span', { text: h.team.text }),
      el('span', { className: 'dot', text: '·' }),
      el('span', { className: 'mono', text: `Acnt ${h.playerAcnt.text}` }),
    ]),
    el('div', { className: 'identity-counts' }, [
      el('span', { text: `${h.gamesPlayed.text} 場出賽` }),
      el('span', { className: 'dot', text: '·' }),
      el('span', { text: `${h.plateAppearances.text} PA` }),
      el('span', { className: 'dot', text: '·' }),
      el('span', { text: `${h.atBats.text} AB` }),
    ]),
  ]);

  const asOf = h.dataAsOf;
  const asOfBlock = el('div', { className: 'as-of' }, [
    el('span', { className: 'as-of-label', text: '資料截至' }),
    el('span', { className: 'as-of-date', text: asOf.referenceDate.text }),
    el('span', { className: 'as-of-basis', text: asOf.basis }),
    el('span', {
      className: 'as-of-flag',
      text: asOf.clockIndependent ? '不依賴系統時鐘' : '',
    }),
    detailsBlock(
      '資料版本（來源檔 sha256）',
      [
        note(asOf.isNotRequestTime),
        el(
          'ul',
          { className: 'digest-list' },
          asOf.sourceFileDigests.map((f) =>
            el('li', {}, [
              el('span', { className: 'mono', text: f.path }),
              el('span', { className: 'mono muted', text: f.sha256.slice(0, 16) }),
              el('span', { className: 'muted', text: `${f.bytes} bytes` }),
            ])
          )
        ),
        el('p', {
          className: 'note',
          text: `API ${h.versions.apiVersion} · Product Output ${h.versions.productOutputVersion} · 唯讀`,
        }),
      ],
      { className: 'details details-inline' }
    ),
  ]);

  root.appendChild(idBlock);
  root.appendChild(asOfBlock);
  return root;
}

// ---------------------------------------------------------------- B. next game

function renderNextGame(ng) {
  const grid = el(
    'div',
    { className: 'grid grid-next' },
    ng.fields.map((f) => kv(f.label, valueNode(f.cell)))
  );

  const resultRow = el('div', { className: 'pending-row' }, [
    el('span', { className: 'kv-label', text: ng.result.label }),
    el('div', { className: 'pending-body' }, [
      el('div', { className: 'pending-head' }, [
        el('span', { className: 'missing-label', text: ng.result.display }),
        statusBadge(ng.result.dataStatus),
      ]),
      note(ng.result.reason, 'missing-reason'),
    ]),
  ]);

  const sp = ng.startingPitcher;
  const pitcherRow = el('div', { className: 'pending-row' }, [
    el('span', { className: 'kv-label', text: sp.label }),
    el('div', { className: 'pending-body' }, [
      el('div', { className: 'pending-head' }, [
        el('span', { className: 'mono', text: `Acnt ${sp.acnt.text}` }),
        statusBadge(sp.dataStatus),
      ]),
      kv('投手姓名', valueNode(sp.name)),
      kv('所屬', el('span', { text: `${sp.team.text}（${sp.teamSide.text}）` })),
      detailsBlock('為什麼標為尚未確認', [
        note(sp.unconfirmedReason),
        el('p', { className: 'note mono', text: `verification_status = ${sp.verificationStatus}` }),
      ]),
    ]),
  ]);

  const hand = ng.startingPitcherHand;
  const handRow = el('div', { className: 'pending-row' }, [
    el('span', { className: 'kv-label', text: hand.label }),
    el('div', { className: 'pending-body' }, [
      el('div', { className: 'pending-head' }, [
        valueNode(hand.hand),
        statusBadge(hand.dataStatus),
      ]),
      detailsBlock('取得方式與目前限制', [
        note(hand.requiredToResolve, 'note mono'),
        el('p', { className: 'note mono', text: `verification_status = ${hand.verificationStatus}` }),
      ]),
    ]),
  ]);

  const rule = detailsBlock('下一場是怎麼選出來的', [
    kv('參考日', el('span', { className: 'mono', text: ng.selectionRule.referenceDate })),
    note(ng.selectionRule.basis),
    note(ng.selectionRule.rule),
    note(ng.selectionRule.note),
  ]);

  return section(
    'next-game',
    'B. 下一場比賽',
    ng.isNot,
    [grid, resultRow, pitcherRow, handRow, rule]
  );
}

// ---------------------------------------------------------------- C. season baseline

function renderSeasonBaseline(sb) {
  const metricCards = el(
    'div',
    { className: 'grid grid-baseline' },
    sb.metrics.map((m) =>
      el('div', { className: 'metric-card' }, [
        el('div', { className: 'metric-card-head' }, [
          el('span', { className: 'metric-name', text: m.label }),
        ]),
        valueNode(m.value, { big: true }),
        el('div', { className: 'metric-sample' }, [
          el('span', { text: `AB ${m.sampleSize.atBats.text}` }),
          el('span', { className: 'dot', text: '·' }),
          el('span', { text: `PA ${m.sampleSize.plateAppearances.text}` }),
        ]),
        el('div', { className: 'metric-formula mono', text: m.derivation }),
        el('div', { className: 'metric-source muted', text: m.sourceStep }),
        m.note ? note(m.note) : null,
      ])
    )
  );

  const counts = el(
    'div',
    { className: 'grid grid-counts' },
    sb.counts.map((c) => kv(c.label, valueNode(c.cell)))
  );

  return section('season-baseline', 'C. 季累計基準', sb.definition, [
    metricCards,
    detailsBlock('季累計原始計數', [counts, note(sb.hoistingNote)]),
  ]);
}

// ---------------------------------------------------------------- metric 表

function renderMetricTable(group) {
  const table = el('table', { className: 'metric-table' });
  const thead = el('thead', {}, [
    el('tr', {}, [
      el('th', { text: '指標' }),
      el('th', { text: '本切分' }),
      el('th', { text: '季累計基準' }),
      el('th', { text: '差距' }),
      el('th', { text: '方向' }),
      el('th', { text: '樣本' }),
      el('th', { text: '單一事件敏感度' }),
      el('th', { text: '滾動分布位置' }),
    ]),
  ]);
  table.appendChild(thead);

  const tbody = el('tbody');
  for (const row of group.metrics) {
    const tr = el('tr', { className: row.available ? '' : 'row-missing' });
    tr.appendChild(el('th', { className: 'metric-name', text: row.label }));
    tr.appendChild(el('td', { attrs: { 'data-label': '本切分' } }, [valueNode(row.current)]));
    tr.appendChild(el('td', { attrs: { 'data-label': '季累計基準' } }, [valueNode(row.baseline)]));
    tr.appendChild(
      el('td', { className: 'cell-diff', attrs: { 'data-label': '差距' } }, [
        valueNode(row.difference),
      ])
    );
    tr.appendChild(
      el('td', { attrs: { 'data-label': '方向' } }, [
        row.direction.value
          ? el('span', {
              className: `direction direction-${row.direction.value}`,
              text: row.direction.label,
              title: row.direction.value,
            })
          : el('span', { className: 'missing-label', text: NO_DATA }),
      ])
    );

    if (row.sampleSize) {
      tr.appendChild(
        el('td', { className: 'cell-sample', attrs: { 'data-label': '樣本' } }, [
          el('span', { text: `AB ${row.sampleSize.atBats.text}` }),
          el('span', { text: `PA ${row.sampleSize.plateAppearances.text}` }),
          row.sampleSize.games.isNull
            ? el('span', { className: 'missing' }, [
                el('span', { className: 'missing-label', text: `場次 ${NO_DATA}` }),
                el('span', {
                  className: 'missing-reason',
                  text: row.sampleSize.games.reason || '',
                }),
              ])
            : el('span', { text: `場次 ${row.sampleSize.games.text}` }),
        ])
      );
    } else {
      tr.appendChild(el('td', { attrs: { 'data-label': '樣本' } }, [valueNode(null)]));
    }

    if (row.sensitivity) {
      const s = row.sensitivity;
      tr.appendChild(
        el('td', { className: 'cell-sens', attrs: { 'data-label': '單一事件敏感度' } }, [
          el('span', { className: 'mono', text: s.fraction }),
          el('span', { className: 'muted', text: `＋1 → ${s.oneMore.text}` }),
          el('span', { className: 'muted', text: `−1 → ${s.oneFewer.text}` }),
          el('span', { className: 'muted', text: `Δ ${s.delta.text}` }),
          el('span', { className: 'micro', text: s.isNot }),
        ])
      );
    } else {
      tr.appendChild(
        el('td', { attrs: { 'data-label': '單一事件敏感度' } }, [valueNode(null)])
      );
    }

    if (row.rolling) {
      tr.appendChild(
        el('td', { className: 'cell-rolling', attrs: { 'data-label': '滾動分布位置' } }, [
          el('span', {
            className: 'mono',
            text: `${row.rolling.rankDesc} / ${row.rolling.distributionN}`,
          }),
          el('span', { className: 'muted', text: row.rolling.percentileRankText }),
          el('span', { className: 'micro', text: row.rolling.sourceStep }),
        ])
      );
    } else {
      tr.appendChild(
        el('td', { attrs: { 'data-label': '滾動分布位置' } }, [
          el('span', { className: 'missing' }, [
            el('span', { className: 'missing-label', text: NO_DATA }),
            row.rollingReason
              ? el('span', { className: 'missing-reason', text: row.rollingReason })
              : null,
          ]),
        ])
      );
    }
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  return table;
}

function renderCrossMetric(cm) {
  if (!cm.available) {
    return el('div', { className: 'cross-metric cross-metric-none' }, [
      el('span', { className: 'cross-label', text: '跨指標方向摘要' }),
      el('span', { className: 'missing-label', text: NO_DATA }),
      el('span', { className: 'missing-reason', text: cm.reason }),
    ]);
  }
  return el('div', { className: 'cross-metric' }, [
    el('div', { className: 'cross-head' }, [
      el('span', { className: 'cross-label', text: '跨指標方向摘要' }),
      el('span', { className: 'cross-consistency mono', text: cm.consistency }),
    ]),
    el(
      'div',
      { className: 'cross-metrics' },
      cm.perMetric.map((p) =>
        el('span', { className: `direction direction-${p.direction}` }, [
          el('span', { className: 'cross-metric-name', text: p.metricLabel }),
          el('span', { text: p.directionLabel }),
        ])
      )
    ),
    detailsBlock('這個摘要不含新數值', [
      note(cm.addsNoNewNumberBasis),
      note(cm.knownLimitation),
      el('p', { className: 'note mono', text: cm.sourceCandidateId }),
    ]),
  ]);
}

function renderLimitations(lim) {
  const children = [];

  children.push(
    el('div', { className: 'lim-block' }, [
      el('h4', { text: '樣本規模' }),
      el('div', { className: 'lim-row' }, [
        el('span', { text: `AB ${lim.sample.atBats.text}` }),
        el('span', { className: 'dot', text: '·' }),
        el('span', { text: `PA ${lim.sample.plateAppearances.text}` }),
        el('span', { className: 'dot', text: '·' }),
        lim.sample.games.isNull
          ? el('span', { className: 'missing-label', text: `場次 ${NO_DATA}` })
          : el('span', { text: `場次 ${lim.sample.games.text}` }),
      ]),
      lim.sample.games.isNull && lim.sample.games.reason
        ? note(lim.sample.games.reason, 'missing-reason')
        : null,
      el(
        'div',
        { className: 'lim-row' },
        lim.sample.singleEventDelta.map((d) =>
          el('span', { className: 'muted' }, [
            el('span', { className: 'metric-name', text: d.label }),
            el('span', { text: ` Δ ${d.cell.text}` }),
          ])
        )
      ),
      note(lim.sample.isNotAFilter),
    ])
  );

  if (lim.unavailableMetrics.count > 0) {
    children.push(
      el('div', { className: 'lim-block lim-warn' }, [
        el('h4', { text: '無法計算的指標' }),
        el('div', { className: 'lim-row' }, [
          el('span', { className: 'missing-label', text: lim.unavailableMetrics.metrics.join('、') }),
        ]),
        note(lim.unavailableMetrics.reason, 'missing-reason'),
        note(lim.unavailableMetrics.valuePolicy),
      ])
    );
  }

  children.push(
    el('div', { className: 'lim-block' }, [
      el('h4', { text: '應用到下一場所需的額外資料' }),
      el(
        'ul',
        { className: 'req-list' },
        lim.required.map((r) =>
          el('li', { className: r.isGap ? 'req-gap' : 'req-ok' }, [
            el('div', { className: 'req-head' }, [
              el('span', { className: 'mono', text: r.item }),
              statusBadge({ value: r.status, label: r.statusLabel }),
            ]),
            note(r.factualBasis),
            el('p', {
              className: 'micro',
              text: r.evidenceSteps.length
                ? `依據 ${r.evidenceSteps.join(' / ')}`
                : '尚未調查，因此沒有依據 Step',
            }),
          ])
        )
      ),
      note(lim.noGuessingNote),
    ])
  );

  if (lim.temporalLimitation) {
    children.push(
      el('div', { className: 'lim-block' }, [
        el('h4', { text: '時間維度限制' }),
        note(lim.temporalLimitation),
      ])
    );
  }

  children.push(
    el('div', { className: 'lim-block' }, [
      el('h4', { text: '這份資料不是什麼' }),
      note(lim.notANextGameProjection),
    ])
  );

  return el('div', { className: 'limitations' }, children);
}

function renderGroupTraceability(tr) {
  return detailsBlock(
    '資料來源與可追溯性',
    [
      el(
        'div',
        { className: 'trace-list' },
        tr.entries.map((e) =>
          el('div', { className: 'trace-item' }, [
            el('div', { className: 'trace-head' }, [
              el('span', { className: 'metric-name', text: e.label }),
              el('span', { className: 'muted mono', text: e.sourceStepIds.join(' / ') }),
            ]),
            kv('source file', el('span', { className: 'mono', text: e.sourceFile })),
            kv(
              'source field',
              el('span', { className: 'mono', text: JSON.stringify(e.sourceField) })
            ),
            kv('derivation', el('span', { className: 'mono', text: e.derivation })),
            e.gameSnos
              ? kv(
                  `game_snos（${e.gameSnosCount} 場）`,
                  el('span', { className: 'mono', text: e.gameSnos.join(', ') })
                )
              : el('div', { className: 'kv' }, [
                  el('span', { className: 'kv-label', text: 'game_snos' }),
                  el('span', { className: 'kv-value missing' }, [
                    el('span', { className: 'missing-label', text: NO_DATA }),
                    el('span', {
                      className: 'missing-reason',
                      text: e.gameSnosMissingReason || '',
                    }),
                  ]),
                ]),
            e.dateRange
              ? kv(
                  '日期範圍',
                  el('span', {
                    className: 'mono',
                    text: `${e.dateRange.first_game_date} ~ ${e.dateRange.last_game_date}`,
                  })
                )
              : null,
            el('p', { className: 'micro mono', text: e.sourceCandidateId }),
          ])
        )
      ),
      el('p', { className: 'micro', text: tr.stepChain.join(' → ') }),
      note(tr.everyNumberTraceableBasis),
    ],
    { className: 'details details-trace' }
  );
}

/** 一個 insight group 卡片。順序由呼叫端給，這裡不排序。 */
function renderGroupCard(group, ref) {
  const head = el('div', { className: 'group-head' }, [
    el('div', { className: 'group-title' }, [
      el('h3', { text: group.scope }),
      group.officialItemName
        ? el('span', { className: 'group-official', text: `官方分項「${group.officialItemName}」` })
        : null,
      ref && ref.presentationPurpose
        ? el('span', { className: 'group-purpose mono', text: ref.presentationPurpose })
        : null,
    ]),
    el('div', { className: 'group-tags' }, [
      el('span', { className: 'tag', text: group.temporal.label }),
      el('span', { className: 'tag', text: group.contextual.label }),
      el('span', {
        className: 'tag tag-interp',
        text: group.interpretationStatus.label,
        title: group.interpretationStatus.value,
      }),
      el('span', { className: 'tag tag-muted', text: `${group.candidateCount} candidates` }),
    ]),
  ]);

  /**
   * 兩個資料狀態分開呈現，刻意不合併成單一燈號。
   * application != available 不代表 evidence 有問題。
   */
  const statusPanel = el('div', { className: 'status-split' }, [
    el('div', { className: 'status-col' }, [
      el('span', { className: 'status-title', text: 'Evidence（數字本身）' }),
      statusBadge(group.dataStatus.evidence, 'badge-lg'),
    ]),
    el('div', { className: 'status-divider' }),
    el('div', { className: 'status-col' }, [
      el('span', { className: 'status-title', text: 'Application（能否用於下一場）' }),
      statusBadge(group.dataStatus.application, 'badge-lg'),
      group.decision.additionalData
        ? el('span', { className: 'status-req mono', text: `需要 ${group.decision.additionalData}` })
        : null,
    ]),
  ]);

  const statusNote = note(group.dataStatus.separationNote, 'note note-status');

  const decision = detailsBlock('決策關聯（來自 Step 19，原樣引用）', [
    kv(
      'evidence 是否依賴下一場',
      el('span', { text: group.decision.evidenceDependsOnNextGame ? '是' : '否' })
    ),
    note(group.decision.evidenceDependsBasis),
    kv(
      '可連到的決策領域',
      el('span', { className: 'mono', text: group.decision.possibleDecisionArea })
    ),
    kv(
      'action link',
      el('span', { className: 'mono', text: group.decision.possibleActionLink })
    ),
    note(group.decision.isNot),
  ]);

  return el('article', { className: 'group-card', attrs: { 'data-scope': group.scope } }, [
    head,
    statusPanel,
    statusNote,
    renderMetricTable(group),
    renderCrossMetric(group.crossMetric),
    renderLimitations(group.limitations),
    decision,
    renderGroupTraceability(group.traceability),
  ]);
}

// ---------------------------------------------------------------- D / E. sections

function renderSection(sec, insights) {
  const meta = el('div', { className: 'section-meta' }, [
    el('span', { text: `${sec.groupCount} 個 group` }),
    el('span', { className: 'dot', text: '·' }),
    el('span', { text: `${sec.candidateCount} 個 candidate` }),
    el('span', { className: 'dot', text: '·' }),
    el('span', { text: sec.temporal.label }),
  ]);

  const subgroups = el(
    'div',
    { className: 'subgroups' },
    Object.keys(sec.subgroupsByContextualRelevance).map((rel) =>
      el('span', { className: 'tag tag-muted' }, [
        el('span', { className: 'mono', text: rel }),
        el('span', { text: `：${sec.subgroupsByContextualRelevance[rel].join('、')}` }),
      ])
    )
  );

  const rule = detailsBlock('成員是怎麼決定的', [
    note(sec.memberSelectionRule.rule_text),
    kv(
      'rule_inputs',
      el('span', { className: 'mono', text: sec.memberSelectionRule.rule_inputs.join(', ') })
    ),
    kv(
      '未被使用的量',
      el('span', { className: 'mono', text: sec.memberSelectionRule.rule_not_inputs.join(', ') })
    ),
    el('p', {
      className: 'note',
      text: sec.memberSelectionRule.all_groups_included
        ? '全部 group 都納入，沒有任何 group 被隱藏或挑選。'
        : '',
    }),
  ]);

  const groups = el(
    'div',
    { className: 'group-list' },
    // 順序照 view model 的 groupRefs（＝ API insight_refs 順序），這裡沒有 sort()。
    // section 只有參照，數值一律從 insights 查表取得。
    sec.groupRefs.map((ref) => renderGroupCard(insights[ref.insightIndex], ref))
  );

  const heading = sec.sectionId === 'current_form' ? 'D. ' : 'E. ';
  return section(sec.sectionId, heading + sec.title, sec.perspectiveNames.join(' ＋ '), [
    meta,
    subgroups,
    rule,
    groups,
  ]);
}

// ---------------------------------------------------------------- F. data status

function renderDataStatus(ds) {
  const table = el('table', { className: 'status-table' });
  table.appendChild(
    el('thead', {}, [
      el('tr', {}, [
        el('th', { text: '切分' }),
        el('th', { text: 'Evidence（數字本身）' }),
        el('th', { text: 'Application（能否用於下一場）' }),
      ]),
    ])
  );
  const tbody = el('tbody');
  for (const row of ds.rows) {
    tbody.appendChild(
      el('tr', {}, [
        el('th', { className: 'mono', text: row.scope }),
        el('td', {}, [statusBadge(row.evidence)]),
        el('td', {}, [statusBadge(row.application)]),
      ])
    );
  }
  table.appendChild(tbody);

  const separation = el('div', { className: 'separation' }, [
    el('div', { className: 'separation-counts' }, [
      el('span', {
        text: `Evidence 值域：${ds.distinctEvidenceValues.length} 種`,
      }),
      el('span', { className: 'dot', text: '·' }),
      el('span', {
        text: `Application 值域：${ds.distinctApplicationValues.length} 種`,
      }),
    ]),
    note(ds.separationBasis),
  ]);

  const registry = el('div', { className: 'registry' }, [
    el('h3', { text: `缺口登錄簿（${ds.registry.length} 筆，其中 ${ds.gapCount} 筆為缺口）` }),
    el(
      'ul',
      { className: 'req-list' },
      ds.registry.map((e) =>
        el('li', { className: e.isGap ? 'req-gap' : 'req-ok' }, [
          el('div', { className: 'req-head' }, [
            el('span', { className: 'mono', text: e.item }),
            statusBadge({ value: e.status, label: e.statusLabel }),
            el('span', { className: 'muted', text: e.affectedScopes.join('、') }),
          ]),
          note(e.factualBasis),
          el('p', {
            className: 'micro',
            text: e.evidenceSteps.length
              ? `依據 ${e.evidenceSteps.join(' / ')}`
              : '尚未調查，因此沒有依據 Step',
          }),
        ])
      )
    ),
  ]);

  const metricGaps = el('div', { className: 'registry' }, [
    el('h3', { text: `無法計算的指標（${ds.metricGapCount} 筆）` }),
    el(
      'ul',
      { className: 'req-list' },
      ds.metricGaps.map((g) =>
        el('li', { className: 'req-gap' }, [
          el('div', { className: 'req-head' }, [
            el('span', { className: 'mono', text: `${g.scope} / ${g.metricLabel}` }),
            el('span', { className: 'missing-label', text: g.display }),
            statusBadge({ value: 'unavailable', label: g.interpretationStatus.label }),
          ]),
          note(g.reason, 'missing-reason'),
          note(g.valuePolicy),
        ])
      )
    ),
  ]);

  const nextGameStatus = el('div', { className: 'registry' }, [
    el('h3', { text: '下一場各欄位的資料狀態' }),
    el(
      'div',
      { className: 'grid grid-counts' },
      ds.nextGameFieldStatus.map((f) =>
        kv(f.field, statusBadge({ value: f.value, label: f.label }))
      )
    ),
  ]);

  const policy = detailsBlock('缺資料的表示規則', [
    el('p', { className: 'note strong', text: ds.nullPolicy.rule }),
    el(
      'ul',
      { className: 'plain-list' },
      ds.nullPolicy.requirements.map((r) => el('li', { text: r }))
    ),
  ]);

  return section(
    'data-status',
    'F. 資料狀態',
    'Evidence 與 Application 是兩件不同的事，這裡刻意分成兩欄，不合併成單一燈號。',
    [table, separation, registry, metricGaps, nextGameStatus, policy]
  );
}

// ---------------------------------------------------------------- G. traceability

function renderTraceability(tr) {
  const files = el(
    'div',
    { className: 'grid grid-files' },
    tr.sourceFiles.map((f) =>
      el('div', { className: 'file-card' }, [
        el('div', { className: 'mono', text: f.path }),
        el('div', { className: 'mono muted', text: f.shortSha }),
        el('div', { className: 'muted', text: `${f.bytes} bytes` }),
      ])
    )
  );

  const steps = detailsBlock(
    `分析步驟登錄（${tr.stepRegistry.length} 個 step）`,
    [
      el('table', { className: 'step-table' }, [
        el('thead', {}, [
          el('tr', {}, [
            el('th', { text: 'Step' }),
            el('th', { text: '主題' }),
            el('th', { text: 'module' }),
            el('th', { text: 'doc' }),
          ]),
        ]),
        el(
          'tbody',
          {},
          tr.stepRegistry.map((s) =>
            el('tr', {}, [
              el('th', { text: s.step }),
              el('td', { text: s.topic }),
              el('td', { className: 'mono', text: s.module }),
              el('td', { className: 'mono', text: s.doc }),
            ])
          )
        ),
      ]),
    ]
  );

  const notTraceable = tr.notTraceable.length
    ? el('div', { className: 'registry' }, [
        el('h3', { text: '無法追溯的指標' }),
        el(
          'ul',
          { className: 'req-list' },
          tr.notTraceable.map((e) =>
            el('li', { className: 'req-gap' }, [
              el('div', { className: 'req-head' }, [
                el('span', { className: 'mono', text: `${e.scope} / ${e.metricLabel}` }),
              ]),
              note(e.reason, 'missing-reason'),
            ])
          )
        ),
      ])
    : null;

  return section(
    'traceability',
    'G. 資料來源與可追溯性',
    `${tr.traceableMetricCount} / ${tr.metricIndexCount} 個指標可追溯到 step / file / field / formula`,
    [files, steps, notTraceable, note(tr.provenanceRule.rule), note(tr.provenanceRule.forbidden)]
  );
}

// ---------------------------------------------------------------- H. meta

function renderMeta(meta) {
  const contract = el('table', { className: 'contract-table' });
  contract.appendChild(
    el('thead', {}, [
      el('tr', {}, [
        el('th', { text: '顯示槽位' }),
        el('th', { text: '資料完整度' }),
        el('th', { text: '來源路徑' }),
        el('th', { text: '說明' }),
      ]),
    ])
  );
  contract.appendChild(
    el(
      'tbody',
      {},
      meta.displayContract.map((d) =>
        el('tr', {}, [
          el('th', { className: 'mono', text: d.slot }),
          el('td', {}, [
            el('span', {
              className: `badge badge-avail-${d.availability}`,
              text: d.availabilityLabel,
            }),
          ]),
          el('td', { className: 'mono micro', text: d.sourcePath }),
          el('td', { className: 'micro', text: d.availabilityNote }),
        ])
      )
    )
  );

  const rules = el('div', { className: 'registry' }, [
    el('h3', { text: '前端必須遵守的規則（由 API 提供）' }),
    el(
      'ul',
      { className: 'plain-list' },
      meta.consumerContract.must_not_do.map((r) => el('li', { text: r }))
    ),
  ]);

  const counts = el(
    'div',
    { className: 'grid grid-counts' },
    Object.keys(meta.counts).map((k) =>
      kv(k, el('span', { className: 'mono', text: String(meta.counts[k]) }))
    )
  );

  return section('meta', 'H. 產品輸出中介資料', `Product Output ${meta.productOutputVersion}`, [
    counts,
    contract,
    rules,
  ]);
}

// ---------------------------------------------------------------- 狀態畫面

function renderLoading(root, url = null) {
  root.replaceChildren(
    el('div', { className: 'state state-loading' }, [
      el('div', { className: 'spinner' }),
      el('p', { text: '正在向後端 API 取得資料……' }),
      url ? el('p', { className: 'micro mono', text: url }) : null,
    ])
  );
}

function renderError(root, vm) {
  const children = [
    el('h2', { text: vm.title }),
    vm.httpStatus ? el('p', { className: 'mono', text: `HTTP ${vm.httpStatus}` }) : null,
    vm.code ? el('p', { className: 'mono', text: `code = ${vm.code}` }) : null,
    vm.message ? el('p', { text: vm.message }) : null,
  ];
  if (vm.requestedPlayerSlug) {
    children.push(el('p', { className: 'mono', text: `requested = ${vm.requestedPlayerSlug}` }));
  }
  if (vm.availablePlayerSlugs) {
    children.push(
      el('p', { className: 'mono', text: `available = ${vm.availablePlayerSlugs.join(', ')}` })
    );
  }
  if (vm.detailNote) children.push(note(vm.detailNote));
  if (vm.hint) children.push(el('p', { className: 'hint mono', text: vm.hint }));
  children.push(
    el('p', {
      className: 'micro',
      text: '以上訊息全部來自 API 回應，前端沒有推測錯誤原因。',
    })
  );
  root.replaceChildren(el('div', { className: 'state state-error' }, children));
}

function renderPage(root, vm) {
  const nav = el(
    'nav',
    { className: 'toc' },
    [
      ['next-game', 'B 下一場'],
      ['season-baseline', 'C 季基準'],
      ['current_form', 'D 近期狀態'],
      ['contextual_evidence', 'E 情境切分'],
      ['data-status', 'F 資料狀態'],
      ['traceability', 'G 可追溯性'],
      ['meta', 'H 中介資料'],
    ].map(([id, text]) => {
      const a = el('a', { text, attrs: { href: `#${id}` } });
      return a;
    })
  );

  root.replaceChildren(
    renderHeader(vm.header),
    nav,
    renderNextGame(vm.nextGame),
    renderSeasonBaseline(vm.seasonBaseline),
    ...vm.sections.map((s) => renderSection(s, vm.insights)),
    renderDataStatus(vm.dataStatus),
    renderTraceability(vm.traceability),
    renderMeta(vm.meta),
    el('footer', { className: 'page-foot' }, [
      el('p', {
        text:
          '本頁只呈現 API 回傳的內容。沒有排序、沒有篩選、沒有重算、'
          + '沒有 score / ranking / threshold，也沒有任何建議或預測。',
      }),
      el('p', {
        className: 'micro mono',
        text:
          `order=${vm.frontendGuards.orderSource}`
          + ` · numbers=${vm.frontendGuards.numberHandling}`
          + ` · source=${vm.frontendGuards.singleSourceOfNumbers}`,
      }),
    ])
  );
}

// ---------------------------------------------------------------- 載入流程

export async function loadAndRender(
  root,
  { fetchImpl = fetch, apiBase = null, playerId = null } = {}
) {
  const base = apiBase || resolveApiBase();
  if (!playerId) {
    renderError(
      root,
      buildErrorViewModel('unexpected', {
        message: '沒有指定球員。請先從 /api/players 取得球員清單。',
      })
    );
    return { ok: false, kind: 'unexpected' };
  }
  const url = playerEndpointUrl(base, playerId);
  renderLoading(root, url);

  let response;
  try {
    response = await fetchImpl(url, { headers: { Accept: 'application/json' } });
  } catch (networkError) {
    renderError(root, buildErrorViewModel('network', { message: '瀏覽器無法完成請求。' }));
    return { ok: false, kind: 'network' };
  }

  let body = null;
  try {
    body = await response.json();
  } catch (parseError) {
    renderError(
      root,
      buildErrorViewModel('unexpected', {
        httpStatus: response.status,
        message: '回應不是有效的 JSON。',
      })
    );
    return { ok: false, kind: 'unexpected' };
  }

  if (response.status === 200) {
    renderPage(root, buildViewModel(body));
    return { ok: true, kind: 'ok' };
  }

  const kindByStatus = {
    400: 'bad_request',
    404: 'not_found',
    405: 'bad_request',
    500: 'server_error',
  };
  const kind = kindByStatus[response.status] || 'unexpected';
  renderError(root, buildErrorViewModel(kind, body));
  return { ok: false, kind };
}

// ---------------------------------------------------------------- player 選單

/**
 * 建立球員選單（UI 層，只在 app.js）。
 *
 * 順序照 `/api/players` 給的順序，沒有 sort。單一球員時仍然顯示，
 * 讓使用者看得到目前 registry 實際支援誰。
 */
function renderPlayerBar(bar, items, activePlayerId, onSelect) {
  const select = el('select', {
    className: 'player-select',
    attrs: { id: 'player-select', 'aria-label': '選擇球員' },
  });
  for (const item of items) {
    const option = el('option', {
      text: item.label,
      attrs: { value: item.playerId },
    });
    if (item.playerId === activePlayerId) option.selected = true;
    select.appendChild(option);
  }
  select.addEventListener('change', () => onSelect(select.value));

  bar.replaceChildren(
    el('label', {
      className: 'player-bar-label',
      text: '球員',
      attrs: { for: 'player-select' },
    }),
    select,
    el('span', {
      className: 'player-bar-note micro',
      text:
        items.length === 1
          ? '目前 registry 只有一位球員（架構已支援多球員）'
          : `registry 共 ${items.length} 位球員（順序為 registry 順序，非排名）`,
    })
  );
  return select;
}

function renderPlayerBarError(bar, vm) {
  bar.replaceChildren(
    el('span', { className: 'player-bar-label', text: '球員' }),
    el('span', { className: 'missing-label', text: '無法取得球員清單' }),
    vm.message ? el('span', { className: 'micro', text: vm.message }) : null
  );
}

/** 取得球員清單。只做 fetch 與 JSON 解析，不做任何資料處理。 */
export async function loadPlayers(apiBase, fetchImpl = fetch) {
  const response = await fetchImpl(playersEndpointUrl(apiBase), {
    headers: { Accept: 'application/json' },
  });
  const body = await response.json();
  return { status: response.status, body };
}

/** 頁面啟動：先取球員清單，再載入選定球員的產品輸出。 */
export async function bootstrap(bar, root, { fetchImpl = fetch, apiBase = null } = {}) {
  const base = apiBase || resolveApiBase();
  let players;
  try {
    players = await loadPlayers(base, fetchImpl);
  } catch (networkError) {
    const vm = buildErrorViewModel('network', {
      message: '瀏覽器無法完成請求。',
    });
    if (bar) renderPlayerBarError(bar, vm);
    renderError(root, vm);
    return { ok: false, kind: 'network' };
  }

  if (players.status !== 200) {
    const vm = buildErrorViewModel('unexpected', {
      httpStatus: players.status,
      message: '無法取得球員清單。',
    });
    if (bar) renderPlayerBarError(bar, vm);
    renderError(root, vm);
    return { ok: false, kind: 'unexpected' };
  }

  const items = playerListItems(players.body);
  const activePlayerId = resolvePlayerId(players.body, resolveRequestedPlayerId());
  if (!activePlayerId) {
    const vm = buildErrorViewModel('unexpected', {
      message: 'registry 中目前沒有任何球員。',
    });
    if (bar) renderPlayerBarError(bar, vm);
    renderError(root, vm);
    return { ok: false, kind: 'unexpected' };
  }

  const select = bar
    ? renderPlayerBar(bar, items, activePlayerId, (playerId) => {
        loadAndRender(root, { fetchImpl, apiBase: base, playerId });
      })
    : null;

  const result = await loadAndRender(root, {
    fetchImpl,
    apiBase: base,
    playerId: activePlayerId,
  });
  return { ...result, activePlayerId, playerCount: items.length, select };
}

if (typeof window !== 'undefined' && typeof document !== 'undefined') {
  window.addEventListener('DOMContentLoaded', () => {
    const root = document.getElementById('app');
    const bar = document.getElementById('player-bar');
    if (root) bootstrap(bar, root);
  });
}
