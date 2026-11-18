"""native 页（时钟 / 计时器）的主机端渲染。

native 页是设备本地画的，服务端不下发位图 —— 但控制台要看画面。
主机端渲染器编译的是**同一份** ink_canvas.cpp / ink_pages.cpp，
画出来的像素和设备上的一致，不是「长得像」。

后台线程渲染，结果落盘缓存；请求只读缓存，不阻塞。

预览代表什么状态：
  - 时钟页：服务端当前时间。设备校时后显示的也是这个时间（时区同样 +8）。
  - 计时器页：**代表性状态**（READY / 15 分钟预设）。
    真实倒计时在设备 RAM 里，服务端看不到，也不假装看得到。
    控制台会明确标注这一点。

帧格式和设备收到的 /api/page/*.bin 完全一致：
296x128、1bpp、MSB first、每行 37 字节、共 4736 字节，1 = 黑。
"""

import fcntl
import json
import logging
import os
import pathlib
import subprocess
import tempfile
import threading
import time

log = logging.getLogger("eink-mini.native")

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
FW = REPO / "firmware"
DATA_DIR = HERE / "data"
CACHE_DIR = DATA_DIR / "native"
BIN = DATA_DIR / "host_render"
LOCK_PATH = DATA_DIR / "native_render.lock"

W, H, ROW = 296, 128, 37
FRAME_BYTES = ROW * H

SRC_FILES = [
    FW / "src" / "ink_canvas.cpp",
    FW / "src" / "ink_pages.cpp",
    FW / "src" / "ink_font_big.cpp",
    FW / "tools" / "host_render.cpp",
]


CLOCK_TTL = 10        # 时钟页有秒，10 秒刷一次
TIMER_TTL = 600       # 代表性状态基本不变
TIMER_STATES = ("READY", "RUN", "PAUSE", "DONE")
TIMER_REMAIN = {"READY": 900, "RUN": 754, "PAUSE": 754, "DONE": 0}


def _need_build():
    """固件渲染代码改了就得重编主机渲染器。"""
    try:
        built = BIN.stat().st_mtime
    except OSError:
        return True
    for src in SRC_FILES:
        try:
            if src.stat().st_mtime > built:
                return True
        except OSError:
            return True
    return False


def build():
    """编译主机渲染器。gunicorn 每个 worker 都可能来抢，靠 flock 排队，只编一次。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(str(LOCK_PATH), "w") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            if not _need_build():
                return True
            tmp = BIN.with_name(BIN.name + ".tmp")
            cmd = [
                "g++", "-std=c++11", "-O2", "-I", str(FW / "src"),
                str(FW / "src" / "ink_canvas.cpp"),
                str(FW / "src" / "ink_pages.cpp"),
                str(FW / "src" / "ink_font_big.cpp"),
                str(FW / "tools" / "host_render.cpp"),
                "-o", str(tmp),
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if res.returncode != 0:
                raise RuntimeError("主机渲染器编译失败:\n" + (res.stderr or "")[-800:])
            os.replace(str(tmp), str(BIN))
            log.info("主机渲染器已编译: %s", BIN)
            return True
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _run_frame(page, **kw):
    """跑一次渲染，取回设备帧字节。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".bin", dir=str(DATA_DIR))
    os.close(fd)
    try:
        args = [str(BIN), "frame", page, tmp]
        for key, value in kw.items():
            args.append("%s=%s" % (key, value))
        res = subprocess.run(args, capture_output=True, text=True, timeout=30)
        if res.returncode != 0:
            raise RuntimeError(
                "渲染 %s 失败: %s" % (page, (res.stderr or res.stdout or "").strip()[-400:])
            )
        data = pathlib.Path(tmp).read_bytes()
        if len(data) != FRAME_BYTES:
            raise RuntimeError("帧长不对: %d（应为 %d）" % (len(data), FRAME_BYTES))
        return data
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def frame_to_image(data):
    """设备帧 -> 灰度图。1 = 黑（和 check_frame.py 同一套解法）。"""
    from PIL import Image

    img = Image.new("L", (W, H), 255)
    px = img.load()
    for y in range(H):
        row = data[y * ROW:(y + 1) * ROW]
        for x in range(W):
            if (row[x >> 3] >> (7 - (x & 7))) & 1:
                px[x, y] = 0
    return img


def _clock_kwargs():
    return {
        "epoch": int(time.time()),
    }


def _timer_kwargs(state="READY", remaining=900):
    return {
        "state": state,
        "remaining": remaining,
    }


def render_timer_state(state):
    """按需渲染计时器的某一种状态（不落缓存）。"""
    state = str(state).upper()
    if state not in TIMER_STATES:
        raise KeyError(state)
    build()
    data = _run_frame("timer", **_timer_kwargs(state, TIMER_REMAIN[state]))
    return frame_to_image(data)


def _cache_path(page):
    return CACHE_DIR / ("%s.png" % page)


def _meta_path(page):
    return CACHE_DIR / ("%s.json" % page)


def _write_cache(page, img):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    png = _cache_path(page)
    tmp = png.with_name(png.name + ".tmp")
    img.save(str(tmp), format="PNG")
    os.replace(str(tmp), str(png))
    _meta_path(page).write_text(
        json.dumps(
            {
                "page": page,
                "rendered_at": time.time(),
                "rendered_at_text": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
        ),
        encoding="utf-8",
    )


def get_preview_png(page):
    """读后台渲染好的 PNG。没有就返回 None（调用方回 503）。"""
    try:
        return _cache_path(page).read_bytes()
    except OSError:
        return None


def get_meta(page):
    try:
        return json.loads(_meta_path(page).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _refresh(page):
    build()
    if page == "clock":
        img = frame_to_image(_run_frame("clock", **_clock_kwargs()))
    else:
        img = frame_to_image(_run_frame("timer", **_timer_kwargs()))
    _write_cache(page, img)


def _stale(page, ttl):
    meta = get_meta(page)
    return (time.time() - float(meta.get("rendered_at") or 0)) > ttl


def _loop():
    while True:
        for page, ttl in (("clock", CLOCK_TTL), ("timer", TIMER_TTL)):
            try:
                if _stale(page, ttl):
                    _refresh(page)
            except Exception as exc:
                log.warning("native 渲染 %s 失败: %s", page, exc)
        time.sleep(CLOCK_TTL)


_start_lock = threading.Lock()
_started = False


def start_background():
    """起后台渲染线程。gunicorn 每个 worker 各起一个，编译靠 flock 去重。"""
    global _started
    with _start_lock:
        if _started:
            return
        _started = True
    thread = threading.Thread(target=_loop, name="native-render", daemon=True)
    thread.start()
