"""狀態目錄與原子寫入。照 wechat-bridge/store.py 的做法。"""

import json
import os
import tempfile

BRIDGE_DIR = os.environ.get(
    "LINE_BRIDGE_DIR", os.path.expanduser("~/workspace/line-bridge")
)


class Store:
    def __init__(self, base_dir=None):
        self.base_dir = base_dir or BRIDGE_DIR
        self.inbox_dir = os.path.join(self.base_dir, "state", "inbox")
        self.pending_dir = os.path.join(self.base_dir, "outbox", "pending")
        self.sent_dir = os.path.join(self.base_dir, "outbox", "sent")
        self.failed_dir = os.path.join(self.base_dir, "outbox", "failed")
        self.pid_path = os.path.join(self.base_dir, "state", "serve.pid")
        self.processed_path = os.path.join(self.base_dir, "state", "processed.json")
        self.last_webhook_path = os.path.join(
            self.base_dir, "state", "last_webhook.txt"
        )
        for d in (
            self.inbox_dir,
            self.pending_dir,
            self.sent_dir,
            self.failed_dir,
            os.path.join(self.base_dir, "state"),
        ):
            os.makedirs(d, exist_ok=True)

    def load_processed(self):
        try:
            with open(self.processed_path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def save_processed(self, items):
        atomic_write_json(self.processed_path, items[-1000:])


def atomic_write_json(path, data):
    text = json.dumps(data, ensure_ascii=False, indent=2)
    atomic_write_text(path, text)


def atomic_write_text(path, text):
    directory = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None
