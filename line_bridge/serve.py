"""LINE webhook 常駐服務：驗簽 -> inbox/；outbox/pending/ -> reply API 發出。

照 wechat-bridge/serve.py 的模式：
- 收到 webhook：先對原始 body 驗簽（失敗回 403，不進處理），
  再把文字訊息寫進 state/inbox/<eventId>.json，一律回 200
  （LINE 收到非 2xx 會重試；Console 的 Verify 會送空 events 陣列，也回 200）。
- 背景執行緒每 2 秒刷 outbox/pending/，用 replyToken 經 reply API 發回，
  發完移到 outbox/sent/；replyToken 過期（400）移到 outbox/failed/，
  不自動改走 push（push 要計每月 200 則額度，需人工決定）。

只收一對一私聊的文字訊息（source.type == "user"），群組與其他事件只記 log。
啟動：python3 -m line_bridge serve（工作目錄須在 line-bridge/ 下，
或 PYTHONPATH 指向它）。環境變數：
  LINE_CHANNEL_SECRET       驗簽用（沒有它就無法驗證，webhook 一律拒絕）
  LINE_CHANNEL_ACCESS_TOKEN 發 reply / push 用（沒有它就只收不發）
  LINE_BRIDGE_PORT          預設 8080
  LINE_BRIDGE_DIR           預設 ~/workspace/line-bridge
"""

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .reply import send_reply
from .store import Store, atomic_write_json, atomic_write_text, load_json
from .verify import verify_signature


def _log(msg):
    print("[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg), flush=True)


def handle_event(store, event):
    """處理一則 webhook event；文字訊息寫 inbox，非文字只記 log。"""
    event_id = event.get("webhookEventId") or ""
    if not event_id:
        # 沒有 webhookEventId 時用 message id + timestamp 拼一個去重鍵
        msg = event.get("message") or {}
        event_id = "%s_%s" % (msg.get("id", ""), event.get("timestamp", ""))
    processed = store.load_processed()
    if event_id in processed:
        return False
    processed.append(event_id)
    store.save_processed(processed)

    if event.get("type") != "message":
        _log("非訊息事件 type=%s，已略過" % event.get("type"))
        return False
    source = event.get("source") or {}
    if source.get("type") != "user":
        _log("非一對一私聊（source.type=%s），已略過" % source.get("type"))
        return False
    message = event.get("message") or {}
    if message.get("type") != "text":
        _log("非文字訊息 type=%s，已略過" % message.get("type"))
        return False
    text = (message.get("text") or "").strip()
    if not text:
        return False
    record = {
        "event_id": event_id,
        "message_id": message.get("id") or "",
        "user_id": source.get("userId") or "",
        "reply_token": event.get("replyToken") or "",
        "text": text,
        "timestamp_ms": event.get("timestamp"),
        "received_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    path = os.path.join(store.inbox_dir, "%s.json" % event_id)
    if not os.path.exists(path):
        atomic_write_json(path, record)
        _log("收到訊息 [%s]: %s" % (event_id, text[:60]))
    return True


def flush_outbox(store, access_token):
    """把 outbox/pending/ 的回覆發出去。沒 token 時只收不發，靜默跳過。"""
    if not access_token:
        return True
    try:
        files = sorted(f for f in os.listdir(store.pending_dir) if f.endswith(".json"))
    except OSError:
        return True
    for name in files:
        path = os.path.join(store.pending_dir, name)
        job = load_json(path)
        if not job:
            continue
        text = job.get("text") or ""
        reply_token = job.get("reply_token") or ""
        if not text or not reply_token:
            _log("跳過無效回覆任務: %s" % name)
            continue
        try:
            status, body = send_reply(reply_token, text, access_token)
        except Exception as e:
            _log("發送失敗，稍後重試: %s" % e)
            continue
        if status == 200:
            os.replace(path, os.path.join(store.sent_dir, name))
            _log("已發送回覆 -> %s" % name)
        elif status in (400, 401):
            # 400 常見原因：replyToken 超過 5 分鐘已過期，改走 push 需人工決定
            # 401：Channel access token 無效，重試也不會好
            os.replace(path, os.path.join(store.failed_dir, name))
            _log("回覆失敗 %s，已移入 failed/（不再重試）: %s | %s"
                 % (status, name, body[:200]))
        else:
            _log("回覆返回異常，稍後重試: %s %s" % (status, body[:200]))
    return True


def make_handler(store, channel_secret):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # 不用預設的 stderr log，改走 _log
            pass

        def _send_json(self, status, payload):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path in ("/health", "/"):
                self._send_json(200, {
                    "status": "ok",
                    "secret_configured": bool(channel_secret),
                })
            else:
                self._send_json(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/webhook":
                self._send_json(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length > 0 else b""
            signature = self.headers.get("X-Line-Signature") or ""
            if not channel_secret:
                _log("LINE_CHANNEL_SECRET 未設定，無法驗簽，拒絕 webhook")
                self._send_json(401, {"error": "channel secret not configured"})
                return
            if not verify_signature(raw, signature, channel_secret):
                _log("簽名驗證失敗，拒絕 webhook")
                self._send_json(403, {"error": "invalid signature"})
                return
            try:
                payload = json.loads(raw.decode("utf-8")) if raw else {}
            except ValueError:
                self._send_json(400, {"error": "invalid json"})
                return
            events = payload.get("events") or []
            atomic_write_text(
                store.last_webhook_path,
                time.strftime("%Y-%m-%d %H:%M:%S"),
            )
            for event in events:
                try:
                    handle_event(store, event)
                except Exception as e:
                    _log("處理事件出錯: %s" % e)
            self._send_json(200, {"status": "ok"})

    return Handler


def main():
    store = Store()
    channel_secret = os.environ.get("LINE_CHANNEL_SECRET") or ""
    access_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN") or ""
    port = int(os.environ.get("LINE_BRIDGE_PORT") or os.environ.get("PORT") or 8080)
    host = os.environ.get("LINE_BRIDGE_HOST") or "127.0.0.1"
    atomic_write_text(store.pid_path, str(os.getpid()))
    _log("line-bridge serve 啟動，port=%d，secret 已設定=%s，token 已設定=%s"
         % (port, bool(channel_secret), bool(access_token)))
    if not channel_secret:
        _log("警告：LINE_CHANNEL_SECRET 未設定，webhook 將一律拒絕（等用戶給 secret 再設）")
    if not access_token:
        _log("提示：LINE_CHANNEL_ACCESS_TOKEN 未設定，只收訊息、不發回覆")

    _flush_lock = threading.Lock()

    def _outbox_loop():
        while True:
            try:
                with _flush_lock:
                    flush_outbox(store, access_token)
            except Exception as e:
                _log("背景刷 outbox 出錯: %s" % e)
            time.sleep(2)

    threading.Thread(target=_outbox_loop, daemon=True).start()
    server = ThreadingHTTPServer((host, port), make_handler(store, channel_secret))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _log("收到中斷，退出 serve。")
        return 0
    finally:
        try:
            os.remove(store.pid_path)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
