"""设备在线状态。

两件事分开记 —— 之前混成一个「在线」，结果两头都不准：

  - **存活**：设备多久没跟服务端说话了（心跳）。在线徽章看这个。
  - **新鲜度**：设备最后拿到内容是什么时候。跟存活不是一回事 ——
    设备活着但停在时钟页时，本来就不该有新内容。

离线阈值不是拍脑袋的常数，是按固件的心跳周期推出来的：

    心跳周期 x 2（允许丢一轮） + HTTP 超时 + 余量

固件那边是 ink_config.h 的 INK_HEARTBEAT_PERIOD_MS，两边必须一致，
改一个就要改另一个。

设备还会主动上报自己的状态（当前页、计时器），见 record_report()。

状态落盘在 data/device_state.json：gunicorn 起 2 个 worker，
内存态跨 worker 不可见，落盘才是唯一真相源。
"""

import json
import os
import pathlib
import threading
import time
from datetime import datetime

DATA_DIR = pathlib.Path(__file__).resolve().parent / "data"
STATE_PATH = DATA_DIR / "device_state.json"

# ---- 与固件对齐的常量（firmware/src/ink_config.h）----
HEARTBEAT_PERIOD_SEC = 60   # INK_HEARTBEAT_PERIOD_MS
HTTP_TIMEOUT_SEC = 15       # INK_HTTP_TIMEOUT_MS
OFFLINE_GRACE_SEC = 45      # 手工余量：网络抖动、服务器慢
# 60 x 2 + 15 + 45 = 180 秒
OFFLINE_AFTER_SEC = HEARTBEAT_PERIOD_SEC * 2 + HTTP_TIMEOUT_SEC + OFFLINE_GRACE_SEC

_lock = threading.Lock()

TIMER_STATES = ("READY", "RUN", "PAUSE", "DONE")


def _blank():
    return {
        "first_seen": None,
        "last_seen": None,          # 任何设备请求 —— 存活
        "last_endpoint": None,
        "ip": None,
        "user_agent": None,
        "manifest_fetched": 0,
        "pages_fetched": 0,
        "reports": 0,               # 设备主动上报的次数
        "last_content_seen": None,  # 最后一次下发位图 —— 内容新鲜度
        "last_content_page": None,
        "report": None,             # 设备上报的状态（当前页 + 计时器）
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
            # 内容新鲜度：位图真的下发了才算数
            state["last_content_seen"] = now
            state["last_content_page"] = endpoint[len("page/"):-len(".bin")]
        elif endpoint.endswith("manifest.json"):
            state["manifest_fetched"] = int(state.get("manifest_fetched") or 0) + 1
        _write(state)
        return state


def record_report(report, ip=None, user_agent=None):
    """记一次设备主动上报的状态（当前页 + 计时器）。

    上报本身也是一次设备请求 —— 算存活。
    """
    with _lock:
        state = _read()
        now = datetime.now()
        if not state.get("first_seen"):
            state["first_seen"] = now.isoformat(timespec="seconds")
        state["last_seen"] = now.isoformat(timespec="seconds")
        state["last_endpoint"] = "device/state"
        if ip:
            state["ip"] = ip
        if user_agent:
            state["user_agent"] = user_agent
        state["reports"] = int(state.get("reports") or 0) + 1
        timer = (report or {}).get("timer") or {}
        state["report"] = {
            "page": str((report or {}).get("page") or "-")[:40],
            "at": now.timestamp(),
            "at_text": now.strftime("%Y-%m-%d %H:%M:%S"),
            "timer": {
                "state": str(timer.get("state") or "READY"),
                "remaining": int(timer.get("remaining") or 0),
                "preset": int(timer.get("preset") or 0),
            },
        }
        _write(state)
        return state


def get_state():
    with _lock:
        return _read()


def is_online(state=None, within_seconds=OFFLINE_AFTER_SEC):
    """最近 within_seconds 内有设备请求算在线。

    默认阈值由心跳周期推导，不是随手写的常数。
    """
    state = state if state is not None else get_state()
    last = state.get("last_seen")
    if not last:
        return False
    try:
        t = datetime.fromisoformat(last)
    except ValueError:
        return False
    return (datetime.now() - t).total_seconds() <= within_seconds


def content_age_seconds(state=None):
    """内容新鲜度：最后一次下发位图距今多少秒。没有就是 None。"""
    state = state if state is not None else get_state()
    last = state.get("last_content_seen")
    if not last:
        return None
    try:
        t = datetime.fromisoformat(last)
    except ValueError:
        return None
    return max(0, int((datetime.now() - t).total_seconds()))


def timer_state(state=None):
    """设备上报的计时器状态，带实时剩余秒数。

    上报里带的是「上报那一刻的剩余」。运行中就按经过的时间往下减 ——
    设备端倒计时是匀速的（millis），这样推算和真机一致。
    """
    state = state if state is not None else get_state()
    report = state.get("report") or {}
    timer = report.get("timer") or {}
    st = str(timer.get("state") or "READY")
    if st not in TIMER_STATES:
        st = "READY"
    remain = int(timer.get("remaining") or 0)
    at = float(report.get("at") or 0.0)
    if st == "RUN" and at > 0:
        elapsed = int(max(0.0, time.time() - at))
        remain = max(0, remain - elapsed)
        if remain == 0:
            st = "DONE"
    return {
        "state": st,
        "remaining": remain,
        "preset": int(timer.get("preset") or 0),
        "page": report.get("page") or "-",
        "at": at,
        "at_text": report.get("at_text") or "",
        "age": int(max(0.0, time.time() - at)) if at > 0 else None,
    }
