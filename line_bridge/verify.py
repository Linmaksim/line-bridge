"""Webhook 簽名驗證。

官方規範（developers.line.biz/en/docs/messaging-api/verify-webhook-signature/）：
LINE 用 Channel secret 對 webhook 請求的原始 body 做 HMAC-SHA256，
base64 編碼後放在 x-line-signature 標頭。驗證時必須對「收到的原始位元組」
計算，驗證前絕對不要解析、重新序列化或改動 body，否則簽名一定對不上。
簽名用的金鑰是 Channel secret，不是 Channel access token，兩者搞混會永遠失敗。

官方測試向量（secret 8c570fa6dd201bb328f1c1eac23a96d8）見 tests/test_signature.py。
"""

import base64
import hashlib
import hmac


def verify_signature(body: bytes, signature: str, channel_secret: str) -> bool:
    """body 是收到的原始請求位元組；任一參數缺失都算驗證失敗。"""
    if not body or not signature or not channel_secret:
        return False
    digest = hmac.new(
        channel_secret.encode("utf-8"), body, hashlib.sha256
    ).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(signature, expected)
