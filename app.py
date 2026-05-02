# -*- coding: utf-8 -*-
"""
競馬データ収集システム — Webアプリケーション
"""

import json
import os
import time
import traceback
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, jsonify, render_template, request, send_file

from pdf_exporter import generate_pdf

from config import OUTPUT_DIR, TRACK_CODES, TRACK_DIRECTION
from scraper import fetch_horse_history, fetch_race_entries, fetch_odds
from analyzer import (
    calc_horse_summary,
    calc_post_position_trend_from_history,
    estimate_pace,
    estimate_running_style,
    estimate_running_style_detail,
    calc_recommendation,
)

app = Flask(__name__)


@app.route("/manifest.json")
def serve_manifest():
    return send_file("static/manifest.json")


@app.route("/sw.js")
def serve_sw():
    return send_file("static/sw.js", mimetype="application/javascript")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/analyze", methods=["POST"])
def analyze():
    """レースデータ収集・分析API"""
    data = request.get_json()
    race_id = data.get("race_id", "").strip()
    track_override = data.get("track", "").strip()
    surface_override = data.get("surface", "").strip()
    distance_override = data.get("distance", 0)
    race_class = data.get("race_class", "").strip()
    history_n = int(data.get("history_n", 10))

    if not race_id:
        return jsonify({"error": "レースIDを入力してください"}), 400

    try:
        result = run_analysis(
            race_id=race_id,
            track_override=track_override,
            surface_override=surface_override,
            distance_override=distance_override,
            race_class=race_class,
            history_n=history_n,
        )
        return jsonify(result)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"分析中にエラーが発生しました: {str(e)}"}), 500


@app.route("/api/video")
def serve_video():
    """動画ファイルを配信するAPI (デプロイ環境では無効または代替パス)"""
    # ユーザーのデスクトップパスを動的に取得（ローカル環境用）
    user_home = os.path.expanduser("~")
    video_path = os.path.join(user_home, "Desktop", "download.MP4")
    
    if not os.path.exists(video_path):
        # ファイルがない場合は404を返す
        return "Video not found", 404
    return send_file(video_path, mimetype="video/mp4")


# PDF保存ディレクトリの設定（デプロイ環境とローカル環境で切り替え）
PDF_OUTPUT_DIR = os.environ.get("PDF_OUTPUT_DIR", os.path.join(os.getcwd(), "output"))
if not os.path.exists(PDF_OUTPUT_DIR):
    os.makedirs(PDF_OUTPUT_DIR, exist_ok=True)


@app.route("/api/export_pdf", methods=["POST"])
def export_pdf():
    """分析結果をPDFとして保存するAPI"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "データがありません"}), 400
    try:
        filepath = generate_pdf(data, PDF_OUTPUT_DIR)
        filename = os.path.basename(filepath)
        return jsonify({"status": "ok", "filename": filename, "path": filepath})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"PDF生成中にエラーが発生しました: {str(e)}"}), 500


def run_analysis(
    race_id: str,
    track_override: str = "",
    surface_override: str = "",
    distance_override: int = 0,
    race_class: str = "",
    history_n: int = 10,
) -> dict:
    """データ収集・分析パイプラインを実行"""

    steps = []

    # ── STEP 1: 出馬表取得 ──
    steps.append({"step": 1, "name": "出馬表取得", "status": "running"})
    race_info, entries = fetch_race_entries(race_id)

    if not entries:
        return {"error": "出馬表を取得できませんでした。race_idを確認してください。"}

    # オッズ・人気をJSON APIから取得（HTMLページはJS依存で常に---.-/** になるため）
    print(f"[INFO] オッズAPIから取得中 ...")
    odds_map = fetch_odds(race_id)
    if odds_map:
        for e in entries:
            umaban = e.get("馬番", 0)
            if umaban in odds_map:
                e["オッズ"] = odds_map[umaban]["オッズ"]
                # 人気も補完（HTMLからは**になるため）
                if not e.get("人気") and odds_map[umaban].get("人気"):
                    e["人気"] = odds_map[umaban]["人気"]
        print(f"[INFO] オッズ補完完了: {sum(1 for e in entries if e.get('オッズ'))}頭")
    else:
        print("[WARN] オッズAPI取得失敗 — オッズなしで続行")


    # パラメータ補完
    track = track_override or race_info.get("track", "")
    surface = surface_override or race_info.get("surface", "")
    distance = distance_override or race_info.get("distance", 0)
    race_date = datetime.now().strftime("%Y-%m-%d")
    race_name = race_info.get("race_name", "")
    track_condition = race_info.get("track_condition", "")
    direction = TRACK_DIRECTION.get(track, "")

    steps[-1]["status"] = "done"

    # ── STEP 2: 各馬の過去成績取得（並列化） ──
    steps.append({"step": 2, "name": "過去成績取得", "status": "running"})
    all_history = {}
    quality_issues = []

    def fetch_single_horse(idx_entry):
        i, entry = idx_entry
        horse_name = entry.get("馬名", f"馬{i+1}")
        horse_id = entry.get("horse_id", "")
        if not horse_id:
            return horse_name, [], f"{horse_name}: horse_id不明"
        try:
            history = fetch_horse_history(horse_id, n=history_n)
            return horse_name, history, None
        except Exception as e:
            return horse_name, [], f"{horse_name}: 過去成績取得エラー - {str(e)}"

    # 並列実行 (最大8スレッド)
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(fetch_single_horse, enumerate(entries)))

    for horse_name, history, error in results:
        all_history[horse_name] = history
        if error:
            quality_issues.append(error)

    steps[-1]["status"] = "done"

    # ── STEP 3: 脚質推定 & サマリー ──
    steps.append({"step": 3, "name": "分析", "status": "running"})
    horse_summaries = []
    entries_with_style = []

    for entry in entries:
        horse_name = entry.get("馬名", "")
        history = all_history.get(horse_name, [])
        summary = calc_horse_summary(entry, history, track, surface, distance)
        horse_summaries.append(summary)
        entries_with_style.append({
            "馬名": horse_name,
            "脚質": summary.get("脚質", "不明"),
        })

    steps[-1]["status"] = "done"

    # ── STEP 4: 枠順傾向 ──
    steps.append({"step": 4, "name": "枠順傾向集計", "status": "running"})
    post_trend = {}
    if track and surface and distance and all_history:
        trend_data = calc_post_position_trend_from_history(
            all_history=all_history,
            track=track,
            surface=surface,
            distance=distance,
        )
        if trend_data.get("対象走数", 0) < 10:
            trend_data = calc_post_position_trend_from_history(
                all_history=all_history,
                track=track,
                surface=surface,
                distance=distance,
                distance_tolerance=200,
            )
        post_trend = trend_data

    steps[-1]["status"] = "done"

    # ── STEP 5: 展開推定 ──
    steps.append({"step": 5, "name": "展開推定", "status": "running"})
    pace_info = estimate_pace(entries_with_style)
    steps[-1]["status"] = "done"

    # ── STEP 6: 推奨馬・買い目生成 ──
    steps.append({"step": 6, "name": "推奨馬分析", "status": "running"})
    # entries_out を作成する前に必要なデータを準備
    temp_entries_for_rec = []
    for i, entry in enumerate(entries):
        horse_name = entry.get("馬名", "")
        summary = horse_summaries[i] if i < len(horse_summaries) else {}
        history = all_history.get(horse_name, [])
        
        # calc_recommendation に必要な情報を付加
        e_copy = entry.copy()
        e_copy.update(summary)
        e_copy["過去走"] = history
        temp_entries_for_rec.append(e_copy)

    recommendation = calc_recommendation(temp_entries_for_rec, pace_info, post_trend)
    steps[-1]["status"] = "done"

    # ── 結果構築 ──
    entries_out = []
    ranking_map = {r["馬番"]: r for r in recommendation.get("ranking", [])}
    for i, entry in enumerate(entries):
        horse_name = entry.get("馬名", "")
        summary = horse_summaries[i] if i < len(horse_summaries) else {}
        history = all_history.get(horse_name, [])
        rec_row = ranking_map.get(entry.get("馬番", 0), {})

        entries_out.append({
            "馬番": entry.get("馬番", 0),
            "枠番": entry.get("枠番", 0),
            "馬名": horse_name,
            "性齢": entry.get("性齢", ""),
            "騎手": entry.get("騎手", ""),
            "斤量": entry.get("斤量", 0),
            "馬体重": entry.get("馬体重", ""),
            "人気": entry.get("人気", 0),
            "オッズ": entry.get("オッズ", 0),
            "脚質": summary.get("脚質", "不明"),
            "平均上がり3F": summary.get("平均上がり3F", 0),
            "最速上がり3F": summary.get("最速上がり3F", 0),
            "平均着順": summary.get("平均着順", 0),
            "戦数": summary.get("戦数", 0),
            "勝率": summary.get("勝率", 0),
            "連対率": summary.get("連対率", 0),
            "複勝率": summary.get("複勝率", 0),
            "同コース成績": summary.get("同コース成績", ""),
            "同距離成績": summary.get("同距離成績", ""),
            "コメント": rec_row.get("comment", ""),
            # 指数情報
            "指数": rec_row.get("score", 0),
            "自信度": rec_row.get("confidence", 0),
            # 妙味情報
            "理論勝率": rec_row.get("理論勝率"),
            "暗示勝率": rec_row.get("暗示勝率"),
            "妙味指数": rec_row.get("妙味指数"),
            "期待値": rec_row.get("期待値"),
            "人気評価": rec_row.get("人気評価", "-"),
            "過去走": [
                {
                    "開催日": r.get("開催日", ""),
                    "競馬場": r.get("競馬場", ""),
                    "レース名": r.get("レース名", ""),
                    "距離": r.get("距離", 0),
                    "馬場": r.get("馬場", ""),
                    "着順": r.get("着順", ""),
                    "タイム": r.get("タイム", ""),
                    "上がり3F": r.get("上がり3F", 0),
                    "通過順位": r.get("通過順位", ""),
                    "人気": r.get("人気", 0),
                }
                for r in history[:5]
            ],
        })

    return {
        "race_id": race_id,
        "race_name": race_name,
        "date": race_date,
        "track": track,
        "surface": surface,
        "distance": distance,
        "race_class": race_class,
        "track_condition": track_condition,
        "direction": direction,
        "entries": entries_out,
        "pace_estimate": pace_info,
        "post_position_trend": post_trend,
        "recommendation": recommendation,
        "quality_issues": quality_issues,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
