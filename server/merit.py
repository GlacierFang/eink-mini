"""赛博木鱼：设备本地计数，服务器只做**只读镜像**。

设备端在木鱼页按 B 键 = 敲一下。**敲没敲只有设备知道** —— 计数存在设备
的 NVS 里，设备把当前计数报上来，服务器只存下来给控制台显示。

服务器不猜、不推断、不合并。以前那套「靠请求间隔猜用户敲了没」的启发式
已经删掉 —— 那正是「一次敲击被算成两次」的根源（显式路径和启发式路径同时
命中同一次敲击）。

所以这里没有「敲一下」的函数：服务器唯一的写入路径是 report()，
调用方是设备的上报。

**帧素材不归这里管**：三帧位图离线烘焙进固件（firmware/tools/
gen_merit_assets.py），生成脚本自己读 images/ 下的原始 PNG。
"""

import fcntl
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent
DATA_DIR = SERVER_DIR / "data"
STATE_FILE = DATA_DIR / "merit.json"
LOCK_FILE = DATA_DIR / "merit.lock"


@contextmanager
def _locked():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    handle = open(LOCK_FILE, "a+")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def _read_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    # 只留这三个字段。老版本留下的 devices / explicit_client 那些是
    # 「猜谁敲了」的记账，逻辑删掉后就没用了。
    return {
        "count": int(raw.get("count", 0) or 0),
        "strike": int(raw.get("strike", 0) or 0),
        "updated_at": int(raw.get("updated_at", 0) or 0),
    }


def _write_state(state):
    tmp = STATE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False)
    os.replace(tmp, STATE_FILE)


def count():
    """当前累计功德（设备报上来的镜像）。"""
    return int(_read_state().get("count", 0) or 0)


def strike():
    """累计敲击次数（设备报上来的镜像）。"""
    return int(_read_state().get("strike", 0) or 0)


def stats():
    state = _read_state()
    return {
        "count": int(state.get("count", 0) or 0),
        "strike": int(state.get("strike", 0) or 0),
        "updated_at": int(state.get("updated_at", 0) or 0),
    }


def report(count_value, strike_value=None):
    """设备上报当前计数。**服务器只存不算。**

    这是服务器唯一的写入路径 —— 网页端不能再敲（它敲了设备不知道，
    两边各算一份只会越算越乱）。
    """
    with _locked():
        state = _read_state()
        state["count"] = max(0, int(count_value or 0))
        if strike_value is not None:
            state["strike"] = max(0, int(strike_value or 0))
        state["updated_at"] = int(time.time())
        _write_state(state)
        return {"count": state["count"], "strike": state["strike"]}
