# -*- coding: utf-8 -*-
"""
LINE Messaging API を使って PDFファイルを送信するモジュール

使い方:
    1. LINE Developers でチャネルアクセストークンとユーザーIDを取得
    2. app.py の LINE_CHANNEL_ACCESS_TOKEN / LINE_USER_ID に設定
    3. 自作BotをLINEで友だち追加する
"""

import os
import mimetypes
import requests


# ── API エンドポイント ──────────────────────────────────────────
_UPLOAD_URL = "https://api-data.line.me/v2/bot/message/upload/multipart"
_PUSH_URL   = "https://api.line.me/v2/bot/message/push"


def send_pdf_to_line(
    pdf_path: str,
    race_name: str,
    channel_access_token: str,
    user_id: str,
) -> dict:
    """
    PDFファイルをLINEにファイルメッセージとして送信する。

    Parameters
    ----------
    pdf_path : str
        送信するPDFファイルの絶対パス
    race_name : str
        レース名（通知テキストに使用）
    channel_access_token : str
        LINE Messaging APIのチャネルアクセストークン
    user_id : str
        送信先のLINEユーザーID (例: "Uxxxxxxxxxxxxxx")

    Returns
    -------
    dict
        {"success": True} または {"success": False, "error": "<理由>"}
    """

    if not os.path.exists(pdf_path):
        return {"success": False, "error": f"PDFファイルが見つかりません: {pdf_path}"}

    if not channel_access_token or channel_access_token.startswith("YOUR_"):
        return {"success": False, "error": "LINE チャネルアクセストークンが設定されていません"}

    if not user_id or user_id.startswith("YOUR_"):
        return {"success": False, "error": "LINE ユーザーIDが設定されていません"}

    headers_auth = {"Authorization": f"Bearer {channel_access_token}"}
    filename = os.path.basename(pdf_path)
    file_size = os.path.getsize(pdf_path)

    # ── STEP 1: テキストメッセージで通知 ────────────────────────────
    try:
        text_body = {
            "to": user_id,
            "messages": [
                {
                    "type": "text",
                    "text": f"📊 競馬分析PDF\nレース: {race_name}\nファイル: {filename}",
                }
            ],
        }
        r_text = requests.post(
            _PUSH_URL,
            headers={**headers_auth, "Content-Type": "application/json"},
            json=text_body,
            timeout=15,
        )
        if r_text.status_code != 200:
            return {
                "success": False,
                "error": f"テキスト送信失敗: HTTP {r_text.status_code} - {r_text.text}",
            }
    except requests.RequestException as e:
        return {"success": False, "error": f"テキスト送信エラー: {e}"}

    # ── STEP 2: PDFファイルをアップロード ────────────────────────────
    try:
        with open(pdf_path, "rb") as f:
            r_upload = requests.post(
                _UPLOAD_URL,
                headers=headers_auth,
                data={
                    "channelId": "",          # 空文字でOK（token認証のため）
                },
                files={
                    "file": (filename, f, "application/pdf"),
                },
                timeout=60,
            )

        if r_upload.status_code != 200:
            return {
                "success": False,
                "error": f"ファイルアップロード失敗: HTTP {r_upload.status_code} - {r_upload.text}",
            }

        upload_result = r_upload.json()
        msg_id = upload_result.get("messageId")
        if not msg_id:
            return {"success": False, "error": f"messageId が取得できません: {r_upload.text}"}

    except requests.RequestException as e:
        return {"success": False, "error": f"ファイルアップロードエラー: {e}"}

    # ── STEP 3: ファイルメッセージを送信 ─────────────────────────────
    try:
        file_body = {
            "to": user_id,
            "messages": [
                {
                    "type": "file",
                    "originalContentUrl": "",   # multipart upload の場合は不要
                    "previewImageUrl": "",
                    "fileSize": file_size,
                    "fileName": filename,
                    "messageId": msg_id,
                }
            ],
        }
        r_push = requests.post(
            _PUSH_URL,
            headers={**headers_auth, "Content-Type": "application/json"},
            json=file_body,
            timeout=15,
        )

        if r_push.status_code != 200:
            return {
                "success": False,
                "error": f"ファイルメッセージ送信失敗: HTTP {r_push.status_code} - {r_push.text}",
            }

    except requests.RequestException as e:
        return {"success": False, "error": f"ファイルメッセージ送信エラー: {e}"}

    return {"success": True}
