"""留言存储：保留最近 50 条，文件落盘。"""

import json
import pathlib
import threading
from datetime import datetime

DATA_DIR = pathlib.Path(__file__).resolve().parent / "data"
MSG_PATH = DATA_DIR / "messages.json"
MAX_MESSAGES = 50

_lock = threading.Lock()


def _read():
    try:
        data = json.loads(MSG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def list_messages(limit=10):
    with _lock:
        msgs = _read()
    # 最新的在前
    return list(reversed(msgs))[:limit]


def add_message(text):
    text = (text or "").strip()
    if not text:
        raise ValueError("留言不能为空")
    item = {
        "text": text[:200],
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    with _lock:
        msgs = _read()
        msgs.append(item)
        msgs = msgs[-MAX_MESSAGES:]
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        MSG_PATH.write_text(
            json.dumps(msgs, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return item


def clear_messages():
    with _lock:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        MSG_PATH.write_text("[]", encoding="utf-8")
