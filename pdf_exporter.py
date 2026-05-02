# -*- coding: utf-8 -*-
"""
競馬分析結果 PDF出力モジュール
"""

import os
import re
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


# ── フォント登録 ──────────────────────────────────────────────
def _register_japanese_font() -> str:
    """Windowsの日本語フォントを登録して名前を返す"""
    candidates = [
        r"C:\Windows\Fonts\msgothic.ttc",
        r"C:\Windows\Fonts\YuGothM.ttc",
        r"C:\Windows\Fonts\meiryo.ttc",
        r"C:\Windows\Fonts\msmincho.ttc",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont("JPN", path))
                return "JPN"
            except Exception:
                continue
    # フォントが見つからなければ Helvetica にフォールバック
    return "Helvetica"


FONT_NAME = _register_japanese_font()

# ── スタイル定義 ──────────────────────────────────────────────
def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title",
            fontName=FONT_NAME,
            fontSize=18,
            leading=24,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#1e3a5f"),
            spaceAfter=4,
        ),
        "subtitle": ParagraphStyle(
            "subtitle",
            fontName=FONT_NAME,
            fontSize=10,
            leading=14,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#64748b"),
            spaceAfter=6,
        ),
        "section": ParagraphStyle(
            "section",
            fontName=FONT_NAME,
            fontSize=12,
            leading=16,
            textColor=colors.HexColor("#1e3a5f"),
            spaceBefore=10,
            spaceAfter=4,
            leftIndent=0,
        ),
        "body": ParagraphStyle(
            "body",
            fontName=FONT_NAME,
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#334155"),
        ),
        "small": ParagraphStyle(
            "small",
            fontName=FONT_NAME,
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#64748b"),
        ),
        "footer": ParagraphStyle(
            "footer",
            fontName=FONT_NAME,
            fontSize=7,
            leading=10,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#94a3b8"),
        ),
    }


# ── ヘルパー関数 ──────────────────────────────────────────────
def _safe(val, default="-"):
    """None や 0 を "-" に変換"""
    if val is None or val == "" or val == 0:
        return default
    return str(val)


def _pace_label(pace: str) -> str:
    return {"H": "ハイペース", "M": "ミドルペース", "S": "スローペース"}.get(pace, pace or "-")


def _mark_color(mark: str):
    return {
        "◎": colors.HexColor("#ef4444"),
        "◯": colors.HexColor("#3b82f6"),
        "▲": colors.HexColor("#f59e0b"),
        "△": colors.HexColor("#6366f1"),
    }.get(mark, colors.black)


def _ev_color(ev: float):
    """期待値に応じた色を返す"""
    if ev is None or ev == 0:
        return colors.black
    if ev >= 1.5: return colors.HexColor("#059669")
    if ev >= 1.0: return colors.HexColor("#10b981")
    if ev >= 0.7: return colors.HexColor("#d97706")
    return colors.HexColor("#dc2626")


# ── PDF生成メイン ─────────────────────────────────────────────
def generate_pdf(data: dict, output_dir: str) -> str:
    """
    分析結果 dict から PDF を生成してファイルパスを返す。

    Parameters
    ----------
    data : dict
        /api/analyze が返す JSON データ
    output_dir : str
        保存先ディレクトリ（存在しない場合は作成）

    Returns
    -------
    str
        生成されたPDFファイルの絶対パス
    """
    os.makedirs(output_dir, exist_ok=True)

    race_name = data.get("race_name") or data.get("race_id", "unknown")
    race_id = data.get("race_id", "")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # ファイル名に使えない文字を除去
    safe_name = re.sub(r'[\\/:*?"<>|]', "_", race_name)
    filename = f"{safe_name}_{race_id}_{timestamp}.pdf"
    filepath = os.path.join(output_dir, filename)

    st = _styles()
    doc = SimpleDocTemplate(
        filepath,
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=race_name,
        author="競馬データ分析システム",
    )

    story = []

    # ── タイトル ──────────────────────────────────────────────
    story.append(Paragraph("競馬データ分析レポート", st["title"]))
    story.append(Paragraph(f"生成日時: {data.get('generated_at', timestamp)}", st["subtitle"]))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#1e3a5f")))
    story.append(Spacer(1, 6))

    # ── レース概要 ────────────────────────────────────────────
    story.append(Paragraph("■ レース概要", st["section"]))
    race_info = [
        ["レース名", Paragraph(race_name or "-", st["body"])],
        ["レースID", Paragraph(race_id or "-", st["body"])],
        ["日付", Paragraph(data.get("date", "-"), st["body"])],
        ["競馬場", Paragraph(data.get("track", "-"), st["body"])],
        ["コース", Paragraph(f"{data.get('surface','')} {data.get('distance','') and str(data.get('distance'))+'m' or ''}".strip(), st["body"])],
        ["回り", Paragraph(data.get("direction", "-"), st["body"])],
        ["馬場状態", Paragraph(data.get("track_condition", "-"), st["body"])],
        ["クラス", Paragraph(data.get("race_class", "-") or "-", st["body"])],
    ]
    t = Table(race_info, colWidths=[35 * mm, 130 * mm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), FONT_NAME),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f5f9")),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#1e3a5f")),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t)
    story.append(Spacer(1, 8))

    # ── 展開予想 ──────────────────────────────────────────────
    pace = data.get("pace_estimate", {})
    if pace:
        story.append(Paragraph("■ 展開予想", st["section"]))
        pace_text = f"<b>{_pace_label(pace.get('pace',''))}</b>　{pace.get('reason','')}"
        story.append(Paragraph(pace_text, st["body"]))
        if pace.get("comment"):
            story.append(Spacer(1, 2))
            story.append(Paragraph(f'<font color="#475569"><i>{pace.get("comment")}</i></font>', st["small"]))
        
        fuguri = pace.get("逃げ候補", [])
        if fuguri:
            story.append(Paragraph(f"逃げ候補: {', '.join(fuguri)}", st["body"]))

        style_row = [["逃げ", "先行", "差し", "追込"],
                     [str(pace.get("逃げ", 0)), str(pace.get("先行", 0)),
                      str(pace.get("差し", 0)), str(pace.get("追込", 0))]]
        st_tbl = Table(style_row, colWidths=[40 * mm] * 4)
        st_tbl.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), FONT_NAME),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a5f")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(Spacer(1, 4))
        story.append(st_tbl)
        story.append(Spacer(1, 8))

    # ── 推奨馬 ────────────────────────────────────────────────
    rec = data.get("recommendation", {})
    ranking = rec.get("ranking", [])
    if ranking:
        story.append(Paragraph("■ 推奨馬", st["section"]))
        rec_header = [["印", "馬番", "馬名", "スコア", "自信度", "期待値", "分析コメント"]]
        rec_rows = []
        # エントリデータを馬番で引きやすくする
        entry_map = {e.get("馬番"): e for e in data.get("entries", [])}

        for r in ranking[:6]:
            bno = r.get("馬番")
            e = entry_map.get(bno, {})
            mark = r.get("印", "")
            conf = r.get("confidence")
            conf_str = f"{conf}%" if conf is not None else "-"
            ev = e.get("期待値", 0)
            rec_rows.append([
                mark,
                _safe(bno),
                Paragraph(r.get("馬名", "-"), st["body"]),
                _safe(r.get("score")),
                conf_str,
                f"{ev:.2f}" if ev else "-",
                Paragraph(e.get("コメント", "-"), st["body"]),
            ])
        rec_tbl = Table(rec_header + rec_rows,
                        colWidths=[12 * mm, 14 * mm, 40 * mm, 16 * mm, 16 * mm, 16 * mm, 52 * mm])
        rec_style = [
            ("FONTNAME", (0, 0), (-1, -1), FONT_NAME),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a5f")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("ALIGN", (2, 1), (2, -1), "LEFT"),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]
        # 印・期待値の色付け
        for i, r in enumerate(ranking[:6], start=1):
            bno = r.get("馬番")
            e = entry_map.get(bno, {})
            mark = r.get("印", "")
            mc = _mark_color(mark)
            rec_style.append(("TEXTCOLOR", (0, i), (0, i), mc))
            rec_style.append(("FONTSIZE", (0, i), (0, i), 11))
            
            # 期待値の色
            ev = e.get("期待値")
            if ev:
                rec_style.append(("TEXTCOLOR", (5, i), (5, i), _ev_color(ev)))
                rec_style.append(("FONTWEIGHT", (5, i), (5, i), "BOLD"))

        rec_tbl.setStyle(TableStyle(rec_style))
        story.append(rec_tbl)
        story.append(Spacer(1, 8))

    # ── 買い目 ────────────────────────────────────────────────
    bets = rec.get("bets", {})
    if bets:
        story.append(Paragraph("■ 推奨買い目", st["section"]))
        bet_data = [["券種", "買い目", "備考"]]
        for category, items in bets.items():
            if not items:
                continue
            for it in items:
                nums = it.get("馬番", [])
                nums_str = " - ".join(map(str, nums)) if isinstance(nums, list) else str(nums)
                bet_data.append([
                    category,
                    Paragraph(nums_str, st["body"]),
                    Paragraph(it.get("備考", ""), st["body"])
                ])
        if len(bet_data) > 1:
            bet_tbl = Table(bet_data, colWidths=[30 * mm, 60 * mm, 76 * mm])
            bet_tbl.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, -1), FONT_NAME),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a5f")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("ALIGN", (2, 1), (2, -1), "LEFT"),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ]))
            story.append(bet_tbl)
            story.append(Spacer(1, 8))

    # ── 出走馬一覧 ────────────────────────────────────────────
    entries = data.get("entries", [])
    if entries:
        story.append(Paragraph("■ 出走馬一覧", st["section"]))
        ranking_map = {r.get("馬番"): r for r in ranking}

        headers = ["印", "番", "馬名", "騎手", "脚質", "上がり", "着順", "勝率", "複勝", "人気", "オッズ", "コメント"]
        # 全体で 180mm 程度に収める
        col_w = [8, 9, 25, 18, 11, 13, 11, 10, 10, 9, 11, 45]
        col_w = [w * mm for w in col_w]

        rows = [headers]
        for e in entries:
            bno = e.get("馬番")
            r = ranking_map.get(bno, {})
            ev = e.get("期待値", 0)
            rows.append([
                r.get("印", ""),
                _safe(bno),
                Paragraph(e.get("馬名", "-"), st["small"]),
                Paragraph(e.get("騎手", "-"), st["small"]),
                e.get("脚質", "-"),
                _safe(e.get("平均上がり3F")),
                _safe(e.get("平均着順")),
                f"{e.get('勝率',0)}%" if e.get("勝率") else "-",
                f"{e.get('複勝率',0)}%" if e.get("複勝率") else "-",
                _safe(e.get("人気")),
                _safe(e.get("オッズ")),
                Paragraph(e.get("コメント", "-"), st["small"]),
            ])

        entry_style = [
            ("FONTNAME", (0, 0), (-1, -1), FONT_NAME),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a5f")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("ALIGN", (2, 1), (2, -1), "LEFT"),
            ("ALIGN", (3, 1), (3, -1), "LEFT"),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ]
        # 印・期待値の色付け
        for i, e in enumerate(entries, start=1):
            bno = e.get("馬番")
            r = ranking_map.get(bno, {})
            mark = r.get("印", "")
            if mark:
                mc = _mark_color(mark)
                entry_style.append(("TEXTCOLOR", (0, i), (0, i), mc))
                entry_style.append(("FONTSIZE", (0, i), (0, i), 10))
            
            # 期待値の色 (末尾列: 11)
            ev = e.get("期待値")
            if ev:
                entry_style.append(("TEXTCOLOR", (11, i), (11, i), _ev_color(ev)))
                entry_style.append(("FONTWEIGHT", (11, i), (11, i), "BOLD"))

        entry_tbl = Table(rows, colWidths=col_w, repeatRows=1)
        entry_tbl.setStyle(TableStyle(entry_style))
        story.append(entry_tbl)
        story.append(Spacer(1, 8))

    # ── 枠順傾向 ─────────────────────────────────────────────
    trend = data.get("post_position_trend", {})
    trend_data = trend.get("枠番別成績", {})
    if trend_data:
        story.append(Paragraph("■ 枠順傾向", st["section"]))
        trend_header = [["枠番", "戦数", "勝率", "複勝率"]]
        trend_rows = [[waku,
                       _safe(stats.get("戦数")),
                       f"{stats.get('勝率', 0)}%",
                       f"{stats.get('複勝率', 0)}%"]
                      for waku, stats in trend_data.items()]
        trend_tbl = Table(trend_header + trend_rows, colWidths=[20 * mm, 25 * mm, 25 * mm, 25 * mm])
        trend_tbl.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), FONT_NAME),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a5f")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(trend_tbl)
        story.append(Spacer(1, 8))

    # ── フッター ─────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1")))
    story.append(Spacer(1, 4))
    story.append(Paragraph("競馬データ分析システム — Powered by netkeiba.com", st["footer"]))

    doc.build(story)
    return filepath
