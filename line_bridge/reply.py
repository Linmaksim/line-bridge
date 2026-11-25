"""經 LINE Messaging API 發送回覆。

- reply：POST https://api.line.me/v2/bot/message/reply，帶 replyToken。
  reply 訊息不計入每月推播額度，但 replyToken 只有 5 分鐘有效，
  過期就發不出去（LINE 回 400），這時不要重試，只能改走 push。
- push：POST https://api.line.me/v2/bot/message/push，帶 to（userId）。
  push 計入每月額度，免費方案每月 200 則。

Channel access token 從環境變數 LINE_CHANNEL_ACCESS_TOKEN 讀，
絕對不要寫進程式或檔案。單則文字上限 5000 字，超長先切段。
"""

import json
import urllib.error
import urllib.request

LINE_API = "https://api.line.me"
MAX_TEXT_LEN = 4500  # 官方上限 5000，留一點餘裕


def chunk_text(text, limit=MAX_TEXT_LEN):
    return [text[i : i + limit] for i in range(0, len(text), limit)] or [""]


def _post(path, access_token, payload):
    req = urllib.request.Request(
        LINE_API + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + access_token,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except urllib.error.URLError as e:
        raise RuntimeError("LINE API 連線失敗: %s" % e)


def send_reply(reply_token, text, access_token):
    """回傳 (status, body)。replyToken 過期時 LINE 回 400。"""
    messages = [
        {"type": "text", "text": part} for part in chunk_text(text)
    ]
    return _post(
        "/v2/bot/message/reply",
        access_token,
        {"replyToken": reply_token, "messages": messages},
    )


def send_push(to_user_id, text, access_token):
    """回傳 (status, body)。計入每月推播額度。"""
    messages = [
        {"type": "text", "text": part} for part in chunk_text(text)
    ]
    return _post(
        "/v2/bot/message/push",
        access_token,
        {"to": to_user_id, "messages": messages},
    )
