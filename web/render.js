/**
 * Step 24 Frontend — 純函式呈現層。
 *
 * 這個模組把 Step 23 API 的回應轉成一個「view model」：只含字串、布林與陣列的
 * 巢狀物件。沒有 DOM、沒有 fetch、沒有時鐘、沒有隨機。
 *
 * 它**不**做什麼：
 *   - 不重算任何數值。current / baseline / difference / direction / sample size /
 *     sensitivity / percentile 全部直接讀 payload
 *   - 不 sort()。所有順序都照 payload 給的順序
 *   - 不 filter()。9 個 group 全部呈現，不因樣本小或差距小而隱藏
 *   - 不建立 score / weight / threshold / ranking / priority / Top-N
 *   - 不產生 recommendation / prediction / 優勢劣勢強弱之類的結論
 *   - 不把 null 當成 0
 *   - 不把 application_data_status != available 當成 evidence 不可靠
 *
 * 唯一的數字處理是 **顯示格式化**（`toFixed`）。原始完整精度一律同時保留在
 * view model 的 `raw` 欄位裡，畫面上也會並排顯示，沒有任何資訊被藏起來。
 */

/** 缺資料時畫面上顯示的文字。刻意不是 0、不是空白、不是 undefined。 */
export const NO_DATA = '尚無資料';
export const NOT_COMPUTABLE = '無法計算';

/**
 * 受控詞彙 -> 中文標籤。
 * 這是**詞彙翻譯表**，不是新的事實判斷：每個標籤都只是把 API 已經給的狀態
 * 換成中文說法，沒有加入任何 API 沒說的內容。
 */
export const DATA_STATUS_LABEL = {
  available: '可取得（已驗證）',
  partially_available: '尚未確認（部分驗證）',
  unavailable: '目前無法取得',
  not_investigated: '尚未調查',
};

export const DIRECTION_LABEL = {
  ABOVE: '高於季累計',
  BELOW: '低於季累計',
  EQUAL: '與季累計相同',
};

export const INTERPRETATION_STATUS_LABEL = {
  factual_with_context: '事實 ＋ 滾動分布脈絡',
  factual_only: '僅事實（無時間維度）',
  blocked_by_missing_data: '資料不足，無法陳述',
};

export const METRIC_LABEL = {
  batting_average: 'AVG',
  on_base_percentage: 'OBP',
  slugging_percentage: 'SLG',
};

export const TEMPORAL_LABEL = {
  recent_games: '近期場次窗口',
  season_cumulative: '季累計',
};

export const CONTEXTUAL_LABEL = {
  none: '無情境切分',
  pitcher_hand: '投手左右手',
  pitcher_role: '投手登板角色',
  pitcher_background: '投手本土／外籍',
};

export const AVAILABILITY_LABEL = {
  available: '完整',
  partial: '部分',
  unavailable: '無',
};

export const SECTION_TITLE = {
  current_form: '近期狀態（Current Form）',
  contextual_evidence: '情境切分（Contextual Evidence）',
};

/** 詞彙翻譯：查不到就原樣回傳代碼，絕不編造。 */
function label(table, code) {
  if (code === null || code === undefined) return NO_DATA;
  return Object.prototype.hasOwnProperty.call(table, code) ? table[code] : code;
}

/** 比率的棒球慣用三位小數（.405）。純格式化，不改變數值。 */
function ratioText(value) {
  if (value === null || value === undefined) return null;
  const fixed = Math.abs(value).toFixed(3);
  const body = fixed.startsWith('0.') ? fixed.slice(1) : fixed;
  return value < 0 ? `-${body}` : body;
}

/** 有號差的三位小數顯示。數值直接來自 payload，沒有重算。 */
function signedText(value) {
  if (value === null || value === undefined) return null;
  const body = Math.abs(value).toFixed(3);
  const trimmed = body.startsWith('0.') ? body.slice(1) : body;
  if (value > 0) return `+${trimmed}`;
  if (value < 0) return `-${trimmed}`;
  return `±${trimmed}`;
}

/** 完整精度，用來與格式化後的值並排顯示。 */
function fullText(value) {
  if (value === null || value === undefined) return null;
  return value.toFixed(8);
}

/**
 * 數值欄位 -> view cell。
 * `raw` 永遠是 payload 原值；`isNull` 明確標記缺值；缺值一定帶 reason。
 */
function numberCell(value, { reason = null, kind = 'ratio' } = {}) {
  if (value === null || value === undefined) {
    return {
      isNull: true,
      text: reason ? NOT_COMPUTABLE : NO_DATA,
      full: null,
      raw: null,
      reason: reason,
    };
  }
  const text = kind === 'signed' ? signedText(value) : ratioText(value);
  return { isNull: false, text, full: fullText(value), raw: value, reason: null };
}

/** 文字欄位 -> view cell。空字串一律視為缺值，不顯示空白。 */
function textCell(value, { reason = null } = {}) {
  const missing = value === null || value === undefined || value === '';
  return {
    isNull: missing,
    text: missing ? NO_DATA : String(value),
    raw: missing ? null : value,
    reason: missing ? reason : null,
  };
}

function intCell(value, { reason = null } = {}) {
  if (value === null || value === undefined) {
    return { isNull: true, text: NO_DATA, raw: null, reason };
  }
  return { isNull: false, text: String(value), raw: value, reason: null };
}

// ---------------------------------------------------------------- A. header

function buildHeader(payload) {
  const p = payload.player;
  const api = payload.api;
  const asOf = api.data_as_of;
  return {
    playerName: textCell(p.player_name),
    playerAcnt: textCell(p.player_acnt),
    team: textCell(p.team),
    season: intCell(p.season),
    kindName: textCell(p.kind_name),
    gamesPlayed: intCell(p.games_played),
    plateAppearances: intCell(p.plate_appearances),
    atBats: intCell(p.at_bats),
    // 資料截至日期一律取自 API 的 data_as_of，絕不使用瀏覽器時間
    dataAsOf: {
      referenceDate: textCell(asOf.reference_date),
      basis: asOf.reference_date_basis,
      clockIndependent: asOf.clock_independent,
      isNotRequestTime: asOf.is_not_request_time,
      sourceFileDigests: asOf.source_file_digests.map((f) => ({
        path: f.path,
        sha256: f.sha256,
        bytes: f.bytes,
      })),
    },
    versions: {
      apiVersion: api.api_version,
      productOutputVersion: api.product_output_version,
      readOnly: api.read_only,
    },
  };
}

// ---------------------------------------------------------------- B. next game

function buildNextGame(payload) {
  const ng = payload.next_game;
  const g = ng.game;
  const r = ng.result_not_available;
  const sp = ng.opponent_starting_pitcher;
  const hand = ng.opponent_starting_pitcher_hand;

  return {
    fields: [
      { key: 'game_date', label: '比賽日期', cell: textCell(g.game_date) },
      { key: 'scheduled_time', label: '開賽時間', cell: textCell(g.scheduled_time) },
      { key: 'opponent', label: '對手', cell: textCell(g.opponent) },
      {
        key: 'home_away',
        label: '主客場',
        cell: textCell(g.home_away === 'home' ? '主場' : g.home_away === 'away' ? '客場' : g.home_away),
      },
      { key: 'venue', label: '球場', cell: textCell(g.venue) },
      { key: 'game_status', label: '比賽狀態', cell: textCell(g.game_status) },
      { key: 'game_sno', label: '場次編號', cell: intCell(g.game_sno) },
    ],
    gameDataStatus: {
      value: g.data_status,
      label: label(DATA_STATUS_LABEL, g.data_status),
    },
    /**
     * 官方對未開打場次的比分預設值是 0。這裡一律顯示「尚無資料」，
     * 絕不顯示 0 或 0:0。檔內原值只放在 traceability 供追溯。
     */
    result: {
      label: '比分',
      home: numberCell(r.home_score),
      visiting: numberCell(r.visiting_score),
      display: NO_DATA,
      reason: r.null_reason,
      dataStatus: {
        value: r.data_status,
        label: label(DATA_STATUS_LABEL, r.data_status),
      },
      rawValuesForTraceabilityOnly: r.raw_values_for_traceability_only,
    },
    startingPitcher: {
      label: '對手先發投手',
      acnt: textCell(sp.pitcher_acnt),
      name: textCell(sp.pitcher_name, { reason: sp.pitcher_name_null_reason }),
      team: textCell(sp.team),
      teamSide: textCell(sp.team_side),
      verificationStatus: sp.verification_status,
      unconfirmedReason: sp.unconfirmed_reason,
      dataStatus: {
        value: sp.data_status,
        label: label(DATA_STATUS_LABEL, sp.data_status),
      },
    },
    startingPitcherHand: {
      label: '先發投手左右手',
      hand: textCell(hand.hand, { reason: hand.null_reason }),
      vocabulary: hand.hand_vocabulary,
      requiredToResolve: hand.required_to_resolve,
      verificationStatus: hand.verification_status,
      dataStatus: {
        value: hand.data_status,
        label: label(DATA_STATUS_LABEL, hand.data_status),
      },
    },
    selectionRule: {
      referenceDate: ng.selection_rule.reference_date,
      basis: ng.selection_rule.reference_date_basis,
      rule: ng.selection_rule.rule,
      clockIndependent: ng.selection_rule.clock_independent,
      note: ng.selection_rule.clock_independent_note,
    },
    isNot: ng.is_not,
  };
}

// ---------------------------------------------------------------- C. season baseline

const BASELINE_METRIC_ORDER = [
  'batting_average',
  'on_base_percentage',
  'slugging_percentage',
];

function buildSeasonBaseline(payload) {
  const sb = payload.season_baseline;
  return {
    definition: sb.definition,
    counts: [
      { label: '出賽場數', cell: intCell(sb.games) },
      { label: '打席 PA', cell: intCell(sb.plate_appearances) },
      { label: '打數 AB', cell: intCell(sb.at_bats) },
      { label: '安打', cell: intCell(sb.hits) },
      { label: '總壘打數', cell: intCell(sb.total_bases) },
      { label: '四壞', cell: intCell(sb.walks) },
      { label: '觸身', cell: intCell(sb.hit_by_pitch) },
      { label: '高飛犧牲打', cell: intCell(sb.sacrifice_flies) },
    ],
    metrics: BASELINE_METRIC_ORDER.map((metric) => {
      const m = sb.metrics[metric];
      return {
        metric,
        label: METRIC_LABEL[metric],
        value: numberCell(m.value),
        derivation: m.derivation,
        sourceStep: m.source_step,
        sourceFile: m.source_file,
        note: m.note || null,
        // 樣本規模與數值並排顯示（AVG / SLG 用 AB，OBP 用打席類分母）
        sampleSize: {
          atBats: intCell(sb.at_bats),
          plateAppearances: intCell(sb.plate_appearances),
        },
      };
    }),
    hoistingNote: sb.hoisting_note,
  };
}

// ---------------------------------------------------------------- metric 列

/**
 * 一個 group 的 metric 列。
 *
 * 三個 metric 的順序與缺值狀態都來自 `phenomenon.statements`（API 已含
 * explicit_null 的槽位）。數值細節從 `primary_metrics` 以 metric 名稱查表取得
 * ——查表不是排序。
 */
function buildMetricRows(insight) {
  const evidenceByMetric = {};
  for (const e of insight.supporting_evidence.primary_metrics) {
    evidenceByMetric[e.metric] = e;
  }
  const unavailableReason =
    insight.limitations.unavailable_metrics.reason || null;

  const rows = [];
  for (const statement of insight.phenomenon.statements) {
    const metric = statement.metric;
    const evidence = evidenceByMetric[metric];

    if (!evidence) {
      // 值不存在：顯示「無法計算」＋ API 給的原因。不轉成 0、不省略這一列。
      rows.push({
        metric,
        label: METRIC_LABEL[metric] || metric,
        available: false,
        statementKind: statement.statement_kind,
        interpretationStatus: {
          value: statement.interpretation_status,
          label: label(INTERPRETATION_STATUS_LABEL, statement.interpretation_status),
        },
        current: numberCell(null, { reason: unavailableReason }),
        baseline: numberCell(null, { reason: unavailableReason }),
        difference: numberCell(null, { reason: unavailableReason }),
        direction: { value: null, label: NO_DATA },
        sampleSize: null,
        sensitivity: null,
        rolling: null,
        rollingReason: null,
        nullReason: unavailableReason,
        statement: statement.statement,
      });
      continue;
    }

    const ss = evidence.sample_size;
    const sv = evidence.sensitivity;
    const rp = evidence.rolling_percentile;

    rows.push({
      metric,
      label: evidence.metric_label,
      available: true,
      statementKind: statement.statement_kind,
      interpretationStatus: {
        value: evidence.interpretation_status,
        label: label(INTERPRETATION_STATUS_LABEL, evidence.interpretation_status),
      },
      // 以下全部直接讀 payload，沒有任何算術
      current: numberCell(evidence.current_value),
      baseline: numberCell(evidence.baseline_value),
      difference: numberCell(evidence.difference, { kind: 'signed' }),
      direction: {
        value: evidence.direction,
        label: label(DIRECTION_LABEL, evidence.direction),
      },
      sampleSize: {
        atBats: intCell(ss.at_bats),
        plateAppearances: intCell(ss.plate_appearances),
        games: intCell(ss.games, { reason: ss.games_missing_reason }),
        sourceStep: ss.source_step,
      },
      sensitivity: {
        fraction: `${sv.numerator} / ${sv.denominator}`,
        numeratorLabel: sv.numerator_label,
        denominatorLabel: sv.denominator_label,
        oneMore: numberCell(sv.one_more_success),
        oneFewer: numberCell(sv.one_fewer_success),
        delta: numberCell(sv.delta_if_one_more, { kind: 'signed' }),
        successUnit: sv.success_unit,
        sourceStep: sv.source_step,
        isNot: sv.is_not,
      },
      rolling: rp
        ? {
            rankDesc: rp.rank_desc,
            distributionN: rp.distribution_n,
            percentileRank: rp.percentile_rank,
            percentileRankText: `${rp.percentile_rank.toFixed(1)}%`,
            percentileStrictText: `${rp.percentile_strict.toFixed(1)}%`,
            definition: rp.definition,
            sourceStep: rp.source_step,
          }
        : null,
      rollingReason: rp ? null : evidence.rolling_percentile_missing_reason,
      nullReason: null,
      statement: statement.statement,
    });
  }
  return rows;
}

function buildCrossMetric(insight) {
  const cm = insight.phenomenon.cross_metric_statement;
  if (!cm) {
    return {
      available: false,
      reason:
        '此切分在 Step 9 沒有三個指標方向一致的 PATTERN，因此沒有跨指標方向摘要。',
    };
  }
  // PATTERN 不另建數值列：只呈現 API 已給的方向摘要
  return {
    available: true,
    statement: cm.statement,
    direction: { value: cm.direction, label: label(DIRECTION_LABEL, cm.direction) },
    perMetric: Object.keys(cm.direction_per_metric).map((key) => ({
      metricLabel: key,
      direction: cm.direction_per_metric[key],
      directionLabel: label(DIRECTION_LABEL, cm.direction_per_metric[key]),
    })),
    consistency: `${cm.consistency_count} / ${cm.total_metrics}`,
    addsNoNewNumber: cm.adds_no_new_number,
    addsNoNewNumberBasis: cm.adds_no_new_number_basis,
    knownLimitation: cm.known_limitation,
    sourceCandidateId: cm.source_candidate_id,
  };
}

function buildLimitations(insight) {
  const lim = insight.limitations;
  const sl = lim.sample_limitation;
  const md = lim.missing_data;
  const um = lim.unavailable_metrics;

  return {
    sample: {
      atBats: intCell(sl.at_bats),
      plateAppearances: intCell(sl.plate_appearances),
      games: intCell(sl.games, { reason: sl.games_missing_reason }),
      singleEventDelta: Object.keys(sl.single_event_delta).map((metric) => ({
        metric,
        label: METRIC_LABEL[metric] || metric,
        cell: numberCell(sl.single_event_delta[metric], { kind: 'signed' }),
      })),
      sourceStep: sl.source_step,
      isNotAFilter: sl.is_not_a_filter,
    },
    required: md.required_additional_data.map((item) => ({
      item: item.item,
      status: item.status,
      statusLabel: label(DATA_STATUS_LABEL, item.status),
      isGap: item.status !== 'available',
      evidenceSteps: item.evidence_steps,
      factualBasis: item.factual_basis,
      sourceStep: item.availability_source_step,
    })),
    missingForApplication: md.missing_for_application.map((item) => ({
      item: item.item,
      status: item.status,
      statusLabel: label(DATA_STATUS_LABEL, item.status),
      factualBasis: item.factual_basis,
    })),
    missingCount: md.missing_count,
    noGuessingNote: md.no_guessing_note,
    unavailableMetrics: {
      metrics: um.metrics.map((m) => METRIC_LABEL[m] || m),
      count: um.count,
      reason: um.reason,
      valuePolicy: um.value_policy,
    },
    temporalLimitation: lim.temporal_limitation,
    notANextGameProjection: lim.not_a_next_game_projection,
  };
}

function buildTraceability(insight) {
  const byMetric = insight.traceability.by_metric;
  const entries = [];
  // 依 metric 名稱鍵的既有順序走訪，不排序
  for (const metric of Object.keys(byMetric)) {
    const e = byMetric[metric];
    entries.push({
      metric,
      label: e.metric_label,
      sourceStep: e.source_step,
      sourceStepIds: e.source_step_ids,
      sourceFile: e.source_file,
      sourceField: e.source_field,
      derivation: e.derivation,
      derivationDetail: e.derivation_detail,
      gameSnos: e.game_snos,
      gameSnosCount: e.game_snos_count,
      gameSnosMissingReason: e.game_snos_missing_reason,
      dateRange: e.date_range,
      sourceCandidateId: e.source_candidate_id,
      docs: e.docs,
    });
  }
  return {
    entries,
    stepChain: insight.traceability.step_chain,
    everyNumberTraceable: insight.traceability.every_number_traceable,
    everyNumberTraceableBasis: insight.traceability.every_number_traceable_basis,
  };
}

/** 一個 insight group 的完整 view。 */
function buildGroupView(insight) {
  const da = insight.limitations.data_availability;
  const ctx = insight.context;
  return {
    insightId: insight.identity.insight_id,
    groupId: insight.identity.group_id,
    scope: insight.identity.scope,
    perspective: insight.identity.perspective,
    perspectiveName: insight.identity.perspective_name,
    candidateIds: insight.identity.candidate_ids,
    candidateCount: insight.identity.candidate_count,
    officialItemName: ctx.context_official_item_name,
    temporal: {
      value: ctx.temporal_relevance,
      label: label(TEMPORAL_LABEL, ctx.temporal_relevance),
    },
    contextual: {
      value: ctx.contextual_relevance,
      label: label(CONTEXTUAL_LABEL, ctx.contextual_relevance),
    },
    interpretationStatus: {
      value: insight.interpretation_status.status,
      label: label(INTERPRETATION_STATUS_LABEL, insight.interpretation_status.status),
      meaning: insight.interpretation_status.meaning,
    },
    /**
     * evidence 與 application 兩個狀態刻意分成兩個欄位，view model 不合併。
     * application != available **不代表** evidence 不可靠。
     */
    dataStatus: {
      evidence: {
        value: da.evidence_data_status,
        label: label(DATA_STATUS_LABEL, da.evidence_data_status),
      },
      application: {
        value: da.application_data_status,
        label: label(DATA_STATUS_LABEL, da.application_data_status),
      },
      merged: false,
      separationNote:
        'evidence 狀態說的是「這個數字本身是否存在且已交叉核對」；'
        + 'application 狀態說的是「能不能直接拿來支援下一場決策」。兩者不同。',
    },
    decision: {
      evidenceDependsOnNextGame: ctx.next_game_dependency.evidence_depends_on_next_game,
      evidenceDependsBasis: ctx.next_game_dependency.basis,
      requiresAdditionalData: ctx.application_dependency.requires_additional_data,
      additionalData: ctx.application_dependency.additional_data,
      possibleDecisionArea: ctx.possible_decision_area,
      possibleActionLink: ctx.possible_action_link,
      isNot: ctx.is_not,
    },
    metrics: buildMetricRows(insight),
    crossMetric: buildCrossMetric(insight),
    limitations: buildLimitations(insight),
    traceability: buildTraceability(insight),
  };
}

// ---------------------------------------------------------------- D / E. sections

const SECTION_ORDER = ['current_form', 'contextual_evidence'];

/**
 * section 只放**參照**，不複製 group 內容。
 *
 * 這與 API 的設計一致（Step 22：section 只放 insight_id 與 pointer，
 * 數值只存在 factual_insights 一處）。view model 沿用同一個原則，
 * 因此同一組數字不會在 view model 裡出現兩次。
 */
function buildSection(payload, sectionId, indexByInsightId) {
  const section = payload[sectionId];
  return {
    sectionId,
    title: SECTION_TITLE[sectionId] || sectionId,
    perspectives: section.perspectives,
    perspectiveNames: section.perspective_names,
    subgroupsByPerspective: section.subgroups_by_perspective,
    subgroupsByContextualRelevance: section.subgroups_by_contextual_relevance,
    groupCount: section.group_count,
    candidateCount: section.candidate_count,
    scopes: section.scopes,
    temporal: {
      value: section.temporal_relevance,
      label: label(TEMPORAL_LABEL, section.temporal_relevance),
    },
    evidenceStatusValues: section.evidence_data_status_values,
    applicationStatusByScope: section.application_data_status_by_scope,
    applicationStatusValues: section.application_data_status_values,
    statusSeparationNote: section.status_separation_note,
    displaySlots: section.display_slots,
    memberSelectionRule: section.member_selection_rule,
    // 順序完全照 API 給的 insight_refs，沒有 sort()
    groupRefs: section.insight_refs.map((ref) => ({
      insightId: ref.insight_id,
      groupId: ref.group_id,
      scope: ref.scope,
      candidateIds: ref.candidate_ids,
      officialItemName: ref.official_item_name,
      presentationPurpose: ref.presentation_purpose,
      // 指向 viewModel.insights 的索引；section 不複製任何數值
      insightIndex: indexByInsightId[ref.insight_id],
    })),
    holdsReferencesOnly: true,
  };
}

// ---------------------------------------------------------------- F. data status

function buildDataStatus(payload) {
  const ds = payload.data_status;
  const scopes = Object.keys(ds.evidence_data_status_by_scope);
  return {
    rows: scopes.map((scope) => ({
      scope,
      evidence: {
        value: ds.evidence_data_status_by_scope[scope],
        label: label(DATA_STATUS_LABEL, ds.evidence_data_status_by_scope[scope]),
      },
      application: {
        value: ds.application_data_status_by_scope[scope],
        label: label(DATA_STATUS_LABEL, ds.application_data_status_by_scope[scope]),
      },
    })),
    distinctEvidenceValues: ds.separation.distinct_evidence_values,
    distinctApplicationValues: ds.separation.distinct_application_values,
    crossTabulation: ds.separation.cross_tabulation,
    fieldsAreIndependent: ds.separation.fields_are_independent,
    separationBasis: ds.separation.basis_is_not_a_single_boolean,
    registry: ds.missing_information_registry.map((e) => ({
      item: e.item,
      status: e.status,
      statusLabel: label(DATA_STATUS_LABEL, e.status),
      isGap: e.is_gap,
      affectedScopes: e.affected_scopes,
      affectedScopeCount: e.affected_scope_count,
      evidenceSteps: e.evidence_steps,
      factualBasis: e.factual_basis,
      sourceStep: e.availability_source_step,
    })),
    gapCount: ds.missing_information_gap_count,
    metricGaps: ds.metric_level_gaps.map((g) => ({
      scope: g.scope,
      metric: g.metric,
      metricLabel: METRIC_LABEL[g.metric] || g.metric,
      display: NOT_COMPUTABLE,
      reason: g.null_reason,
      interpretationStatus: {
        value: g.interpretation_status,
        label: label(INTERPRETATION_STATUS_LABEL, g.interpretation_status),
      },
      valuePolicy: g.value_policy,
    })),
    metricGapCount: ds.metric_level_gap_count,
    nextGameFieldStatus: Object.keys(ds.next_game_field_status).map((key) => ({
      field: key,
      value: ds.next_game_field_status[key],
      label: label(DATA_STATUS_LABEL, ds.next_game_field_status[key]),
    })),
    nullPolicy: ds.null_representation_policy,
  };
}

// ---------------------------------------------------------------- G. traceability

function buildGlobalTraceability(payload) {
  const tr = payload.traceability;
  return {
    sourceFiles: tr.source_files.map((f) => ({
      path: f.path,
      sha256: f.sha256,
      shortSha: f.sha256.slice(0, 12),
      bytes: f.bytes,
      exists: f.exists,
    })),
    stepRegistry: tr.step_registry.map((s) => ({
      step: s.step,
      topic: s.topic,
      module: s.module,
      doc: s.doc,
    })),
    metricIndexCount: tr.metric_index_count,
    traceableMetricCount: tr.traceable_metric_count,
    notTraceable: tr.metric_index
      .filter((e) => !e.traceable)
      .map((e) => ({
        scope: e.scope,
        metric: e.metric,
        metricLabel: METRIC_LABEL[e.metric] || e.metric,
        reason: e.not_traceable_reason,
      })),
    pointerNote: tr.pointer_note,
    provenanceRule: tr.provenance_rule,
  };
}

// ---------------------------------------------------------------- H. metadata

function buildMeta(payload) {
  const md = payload.metadata;
  return {
    productOutputVersion: md.product_output_version,
    counts: md.counts,
    determinism: md.determinism,
    displayContract: md.display_contract.map((d) => ({
      slot: d.slot,
      sourcePath: d.source_path,
      additionalSourcePaths: d.additional_source_paths || [],
      sourceStep: d.source_step,
      availability: d.availability,
      availabilityLabel: label(AVAILABILITY_LABEL, d.availability),
      availabilityNote: d.availability_note,
    })),
    consumerContract: md.consumer_contract,
    generatedFromSteps: md.generated_from_steps,
    containsNo: md.contains_no,
  };
}

// ---------------------------------------------------------------- 入口

/**
 * payload -> view model。
 *
 * `insights` 的順序直接照 `factual_insights` 的鍵順序（API 以 sort_keys 序列化，
 * JSON.parse 會保留該順序）。這裡沒有呼叫 sort()。
 */
export function buildViewModel(payload) {
  // insights 是唯一的數值來源，順序照 factual_insights 的鍵順序
  const insightIds = Object.keys(payload.factual_insights);
  const insights = insightIds.map((id) =>
    buildGroupView(payload.factual_insights[id])
  );
  const indexByInsightId = {};
  insightIds.forEach((id, index) => {
    indexByInsightId[id] = index;
  });
  const sections = SECTION_ORDER.map((id) =>
    buildSection(payload, id, indexByInsightId)
  );

  return {
    header: buildHeader(payload),
    nextGame: buildNextGame(payload),
    seasonBaseline: buildSeasonBaseline(payload),
    sections,
    insights,
    insightIndexById: indexByInsightId,
    dataStatus: buildDataStatus(payload),
    traceability: buildGlobalTraceability(payload),
    meta: buildMeta(payload),
    /** 前端自我宣告：這些事情這一層都沒有做。 */
    frontendGuards: {
      sorted: false,
      filtered: false,
      recomputed: false,
      createsScore: false,
      createsRanking: false,
      createsThreshold: false,
      createsPriority: false,
      createsTopN: false,
      createsRecommendation: false,
      createsPrediction: false,
      mergesDataStatus: false,
      treatsNullAsZero: false,
      usesBrowserClockForDataDate: false,
      usesLlm: false,
      readsLocalDataDirectory: false,
      duplicatesNumbers: false,
      orderSource: 'api_payload_order',
      numberHandling: 'display_formatting_only',
      singleSourceOfNumbers: 'insights',
    },
  };
}

/** 錯誤狀態 -> view model。訊息只用 API 給的欄位，不猜測原因。 */
export function buildErrorViewModel(kind, detail) {
  const KINDS = {
    network: {
      title: '無法連線到後端 API',
      hint: '請確認後端已啟動：python src/api.py --cors-origin http://127.0.0.1:5173',
    },
    not_found: { title: '找不到這位球員的資料', hint: null },
    bad_request: { title: '請求路徑不正確', hint: null },
    server_error: { title: '後端產生資料時發生錯誤', hint: null },
    unexpected: { title: '收到非預期的回應', hint: null },
  };
  const base = KINDS[kind] || KINDS.unexpected;
  const err = detail && detail.error ? detail.error : null;
  return {
    kind,
    title: base.title,
    hint: base.hint,
    // 以下全部照抄 API 的錯誤物件，不做任何推測
    code: err ? err.code : null,
    httpStatus: err ? err.http_status : (detail && detail.httpStatus) || null,
    message: err ? err.message : (detail && detail.message) || null,
    availablePlayerSlugs: err ? err.available_player_slugs || null : null,
    requestedPlayerSlug: err ? err.requested_player_slug || null : null,
    detailDisclosed: err ? err.detail_disclosed : null,
    detailNote: err ? err.detail_note || null : null,
  };
}
