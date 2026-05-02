# -*- coding: utf-8 -*-
"""
競馬データ収集システム — メインスクリプト

Usage:
    python collect_race_data.py --race_id 202505020811 --track 東京 --surface 芝 --distance 1600 --race_class G1
    python collect_race_data.py --race_id 202505020811   (track/surface/distanceは出馬表から自動取得)
"""

import argparse
import csv
import json
import os
import sys
import traceback
from datetime import datetime

from config import OUTPUT_DIR, TRACK_DIRECTION
from scraper import (
    fetch_horse_history,
    fetch_race_entries,
)
from analyzer import (
    calc_course_fitness,
    calc_horse_summary,
    calc_post_position_trend_from_history,
    estimate_pace,
    estimate_running_style,
    estimate_running_style_detail,
)


def main():
    parser = argparse.ArgumentParser(description="競馬データ収集システム")
    parser.add_argument("--race_id", type=str, required=True, help="レースID (例: 202505020811)")
    parser.add_argument("--track", type=str, default="", help="競馬場 (例: 東京)")
    parser.add_argument("--surface", type=str, default="", help="芝/ダート")
    parser.add_argument("--distance", type=int, default=0, help="距離 (例: 1600)")
    parser.add_argument("--race_class", type=str, default="", help="クラス (G1/G2/G3/OP/3勝/2勝/1勝/新馬/未勝利)")
    parser.add_argument("--race_date", type=str, default="", help="開催日 (YYYY-MM-DD)")
    parser.add_argument("--history_n", type=int, default=10, help="過去走数 (デフォルト: 10)")
    parser.add_argument("--past_years", type=int, default=3, help="過去レース検索年数 (デフォルト: 3)")
    args = parser.parse_args()

    # 出力ディレクトリ作成
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # データ品質レポート用
    quality_issues = []

    print("=" * 60)
    print("競馬データ収集システム")
    print("=" * 60)

    # ─────────────────────────────────────────────
    # STEP 1: 出馬表取得
    # ─────────────────────────────────────────────
    print("\n[STEP 1] 出馬表取得...")
    race_info, entries = fetch_race_entries(args.race_id)

    if not entries:
        print("[ERROR] 出馬表を取得できませんでした。")
        print("  → race_id を確認してください。")
        quality_issues.append("出馬表: 取得失敗 - race_idが無効または出馬表未発表")
        # データが0でも続行（空の出力ファイルを生成）

    # パラメータ補完（出馬表から取得 or CLI引数優先）
    track = args.track or race_info.get("track", "")
    surface = args.surface or race_info.get("surface", "")
    distance = args.distance or race_info.get("distance", 0)
    race_class = args.race_class
    race_date = args.race_date or datetime.now().strftime("%Y-%m-%d")
    race_name = race_info.get("race_name", "")
    track_condition = race_info.get("track_condition", "")

    print(f"\n  レース: {race_name}")
    print(f"  条件: {track} {surface}{distance}m {race_class}")
    print(f"  馬場: {track_condition}")
    print(f"  出走頭数: {len(entries)}")

    if not track:
        quality_issues.append("競馬場: 未取得 - CLI引数で指定してください")
    if not surface:
        quality_issues.append("芝/ダート: 未取得 - CLI引数で指定してください")
    if not distance:
        quality_issues.append("距離: 未取得 - CLI引数で指定してください")

    # ─────────────────────────────────────────────
    # STEP 2: 各馬の過去成績取得
    # ─────────────────────────────────────────────
    print(f"\n[STEP 2] 各馬の過去成績取得 ({len(entries)}頭 × 最大{args.history_n}走)...")
    all_history = {}   # {馬名: [race_records]}

    for i, entry in enumerate(entries):
        horse_name = entry.get("馬名", f"馬{i+1}")
        horse_id = entry.get("horse_id", "")

        if not horse_id:
            print(f"  [{i+1}/{len(entries)}] {horse_name}: horse_id不明 → スキップ")
            quality_issues.append(f"{horse_name}: horse_id不明のため過去成績取得不可")
            all_history[horse_name] = []
            continue

        print(f"  [{i+1}/{len(entries)}] {horse_name} (ID: {horse_id})")
        try:
            history = fetch_horse_history(horse_id, n=args.history_n)
            all_history[horse_name] = history
            if not history:
                quality_issues.append(f"{horse_name}: 過去成績テーブルが見つからない")
        except Exception as e:
            print(f"    [ERROR] {e}")
            quality_issues.append(f"{horse_name}: 過去成績取得エラー - {str(e)}")
            all_history[horse_name] = []

    # ─────────────────────────────────────────────
    # STEP 3: 脚質推定 & サマリー計算
    # ─────────────────────────────────────────────
    print(f"\n[STEP 3] 脚質推定 & サマリー計算...")
    horse_summaries = []
    entries_with_style = []

    for entry in entries:
        horse_name = entry.get("馬名", "")
        history = all_history.get(horse_name, [])

        # サマリー計算
        summary = calc_horse_summary(entry, history, track, surface, distance)
        horse_summaries.append(summary)

        # 展開推定用
        entries_with_style.append({
            "馬名": horse_name,
            "馬番": entry.get("馬番", 0),
            "枠番": entry.get("枠番", 0),
            "脚質": summary["脚質"],
        })

        print(f"  {entry.get('馬番', '?')}. {horse_name}: {summary['脚質']} "
              f"(上がり平均 {summary['平均上がり3F']})")

    # ─────────────────────────────────────────────
    # STEP 4: 枠順傾向集計（既取得の過去成績ベース）
    # ─────────────────────────────────────────────
    post_trend = {}

    if track and surface and distance and all_history:
        print(f"\n[STEP 4] 枠順傾向集計 ({track} {surface}{distance}m)...")
        try:
            # まず完全一致で検索
            trend_data = calc_post_position_trend_from_history(
                all_history=all_history,
                track=track,
                surface=surface,
                distance=distance,
            )
            matched_count = trend_data["対象走数"]

            # データ不足なら距離±200mに拡大して再検索
            if matched_count < 10:
                print(f"  完全一致: {matched_count}走 (不足) → 距離±200m に拡大")
                trend_data = calc_post_position_trend_from_history(
                    all_history=all_history,
                    track=track,
                    surface=surface,
                    distance=distance,
                    distance_tolerance=200,
                )
                matched_count = trend_data["対象走数"]

            post_trend = trend_data
            n_races = trend_data.get("対象レース数(推定)", 0)
            print(f"  → {n_races}レース {matched_count}走から枠順傾向を集計")

            if matched_count == 0:
                quality_issues.append("枠順傾向: 同条件の過去走データが不足")
        except Exception as e:
            print(f"  [ERROR] 枠順傾向集計失敗: {e}")
            quality_issues.append(f"枠順傾向集計: エラー - {str(e)}")
    else:
        print(f"\n[STEP 4] 条件不足のため枠順傾向集計をスキップ")
        quality_issues.append("枠順傾向: 条件不足(track/surface/distance)でスキップ")

    # ─────────────────────────────────────────────
    # STEP 5: 展開推定
    # ─────────────────────────────────────────────
    print(f"\n[STEP 5] 展開推定...")
    pace_info = estimate_pace(entries_with_style)
    print(f"  ペース予想: {pace_info['pace']} ({pace_info['reason']})")
    print(f"  逃げ候補: {', '.join(pace_info['逃げ候補']) if pace_info['逃げ候補'] else 'なし'}")

    # ─────────────────────────────────────────────
    # STEP 6: ファイル出力
    # ─────────────────────────────────────────────
    print(f"\n[STEP 6] ファイル出力...")

    # ── A) race_context.json ──
    race_context = {
        "race_id": args.race_id,
        "race_name": race_name,
        "date": race_date,
        "track": track,
        "surface": surface,
        "distance": distance,
        "race_class": race_class,
        "track_condition": track_condition,
        "direction": TRACK_DIRECTION.get(track, ""),
        "entries": [
            {
                "馬番": e.get("馬番", 0),
                "枠番": e.get("枠番", 0),
                "馬名": e.get("馬名", ""),
                "性齢": e.get("性齢", ""),
                "騎手": e.get("騎手", ""),
                "斤量": e.get("斤量", 0),
                "馬体重": e.get("馬体重", ""),
                "人気": e.get("人気", 0),
                "オッズ": e.get("オッズ", 0),
            }
            for e in entries
        ],
        "pace_estimate": pace_info,
        "post_position_trend": post_trend,
        "data_generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    ctx_path = os.path.join(OUTPUT_DIR, "race_context.json")
    with open(ctx_path, "w", encoding="utf-8") as f:
        json.dump(race_context, f, ensure_ascii=False, indent=2)
    print(f"  [OK] {ctx_path}")

    # ── B) horse_history.csv ──
    history_path = os.path.join(OUTPUT_DIR, "horse_history.csv")
    history_columns = [
        "馬名", "horse_id", "開催日", "競馬場", "レース名", "芝ダート", "距離",
        "馬場", "着順", "タイム", "上がり3F", "通過順位", "枠番", "馬番",
        "斤量", "騎手", "人気", "オッズ", "頭数", "着差", "馬体重",
    ]
    with open(history_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=history_columns, extrasaction="ignore")
        writer.writeheader()
        for entry in entries:
            horse_name = entry.get("馬名", "")
            horse_id = entry.get("horse_id", "")
            for race in all_history.get(horse_name, []):
                row = dict(race)
                row["馬名"] = horse_name
                row["horse_id"] = horse_id
                writer.writerow(row)
    print(f"  [OK] {history_path}")

    # ── C) horse_summary.csv ──
    summary_path = os.path.join(OUTPUT_DIR, "horse_summary.csv")
    summary_columns = [
        "馬名", "枠番", "馬番", "騎手", "斤量", "脚質",
        "逃げ回数", "先行回数", "差し回数", "追込回数",
        "平均上がり3F", "最速上がり3F", "平均着順", "戦数",
        "勝率", "連対率", "複勝率",
        "同コース成績", "同距離成績", "距離延長成績", "距離短縮成績",
    ]
    with open(summary_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=summary_columns, extrasaction="ignore")
        writer.writeheader()
        for s in horse_summaries:
            writer.writerow(s)
    print(f"  [OK] {summary_path}")

    # ── D) data_quality_report.txt ──
    report_path = os.path.join(OUTPUT_DIR, "data_quality_report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("=" * 60 + "\n")
        f.write("データ品質レポート\n")
        f.write(f"生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"レースID: {args.race_id}\n")
        f.write(f"レース: {race_name} ({track} {surface}{distance}m {race_class})\n")
        f.write("=" * 60 + "\n\n")

        # 取得状況サマリー
        total_horses = len(entries)
        horses_with_history = sum(1 for h in all_history.values() if h)
        total_races = sum(len(h) for h in all_history.values())
        f.write(f"【取得状況サマリー】\n")
        f.write(f"  出走馬数: {total_horses}\n")
        f.write(f"  過去成績取得成功: {horses_with_history}/{total_horses}\n")
        f.write(f"  取得レース数合計: {total_races}\n")
        f.write(f"  枠順傾向データ: {post_trend.get('対象走数', 0)}走\n\n")

        if quality_issues:
            f.write(f"【欠損・問題項目 ({len(quality_issues)}件)】\n")
            for i, issue in enumerate(quality_issues, 1):
                f.write(f"  {i}. {issue}\n")
        else:
            f.write("【欠損・問題項目】\n  なし — 全データ正常取得\n")

        # 馬別の取得状況
        f.write(f"\n【馬別取得状況】\n")
        for entry in entries:
            name = entry.get("馬名", "?")
            hid = entry.get("horse_id", "なし")
            races = all_history.get(name, [])
            agari_count = sum(1 for r in races if r.get("上がり3F", 0) > 0)
            pass_count = sum(1 for r in races if r.get("通過順位", ""))
            f.write(f"  {entry.get('馬番', '?'):>2}. {name:<12} "
                    f"ID:{hid:<12} 過去走:{len(races):>2} "
                    f"上がり3F:{agari_count:>2} 通過順位:{pass_count:>2}\n")

    print(f"  [OK] {report_path}")

    # ─────────────────────────────────────────────
    # 完了
    # ─────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("[OK] データ収集完了!")
    print(f"  出力先: {OUTPUT_DIR}")
    print(f"  - race_context.json  (レース全体情報)")
    print(f"  - horse_history.csv  ({total_races}走分の過去成績)")
    print(f"  - horse_summary.csv  ({total_horses}頭の集計)")
    print(f"  - data_quality_report.txt")
    if quality_issues:
        print(f"  [!] {len(quality_issues)}件の欠損・問題あり (詳細は data_quality_report.txt)")
    print("=" * 60)


if __name__ == "__main__":
    main()
