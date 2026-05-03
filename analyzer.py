# -*- coding: utf-8 -*-
"""
競馬データ収集システム — 分析・集計モジュール
"""

import re
from collections import Counter
from typing import Dict, List, Optional

from config import STYLE_THRESHOLDS, TRACK_DIRECTION


# ============================================================
# 脚質推定
# ============================================================

def _parse_passing(passing_str: str) -> List[int]:
    """
    通過順位文字列 "03-03-02-02" → [3, 3, 2, 2]
    """
    if not passing_str:
        return []
    nums = re.findall(r"\d+", passing_str)
    return [int(n) for n in nums]


def estimate_running_style(history: List[Dict]) -> str:
    """
    過去走の通過順位から脚質を推定。
    Returns: "逃げ" / "先行" / "差し" / "追込" / "不明"
    """
    if not history:
        return "不明"

    positions = []
    for race in history:
        passing = race.get("通過順位", "")
        nums = _parse_passing(passing)
        n_runners = race.get("頭数", 18)
        if not n_runners or n_runners == 0:
            n_runners = 18  # デフォルト
        if nums:
            # 1角の通過順位を使用（最初の値）
            first_corner = nums[0]
            ratio = first_corner / n_runners
            positions.append(ratio)

    if not positions:
        return "不明"

    avg_ratio = sum(positions) / len(positions)

    if avg_ratio <= STYLE_THRESHOLDS["逃げ"]:
        return "逃げ"
    elif avg_ratio <= STYLE_THRESHOLDS["先行"]:
        return "先行"
    elif avg_ratio <= STYLE_THRESHOLDS["差し"]:
        return "差し"
    else:
        return "追込"


def estimate_running_style_detail(history: List[Dict]) -> Dict:
    """
    脚質の詳細情報を返す。
    """
    style = estimate_running_style(history)
    style_counts = Counter()

    for race in history:
        passing = race.get("通過順位", "")
        nums = _parse_passing(passing)
        n_runners = race.get("頭数", 18) or 18
        if nums:
            ratio = nums[0] / n_runners
            if ratio <= STYLE_THRESHOLDS["逃げ"]:
                style_counts["逃げ"] += 1
            elif ratio <= STYLE_THRESHOLDS["先行"]:
                style_counts["先行"] += 1
            elif ratio <= STYLE_THRESHOLDS["差し"]:
                style_counts["差し"] += 1
            else:
                style_counts["追込"] += 1

    return {
        "脚質": style,
        "逃げ回数": style_counts.get("逃げ", 0),
        "先行回数": style_counts.get("先行", 0),
        "差し回数": style_counts.get("差し", 0),
        "追込回数": style_counts.get("追込", 0),
    }


# ============================================================
# 条件適性集計
# ============================================================

def calc_course_fitness(
    history: List[Dict],
    track: str,
    surface: str,
    distance: int,
) -> Dict:
    """
    同競馬場×同距離×同コースでの成績を集計。
    """
    same_all = []      # 同競馬場×同距離×同コース
    same_track = []    # 同競馬場
    same_surface = []  # 同コース
    same_dist = []     # 同距離
    dist_up = []       # 距離延長時
    dist_down = []     # 距離短縮時
    left_turn = []     # 左回り
    right_turn = []    # 右回り

    # 前走距離の追跡
    prev_dist = None

    for race in history:
        r_track = race.get("競馬場", "")
        r_surface = race.get("芝ダート", "")
        r_dist = race.get("距離", 0)
        r_finish = race.get("着順", 99)

        # 着順が数値でない場合スキップ
        if isinstance(r_finish, str):
            if r_finish.isdigit():
                r_finish = int(r_finish)
            else:
                prev_dist = r_dist
                continue

        result = {"着順": r_finish, "競馬場": r_track, "距離": r_dist}

        # 同条件チェック
        track_match = (r_track == track)
        surface_match = (r_surface == surface or
                         (surface == "芝" and r_surface == "芝") or
                         (surface in ("ダート", "ダ") and r_surface in ("ダート", "ダ")))
        dist_match = (r_dist == distance)

        if track_match:
            same_track.append(result)
        if surface_match:
            same_surface.append(result)
        if dist_match:
            same_dist.append(result)
        if track_match and surface_match and dist_match:
            same_all.append(result)

        # 距離延長/短縮
        if prev_dist and r_dist:
            if r_dist > prev_dist:
                dist_up.append(result)
            elif r_dist < prev_dist:
                dist_down.append(result)
        prev_dist = r_dist

        # 左回り/右回り
        direction = TRACK_DIRECTION.get(r_track, "")
        if direction == "左":
            left_turn.append(result)
        elif direction == "右":
            right_turn.append(result)

    def _summarize(races):
        if not races:
            return {"戦数": 0, "勝利": 0, "連対": 0, "複勝": 0, "勝率": 0, "連対率": 0, "複勝率": 0}
        n = len(races)
        wins = sum(1 for r in races if r["着順"] == 1)
        top2 = sum(1 for r in races if r["着順"] <= 2)
        top3 = sum(1 for r in races if r["着順"] <= 3)
        return {
            "戦数": n,
            "勝利": wins,
            "連対": top2,
            "複勝": top3,
            "勝率": round(wins / n * 100, 1),
            "連対率": round(top2 / n * 100, 1),
            "複勝率": round(top3 / n * 100, 1),
        }

    return {
        "同コース同距離": _summarize(same_all),
        "同競馬場": _summarize(same_track),
        "同コース種別": _summarize(same_surface),
        "同距離": _summarize(same_dist),
        "距離延長": _summarize(dist_up),
        "距離短縮": _summarize(dist_down),
        "左回り": _summarize(left_turn),
        "右回り": _summarize(right_turn),
    }


# ============================================================
# 馬ごとのサマリー計算
# ============================================================

def calc_horse_summary(
    entry: Dict,
    history: List[Dict],
    track: str,
    surface: str,
    distance: int,
) -> Dict:
    """
    馬ごとの集計サマリーを計算。
    """
    summary = {
        "馬名": entry.get("馬名", ""),
        "枠番": entry.get("枠番", 0),
        "馬番": entry.get("馬番", 0),
        "騎手": entry.get("騎手", ""),
        "斤量": entry.get("斤量", 0),
    }

    # 脚質
    style_info = estimate_running_style_detail(history)
    summary["脚質"] = style_info["脚質"]
    summary["逃げ回数"] = style_info["逃げ回数"]
    summary["先行回数"] = style_info["先行回数"]
    summary["差し回数"] = style_info["差し回数"]
    summary["追込回数"] = style_info["追込回数"]

    # 上がり3F平均
    agari_times = [r.get("上がり3F", 0) for r in history if r.get("上がり3F", 0) > 0]
    summary["平均上がり3F"] = round(sum(agari_times) / len(agari_times), 1) if agari_times else 0
    summary["最速上がり3F"] = min(agari_times) if agari_times else 0

    # 平均着順
    finishes = []
    for r in history:
        f = r.get("着順")
        if f is None: continue
        if isinstance(f, (int, float)) and f > 0:
            finishes.append(int(f))
        elif isinstance(f, str):
            # 文字列から数値を抽出 (例: "1(降)" -> 1)
            m = re.search(r"(\d+)", f)
            if m:
                finishes.append(int(m.group(1)))
    summary["平均着順"] = round(sum(finishes) / len(finishes), 1) if finishes else 0

    # 勝率等
    n = len(finishes)
    if n > 0:
        summary["戦数"] = n
        summary["勝率"] = round(sum(1 for f in finishes if f == 1) / n * 100, 1)
        summary["連対率"] = round(sum(1 for f in finishes if f <= 2) / n * 100, 1)
        summary["複勝率"] = round(sum(1 for f in finishes if f <= 3) / n * 100, 1)
    else:
        summary["戦数"] = 0
        summary["勝率"] = 0
        summary["連対率"] = 0
        summary["複勝率"] = 0

    # 条件適性
    fitness = calc_course_fitness(history, track, surface, distance)
    same_cd = fitness["同コース同距離"]
    summary["同コース成績"] = f"{same_cd['勝利']}-{same_cd['連対']-same_cd['勝利']}-{same_cd['複勝']-same_cd['連対']}-{same_cd['戦数']-same_cd['複勝']}" if same_cd["戦数"] > 0 else "0-0-0-0"
    same_d = fitness["同距離"]
    summary["同距離成績"] = f"{same_d['勝利']}-{same_d['連対']-same_d['勝利']}-{same_d['複勝']-same_d['連対']}-{same_d['戦数']-same_d['複勝']}" if same_d["戦数"] > 0 else "0-0-0-0"
    dist_u = fitness["距離延長"]
    summary["距離延長成績"] = f"{dist_u['勝利']}-{dist_u['連対']-dist_u['勝利']}-{dist_u['複勝']-dist_u['連対']}-{dist_u['戦数']-dist_u['複勝']}" if dist_u["戦数"] > 0 else "0-0-0-0"
    dist_d = fitness["距離短縮"]
    summary["距離短縮成績"] = f"{dist_d['勝利']}-{dist_d['連対']-dist_d['勝利']}-{dist_d['複勝']-dist_d['連対']}-{dist_d['戦数']-dist_d['複勝']}" if dist_d["戦数"] > 0 else "0-0-0-0"

    return summary


# ============================================================
# 展開推定
# ============================================================

def estimate_pace(entries_with_style: List[Dict]) -> Dict:
    """
    展開（ペース）を推定する。
    entries_with_style: [{"馬名": ..., "脚質": ..., ...}, ...]
    """
    styles = [e.get("脚質", "不明") for e in entries_with_style]
    n_runners = len(entries_with_style)

    nige_count = styles.count("逃げ")
    senkou_count = styles.count("先行")
    front_runners = nige_count + senkou_count
    sashi_count = styles.count("差し")
    oikomi_count = styles.count("追込")

    # ペース推定ロジック
    if nige_count >= 3:
        pace = "H"
        reason = f"逃げ馬{nige_count}頭でハイペースが予想される"
        comment = f"逃げ馬が{nige_count}頭と激戦。ハナ争いが激化しハイペース必至です。前に行きたい馬には非常に厳しい流れになり、スタミナと直線での底力が問われるタフな展開になるでしょう。"
    elif nige_count >= 2:
        pace = "H"
        reason = f"逃げ馬{nige_count}頭で前傾ペース"
        comment = f"逃げ馬が複数おり、序盤から速い流れが予想されます。中盤以降も緩みにくい展開になりやすく、中団から差し脚を伸ばせる馬にチャンスが巡ってきそうです。"
    elif nige_count == 1 and senkou_count >= 4:
        pace = "M"
        reason = f"単騎逃げだが先行馬が多く平均ペース"
        comment = f"単騎逃げが想定されますが、先行勢が層が厚く、極端なスローにはならないでしょう。平均的なペースで、枠順や道中の立ち回りが勝敗を分ける実力通りの決着になりやすい展開です。"
    elif nige_count == 0 and senkou_count <= 2:
        pace = "S"
        reason = f"逃げ馬不在でスローペース濃厚"
        comment = f"確たる逃げ馬がおらず、序盤は牽制し合うようなスローペースになりそうです。瞬発力勝負は確実で、4コーナーでの位置取りと上がりの速さが極めて重要になります。"
    elif nige_count <= 1 and senkou_count <= 3:
        pace = "S"
        reason = f"逃げ馬少なく落ち着いたペース"
        comment = f"逃げ・先行馬が少なく、落ち着いた流れが予想されます。前残りの展開に注意が必要で、後方の馬にとっては早めに動かないと厳しい競馬になるかもしれません。"
    else:
        pace = "M"
        reason = f"標準的な脚質分布で平均的なペース"
        comment = f"脚質のバランスが良く、極端な偏りのない平均的なペースになりそうです。展開の紛れは少なく、コース適性や現在の充実度がそのまま結果に繋がりやすい構成です。"

    # 逃げ候補リスト
    nige_candidates = [
        e.get("馬名", "") for e in entries_with_style
        if e.get("脚質") == "逃げ"
    ]

    return {
        "pace": pace,
        "reason": reason,
        "comment": comment,
        "front_runners": front_runners,
        "逃げ": nige_count,
        "先行": senkou_count,
        "差し": sashi_count,
        "追込": oikomi_count,
        "不明": styles.count("不明"),
        "逃げ候補": nige_candidates,
        "出走頭数": n_runners,
    }


# ============================================================
# 枠順傾向集計
# ============================================================

def calc_post_position_trend(past_results: List[List[Dict]]) -> Dict:
    """
    過去レース結果から枠番別成績を集計。
    past_results: [race1_results, race2_results, ...]
    各race_results: [{"枠番": 1, "着順": 3, ...}, ...]
    """
    post_stats = {}  # {枠番: {"戦数": N, "勝利": N, "連対": N, "複勝": N}}

    for race_results in past_results:
        for r in race_results:
            waku = r.get("枠番", 0)
            finish = r.get("着順", 99)
            if isinstance(finish, str):
                if finish.isdigit():
                    finish = int(finish)
                else:
                    continue

            if waku not in post_stats:
                post_stats[waku] = {"戦数": 0, "勝利": 0, "連対": 0, "複勝": 0}

            post_stats[waku]["戦数"] += 1
            if finish == 1:
                post_stats[waku]["勝利"] += 1
            if finish <= 2:
                post_stats[waku]["連対"] += 1
            if finish <= 3:
                post_stats[waku]["複勝"] += 1

    # 率を計算
    for waku, stats in post_stats.items():
        n = stats["戦数"]
        if n > 0:
            stats["勝率"] = round(stats["勝利"] / n * 100, 1)
            stats["連対率"] = round(stats["連対"] / n * 100, 1)
            stats["複勝率"] = round(stats["複勝"] / n * 100, 1)

    return dict(sorted(post_stats.items()))


# ============================================================
# 枠順傾向集計（馬の過去成績ベース）
# ============================================================

def calc_post_position_trend_from_history(
    all_history: Dict[str, List[Dict]],
    track: str,
    surface: str,
    distance: int,
    distance_tolerance: int = 0,
) -> Dict:
    """
    各馬の過去成績データから、同条件レースの枠番別成績を集計。
    db.netkeiba.com のレース検索がJS依存で使えないため、
    既に取得済みの馬過去成績から枠順傾向を抽出する代替手法。

    all_history: {"馬名": [race_records, ...], ...}
    track: 競馬場 (例: "中山")
    surface: 芝/ダート
    distance: 距離 (例: 2000)
    distance_tolerance: 距離許容誤差 (0なら完全一致)
    """
    post_stats = {}  # {枠番: {"戦数": N, "勝利": N, "連対": N, "複勝": N}}
    matched_races = set()  # 重複排除用 (開催日+競馬場+R)

    for horse_name, history in all_history.items():
        for race in history:
            r_track = race.get("競馬場", "")
            r_surface = race.get("芝ダート", "")
            r_dist = race.get("距離", 0)
            r_waku = race.get("枠番", 0)
            r_finish = race.get("着順", 99)
            r_date = race.get("開催日", "")

            # 条件一致チェック
            if r_track != track:
                continue
            surface_match = (
                (surface == "芝" and r_surface == "芝") or
                (surface in ("ダート", "ダ") and r_surface in ("ダート", "ダ"))
            )
            if not surface_match:
                continue
            if distance_tolerance == 0:
                if r_dist != distance:
                    continue
            else:
                if abs(r_dist - distance) > distance_tolerance:
                    continue

            # 着順チェック
            if isinstance(r_finish, str):
                if r_finish.isdigit():
                    r_finish = int(r_finish)
                else:
                    continue

            if not r_waku or r_waku == 0:
                continue

            # 集計
            if r_waku not in post_stats:
                post_stats[r_waku] = {"戦数": 0, "勝利": 0, "連対": 0, "複勝": 0}

            post_stats[r_waku]["戦数"] += 1
            if r_finish == 1:
                post_stats[r_waku]["勝利"] += 1
            if r_finish <= 2:
                post_stats[r_waku]["連対"] += 1
            if r_finish <= 3:
                post_stats[r_waku]["複勝"] += 1

            # レース特定キー
            r_name = race.get("レース名", "")
            race_key = f"{r_date}_{r_track}_{r_name}"
            if race_key:
                matched_races.add(race_key)

    # 率を計算
    for waku, stats in post_stats.items():
        n = stats["戦数"]
        if n > 0:
            stats["勝率"] = round(stats["勝利"] / n * 100, 1)
            stats["連対率"] = round(stats["連対"] / n * 100, 1)
            stats["複勝率"] = round(stats["複勝"] / n * 100, 1)

    total_entries = sum(s["戦数"] for s in post_stats.values())

    return {
        "枠番別成績": dict(sorted(post_stats.items())),
        "データソース": "出走馬過去成績",
        "対象レース数(推定)": len(matched_races),
        "対象走数": total_entries,
    }


# ============================================================
# 推奨馬スコアリング & 買い目生成
# ============================================================

# 展開適性マトリクス: pace × style → 加点率 (0.0〜1.0)
_PACE_STYLE_MATRIX = {
    "H": {"逃げ": 0.3, "先行": 0.5, "差し": 0.9, "追込": 1.0, "不明": 0.5},
    "M": {"逃げ": 0.6, "先行": 0.7, "差し": 0.7, "追込": 0.6, "不明": 0.5},
    "S": {"逃げ": 1.0, "先行": 0.8, "差し": 0.5, "追込": 0.3, "不明": 0.5},
}


def _parse_record(record_str: str):
    """'1-2-0-3' → (wins, seconds, thirds, others)"""
    try:
        parts = [int(x) for x in record_str.split("-")]
        if len(parts) == 4:
            return tuple(parts)
    except (ValueError, AttributeError):
        pass
    return (0, 0, 0, 0)


def calc_recommendation(
    entries: List[Dict],
    pace_info: Dict,
    post_trend: Dict,
) -> Dict:
    """
    各馬をスコアリングし、推奨馬・買い目を生成。

    Returns: {
        "ranking": [{"馬番", "馬名", "score", "印", "factors": {...}}, ...],
        "bets": {"単勝": [...], "複勝": [...], "馬連": [...], ...},
    }
    """
    pace = pace_info.get("pace", "M")
    trend_data = post_trend.get("枠番別成績", {})

    scored = []
    all_agari = [e.get("平均上がり3F", 0) for e in entries if e.get("平均上がり3F", 0) > 0]
    all_avg_finish = [e.get("平均着順", 0) for e in entries if e.get("平均着順", 0) > 0]

    # ベンチマーク値
    best_agari = min(all_agari) if all_agari else 33.0
    worst_agari = max(all_agari) if all_agari else 40.0
    agari_range = max(worst_agari - best_agari, 0.5)

    best_finish = min(all_avg_finish) if all_avg_finish else 1.0
    worst_finish = max(all_avg_finish) if all_avg_finish else 15.0
    finish_range = max(worst_finish - best_finish, 1.0)

    for entry in entries:
        factors = {}
        umaban = entry.get("馬番", 0)
        waku = entry.get("枠番", 0)

        # ── (1) 能力値: 30点 ──
        agari = entry.get("平均上がり3F", 0)
        avg_finish = entry.get("平均着順", 0)
        win_rate = entry.get("勝率", 0)

        ability_agari = 0
        if agari > 0:
            ability_agari = max(0, (worst_agari - agari) / agari_range) * 15

        ability_finish = 0
        if avg_finish > 0:
            ability_finish = max(0, (worst_finish - avg_finish) / finish_range) * 10

        ability_win = min(win_rate / 100 * 5, 5)

        ability_score = round(ability_agari + ability_finish + ability_win, 1)
        factors["能力値"] = round(ability_score, 1)

        # ── (2) 展開適性: 20点 ──
        style = entry.get("脚質", "不明")
        pace_matrix = _PACE_STYLE_MATRIX.get(pace, _PACE_STYLE_MATRIX["M"])
        pace_fit = pace_matrix.get(style, 0.5)
        pace_score = round(pace_fit * 20, 1)
        factors["展開適性"] = pace_score

        # ── (3) コース適性: 20点 ──
        same_course = entry.get("同コース成績", "0-0-0-0")
        same_dist = entry.get("同距離成績", "0-0-0-0")
        c_w, c_2, c_3, c_o = _parse_record(same_course)
        d_w, d_2, d_3, d_o = _parse_record(same_dist)
        c_total = c_w + c_2 + c_3 + c_o
        d_total = d_w + d_2 + d_3 + d_o

        course_score = 0
        if c_total > 0:
            course_score += (c_w * 4 + c_2 * 2.5 + c_3 * 1.5) / max(c_total, 1) * 5
        if d_total > 0:
            course_score += (d_w * 4 + d_2 * 2.5 + d_3 * 1.5) / max(d_total, 1) * 5
        course_score = min(round(course_score, 1), 20)
        factors["コース適性"] = course_score

        # ── (4) 近走調子: 15点 ──
        recent = entry.get("過去走", [])[:3]
        form_score = 0
        if recent:
            recent_finishes = []
            for r in recent:
                f = r.get("着順", 99)
                if isinstance(f, int):
                    recent_finishes.append(f)
                elif isinstance(f, str) and f.isdigit():
                    recent_finishes.append(int(f))

            if recent_finishes:
                weights = [1.5, 1.0, 0.5][:len(recent_finishes)]
                weighted_avg = sum(f * w for f, w in zip(recent_finishes, weights)) / sum(weights)
                form_score = max(0, (10 - weighted_avg) / 7) * 15

                if len(recent_finishes) >= 2 and recent_finishes[0] < recent_finishes[-1]:
                    form_score = min(form_score + 2, 15)

        form_score = round(min(form_score, 15), 1)
        factors["近走調子"] = form_score

        # ── (5) 枠順傾向: 15点 ──
        waku_score = 0
        waku_stats = trend_data.get(str(waku), {})
        if waku_stats:
            waku_place_rate = waku_stats.get("複勝率", 0)
            waku_win_rate = waku_stats.get("勝率", 0)
            waku_score = (waku_place_rate / 100) * 10 + (waku_win_rate / 100) * 5
        waku_score = round(min(waku_score, 15), 1)
        factors["枠順傾向"] = waku_score

        # ── 合計 ──
        total = round(ability_score + pace_score + course_score + form_score + waku_score, 1)

        scored.append({
            "馬番": umaban,
            "枠番": waku,
            "馬名": entry.get("馬名", ""),
            "score": total,
            "factors": factors,
            "オッズ": entry.get("オッズ", 0),
            "comment": _generate_horse_comment(entry, pace),
        })

    # スコア降順ソート
    scored.sort(key=lambda x: x["score"], reverse=True)

    # 自信度(%) を計算: 1位馬のスコアを100%基準として正規化
    max_score = scored[0]["score"] if scored and scored[0]["score"] > 0 else 1
    for s in scored:
        s["confidence"] = round(s["score"] / max_score * 100, 1)

    # ── 妙味指数計算 ──
    # 理論勝率: 各馬のスコアをレース全体で正規化
    total_score = sum(s["score"] for s in scored) or 1
    for s in scored:
        s["理論勝率"] = round(s["score"] / total_score * 100, 1)

    # 暗示勝率: 1/オッズ × 100
    # オッズ情報は entries から取得（scoredict に格納済み）
    for s in scored:
        odds = s.get("オッズ", 0)
        if odds and odds > 1.0:
            s["暗示勝率"] = round(1 / odds * 100, 1)
        else:
            s["暗示勝率"] = None

    # 妙味指数 = 理論勝率 / 暗示勝率
    for s in scored:
        theo = s["理論勝率"]
        impl = s["暗示勝率"]
        odds = s.get("オッズ", 0)
        if impl and impl > 0:
            vi = round(theo / impl, 2)
            s["妙味指数"] = vi
            if vi >= 1.3:
                s["人気評価"] = "過少人気"
            elif vi <= 0.7:
                s["人気評価"] = "過剰人気"
            else:
                s["人気評価"] = "適正"
        else:
            s["妙味指数"] = None
            s["人気評価"] = "-"
        # 期待値 EV = オッズ × (理論勝率 / 100)
        # EV > 1.0 → 期待値プラス（妙味あり）
        if odds and odds > 1.0 and theo:
            s["期待値"] = round(odds * theo / 100, 2)
        else:
            s["期待値"] = None

    # 印を付与
    marks = ["◎", "◯", "▲", "△", "△"]
    for i, s in enumerate(scored):
        s["印"] = marks[i] if i < len(marks) else ""

    # 買い目生成
    bets = _generate_bets(scored)

    return {
        "ranking": scored,
        "bets": bets,
    }


def _generate_horse_comment(entry: Dict, pace: str) -> str:
    """個別の推奨コメントを生成"""
    style = entry.get("脚質", "不明")
    score = entry.get("score", 0)
    same_course = entry.get("同コース成績", "0-0-0-0")
    c_w, c_2, c_3, c_o = _parse_record(same_course)
    
    comments = []
    
    # ペースとの相性
    if pace == "H":
        if style in ("差し", "追込"):
            comments.append("ハイペース予想で、この馬の決め手が生きる絶好の展開。")
        elif style == "逃げ":
            comments.append("展開は厳しいが、粘り腰を発揮できれば。")
    elif pace == "S":
        if style in ("逃げ", "先行"):
            comments.append("スロー濃厚で前残りの恩恵を受けやすく、押し切りの期待大。")
        elif style in ("差し", "追込"):
            comments.append("展開は不向きだが、上がりの速さでどこまで肉薄できるか。")
    
    # 適性
    if c_w > 0:
        comments.append("同コースでの勝利経験があり、舞台適性は高い。")
    
    # 枠順傾向（簡易）
    waku = entry.get("枠番", 0)
    if waku in (1, 2) and pace == "S":
        comments.append("内枠を活かしてロスなく立ち回れば好勝負可能。")
    
    # 近走
    recent = entry.get("過去走", [])
    if recent:
        first_finish = recent[0].get("着順")
        if isinstance(first_finish, int) and first_finish <= 3:
            comments.append("前走も好走しており、引き続き状態は良さそう。")
            
    if not comments:
        if style != "不明":
            comments.append(f"{style}の脚質を活かして、自分の競馬に持ち込みたい。")
        else:
            comments.append("過去のデータは少ないが、能力的には引けを取らない。")
            
    return "".join(comments[:2]) # 最大2つまで組み合わせて返す


def _generate_bets(ranking: List[Dict]) -> Dict:
    """推奨買い目を生成"""
    if len(ranking) < 2:
        return {}

    honmei = ranking[0]["馬番"]   # ◎
    taikou = ranking[1]["馬番"]   # ◯
    anaume = ranking[2]["馬番"] if len(ranking) > 2 else None  # ▲
    renka = [r["馬番"] for r in ranking[3:5] if r.get("印")]   # △

    top3 = [honmei, taikou]
    if anaume:
        top3.append(anaume)
    top5 = top3 + renka

    bets = {}

    # 単勝
    bets["単勝"] = [{"馬番": honmei, "備考": "本命◎"}]

    # 複勝
    bets["複勝"] = [
        {"馬番": honmei, "備考": "◎"},
        {"馬番": taikou, "備考": "◯"},
    ]
    if anaume:
        bets["複勝"].append({"馬番": anaume, "備考": "▲"})

    # 馬連
    umaren = []
    for partner in [taikou] + ([anaume] if anaume else []) + renka:
        pair = sorted([honmei, partner])
        umaren.append({"馬番": pair, "備考": f"{honmei}-{partner}"})
    bets["馬連"] = umaren

    # ワイド
    wide = []
    pairs_done = set()
    for i, a in enumerate(top3):
        for b in top3[i + 1:]:
            pair = tuple(sorted([a, b]))
            if pair not in pairs_done:
                wide.append({"馬番": list(pair), "備考": f"{pair[0]}-{pair[1]}"})
                pairs_done.add(pair)
    bets["ワイド"] = wide

    # 三連複
    sanrenpuku = []
    if len(top5) >= 3:
        others = top5[2:]
        for o in others:
            trio = sorted([honmei, taikou, o])
            sanrenpuku.append({"馬番": trio, "備考": f"{trio[0]}-{trio[1]}-{trio[2]}"})
        if anaume:
            for o in renka:
                trio = sorted([honmei, anaume, o])
                entry = {"馬番": trio, "備考": f"{trio[0]}-{trio[1]}-{trio[2]}"}
                if entry not in sanrenpuku:
                    sanrenpuku.append(entry)
    bets["三連複"] = sanrenpuku

    return bets

