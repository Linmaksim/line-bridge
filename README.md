# line-bridge

把 LINE 接到 Muse：LINE 上的訊息經官方 Messaging API webhook 進來，
轉成 JSON 落盤，Agent 讀了回覆，再經 reply API 發回 LINE。

走官方路線，不用任何非官方個人號登入方案。照
`~/workspace/wechat-bridge/` 的同一套模式（inbox / outbox / watchdog）。

```
+--------+  HTTPS POST /webhook   +--------------+  state/inbox/   +------+
|        |  x-line-signature  ->  |              |  一則一 JSON -> |      |
|  LINE  |  (HMAC-SHA256 驗簽)    | line-bridge  |                 | 大满  |
|        |  <- reply API (200)   |  (本機:8080)  |  <- outbox/     |      |
+--------+  cloudflared 隧道對外  +--------------+  pending/       +------+
```

## 狀態（2026-11-19 實測）

- Webhook server 已寫好、已驗過（見「已驗證」）。
- **隧道目前還沒通**：cloudflared 2026.11.1 已裝在 `bin/cloudflared`，
  但免費 quick tunnel 在這台 VM 上建不起來，兩次都報
  `failed to request quick Tunnel: ... tls: first record does not look like a TLS handshake`
  （對 `api.trycloudflare.com` 的 POST 被 VM 出口代理擋掉；同主機 curl 測試
  可以通，是 cloudflared 自身的 TLS 握手被擋）。
  備用 localtunnel 也試過，`npx localtunnel --port 8080` 跑起來後
  45 秒以上拿不到網址，同樣疑似被出口擋掉，已停掉。
  在隧道通之前，LINE 還沒辦法把 webhook 送進來。解法見「隧道」一節。
- 還缺用戶給的東西：Channel secret、Channel access token
  （他在 LINE Developers 開 Messaging API 頻道拿）。

## Altare 部署（2026-11-25 新增路線）

VM 上的 cloudflared 隧道走不通（quick tunnel 403、命名隧道 token 遺失），
改走 Altare 免費伺服器當 webhook 對外網址：

- Build：`pip install -r requirements.txt`（空的，只有標準庫）
- Start：`LINE_BRIDGE_HOST=0.0.0.0 python -m line_bridge serve`
  （port 吃 Altare 給的 `$PORT`；`LINE_BRIDGE_PORT` 也可指定）
- 環境變數：`LINE_CHANNEL_SECRET`、`LINE_CHANNEL_ACCESS_TOKEN`
  （沒設時 webhook 一律拒絕，只跑 `/health`）

## 檔案

```
line_bridge/
  __init__.py   # 套件入口
  serve.py      # webhook server：驗簽、寫 inbox、背景刷 outbox
  verify.py     # HMAC-SHA256 簽名驗證
  reply.py      # reply / push API 呼叫
  store.py      # 目錄、原子寫入、processed 去重
  __main__.py   # python3 -m line_bridge serve
tests/
  test_signature.py   # 官方測試向量驗簽測試
run.sh          # 啟動 serve（setsid 脫離，照微信橋接做法）
watchdog.sh     # 每 5 分鐘檢查 serve 在不在，死了重拉
tunnel.sh       # 啟動 cloudflared 免費隧道（目前在 VM 上建不起來，見上）
.env.example    # 環境變數範本（不要填真實值）
state/          # 執行期狀態：serve.pid、serve.log、last_webhook.txt、inbox/
outbox/         # pending/ 待發回覆、sent/ 已發、failed/ 發失敗
bin/            # cloudflared 執行檔
```

訊息格式（`state/inbox/<eventId>.json`，照微信 inbox 的寫法）：

```json
{
  "event_id": "01...",
  "message_id": "100001",
  "user_id": "U...",
  "reply_token": "nHuyWiB7...",
  "text": "你好",
  "timestamp_ms": 1795100000000,
  "received_at": "2026-11-19 18:55:12"
}
```

回覆任務格式（`outbox/pending/<檔名>.json`，Agent 寫入後 serve 自動發）：

```json
{"reply_token": "nHuyWiB7...", "text": "回覆內容", "to_user_id": "U...", "message_id": "100001"}
```

## 啟動

只用 Python 標準庫，不需要裝套件。先設環境變數
（真實值走 Secure Vault 流程，**絕對不要寫進任何檔案**）：

```bash
export LINE_CHANNEL_SECRET='...'
export LINE_CHANNEL_ACCESS_TOKEN='...'
export LINE_BRIDGE_PORT=8080   # 可不設，預設 8080

bash run.sh                    # 啟動 serve
curl http://127.0.0.1:8080/health   # 應回 {"status": "ok", ...}
```

沒設 secret 時 serve 照樣跑，但 webhook 一律回 401（無法驗簽）；
沒設 token 時只收訊息、不發回覆。

## 隧道

LINE 只接受公開 HTTPS 的 webhook URL，所以本機 port 要曝出去：

```bash
bash tunnel.sh   # 成功時印出 Webhook URL，形如 https://xxx.trycloudflare.com/webhook
```

**已知限制（2026-11-19 實測）：**

- 免費 quick tunnel 的網址每次重開都會變，要重貼到 LINE Developers Console。
  當前網址記在 `state/tunnel_url.txt`，log 在 `state/tunnel.log`。
- 這台 VM 上 quick tunnel 目前建不起來（見「狀態」），可選的解法：
  1. **命名隧道（建議）**：有 Cloudflare 帳號的話，在瀏覽器跑一次
     `cloudflared tunnel login` 授權，再建一條命名隧道，網址固定。
     這步要用戶在自己的瀏覽器操作，大满沒辦法代做。
  2. **換一台出口乾淨的機器跑 webhook**：例如 Simular Box（雲端 Ubuntu，
     直接對外）或林哥的 Mac（家裡網路直接出去），在那台機器上裝
     cloudflared 跑 quick tunnel，程式原封不動搬過去就能用。
  3. 等 VM 出口問題解決後再重試 `bash tunnel.sh`。
- VM 重啟後要重開 serve 和隧道（跟微信橋接一樣，watchdog 只顧 serve，
  不顧隧道）。

## 接線（等用戶拿回 token 後）

1. LINE Developers Console → 該頻道 → Messaging API →
   Webhook URL 填 `https://<隧道網址>/webhook`，按 Verify，
   應顯示 Success（Console 會送一個空 events 的簽名請求，server 回 200）。
2. 把 Channel secret 設成 `LINE_CHANNEL_SECRET`、
   Channel access token 設成 `LINE_CHANNEL_ACCESS_TOKEN`，
   重啟 serve：`bash run.sh`（先停舊的，再啟）。
3. 用戶在 LINE 加機器人好友、發一句話，`state/inbox/` 應出現一則 JSON。
4. Agent 回覆：寫一個 `outbox/pending/*.json`（格式見上），
   serve 兩秒內經 reply API 發回。

## 已驗證（2026-11-19，本機假 secret / 假 token）

- `tests/test_signature.py` 全過：官方測試向量
  （secret `8c570fa6dd201bb328f1c1eac23a96d8`、
  body `{"destination":"U8e742f61d673b39c7fff3cecb7536ef0","events":[]}`、
  簽名 `GhRKmvmHys4Pi8DxkF4+EayaH0OqtJtaZxgTD9fMDLs=`）算出一致；
  竄改 body、錯 secret、缺參數都正確拒絕。
- Webhook 端到端：正確簽名 → 200，`state/inbox/01testevent0001.json`
  內容正確；錯誤簽名 → 403、不寫檔；空 events（Verify 模擬）→ 200；
  群組訊息 → 200 但略過不寫檔；沒設 secret → 401。
- Outbox：假 token 回 401，任務正確移入 `outbox/failed/` 不再重試；
  回覆函式本身直連 `api.line.me` 實測 0.6 秒回 401（假 token 預期結果），
  代表 VM 到 LINE API 是通的。
- `watchdog.sh`：serve 死了 → `SERVE_RESTARTED` 且進程回來；
  活著 → `SERVE_ALIVE`。
- 測試用的假 secret / 假 token、測試訊息與測試任務檔事後都已清掉，
  state/ 目前是乾淨的。

## 未驗證

- **沒有用真實 Channel secret / token 跑過**：真的 webhook 簽名、
  真的 reply 發送、Console 的 Verify，都要等用戶給 token 後再驗。
- **隧道沒通**：上面寫了，quick tunnel 在 VM 上建不起來，
  還沒有公開網址可貼到 Console。
- reply token 5 分鐘過期、push 每月 200 則免費額度，都是照官方文件寫的，
  沒有實測過。

## 已知限制（官方）

- LINE 上聊的是機器人帳號，不是林哥個人 LINE 號；要加好友才能對話。
- replyToken 只有 5 分鐘有效：超過 5 分鐘才回，reply 發不出去
  （任務會進 `outbox/failed/`），要改走 push（計每月 200 則額度）
  需人工決定，程式不會自動改發 push。
- 單則文字上限 5000 字，程式在 4500 字切段。
- 只收一對一私聊文字訊息；群組、貼圖、圖片、語音目前只記 log、不進 inbox。
- Webhook 必須 2 秒內回 200，否則 LINE 記 `request_timeout`
  （程式先回 200 再處理，符合要求）。
- 伺服器時間是 UTC，`received_at` 記的是 VM 當地時間。
