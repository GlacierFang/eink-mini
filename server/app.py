"""eink-mini 服务端：页面清单 + 1bpp 位图 + 设备状态。

设备侧契约（与固件 ink_client.cpp 对齐）：
  GET  /api/manifest.json      页面清单，最多 12 页
  GET  /api/page/{id}.bin      1bpp 帧，296x128，4736 字节

浏览器侧：
  GET  /                       控制台（功能分区：预览 + 配置 + 设备状态）
  GET  /preview/{id}.png       页面预览图
  GET  /api/config             读取配置
  POST /api/config             改配置
  GET  /api/device             设备在线状态
"""

import json
import threading
from datetime import datetime

from flask import Flask, Response, jsonify, render_template, request

import config_store
import device_state
import pages
import renderer
import weather

app = Flask(__name__)

# 页面注册表：id、type、标题
# type 的含义由固件决定：native=设备本地渲染，bitmap=服务端下发位图
PAGES = [
    {"id": "clock", "type": "native", "title": "CLOCK"},
    {"id": "weather", "type": "bitmap", "title": "WEATHER"},
    {"id": "calendar", "type": "bitmap", "title": "CALENDAR"},
]

MAX_PAGES = 12

# 渲染缓存：key = (page_id, 缓存键)，值 = (图片, 失效时间戳)
_cache = {}
_cache_lock = threading.Lock()

WEATHER_CACHE_KEY = "weather"
CALENDAR_CACHE_KEY = "calendar"


def _cache_key(page_id):
    if page_id == "weather":
        cfg = config_store.get_config()
        w = weather.get_weather(cfg["lat"], cfg["lon"], cfg["city"])
        stamp = "no-data" if not w else str(w.get("temp")) + str(w.get("code"))
        return (page_id, WEATHER_CACHE_KEY, stamp)
    if page_id == "calendar":
        return (page_id, CALENDAR_CACHE_KEY, datetime.now().strftime("%Y%m%d"))
    return (page_id, "static", "")


def render_page(page_id):
    """渲染指定页面，返回 PIL 图片。"""
    key = _cache_key(page_id)
    now = datetime.now().timestamp()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and hit[1] > now:
            return hit[0]
    if page_id == "weather":
        cfg = config_store.get_config()
        data = weather.get_weather(cfg["lat"], cfg["lon"], cfg["city"])
        img = pages.render_weather(data, cfg["city"])
    elif page_id == "calendar":
        img = pages.render_calendar()
    else:
        raise KeyError(page_id)
    with _cache_lock:
        _cache[key] = (img, now + 60)
    return img


def _page_entry(page_id):
    for p in PAGES:
        if p["id"] == page_id:
            return p
    return None


@app.after_request
def no_cache(resp):
    # 设备每 30 秒拉一次，别让中间代理缓存住旧帧
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/")
def index():
    cfg = config_store.get_config()
    state = device_state.get_state()
    return render_template(
        "index.html",
        pages=PAGES,
        config=cfg,
        device=state,
        device_online=device_state.is_online(state),
    )


@app.route("/api/health")
def health():
    return jsonify({"ok": True, "service": "eink-mini", "time": datetime.now().isoformat()})


@app.route("/api/manifest.json")
def manifest():
    # 设备靠 version 判断页面是否变了，所以 version 必须跟着内容走，
    # 不能用时间戳——那样每次请求都变，设备会反复重下所有位图。
    cfg = config_store.get_config()
    pages_out = []
    for i, p in enumerate(PAGES[:MAX_PAGES]):
        # native 页由设备本地渲染，标题直接用配置里的 device_title，
        # 这样控制台改标题才会真的出现在屏上
        title = p["title"]
        if p["type"] == "native":
            title = cfg.get("device_title") or p["title"]
        pages_out.append(
            {
                "id": p["id"],
                "type": p["type"],
                "title": title,
                "order": i,
                "version": _page_version(p["id"]),
            }
        )
    resp = jsonify(
        {
            "version": _manifest_version(),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "pages": pages_out,
        }
    )
    device_state.record(
        "manifest.json",
        ip=request.remote_addr,
        user_agent=request.headers.get("User-Agent"),
    )
    return resp


def _page_version(page_id):
    """页面内容指纹：内容不变则版本不变。

    只用便宜的输入算，绝不在这里渲染页面——渲染天气页会触发实时天气请求，
    会把清单接口阻塞住。版本号的作用是让设备知道"要不要重下这张图"，
    配置和日期变了才算变了，够用。
    """
    import hashlib

    entry = _page_entry(page_id)
    if not entry:
        return 0
    cfg = config_store.get_config()
    if page_id == "weather":
        seed = "weather|%s|%.4f|%.4f" % (cfg["city"], cfg["lat"], cfg["lon"])
    elif page_id == "calendar":
        seed = "calendar|%s" % datetime.now().strftime("%Y%m%d")
    else:
        seed = "clock|%s" % cfg.get("device_title", "")
    return int(hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8], 16)


def _manifest_version():
    import hashlib

    payload = json.dumps([_page_version(p["id"]) for p in PAGES], sort_keys=True)
    return int(hashlib.sha1(payload.encode("utf-8")).hexdigest()[:8], 16)


@app.route("/api/page/<page_id>.bin")
def page_bin(page_id):
    entry = _page_entry(page_id)
    if not entry:
        return Response(status=404)
    if entry["type"] != "bitmap":
        return Response(status=400)
    try:
        img = render_page(page_id)
    except KeyError:
        return Response(status=404)
    data = renderer.image_to_1bpp(img)
    resp = Response(data, mimetype="application/octet-stream")
    resp.headers["Content-Length"] = str(len(data))
    device_state.record(
        "page/" + page_id + ".bin",
        ip=request.remote_addr,
        user_agent=request.headers.get("User-Agent"),
    )
    return resp


@app.route("/preview/<page_id>.png")
def preview_png(page_id):
    entry = _page_entry(page_id)
    if not entry:
        return Response(status=404)
    try:
        img = render_page(page_id)
    except KeyError:
        return Response(status=404)
    return Response(renderer.image_to_png(img), mimetype="image/png")


@app.route("/api/config", methods=["GET"])
def get_cfg():
    return jsonify(config_store.get_config())


@app.route("/api/config", methods=["POST"])
def set_cfg():
    data = request.get_json(silent=True) or {}
    patch = {}
    if "city" in data:
        city = str(data["city"]).strip()
        if not city:
            return jsonify({"ok": False, "error": "城市不能为空"}), 400
        hit = weather.geocode(city)
        if not hit:
            return jsonify({"ok": False, "error": "查不到这个城市：" + city}), 400
        patch["city"] = city
        patch["lat"] = hit[0]
        patch["lon"] = hit[1]
    if "device_title" in data:
        title = str(data["device_title"]).strip()
        if not title:
            return jsonify({"ok": False, "error": "标题不能为空"}), 400
        # 设备屏上没有中文字库，标题只能是 ASCII
        if not title.isascii():
            return jsonify({"ok": False, "error": "标题只能用 ASCII（设备屏无中文字库）"}), 400
        patch["device_title"] = title[:16]
    if not patch:
        return jsonify({"ok": False, "error": "没有可更新的字段"}), 400
    return jsonify({"ok": True, "config": config_store.update_config(patch)})


@app.route("/api/device")
def api_device():
    state = device_state.get_state()
    return jsonify(
        {
            "online": device_state.is_online(state),
            "state": state,
            "pages": [p["id"] for p in PAGES],
        }
    )


if __name__ == "__main__":
    import os

    port = int(os.environ.get("EINK_MINI_PORT", "18842"))
    app.run(host="127.0.0.1", port=port, threaded=True)
