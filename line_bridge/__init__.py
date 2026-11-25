"""LINE 橋接：把 LINE Messaging API 接到 Muse。

照 ~/workspace/wechat-bridge 的同一套模式：
LINE webhook 收到訊息 -> state/inbox/ 一則訊息一個 JSON -> Agent 讀了回覆
-> outbox/pending/ 的回覆任務由 serve 的背景執行緒經 reply API 發回 LINE。

只用 Python 標準庫，不需要裝任何套件。
Token / secret 一律走環境變數，絕對不要寫進程式或檔案。
"""

from .serve import main  # noqa: F401  (python3 -m line_bridge serve)

__all__ = ["main"]
