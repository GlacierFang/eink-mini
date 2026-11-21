"""赛博木鱼：累计功德。

一个只增不减的计数器 —— 不按天清零，不设上限。
设备端在木鱼页按 B 键 = 敲一下；网页端点木鱼 = 敲一下。两条路写同一个计数。

状态落在 data/merit.json：服务端是 gunicorn 2 worker，内存态跨 worker 不可见，
所以状态落盘，写入走 flock 锁 + 原子替换。

素材在 ../images/：1.png 抬槌 / 2.png 击打 / 3.png 挥过。
"""

import fcntl
import json
import os
import time
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from PIL import Image

SERVER_DIR = Path(__file__).resolve().parent
DATA_DIR = SERVER_DIR / "data"
STATE_FILE = DATA_DIR / "merit.json"
LOCK_FILE = DATA_DIR / "merit.lock"

IMAGE_DIR = SERVER_DIR.parent / "images"

FRAME_IDLE = 0
FRAME_STRIKE = 1
FRAME_SWING = 2
FRAME_FILES = {FRAME_IDLE: "1.png", FRAME_STRIKE: "2.png", FRAME_SWING: "3.png"}

MERIT_PAGE_ID = "merit"

# 判定「用户主动敲」而不是「自动轮询」：
#
# 固件每 30 秒拉一次 manifest，拉完立刻拉当前页位图 ——
# 所以稳态下请求序列是 manifest -> 位图，一对一对的。
# 用户在木鱼页按 B 键（刷新当前页）会多出一次位图请求，
# 前面没有 manifest 兜底 —— 这一对位图请求挨得很近。
#
# 只认「上一次也是木鱼页位图」：从别的页切进木鱼页也会多一次请求，
# 但那次的上一请求是别的页，排掉。
#
# 29 秒的上限：manifest 拉失败时固件会自己补一次位图（周期 30 秒），
# 那次也是没有 manifest 兜底，但离上一次拉取超过 30 秒，不算敲。
# 卡在 29 秒是为了把「误判窗口」压到 1 秒：用户在前 29 秒内敲都算数。
TAP_MAX_GAP_SEC = 29.0

# 网页端敲击限流：同一 IP 每分钟最多 60 次。
WEB_TAPS_PER_MIN = 60


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
            state = json.load(fh)
    except (OSError, ValueError):
        state = {}
    if not isinstance(state, dict):
        state = {}
    state.setdefault("count", 0)
    state.setdefault("strike", 0)
    state.setdefault("updated_at", 0)
    state.setdefault("last_source", "")
    state.setdefault("devices", {})
    return state


def _write_state(state):
    tmp = STATE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False)
    os.replace(tmp, STATE_FILE)


def count():
    """当前累计功德。"""
    return int(_read_state().get("count", 0) or 0)


def stats():
    state = _read_state()
    return {
        "count": int(state.get("count", 0) or 0),
        "strike": int(state.get("strike", 0) or 0),
        "updated_at": int(state.get("updated_at", 0) or 0),
    }


def frame_for_strike(strike):
    """敲一次出一帧：击打 -> 挥过 -> 静息，循环。

    设备每敲一次只回一帧，三帧轮着来，按键连敲就是一段动画。
    """
    return int(strike) % 3


def frame_path(frame):
    return IMAGE_DIR / FRAME_FILES.get(frame, FRAME_FILES[FRAME_IDLE])


@lru_cache(maxsize=16)
def _frame_rgba_scaled(frame, px):
    """素材帧 -> 缩放好的 RGBA。缓存住，因为 LANCZOS 缩放很贵（36ms）。

    素材是固定文件，进程内不会变。改了图片要重启服务才生效。
    """
    path = frame_path(frame)
    if not path.exists():
        return None
    rgba = Image.open(path).convert("RGBA")
    if rgba.size != (px, px):
        rgba = rgba.resize((px, px), Image.LANCZOS)
    return rgba


def frame_gray(frame, px):
    """素材帧 -> 灰度图（白底），px 是输出边长。

    PNG 是 RGBA：先按 alpha 合成到白底再转灰度，透明区是白不是黑。
    """
    rgba = _frame_rgba_scaled(frame, px)
    if rgba is None:
        return Image.new("L", (px, px), 255)
    white = Image.new("L", (px, px), 255)
    white.paste(rgba.convert("L"), (0, 0), rgba.split()[3])
    return white


_web_taps = {}


def _allow_web_tap(ip):
    now = time.time()
    hits = [t for t in _web_taps.get(ip, []) if now - t < 60]
    if len(hits) >= WEB_TAPS_PER_MIN:
        _web_taps[ip] = hits
        return False
    hits.append(now)
    _web_taps[ip] = hits
    return True


def tap(source="web", ip=None):
    """网页端敲一下。count +1，返回新计数。"""
    if ip and not _allow_web_tap(ip):
        return None
    with _locked():
        state = _read_state()
        state["count"] = int(state.get("count", 0) or 0) + 1
        state["strike"] = int(state.get("strike", 0) or 0) + 1
        state["updated_at"] = int(time.time())
        state["last_source"] = source
        _write_state(state)
        return {"count": state["count"], "strike": state["strike"]}


def note_page_explicit(device_key, page_id, frame):
    """固件显式指定要显示的帧（请求带 ?f=N）。

    只有击打帧（f=1）计一次功德 —— 一次按键连发三帧请求，
    算起来还是敲一下、功德 +1。挥过帧和静息帧只是同一次敲击的后续画面。

    返回 (当前计数, 要显示的帧)。
    """
    frame = int(frame) % 3
    if not device_key:
        return count(), FRAME_IDLE
    with _locked():
        state = _read_state()
        devices = state.setdefault("devices", {})
        device = devices.setdefault(device_key, {})
        now = time.time()
        if page_id == MERIT_PAGE_ID and frame == FRAME_STRIKE:
            state["count"] = int(state.get("count", 0) or 0) + 1
            state["strike"] = int(state.get("strike", 0) or 0) + 1
            state["updated_at"] = int(now)
            state["last_source"] = "device"
        # 不动 last_kind / last_page / last_page_at ——
        # 那是「自动轮询 vs 用户按键」的启发式依据。
        # 显式帧的敲击请求不参与它，否则三帧请求会把下一次自动轮询
        # 误判成又敲了一下。
        _write_state(state)
        count_v = int(state.get("count", 0) or 0)
    return count_v, frame


def note_page_explicit_batch(device_key, page_id, frames):
    """固件一次要多帧（请求带 ?f=1,2,0 —— 木鱼敲击的三帧）。

    为什么合并成一次请求：设备走 frp 隧道到公网域名，一次往返约 450ms，
    分三次请求就是 1.4 秒，比面板刷新本身（3 × 420ms）还慢。

    计数语义和逐帧请求完全一致：**只有击打帧（f=1）计一次功德**，
    三帧一次取回也算敲一下、功德 +1。三帧用同一个计数渲染。

    返回渲染用的计数。
    """
    frames = [int(f) % 3 for f in frames]
    if not device_key:
        return count()
    with _locked():
        state = _read_state()
        count_v = int(state.get("count", 0) or 0)
        if FRAME_STRIKE in frames:
            count_v += 1
            state["count"] = count_v
            state["strike"] = int(state.get("strike", 0) or 0) + 1
            state["updated_at"] = int(time.time())
            state["last_source"] = "device"
            _write_state(state)
    return count_v


def note_manifest(device_key):
    """设备拉了 manifest。记下来 —— 下一次位图请求若紧跟其后，就是自动轮询。"""
    if not device_key:
        return
    with _locked():
        state = _read_state()
        devices = state.setdefault("devices", {})
        device = devices.setdefault(device_key, {})
        device["last_kind"] = "manifest"
        _write_state(state)


def note_page(device_key, page_id):
    """设备拉了某个页面的位图。

    返回 (是否算敲了一下, 当前计数, 该显示哪一帧)。
    """
    if not device_key:
        return False, count(), FRAME_IDLE
    with _locked():
        state = _read_state()
        devices = state.setdefault("devices", {})
        device = devices.setdefault(device_key, {})
        now = time.time()
        is_tap = False
        if page_id == MERIT_PAGE_ID:
            last_kind = device.get("last_kind", "")
            last_page = device.get("last_page", "")
            last_at = float(device.get("last_page_at", 0.0) or 0.0)
            if (last_kind == "page"
                    and last_page == MERIT_PAGE_ID
                    and (now - last_at) < TAP_MAX_GAP_SEC):
                is_tap = True
                state["count"] = int(state.get("count", 0) or 0) + 1
                state["strike"] = int(state.get("strike", 0) or 0) + 1
                state["updated_at"] = int(now)
                state["last_source"] = "device"
        device["last_kind"] = "page"
        device["last_page"] = page_id
        device["last_page_at"] = now
        _write_state(state)
        count_v = int(state.get("count", 0) or 0)
        strike = int(state.get("strike", 0) or 0)
    if is_tap:
        return True, count_v, frame_for_strike(strike)
    return False, count_v, FRAME_IDLE
