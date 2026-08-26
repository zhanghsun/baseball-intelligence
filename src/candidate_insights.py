"""Candidate Insight Engine 第一版（Step 9）。

它做什麼：把已經算好、已經驗證過的 evidence，組織成 machine-readable 的「候選」。

它**不**做什麼：
    - 不判斷好壞、強弱、擅長與否
    - 不設任何 threshold（沒有任何 `if diff > X` 之類的判斷）
    - 不算 final ranking score，不對任何指標加權
    - 不產生自然語言結論、不預測、不給建議
    - 不使用 LLM
    - 不發任何 HTTP 請求（程式啟動時會直接封鎖 socket 來保證這件事）
    - 不修改 raw / processed data（執行前後以 sha256 驗證）

Candidate 類型：
    TREND                 最近 10 / 15 場 vs 季累計（AVG、SLG）
    CONTEXT               7 個官方投手屬性情境（AVG、OBP、SLG）
    MULTI_METRIC_PATTERN  同一 context 中 AVG / OBP / SLG 三個方向一致時

資料輸入（全部為本地檔案，唯讀）：
    data/processed/zhang_yucheng_game_logs_2026.json          Step 4 產出
    data/raw/apart_score_0000006888_2026_A_01.json            Step 8 存下的官方分項快取

用法：
    python src/candidate_insights.py            列出全部 candidates
    python src/candidate_insights.py --write     另外寫出 JSON 檔
"""

from __future__ import annotations

import hashlib
import json
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 沿用既有 evidence 程式，避免重複實作造成數字分歧。
# 注意：這些模組本身有網路能力（Step 2/3/8 用得到），本階段只用它們的純計算函式。
from context_splits import build_context, trunc4  # noqa: E402
from player_form_analysis import build_window, sort_by_date  # noqa: E402
from rolling_baseline import build_rolling_windows, rank_and_percentile  # noqa: E402

# 球員身分與資料路徑的唯一來源。player_registry 在 module 層級不 import 本模組，
# 因此不會形成循環（它的交叉核對是延後 import）。
import player_registry as registry  # noqa: E402


# ------------------------------------------------------------------ 網路封鎖
# 封鎖對外連線，確保本階段不可能發出任何網路請求。
# 這不是裝飾性的宣告，是可驗證的執行期保證：任何嘗試連線都會直接拋錯。
# 在 import 完成之後才安裝，因為 ssl 模組在 import 期間會繼承 socket.socket。


class NetworkBlocked(RuntimeError):
    pass


def _blocked_connect(*args, **kwargs):  # noqa: ANN002, ANN003
    raise NetworkBlocked(
        "本階段禁止任何網路存取。candidate engine 只能讀本地已驗證的 evidence。"
    )


def install_network_guard() -> None:
    socket.socket.connect = _blocked_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = _blocked_connect  # type: ignore[method-assign]
    socket.create_connection = _blocked_connect  # type: ignore[assignment]


def network_guard_active() -> bool:
    return (
        socket.socket.connect is _blocked_connect
        and socket.socket.connect_ex is _blocked_connect
        and socket.create_connection is _blocked_connect
    )


install_network_guard()

# ------------------------------------------------------------------ 常數

ROOT = Path(__file__).resolve().parent.parent

# ---- 球員身分與資料路徑：**唯一來源是 src/player_registry.py** ----
# Step 29B 起本模組不再自己宣告球員帳號、姓名或檔名。
# 以下常數全部是 registry 的衍生值，名稱保留是為了不破壞既有 10 支模組的 import。
_ACTIVE_PLAYER_ID = registry.default_player_id()
_DATA_PATHS = registry.data_paths(_ACTIVE_PLAYER_ID)

PLAYER_LOG_PATH = _DATA_PATHS["player_log"]
APART_CACHE_PATH = _DATA_PATHS["apart_raw"]
OUTPUT_PATH = _DATA_PATHS["candidate_output"]

SUBJECT = registry.subject(_ACTIVE_PLAYER_ID)
SUBJECT_SLUG = registry.subject_slug(_ACTIVE_PLAYER_ID)

# 官方 ItemName -> candidate 用的 context 代碼
CONTEXT_CODES = {
    "VS. 右投": "VS_RIGHT",
    "VS. 左投": "VS_LEFT",
    "VS. 先發": "VS_STARTER",
    "VS. 中繼": "VS_RELIEF",
    "VS. 救援": "VS_CLOSER",
    "VS. 本土投手": "VS_DOMESTIC",
    "VS. 外籍投手": "VS_FOREIGN",
}
# 供對帳用的組別（三組都是同一批打席的完備切分，Step 8 已驗證）
CONTEXT_GROUP_OF = {
    "VS_RIGHT": "pitcher_hand", "VS_LEFT": "pitcher_hand",
    "VS_STARTER": "pitcher_role", "VS_RELIEF": "pitcher_role",
    "VS_CLOSER": "pitcher_role",
    "VS_DOMESTIC": "pitcher_origin", "VS_FOREIGN": "pitcher_origin",
}

WINDOW_SIZES = {"RECENT_10": 10, "RECENT_15": 15}


# ------------------------------------------------------------------ 工具

def sha256_of(path: Path) -> tuple[str, int]:
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data)


def ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def direction_of(value: float | None, baseline: float | None) -> str | None:
    """只描述數值方向，不含任何好壞判斷。"""
    if value is None or baseline is None:
        return None
    if value > baseline:
        return "ABOVE"
    if value < baseline:
        return "BELOW"
    return "EQUAL"


def fmt(value: float | None, digits: int = 8) -> str:
    return "None" if value is None else f"{value:.{digits}f}"


# ------------------------------------------------------------------ 載入 evidence

def load_inputs() -> tuple[list, list]:
    for path in (PLAYER_LOG_PATH, APART_CACHE_PATH):
        if not path.exists():
            raise SystemExit(
                f"找不到 {path}\n"
                "candidate engine 不會自己去抓資料。請先執行：\n"
                "  python src/build_processed_data.py\n"
                "  python src/context_splits.py --refetch"
            )
    logs = json.loads(PLAYER_LOG_PATH.read_text(encoding="utf-8"))
    apart_rows = json.loads(APART_CACHE_PATH.read_text(encoding="utf-8"))
    return logs, apart_rows


def build_season_baseline(logs: list, contexts: dict) -> dict:
    """季累計基準值。

    AVG 與 SLG 直接由 processed data 逐場加總（與 Step 5 同一來源）。
    OBP 需要犧牲飛球，而 processed data 沒有收；因此改用官方 context evidence
    的加總（Step 8 已驗證三組加總都與 processed data 對得上）。
    整個推導過程都記錄在 candidate 的 calculation_reference 中。
    """
    pa = sum(g["plate_appearances"] for g in logs)
    ab = sum(g["at_bats"] for g in logs)
    h = sum(g["hits"] for g in logs)
    tb = sum(g["total_bases"] for g in logs)

    # 用「投手手別」這一組加總取得 BB / HBP / SF（三組加總相同，Step 8 已驗證）
    hand = [contexts["VS_RIGHT"], contexts["VS_LEFT"]]
    bb = sum(c["walks"] for c in hand)
    hbp = sum(c["hit_by_pitch"] for c in hand)
    sf = sum(c["sacrifice_flies"] for c in hand)

    obp_num = h + bb + hbp
    obp_den = ab + bb + hbp + sf
    return {
        "plate_appearances": pa,
        "at_bats": ab,
        "hits": h,
        "total_bases": tb,
        "walks": bb,
        "hit_by_pitch": hbp,
        "sacrifice_flies": sf,
        "batting_average": ratio(h, ab),
        "slugging_percentage": ratio(tb, ab),
        "on_base_percentage": ratio(obp_num, obp_den),
        "obp_numerator": obp_num,
        "obp_denominator": obp_den,
    }


# ------------------------------------------------------------------ Candidate Type 1

def build_trend_candidates(logs: list, season: dict) -> tuple[list, dict]:
    """Recent 10 / Recent 15 vs 季累計。回傳 (candidates, 供驗證用的中間結果)。"""
    games = sort_by_date(logs)
    candidates = []
    internals: dict = {}

    for window_name, size in WINDOW_SIZES.items():
        window = build_window(f"Recent {size} Games", games[-size:])
        # 同尺寸的滾動窗口分布，用來給經驗百分位
        rolling = build_rolling_windows(games, size=size)
        avg_dist = [
            w["batting_average"] for w in rolling if w["batting_average"] is not None
        ]
        slg_dist = [
            w["slugging_percentage"] for w in rolling
            if w["slugging_percentage"] is not None
        ]
        internals[window_name] = {
            "window": window,
            "rolling_count": len(rolling),
            "avg_dist": avg_dist,
            "slg_dist": slg_dist,
        }

        for metric, value, baseline, dist, formula in (
            ("batting_average", window["batting_average"], season["batting_average"],
             avg_dist, "hits / at_bats"),
            ("slugging_percentage", window["slugging"], season["slugging_percentage"],
             slg_dist, "total_bases / at_bats"),
        ):
            pos = rank_and_percentile(dist, value) if value is not None else None
            diff = None if (value is None or baseline is None) else value - baseline
            metric_short = {"batting_average": "AVG", "slugging_percentage": "SLG"}[metric]
            candidates.append(
                {
                    "candidate_id": f"TREND-{SUBJECT_SLUG}-{window_name}-{metric_short}",
                    "type": "TREND",
                    "subject": dict(SUBJECT),
                    "metric": metric,
                    "window": {
                        "name": window_name,
                        "definition": f"依 game_date 升冪排序後的最後 {size} 場實際出賽",
                        "size_games": size,
                        "granularity": "player_games",
                    },
                    "current_value": value,
                    "baseline_value": baseline,
                    "baseline_definition": "2026 一軍例行賽季累計（77 場實際出賽）",
                    # 有號差（current - baseline）與其絕對值都提供，避免命名歧義
                    "absolute_difference": diff,
                    "absolute_difference_magnitude": None if diff is None else abs(diff),
                    "direction": direction_of(value, baseline),
                    "rolling_percentile": None if pos is None else {
                        "window_size": size,
                        "distribution_n": pos["n"],
                        "rank_desc": pos["rank_desc"],
                        "count_below": pos["below"],
                        "count_equal": pos["equal"],
                        "count_above": pos["above"],
                        "percentile_rank": pos["percentile_rank"],
                        "percentile_strict": pos["percentile_strict"],
                        "definition": (
                            "percentile_rank = (低於 + 相同) / n × 100；"
                            "percentile_strict = 低於 / n × 100"
                        ),
                    },
                    "games": window["games"],
                    "at_bats": window["at_bats"],
                    "plate_appearances": window["plate_appearances"],
                    "ranking_inputs": {
                        "_note": "原始素材，未加權、未合成任何 score",
                        "magnitude": None if diff is None else abs(diff),
                        "sample_size_at_bats": window["at_bats"],
                        "percentile_rank": None if pos is None else pos["percentile_rank"],
                        "consistency_count": None,
                    },
                    "source_evidence": ["player_form_analysis", "rolling_baseline"],
                    "source_files": [
                        "data/processed/zhang_yucheng_game_logs_2026.json"
                    ],
                    "calculation_reference": {
                        "formula": formula,
                        "sorting": "依 (game_date, game_sno) 升冪；不使用 game_sno 排序",
                        "percentile_source": (
                            f"同一份逐場資料切出的 {size} 場滾動窗口，"
                            f"共 {len(rolling)} 個（= 77 - {size} + 1）"
                        ),
                        "docs": [
                            "docs/FIRST_EVIDENCE_ANALYSIS.md",
                            "docs/ROLLING_BASELINE_ANALYSIS.md",
                        ],
                    },
                    "traceability": {
                        "date_range": {
                            "first_game_date": window["first_game_date"],
                            "last_game_date": window["last_game_date"],
                        },
                        "game_snos": list(window["game_snos"]),
                    },
                }
            )
    return candidates, internals


# ------------------------------------------------------------------ Candidate Type 2

def build_context_evidence(apart_rows: list) -> dict:
    """從官方分項快取建出 7 個 context 的事實（沿用 Step 8 的 build_context）。"""
    group3 = [r for r in apart_rows if str(r.get("ItemGroupCode")) == "3"]
    by_name = {r["ItemName"].strip(): r for r in group3}
    contexts = {}
    for item_name, code in CONTEXT_CODES.items():
        if item_name not in by_name:
            raise RuntimeError(f"官方分項快取中找不到 {item_name}")
        contexts[code] = build_context(by_name[item_name], code)
    return contexts


CONTEXT_METRICS = (
    ("batting_average", "AVG", "hits / at_bats"),
    ("on_base_percentage", "OBP",
     "(hits + walks + hit_by_pitch) / (at_bats + walks + hit_by_pitch + sacrifice_flies)"),
    ("slugging_percentage", "SLG", "total_bases / at_bats"),
)


def build_context_candidates(contexts: dict, season: dict) -> list:
    candidates = []
    for code, ctx in contexts.items():
        for metric, short, formula in CONTEXT_METRICS:
            value = ctx[metric]
            baseline = season[metric]
            diff = None if (value is None or baseline is None) else value - baseline
            candidates.append(
                {
                    "candidate_id": f"CONTEXT-{SUBJECT_SLUG}-{code}-{short}",
                    "type": "CONTEXT",
                    "subject": dict(SUBJECT),
                    "context": {
                        "code": code,
                        "official_item_name": ctx["item_name"],
                        "group": CONTEXT_GROUP_OF[code],
                        "definition_source": "CPBL 官方分項成績 ItemGroupCode = 3",
                        "definition_note": (
                            "分項的判定規則官方沒有文字說明（例如先發/中繼/救援如何界定、"
                            "本土/外籍如何界定），本專案不自行定義"
                        ),
                        "granularity": "season_cumulative",
                    },
                    "metric": metric,
                    "value": value,
                    "at_bats": ctx["at_bats"],
                    "plate_appearances": ctx["plate_appearances"],
                    # 對照組只記錄「與季累計的關係」，不比較不同 context 之間的高低
                    "comparison": {
                        "comparison_basis": "same_player_season_cumulative",
                        "baseline_value": baseline,
                        "difference": diff,
                        "difference_magnitude": None if diff is None else abs(diff),
                        "direction": direction_of(value, baseline),
                        "_note": (
                            "只與同一球員的季累計比較。刻意不在不同 context 之間排序或選出"
                            "最高最低，因為各 context 樣本量差異很大且彼此不獨立"
                        ),
                    },
                    "official_reference_value": {
                        "batting_average": ctx["official_avg"],
                        "on_base_percentage": ctx["official_obp"],
                        "slugging_percentage": ctx["official_slg"],
                    }[metric],
                    "own_value_truncated_4dp": None if value is None else trunc4(value),
                    "counting_fields": {
                        k: ctx[k] for k in (
                            "hits", "doubles", "triples", "home_runs", "walks",
                            "intentional_walks", "hit_by_pitch", "sacrifice_flies",
                            "strikeouts", "rbi", "total_bases",
                        )
                    },
                    "runs": None,
                    "ranking_inputs": {
                        "_note": "原始素材，未加權、未合成任何 score",
                        "magnitude": None if diff is None else abs(diff),
                        "sample_size_at_bats": ctx["at_bats"],
                        "percentile_rank": None,
                        "percentile_note": (
                            "官方分項沒有時間維度，無法建立滾動分布，因此沒有百分位"
                        ),
                        "consistency_count": None,
                    },
                    "source_evidence": ["contextual_evidence"],
                    "source_files": [
                        "data/raw/apart_score_0000006888_2026_A_01.json",
                        "data/processed/zhang_yucheng_game_logs_2026.json",
                    ],
                    "calculation_reference": {
                        "formula": formula,
                        "walks_semantics": (
                            "walks（官方 BasesONBallsCnt）已包含故意四壞，"
                            "OBP 不再另加 intentional_walks（Step 7B 以打席恆等式實證）"
                        ),
                        "official_rounding": "官方比率為截斷到 4 位小數；本專案值保留完整精度",
                        "docs": [
                            "docs/CONTEXT_EVIDENCE.md",
                            "docs/VS_HAND_EVIDENCE.md",
                        ],
                    },
                    "traceability": {
                        "date_range": {
                            "first_game_date": None,
                            "last_game_date": None,
                            "_note": "官方分項不提供日期或場次，無法追溯到個別比賽",
                        },
                        "game_snos": None,
                        "context_definition": (
                            f"官方 ItemName「{ctx['item_name']}」，"
                            f"ItemGroupCode = 3，year = 2026，kindCode = A，position = 01"
                        ),
                    },
                }
            )
    return candidates


# ------------------------------------------------------------------ Candidate Type 3

def build_pattern_candidates(contexts: dict, season: dict) -> tuple[list, list]:
    """同一 context 中 AVG / OBP / SLG 三個方向一致時建立 pattern。

    回傳 (candidates, 全部 context 的方向記錄)。方向記錄含未形成 pattern 的，
    是為了讓輸出透明，不是為了篩選。
    """
    candidates = []
    direction_log = []

    for code, ctx in contexts.items():
        dirs = {}
        for metric, short, _ in CONTEXT_METRICS:
            dirs[short] = direction_of(ctx[metric], season[metric])
        values = list(dirs.values())
        # consistency_count = 出現最多的那個方向的個數
        counts = {d: values.count(d) for d in set(values)}
        dominant = max(counts, key=lambda d: counts[d])
        consistency_count = counts[dominant]
        total_metrics = len(values)

        direction_log.append(
            {
                "context": code,
                "directions": dirs,
                "consistency_count": consistency_count,
                "total_metrics": total_metrics,
                "pattern_created": consistency_count == total_metrics,
            }
        )

        if consistency_count != total_metrics:
            continue  # 方向不一致，不建立 pattern（不是被門檻篩掉，是定義上不成立）

        candidates.append(
            {
                "candidate_id": f"PATTERN-{SUBJECT_SLUG}-{code}-AVG_OBP_SLG",
                "type": "MULTI_METRIC_PATTERN",
                "subject": dict(SUBJECT),
                "context": {
                    "code": code,
                    "official_item_name": ctx["item_name"],
                    "group": CONTEXT_GROUP_OF[code],
                    "granularity": "season_cumulative",
                },
                "metrics": ["batting_average", "on_base_percentage", "slugging_percentage"],
                "direction": dominant,
                "direction_per_metric": dirs,
                "consistency_count": consistency_count,
                "total_metrics": total_metrics,
                "metric_values": {
                    metric: {
                        "value": ctx[metric],
                        "baseline_value": season[metric],
                        "difference": (
                            None if (ctx[metric] is None or season[metric] is None)
                            else ctx[metric] - season[metric]
                        ),
                    }
                    for metric, _, _ in CONTEXT_METRICS
                },
                "at_bats": ctx["at_bats"],
                "plate_appearances": ctx["plate_appearances"],
                "ranking_inputs": {
                    "_note": "原始素材，未加權、未合成任何 score",
                    "magnitude": max(
                        abs(ctx[m] - season[m])
                        for m, _, _ in CONTEXT_METRICS
                        if ctx[m] is not None and season[m] is not None
                    ),
                    "sample_size_at_bats": ctx["at_bats"],
                    "percentile_rank": None,
                    "consistency_count": consistency_count,
                },
                "naming_note": (
                    "本欄位只稱為 pattern。刻意不使用 strength / weakness / "
                    "advantage / disadvantage 等帶價值判斷的命名"
                ),
                "source_evidence": ["contextual_evidence"],
                "source_files": [
                    "data/raw/apart_score_0000006888_2026_A_01.json",
                    "data/processed/zhang_yucheng_game_logs_2026.json",
                ],
                "calculation_reference": {
                    "direction_rule": (
                        "逐指標與同一球員的季累計比較：value > baseline 記為 ABOVE，"
                        "< 記為 BELOW，= 記為 EQUAL。三個指標方向相同才建立 pattern"
                    ),
                    "no_threshold": "方向判定不含任何最小差距門檻，差距再小也照方向記錄",
                    "docs": ["docs/CONTEXT_EVIDENCE.md"],
                },
                "traceability": {
                    "date_range": {
                        "first_game_date": None,
                        "last_game_date": None,
                        "_note": "官方分項不提供日期或場次",
                    },
                    "game_snos": None,
                    "context_definition": (
                        f"官方 ItemName「{ctx['item_name']}」，ItemGroupCode = 3，"
                        "year = 2026，kindCode = A，position = 01"
                    ),
                },
            }
        )
    return candidates, direction_log


# ------------------------------------------------------------------ 輸出

REQUIRED_TRACE_KEYS = ("source_evidence", "source_files", "calculation_reference",
                       "traceability")


def print_candidates(candidates: list) -> None:
    for c in candidates:
        print("\n" + "-" * 88)
        print(f"Candidate ID : {c['candidate_id']}")
        print(f"Type         : {c['type']}")
        if c["type"] == "TREND":
            print(f"Metric       : {c['metric']}")
            print(f"Window       : {c['window']['name']}"
                  f"（{c['window']['definition']}）")
            print(f"Evidence     : current={fmt(c['current_value'])}"
                  f"  baseline={fmt(c['baseline_value'])}"
                  f"  diff={fmt(c['absolute_difference'])}"
                  f"  direction={c['direction']}")
            rp = c["rolling_percentile"]
            print(f"               games={c['games']}  at_bats={c['at_bats']}"
                  f"  PA={c['plate_appearances']}")
            print(f"               rolling: n={rp['distribution_n']}"
                  f"  rank={rp['rank_desc']}"
                  f"  percentile_rank={rp['percentile_rank']:.1f}%"
                  f"  percentile_strict={rp['percentile_strict']:.1f}%")
            print(f"Traceability : {c['traceability']['date_range']['first_game_date']}"
                  f" ~ {c['traceability']['date_range']['last_game_date']}")
            print(f"               game_snos={c['traceability']['game_snos']}")
        elif c["type"] == "CONTEXT":
            print(f"Context      : {c['context']['code']}"
                  f"（官方 {c['context']['official_item_name']}，"
                  f"組別 {c['context']['group']}）")
            print(f"Metric       : {c['metric']}")
            print(f"Evidence     : value={fmt(c['value'])}"
                  f"  at_bats={c['at_bats']}  PA={c['plate_appearances']}")
            cmp_ = c["comparison"]
            print(f"               vs season baseline={fmt(cmp_['baseline_value'])}"
                  f"  diff={fmt(cmp_['difference'])}"
                  f"  direction={cmp_['direction']}")
            print(f"               官方 reference={c['official_reference_value']}"
                  f"  本專案截斷 4 位={c['own_value_truncated_4dp']}")
            print(f"Traceability : {c['traceability']['context_definition']}")
            print(f"               game_snos=None（官方分項無場次明細）")
        else:  # MULTI_METRIC_PATTERN
            print(f"Context      : {c['context']['code']}"
                  f"（官方 {c['context']['official_item_name']}）")
            print(f"Metrics      : {', '.join(c['metrics'])}")
            print(f"Evidence     : direction={c['direction']}"
                  f"  consistency_count={c['consistency_count']}"
                  f"/{c['total_metrics']}")
            for metric, mv in c["metric_values"].items():
                print(f"               {metric:<20} value={fmt(mv['value'])}"
                      f"  baseline={fmt(mv['baseline_value'])}"
                      f"  diff={fmt(mv['difference'])}")
            print(f"               at_bats={c['at_bats']}  PA={c['plate_appearances']}")
            print(f"Traceability : {c['traceability']['context_definition']}")
        print(f"Source       : evidence={c['source_evidence']}")
        print(f"               files={c['source_files']}")
        print(f"Ranking inputs (未加權): {json.dumps(c['ranking_inputs'], ensure_ascii=False)}")


# ------------------------------------------------------------------ 驗證

def run_validation(
    candidates: list,
    internals: dict,
    contexts: dict,
    season: dict,
    fingerprints_before: dict,
) -> list:
    checks: list[tuple[str, bool, str]] = []
    by_id = {c["candidate_id"]: c for c in candidates}

    # 1 / 2：TREND candidate 與 Step 5 / Step 6 的已知數字一致
    #        這些期望值直接抄自 Step 5 與 Step 6 的文件記錄
    expected_trend = {
        f"TREND-{SUBJECT_SLUG}-RECENT_10-AVG": {
            "current": 17 / 42, "games": 10, "at_bats": 42,
            "rank": 5, "n": 68, "source": "Step 5 Recent 10 / Step 6 窗口 #68",
        },
        f"TREND-{SUBJECT_SLUG}-RECENT_10-SLG": {
            "current": 26 / 42, "games": 10, "at_bats": 42,
            "rank": 20, "n": 68, "source": "Step 5 Recent 10 / Step 6 窗口 #68",
        },
        f"TREND-{SUBJECT_SLUG}-RECENT_15-AVG": {
            "current": 19 / 58, "games": 15, "at_bats": 58,
            "rank": None, "n": 63, "source": "Step 5 Recent 15",
        },
        f"TREND-{SUBJECT_SLUG}-RECENT_15-SLG": {
            "current": 29 / 58, "games": 15, "at_bats": 58,
            "rank": None, "n": 63, "source": "Step 5 Recent 15",
        },
    }
    for cid, exp in expected_trend.items():
        c = by_id.get(cid)
        if c is None:
            checks.append((f"{cid} 存在", False, "找不到此 candidate"))
            continue
        ok = (
            abs(c["current_value"] - exp["current"]) < 1e-12
            and c["games"] == exp["games"]
            and c["at_bats"] == exp["at_bats"]
            and c["rolling_percentile"]["distribution_n"] == exp["n"]
            and (exp["rank"] is None
                 or c["rolling_percentile"]["rank_desc"] == exp["rank"])
        )
        detail = (
            f"current={fmt(c['current_value'])}（期望 {fmt(exp['current'])}）"
            f"　games={c['games']}　at_bats={c['at_bats']}"
            f"　rolling n={c['rolling_percentile']['distribution_n']}"
            f"（期望 {exp['n']}）"
            f"　rank={c['rolling_percentile']['rank_desc']}"
            f"　來源 {exp['source']}"
        )
        checks.append((f"{cid} 與既有 evidence 一致", ok, detail))

    # Recent 15 的最新窗口應等於 Step 5 的 Recent 15（用滾動窗口最後一個交叉核對）
    for window_name, size in WINDOW_SIZES.items():
        rolling = build_rolling_windows(sort_by_date_cache["games"], size=size)
        latest = rolling[-1]
        w = internals[window_name]["window"]
        ok = (
            latest["game_snos"] == w["game_snos"]
            and abs(latest["batting_average"] - w["batting_average"]) < 1e-12
            and abs(latest["slugging_percentage"] - w["slugging"]) < 1e-12
        )
        checks.append(
            (f"{window_name}：最新滾動窗口 == build_window 結果（跨實作交叉核對）",
             ok,
             f"game_snos 相同={latest['game_snos'] == w['game_snos']}"
             f"　AVG {fmt(latest['batting_average'])} vs {fmt(w['batting_average'])}"
             f"　SLG {fmt(latest['slugging_percentage'])} vs {fmt(w['slugging'])}")
        )

    # 3：CONTEXT candidate 與 Step 8 記錄的數字一致
    expected_context = {
        "VS_RIGHT": (258, 219, 68, 122), "VS_LEFT": (62, 54, 17, 23),
        "VS_STARTER": (209, 180, 61, 102), "VS_RELIEF": (80, 66, 20, 39),
        "VS_CLOSER": (31, 27, 4, 4),
        "VS_DOMESTIC": (202, 173, 50, 86), "VS_FOREIGN": (118, 100, 35, 59),
    }
    for code, (pa, ab, h, tb) in expected_context.items():
        ctx = contexts[code]
        ok = (
            ctx["plate_appearances"] == pa and ctx["at_bats"] == ab
            and ctx["hits"] == h and ctx["total_bases"] == tb
        )
        checks.append(
            (f"CONTEXT {code} 的 PA/AB/H/TB 與 Step 8 一致", ok,
             f"實際 {ctx['plate_appearances']}/{ctx['at_bats']}/{ctx['hits']}/"
             f"{ctx['total_bases']}　期望 {pa}/{ab}/{h}/{tb}")
        )

    # CONTEXT 比率截斷後應與官方值相符（沿用 Step 8 的判定）
    bad_ratio = []
    for c in candidates:
        if c["type"] != "CONTEXT":
            continue
        official = c["official_reference_value"]
        ours_trunc = c["own_value_truncated_4dp"]
        if official is None or ours_trunc is None:
            bad_ratio.append(f"{c['candidate_id']} 缺值")
        elif abs(ours_trunc - official) >= 1e-9:
            bad_ratio.append(
                f"{c['candidate_id']} 截斷 {ours_trunc} vs 官方 {official}"
            )
    checks.append(
        ("全部 CONTEXT candidate 的比率截斷 4 位後與官方值相符", not bad_ratio,
         "21 項全部相符" if not bad_ratio else "；".join(bad_ratio))
    )

    # 三組 context 加總與 season totals 對帳（沿用 Step 8 的檢查）
    groups: dict[str, list] = {}
    for code, ctx in contexts.items():
        groups.setdefault(CONTEXT_GROUP_OF[code], []).append(ctx)
    for group, members in groups.items():
        ok = True
        parts = []
        for field, short in (("plate_appearances", "PA"), ("at_bats", "AB"),
                             ("hits", "H"), ("total_bases", "TB")):
            total = sum(m[field] for m in members)
            ok = ok and total == season[field]
            parts.append(f"{short} {total}/{season[field]}")
        checks.append(
            (f"context 組別 {group} 加總 == season totals", ok, "　".join(parts))
        )

    # 4：每個 candidate 都有 traceability
    missing_trace = []
    for c in candidates:
        for key in REQUIRED_TRACE_KEYS:
            if key not in c or c[key] in (None, [], {}):
                missing_trace.append(f"{c['candidate_id']} 缺 {key}")
        if not c.get("source_files"):
            missing_trace.append(f"{c['candidate_id']} source_files 為空")
    checks.append(
        ("每個 candidate 都有 source_evidence / source_files / "
         "calculation_reference / traceability",
         not missing_trace,
         f"{len(candidates)} 個 candidate 全部具備" if not missing_trace
         else "；".join(missing_trace))
    )

    # 5：沒有 candidate 使用不存在的資料
    #    (a) source_files 指向的檔案必須真的存在
    #    (b) runs 必須是 None（官方分項沒有得分欄位）
    #    (c) CONTEXT / PATTERN 的 game_snos 必須是 None，不可憑空給場次
    bad_data = []
    for c in candidates:
        for f in c["source_files"]:
            if not (ROOT / f).exists():
                bad_data.append(f"{c['candidate_id']} 引用不存在的檔案 {f}")
        if c["type"] == "CONTEXT" and c.get("runs") is not None:
            bad_data.append(f"{c['candidate_id']} runs 不應有值")
        if c["type"] in ("CONTEXT", "MULTI_METRIC_PATTERN"):
            if c["traceability"]["game_snos"] is not None:
                bad_data.append(f"{c['candidate_id']} 不應有 game_snos")
        if c["type"] == "TREND":
            if len(c["traceability"]["game_snos"]) != c["games"]:
                bad_data.append(f"{c['candidate_id']} game_snos 數量與 games 不符")
    checks.append(
        ("沒有 candidate 使用不存在的資料", not bad_data,
         "全部通過" if not bad_data else "；".join(bad_data))
    )

    # 6：沒有 HTTP request
    ok_net = network_guard_active()
    checks.append(
        ("沒有任何 HTTP request", ok_net,
         "socket.connect / connect_ex / create_connection 已在程式啟動時被封鎖，"
         "任何連線嘗試都會拋 NetworkBlocked；資料全部來自本地檔案")
    )

    # 7：沒有修改 raw / processed data
    changed = []
    for path, before in fingerprints_before.items():
        after = sha256_of(path)
        if after != before:
            changed.append(f"{path.name} 被修改")
    checks.append(
        ("沒有修改 raw / processed data", not changed,
         "　".join(f"{p.name} sha256 {v[0][:8]} / {v[1]} bytes"
                   for p, v in fingerprints_before.items())
         if not changed else "；".join(changed))
    )

    # 8：沒有自然語言結論
    #    檢查所有 candidate 欄位中不得出現價值判斷字眼
    forbidden = ["strength", "weakness", "advantage", "disadvantage",
                 "擅長", "不擅長", "弱點", "優勢", "劣勢", "變好", "變差",
                 "建議", "應該", "預測", "important", "insight_text"]
    hits = []
    blob = json.dumps(candidates, ensure_ascii=False)
    for word in forbidden:
        # naming_note 內明確聲明「不使用」這些字，屬於說明而非結論，需排除
        occurrences = blob.count(word)
        allowed = json.dumps(
            [c.get("naming_note", "") for c in candidates], ensure_ascii=False
        ).count(word)
        if occurrences - allowed > 0:
            hits.append(f"{word}×{occurrences - allowed}")
    checks.append(
        ("candidate 中沒有自然語言結論或價值判斷字眼", not hits,
         "未出現任何禁用字眼（naming_note 中的宣告性提及已排除）" if not hits
         else "、".join(hits))
    )

    # 9：沒有 threshold
    #    所有 candidate 都是由「存在的 evidence」直接產生，沒有任何被篩掉的項目。
    expected_counts = {
        "TREND": len(WINDOW_SIZES) * 2,          # 2 窗口 × 2 指標
        "CONTEXT": len(CONTEXT_CODES) * 3,        # 7 context × 3 指標
    }
    actual_trend = sum(1 for c in candidates if c["type"] == "TREND")
    actual_context = sum(1 for c in candidates if c["type"] == "CONTEXT")
    ok_no_filter = (
        actual_trend == expected_counts["TREND"]
        and actual_context == expected_counts["CONTEXT"]
    )
    checks.append(
        ("沒有 threshold：TREND 與 CONTEXT candidate 全數產生，沒有任何項目被篩掉",
         ok_no_filter,
         f"TREND {actual_trend}/{expected_counts['TREND']}"
         f"　CONTEXT {actual_context}/{expected_counts['CONTEXT']}"
         "（MULTI_METRIC_PATTERN 依定義只在三指標方向一致時成立，不是門檻篩選）")
    )

    # 10：沒有 final ranking score
    score_keys = []
    for c in candidates:
        for key in c:
            if key.lower() in ("score", "final_score", "rank", "importance",
                               "priority", "weight"):
                score_keys.append(f"{c['candidate_id']}.{key}")
        ri = c.get("ranking_inputs", {})
        for key in ri:
            if "score" in key.lower() or "weight" in key.lower():
                score_keys.append(f"{c['candidate_id']}.ranking_inputs.{key}")
    checks.append(
        ("沒有 final ranking score 或加權", not score_keys,
         "ranking_inputs 只存放未加權的原始素材"
         "（magnitude / sample_size / percentile / consistency_count）"
         if not score_keys else "；".join(score_keys))
    )

    return checks


# 給驗證函式共用排序後的比賽清單
sort_by_date_cache: dict = {}


# ------------------------------------------------------------------ main

def main() -> None:
    write_output = "--write" in sys.argv

    logs, apart_rows = load_inputs()
    fingerprints_before = {
        PLAYER_LOG_PATH: sha256_of(PLAYER_LOG_PATH),
        APART_CACHE_PATH: sha256_of(APART_CACHE_PATH),
    }
    sort_by_date_cache["games"] = sort_by_date(logs)

    contexts = build_context_evidence(apart_rows)
    season = build_season_baseline(logs, contexts)

    print("=" * 88)
    print("Candidate Insight Engine — 第一版（Step 9）")
    print(f"對象：{SUBJECT['player_name']}（Acnt {SUBJECT['player_acnt']}）"
          f"　{SUBJECT['season']} {SUBJECT['kind_name']}")
    print("這一步只把既有 evidence 組織成候選。沒有 threshold、沒有 ranking score、")
    print("沒有自然語言結論、沒有 LLM、沒有網路存取。")
    print("=" * 88)
    print("\n季累計基準值（baseline，來自既有 evidence）：")
    print(f"  PA={season['plate_appearances']}  AB={season['at_bats']}  "
          f"H={season['hits']}  TB={season['total_bases']}  "
          f"BB={season['walks']}  HBP={season['hit_by_pitch']}  "
          f"SF={season['sacrifice_flies']}")
    print(f"  AVG = {season['hits']} / {season['at_bats']} = "
          f"{fmt(season['batting_average'])}")
    print(f"  OBP = {season['obp_numerator']} / {season['obp_denominator']} = "
          f"{fmt(season['on_base_percentage'])}")
    print(f"  SLG = {season['total_bases']} / {season['at_bats']} = "
          f"{fmt(season['slugging_percentage'])}")
    print("  註：AVG / SLG 由 processed data 逐場加總；OBP 的 BB / HBP / SF 取自官方")
    print("  　　context evidence 加總（Step 8 已驗證三組加總與 processed data 相符）。")

    trend_candidates, internals = build_trend_candidates(logs, season)
    context_candidates = build_context_candidates(contexts, season)
    pattern_candidates, direction_log = build_pattern_candidates(contexts, season)
    candidates = trend_candidates + context_candidates + pattern_candidates

    for title, group in (
        ("Candidate Type 1 — TREND", trend_candidates),
        ("Candidate Type 2 — CONTEXT", context_candidates),
        ("Candidate Type 3 — MULTI_METRIC_PATTERN", pattern_candidates),
    ):
        print("\n" + "=" * 88)
        print(f"{title}（{len(group)} 個）")
        print("=" * 88)
        print_candidates(group)

    print("\n" + "=" * 88)
    print("全部 context 的方向記錄（透明度用，不是篩選結果）")
    print("=" * 88)
    print(f"  {'context':<14} {'AVG':<7} {'OBP':<7} {'SLG':<7} "
          f"{'consistency':<12} pattern_created")
    for d in direction_log:
        print(f"  {d['context']:<14} {d['directions']['AVG']:<7} "
              f"{d['directions']['OBP']:<7} {d['directions']['SLG']:<7} "
              f"{d['consistency_count']}/{d['total_metrics']:<10} "
              f"{d['pattern_created']}")
    print("\n  consistency_count < total_metrics 的 context 沒有建立 pattern，")
    print("  這是因為「三指標方向一致」在定義上不成立，不是被任何門檻篩掉。")

    print("\n" + "=" * 88)
    print("Summary")
    print("=" * 88)
    print(f"  TREND                : {len(trend_candidates)}")
    print(f"  CONTEXT              : {len(context_candidates)}")
    print(f"  MULTI_METRIC_PATTERN : {len(pattern_candidates)}")
    print(f"  總計                 : {len(candidates)}")

    print("\n" + "=" * 88)
    print("Validation")
    print("=" * 88)
    checks = run_validation(candidates, internals, contexts, season, fingerprints_before)
    for name, passed, detail in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        print(f"         {detail}")
    failed = [c for c in checks if not c[1]]
    print(f"\n  共 {len(checks)} 項檢查，通過 {len(checks) - len(failed)} 項，"
          f"失敗 {len(failed)} 項。")
    if failed:
        print("  失敗項目未被修正，原值保留，請見 docs/CANDIDATE_INSIGHT_DESIGN.md。")

    if write_output:
        payload = {
            "_meta": {
                "artifact_type": "derived_analysis_output",
                "note": (
                    "這不是來源資料，是由 src/candidate_insights.py 從既有 evidence "
                    "重新產生的衍生輸出。可隨時重建，不應被當成事實來源。"
                    "事實來源是 data/processed/ 的逐場資料與 data/raw/ 的官方分項快取。"
                ),
                "generator": "src/candidate_insights.py",
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "subject": dict(SUBJECT),
                "season_baseline": season,
                "candidate_counts": {
                    "TREND": len(trend_candidates),
                    "CONTEXT": len(context_candidates),
                    "MULTI_METRIC_PATTERN": len(pattern_candidates),
                    "total": len(candidates),
                },
                "contains_no": [
                    "threshold", "final_ranking_score", "weighting",
                    "natural_language_conclusion", "prediction", "recommendation",
                ],
                "context_direction_log": direction_log,
            },
            "candidates": candidates,
        }
        OUTPUT_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"\n已寫出 {OUTPUT_PATH.relative_to(ROOT)}"
              f"（{len(candidates)} 個 candidate，data/ 已被 .gitignore 排除）")
    else:
        print("\n（未寫檔。要輸出 JSON 請加 --write）")


if __name__ == "__main__":
    main()
