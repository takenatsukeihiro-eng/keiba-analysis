# -*- coding: utf-8 -*-
"""
競馬データ収集システム — netkeiba スクレイパー
"""

import re
import time
import traceback
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

from config import (
    HORSE_RESULT_URL,
    HORSE_TOP_URL,
    ODDS_API_URL,
    ODDS_URL,
    RACE_RESULT_URL,
    REQUEST_DELAY,
    REQUEST_HEADERS,
    REQUEST_TIMEOUT,
    SHUTUBA_URL,
    TRACK_CODES,
    TRACK_NAME_TO_CODE,
)

# 共通セッションの作成
session = requests.Session()
session.headers.update(REQUEST_HEADERS)

# ============================================================
# ユーティリティ
# ============================================================

def _get(url: str) -> Optional[BeautifulSoup]:
    """URLからHTMLを取得してBeautifulSoupオブジェクトを返す"""
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.encoding = resp.apparent_encoding or "euc-jp"
        if resp.status_code == 200:
            return BeautifulSoup(resp.text, "html.parser")
        print(f"  [WARN] HTTP {resp.status_code}: {url}")
        # 403エラー（アクセス拒否）などの場合は情報を残す
        if resp.status_code == 403:
            print("  [ERROR] アクセスが拒否されました (403 Forbidden)。制限を受けている可能性があります。")
    except Exception as e:
        print(f"  [ERROR] {e}: {url}")
    return None


def _safe_int(text: str, default: int = 0) -> int:
    """文字列から安全に int 変換"""
    if not text:
        return default
    text = text.strip().replace(",", "")
    m = re.search(r"\d+", text)
    return int(m.group()) if m else default


def _safe_float(text: str, default: float = 0.0) -> float:
    """文字列から安全に float 変換"""
    if not text:
        return default
    text = text.strip().replace(",", "")
    m = re.search(r"[\d.]+", text)
    return float(m.group()) if m else default


def _clean(text: str) -> str:
    """テキストのクリーニング"""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


# ============================================================
# 単勝オッズ取得（専用オッズページ）
# ============================================================

def fetch_odds(race_id: str) -> Dict[int, Dict]:
    """
    netkeiba の JSON API から単勝オッズ・人気を取得。
    Returns: {馬番(int): {"オッズ": float, "人気": int}, ...}
    出馬表でオッズが取得できなかった場合のフォールバックとして使用。
    """
    import json as _json

    url = ODDS_API_URL.format(race_id=race_id)
    print(f"  [INFO] オッズAPI取得: {url}")
    time.sleep(REQUEST_DELAY)

    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            print(f"  [WARN] オッズAPI HTTP {resp.status_code}")
            return {}
        data = resp.json()
    except Exception as e:
        print(f"  [ERROR] オッズAPI取得失敗: {e}")
        return {}

    # data["data"]["odds"]["1"] = {"01": ["3.5", "", "2"], "02": [...], ...}
    odds_raw = data.get("data", {}).get("odds", {}).get("1", {})
    if not odds_raw:
        print("  [WARN] オッズAPIにデータなし")
        return {}

    odds_map: Dict[int, Dict] = {}
    for umaban_str, values in odds_raw.items():
        try:
            umaban = int(umaban_str)
            odds_val = float(values[0]) if values[0] else 0.0
            ninki_val = int(values[2]) if len(values) > 2 and values[2] else 0
            if odds_val > 0:
                odds_map[umaban] = {"オッズ": odds_val, "人気": ninki_val}
        except (ValueError, IndexError):
            pass

    print(f"  → オッズ取得: {len(odds_map)}頭")
    return odds_map


# ============================================================
# 出馬表取得
# ============================================================

def fetch_race_entries(race_id: str) -> Tuple[Dict, List[Dict]]:
    """
    出馬表を取得して (race_info, entries) を返す。
    race_info: レース名、条件等
    entries:   各馬の基本情報リスト
    """
    url = SHUTUBA_URL.format(race_id=race_id)
    print(f"[INFO] 出馬表取得: {url}")
    soup = _get(url)
    if not soup:
        return {}, []

    # レース情報
    race_info = {"race_id": race_id}

    # レース名
    race_name_tag = soup.select_one(".RaceName")
    if race_name_tag:
        race_info["race_name"] = _clean(race_name_tag.get_text())

    # レース条件（芝/ダート、距離、etc）
    race_data_tag = soup.select_one(".RaceData01")
    if race_data_tag:
        text = _clean(race_data_tag.get_text())
        race_info["race_data01"] = text
        # 芝/ダート
        if "芝" in text:
            race_info["surface"] = "芝"
        elif "ダート" in text or "ダ" in text:
            race_info["surface"] = "ダート"
        # 距離
        dist_m = re.search(r"(\d{3,5})m", text)
        if dist_m:
            race_info["distance"] = int(dist_m.group(1))
        # 馬場状態
        cond_m = re.search(r"(良|稍重|重|不良)", text)
        if cond_m:
            race_info["track_condition"] = cond_m.group(1)

    race_data2_tag = soup.select_one(".RaceData02")
    if race_data2_tag:
        text2 = _clean(race_data2_tag.get_text())
        race_info["race_data02"] = text2
        # 競馬場
        for code, name in TRACK_CODES.items():
            if name in text2:
                race_info["track"] = name
                break

    # 出馬表パース
    # テーブル構造（netkeiba 出馬表 Shutuba_Table）:
    #   td[0]: 枠番 (class=WakuN)
    #   td[1]: 馬番 (class=UmabanN)
    #   td[2]: チェックマーク (class=CheckMark) — スキップ
    #   td[3]: 馬名 (class=HorseInfo)
    #   td[4]: 性齢 (class=Barei) — 「牡6」等
    #   td[5]: 斤量 (class=Txt_C) — 「53.0」等
    #   td[6]: 騎手 (class=Jockey)
    #   td[7]: 調教師 (class=Trainer)
    #   td[8]: 馬体重 (class=Weight) — 「496(+2)」形式
    #   td[9]: オッズ (class=Txt_R Popular) — 「---.-」or「3.5」
    #   td[10]: 人気 (class=Popular Popular_Ninki) — 「**」or「1」
    entries = []
    rows = soup.select("table.Shutuba_Table tr.HorseList, table.ShutubaTable tr.HorseList")
    if not rows:
        rows = soup.select("table tr[id^='tr_']")

    for row in rows:
        tds = row.select("td")
        # ゴーストエントリー除外: 馬データ行は通常10+個のtdを持つ
        if len(tds) < 7:
            continue

        entry = {}

        # 枠番 (td[0]) — クラス名は Waku1, Waku2 等
        waku_td = row.select_one("td[class*='Waku']")
        entry["枠番"] = _safe_int(waku_td.get_text()) if waku_td else 0

        # 馬番 (td[1]) — クラス名は Umaban1, Umaban2 等
        umaban_td = row.select_one("td[class*='Umaban']")
        entry["馬番"] = _safe_int(umaban_td.get_text()) if umaban_td else 0

        # 馬番が0の行はデータ行でないのでスキップ
        if entry["馬番"] == 0:
            continue

        # 馬名 & horse_id (td[3])
        horse_link = row.select_one("td.HorseInfo a, span.HorseName a")
        if horse_link:
            entry["馬名"] = _clean(horse_link.get_text())
            href = horse_link.get("href", "")
            hid_m = re.search(r"/horse/(\d+)", href)
            if hid_m:
                entry["horse_id"] = hid_m.group(1)
        else:
            horse_td = row.select_one("td.HorseInfo")
            entry["馬名"] = _clean(horse_td.get_text()) if horse_td else ""

        # 性齢 (td[4] class=Barei)
        barei_td = row.select_one("td.Barei")
        if barei_td:
            entry["性齢"] = _clean(barei_td.get_text())

        # 斤量 (td[5]) — Bareiの直後のtd
        # Bareiの次のsibling tdを取得
        if barei_td:
            kinryou_td = barei_td.find_next_sibling("td")
            if kinryou_td:
                entry["斤量"] = _safe_float(kinryou_td.get_text())
        elif len(tds) > 5:
            entry["斤量"] = _safe_float(tds[5].get_text())

        # 騎手 (td[6])
        jockey_link = row.select_one("td.Jockey a")
        if jockey_link:
            entry["騎手"] = _clean(jockey_link.get_text())
        else:
            jockey_td = row.select_one("td.Jockey")
            entry["騎手"] = _clean(jockey_td.get_text()) if jockey_td else ""

        # 馬体重 (td[8] class=Weight)
        weight_td = row.select_one("td.Weight")
        if weight_td:
            entry["馬体重"] = _clean(weight_td.get_text())

        # オッズ (td[9] class=Txt_R + Popular)
        odds_td = row.select_one("td.Txt_R.Popular")
        if odds_td:
            odds_text = _clean(odds_td.get_text())
            if odds_text and odds_text not in ("---.-", "---"):
                entry["オッズ"] = _safe_float(odds_text)

        # 人気 (td[10] class=Popular_Ninki)
        ninki_td = row.select_one("td.Popular_Ninki")
        if ninki_td:
            ninki_text = _clean(ninki_td.get_text())
            if ninki_text and ninki_text != "**":
                entry["人気"] = _safe_int(ninki_text)

        if entry.get("馬名"):
            entries.append(entry)

    print(f"  → {len(entries)} 頭取得")
    return race_info, entries


# ============================================================
# 馬の過去成績取得
# ============================================================

def fetch_horse_history(horse_id: str, n: int = 10) -> List[Dict]:
    """
    馬の過去成績をN走分取得。
    db.netkeiba.com/horse/result/{horse_id}/ の静的HTMLテーブルをパースする。
    """
    # 成績テーブルは /horse/result/ にのみ存在する
    url = HORSE_RESULT_URL.format(horse_id=horse_id)
    print(f"  [INFO] 過去成績取得: {horse_id}")
    time.sleep(REQUEST_DELAY)

    soup = _get(url)
    if not soup:
        print(f"    [WARN] 過去成績ページが取得できませんでした (403/404?): {horse_id}")
        # フォールバック: トップページ
        url2 = HORSE_TOP_URL.format(horse_id=horse_id)
        soup = _get(url2)
        if not soup:
            print(f"    [WARN] 馬トップページも取得できませんでした: {horse_id}")
            return []

    # 成績テーブルを探す
    perf_table = (
        soup.find("table", {"summary": "全競走成績"}) or 
        soup.select_one("table.db_h_race_results") or 
        soup.select_one("table[class*='result']")
    )
    if not perf_table:
        # テーブルIDで探す
        perf_table = soup.select_one("#contents table.nk_tb_common")
        if not perf_table:
            tables = soup.select("table")
            for t in tables:
                headers = [_clean(th.get_text()) for th in t.select("th")]
                if "着順" in headers and "競馬場" in headers:
                    perf_table = t
                    break
    if not perf_table:
        print(f"    [WARN] 成績テーブルが見つかりません: {horse_id} (ページ内容が期待と異なるか、アクセス制限の可能性があります)")
        return []

    # ヘッダー取得
    header_row = perf_table.select("tr")[0] if perf_table.select("tr") else None
    if not header_row:
        return []

    headers = [_clean(th.get_text()) for th in header_row.select("th, td")]

    # データ行パース
    results = []
    data_rows = perf_table.select("tr")[1:]
    for row in data_rows[:n]:
        cells = row.select("td")
        if len(cells) < 5:
            continue

        record = {}
        cell_texts = [_clean(c.get_text()) for c in cells]

        # ヘッダーベースでマッピング
        for i, h in enumerate(headers):
            if i < len(cell_texts):
                val = cell_texts[i]
                if h in ("日付", "開催日"):
                    record["開催日"] = val
                elif h in ("開催", "競馬場"):
                    # "5東京3" のようなフォーマットから競馬場名を抽出
                    track_match = re.search(r"(札幌|函館|福島|新潟|東京|中山|中京|京都|阪神|小倉)", val)
                    record["競馬場"] = track_match.group(1) if track_match else val
                elif h == "天気":
                    record["天気"] = val
                elif h in ("R", "レース番号"):
                    record["R"] = val
                elif h in ("レース名",):
                    record["レース名"] = val
                elif h in ("映像",):
                    pass  # skip
                elif h in ("頭数",):
                    record["頭数"] = _safe_int(val)
                elif h in ("枠番", "枠"):
                    record["枠番"] = _safe_int(val)
                elif h in ("馬番",):
                    record["馬番"] = _safe_int(val)
                elif h in ("オッズ",):
                    record["オッズ"] = _safe_float(val)
                elif h in ("人気",):
                    record["人気"] = _safe_int(val)
                elif h in ("着順",):
                    record["着順"] = _safe_int(val) if val.isdigit() else val
                elif h in ("騎手",):
                    # リンクからも取得試行
                    link = cells[i].select_one("a") if i < len(cells) else None
                    record["騎手"] = _clean(link.get_text()) if link else val
                elif h in ("斤量",):
                    record["斤量"] = _safe_float(val)
                elif h in ("距離",):
                    # "芝1600" or "ダ1200" 形式
                    if val:
                        if val.startswith("芝"):
                            record["芝ダート"] = "芝"
                            record["距離"] = _safe_int(val[1:])
                        elif val.startswith("ダ"):
                            record["芝ダート"] = "ダート"
                            record["距離"] = _safe_int(val[1:])
                        else:
                            record["距離"] = _safe_int(val)
                elif h in ("馬場",):
                    record["馬場"] = val
                elif h in ("馬場指数", "馬場差"):
                    pass
                elif h in ("タイム", "走破タイム"):
                    record["タイム"] = val
                elif h in ("着差",):
                    record["着差"] = val
                elif h in ("ﾀｲﾑ指数", "タイム指数"):
                    pass
                elif h in ("通過",):
                    record["通過順位"] = val
                elif h in ("ペース",):
                    record["ペース"] = val
                elif h in ("上り", "上がり", "上がり3F"):
                    record["上がり3F"] = _safe_float(val)
                elif h in ("馬体重",):
                    record["馬体重"] = val
                elif h in ("勝ち馬", "勝ち馬(2着馬)"):
                    record["勝ち馬"] = val
                elif h in ("賞金",):
                    record["賞金"] = val

        if record.get("開催日") or record.get("着順"):
            results.append(record)

    print(f"    → {len(results)} 走取得")
    return results


# ============================================================
# レース結果取得（同条件過去レース）
# ============================================================

def fetch_race_result(race_id: str) -> List[Dict]:
    """
    レース結果ページから全馬の結果を取得。
    """
    url = RACE_RESULT_URL.format(race_id=race_id)
    time.sleep(REQUEST_DELAY)
    soup = _get(url)
    if not soup:
        return []

    results = []
    result_table = soup.select_one("table.race_table_01, table[class*='result']")
    if not result_table:
        tables = soup.select("table")
        for t in tables:
            ths = [_clean(th.get_text()) for th in t.select("th")]
            if "着順" in ths:
                result_table = t
                break
    if not result_table:
        return []

    header_row = result_table.select("tr")[0]
    headers = [_clean(th.get_text()) for th in header_row.select("th, td")]

    for row in result_table.select("tr")[1:]:
        cells = row.select("td")
        if len(cells) < 5:
            continue
        cell_texts = [_clean(c.get_text()) for c in cells]
        record = {}
        for i, h in enumerate(headers):
            if i < len(cell_texts):
                val = cell_texts[i]
                if h in ("着順",):
                    record["着順"] = _safe_int(val) if val.isdigit() else val
                elif h in ("枠番", "枠"):
                    record["枠番"] = _safe_int(val)
                elif h in ("馬番",):
                    record["馬番"] = _safe_int(val)
                elif h in ("馬名",):
                    link = cells[i].select_one("a") if i < len(cells) else None
                    record["馬名"] = _clean(link.get_text()) if link else val
                elif h in ("性齢",):
                    record["性齢"] = val
                elif h in ("斤量",):
                    record["斤量"] = _safe_float(val)
                elif h in ("騎手",):
                    link = cells[i].select_one("a") if i < len(cells) else None
                    record["騎手"] = _clean(link.get_text()) if link else val
                elif h in ("タイム",):
                    record["タイム"] = val
                elif h in ("着差",):
                    record["着差"] = val
                elif h in ("通過",):
                    record["通過順位"] = val
                elif h in ("上り", "上がり", "上がり3F"):
                    record["上がり3F"] = _safe_float(val)
                elif h in ("人気",):
                    record["人気"] = _safe_int(val)
                elif h in ("単勝",):
                    record["オッズ"] = _safe_float(val)
                elif h in ("馬体重",):
                    record["馬体重"] = val
        if record:
            results.append(record)

    return results


# ============================================================
# 同条件の過去レース検索
# ============================================================

def search_past_races(
    track: str,
    surface: str,
    distance: int,
    race_class: str = "",
    years: int = 3,
) -> List[Dict]:
    """
    db.netkeiba.com の検索機能で同条件の過去レースを探す。
    返却: [{race_id, race_name, date, track, ...}, ...]
    """
    from datetime import datetime, timedelta

    current_year = datetime.now().year
    start_year = current_year - years

    # 競馬場コード
    track_code = TRACK_NAME_TO_CODE.get(track, "")

    # コース種別パラメータ
    if surface in ("芝", "turf"):
        surface_param = "1"
    elif surface in ("ダート", "ダ", "dirt"):
        surface_param = "2"
    else:
        surface_param = ""

    found_races = []

    for year in range(start_year, current_year + 1):
        url = (
            f"https://db.netkeiba.com/race/list/"
            f"?pid=race_list"
            f"&start_year={year}&end_year={year}"
            f"&jyo%5B%5D={track_code}"
            f"&kyori_min={distance}&kyori_max={distance}"
            f"&track%5B%5D={surface_param}"
        )
        # クラスフィルタ（取得可能な場合）
        # netkeibaの検索パラメータはグレード指定が複雑なため、結果をフィルタリングする

        print(f"  [INFO] 過去レース検索 ({year}): {track} {surface} {distance}m")
        time.sleep(REQUEST_DELAY)
        soup = _get(url)
        if not soup:
            continue

        # レースリストのパース
        race_links = soup.select("a[href*='/race/']")
        for link in race_links:
            href = link.get("href", "")
            rid_m = re.search(r"/race/(\d{12})/", href)
            if not rid_m:
                continue
            rid = rid_m.group(1)
            rname = _clean(link.get_text())
            if not rname or rname in ("レース結果", "結果"):
                continue

            # クラスフィルタリング
            if race_class:
                class_match = False
                from config import CLASS_KEYWORDS
                keywords = CLASS_KEYWORDS.get(race_class, [race_class])
                for kw in keywords:
                    if kw in rname:
                        class_match = True
                        break
                # クラスフィルタが厳密に一致しない場合でも追加
                # （後段でフィルタ可能）

            # 日付を推定（race_idから）
            # race_id形式: YYYYJJKKDD RR (年+場番+回次+日+R番号)
            race_year = rid[:4]

            found_races.append({
                "race_id": rid,
                "race_name": rname,
                "year": race_year,
                "track": track,
                "surface": surface,
                "distance": distance,
            })

    # 重複排除
    seen = set()
    unique = []
    for r in found_races:
        if r["race_id"] not in seen:
            seen.add(r["race_id"])
            unique.append(r)

    print(f"  → 過去レース {len(unique)} 件発見")
    return unique


# ============================================================
# メインテスト
# ============================================================

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        rid = sys.argv[1]
        info, entries = fetch_race_entries(rid)
        print(f"\n=== レース情報 ===")
        for k, v in info.items():
            print(f"  {k}: {v}")
        print(f"\n=== 出走馬 ({len(entries)}頭) ===")
        for e in entries:
            print(f"  {e.get('馬番', '?')}. {e.get('馬名', '?')} ({e.get('騎手', '?')})")
    else:
        print("Usage: python scraper.py <race_id>")
