"""eink-mini 服务端：页面清单 + 1bpp 位图 + 留言板。

设备侧契约（与固件 ink_client.cpp 对齐）：
  GET  /api/manifest.json      页面清单，最多 12 页
  GET  /api/page/{id}.bin      1bpp 帧，296x128，4736 字节
  GET  /api/message            留言，字符串数组（最新在前）
  POST /api/message            写留言（需要 token，默认关闭）

浏览器侧：
  GET  /                       Web UI
  GET  /preview/{id}.png       页面预览图
"""

import json
import threading
from datetime import datetime

from flask import Flask, Response, jsonify, render_template, request

import config_store
import pages
import renderer
import store
import weather

app = Flask(__name__)

# 页面注册表：id、type（native/bitmap/message）、标题
# type 的含义由固件决定：native=设备本地渲染，bitmap=服务端下发位图，message=消息页
PAGES = [
    {"id": "clock", "type": "native", "title": "CLOCK"},
    {"id": "weather", "type": "bitmap", "title": "WEATHER"},
    {"id": "calendar", "type": "bitmap", "title": "CALENDAR"},
    {"id": "message", "type": "message", "title": "MESSAGE"},
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
    return render_template(
        "index.html",
        pages=PAGES,
        config=cfg,
        write_enabled=bool(cfg.get("write_token")),
        messages=store.list_messages(20),
    )


@app.route("/api/health")
def health():
    return jsonify({"ok": True, "service": "eink-mini", "time": datetime.now().isoformat()})


@app.route("/api/manifest.json")
def manifest():
    pages_out = []
    for i, p in enumerate(PAGES[:MAX_PAGES]):
        pages_out.append(
            {
                "id": p["id"],
                "type": p["type"],
                "title": p["title"],
                "order": i,
                "version": int(datetime.now().timestamp()),
            }
        )
    return jsonify(
        {
            "version": 1,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "pages": pages_out,
        }
    )


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
    return resp


@app.route("/preview/<page_id>.png")
def preview_png(page_id):
    entry = _page_entry(page_id)
    if not entry:
        return Response(status=404)
    if entry["type"] == "message":
        img = pages.render_message(store.list_messages(3))
    else:
        try:
            img = render_page(page_id)
        except KeyError:
            return Response(status=404)
    return Response(renderer.image_to_png(img), mimetype="image/png")


@app.route("/api/message")
def get_message():
    # 固件 collectStrings 期望字符串数组：最新一条在前
    msgs = store.list_messages(3)
    return jsonify([m.get("text", "") for m in msgs])


@app.route("/api/messages")
def list_messages():
    return jsonify(store.list_messages(50))


def _write_authorized():
    cfg = config_store.get_config()
    token = cfg.get("write_token") or ""
    if not token:
        return False, "写入接口未启用（服务端未配置 write_token）"
    given = request.headers.get("X-Token") or request.args.get("token") or ""
    if given != token:
        return False, "令牌不正确"
    return True, ""


@app.route("/api/message", methods=["POST"])
def post_message():
    ok, why = _write_authorized()
    if not ok:
        return jsonify({"ok": False, "error": why}), 403
    data = request.get_json(silent=True) or request.form or {}
    text = (data.get("text") or data.get("message") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "内容为空"}), 400
    item = store.add_message(text)
    return jsonify({"ok": True, "message": item})


@app.route("/api/messages", methods=["DELETE"])
def delete_messages():
    ok, why = _write_authorized()
    if not ok:
        return jsonify({"ok": False, "error": why}), 403
    store.clear_messages()
    return jsonify({"ok": True})


@app.route("/api/config", methods=["GET"])
def get_cfg():
    cfg = config_store.get_config()
    # 不把令牌明文吐出去
    cfg = dict(cfg)
    cfg["write_token"] = "***" if cfg.get("write_token") else ""
    cfg["write_enabled"] = bool(config_store.get_config().get("write_token"))
    return jsonify(cfg)


@app.route("/api/config", methods=["POST"])
def set_cfg():
    ok, why = _write_authorized()
    if not ok:
        return jsonify({"ok": False, "error": why}), 403
    data = request.get_json(silent=True) or {}
    patch = {}
    if "city" in data:
        city = str(data["city"]).strip()
        hit = weather.geocode(city)
        if hit:
            patch["city"] = city
            patch["lat"] = hit[0]
            patch["lon"] = hit[1]
    if "device_title" in data:
        patch["device_title"] = str(data["device_title"]).strip()[:32]
    if not patch:
        return jsonify({"ok": False, "error": "没有可更新的字段"}), 400
    return jsonify({"ok": True, "config": config_store.update_config(patch)})


if __name__ == "__main__":
    import os

    port = int(os.environ.get("EINK_MINI_PORT", "18842"))
    app.run(host="127.0.0.1", port=port, threaded=True)
