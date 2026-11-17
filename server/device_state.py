"""设备在线状态：记录设备最后一次拉取的时间、来源和目标。

设备每 30 秒拉一次清单或页面位图，服务端在这些路由上记一笔，
控制台据此显示在线 / 离线与最后活动。

状态落盘在 data/device_state.json：gunicorn 起 2 个 worker，
内存态跨 worker 不可见，落盘才是唯一真相源。
"""

import json
import os
import pathlib
import threading
from datetime import datetime

DATA_DIR = pathlib.Path(__file__).resolve().parent / "data"
STATE_PATH = DATA_DIR / "device_state.json"

_lock = threading.Lock()


def _blank():
    return {
        "first_seen": None,
        "last_seen": None,
        "last_endpoint": None,
        "ip": None,
        "user_agent": None,
        "manifest_fetched": 0,
        "pages_fetched": 0,
    }


def _read():
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _blank()
    if not isinstance(data, dict):
        return _blank()
    state = _blank()
    state.update({k: v for k, v in data.items() if k in state})
    return state


def _write(state):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(STATE_PATH))


def record(endpoint, ip=None, user_agent=None):
    """记一笔设备请求，返回最新状态。"""
    with _lock:
        state = _read()
        now = datetime.now().isoformat(timespec="seconds")
        if not state.get("first_seen"):
            state["first_seen"] = now
        state["last_seen"] = now
        state["last_endpoint"] = endpoint
        state["ip"] = ip
        state["user_agent"] = user_agent
        if endpoint.endswith(".bin"):
            state["pages_fetched"] = int(state.get("pages_fetched") or 0) + 1
        elif endpoint.endswith("manifest.json"):
            state["manifest_fetched"] = int(state.get("manifest_fetched") or 0) + 1
        _write(state)
        return state


def get_state():
    with _lock:
        return _read()


def is_online(state=None, within_seconds=180):
    """最近 within_seconds 内有拉取算在线。"""
    state = state if state is not None else get_state()
    last = state.get("last_seen")
    if not last:
        return False
    try:
        t = datetime.fromisoformat(last)
    except ValueError:
        return False
    return (datetime.now() - t).total_seconds() <= within_seconds
