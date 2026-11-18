"""eink-mini 服务端：页面清单 + 1bpp 位图 + 设备状态 + 功能配置。

设备侧契约（与固件 ink_client.cpp 对齐）：
  GET  /api/manifest.json      页面清单，最多 12 页
  GET  /api/page/{id}.bin      1bpp 帧，296x128，4736 字节

浏览器侧：
  GET  /                       控制台（标签页：设备 + 每个功能一区）
  GET  /preview/{id}.png       页面预览图
  GET  /api/config             读配置
  POST /api/config             改配置
  GET  /api/device             设备在线状态
"""

import hashlib
import json
import threading
from datetime import datetime

from flask import Flask, Response, jsonify, render_template, request

import config_store
import device_state
import native_render
import pages
import renderer
import weather

app = Flask(__name__)

MAX_PAGES = 12

# 配置字段表：控制台的表单和 POST 校验都从这里长出来。
# 加一个可配置项 = 在这里加一行，前后端都跟着长，不用改两处。
CONFIG_FIELDS = {
    "city": {
        "label": "城市",
        "type": "text",
        "hint": "填城市名，比如「杭州」。改了会重新查坐标并立刻取一次天气。",
    },
    "device_title": {
        "label": "屏幕标题",
        "type": "text",
        "hint": "显示在设备时钟页右上角。只能用 ASCII —— 设备屏没有中文字库。",
    },
}

# 页面注册表：id、type、标题、控制台里归到哪个功能分区
# type 的含义由固件决定：native=设备本地渲染，bitmap=服务端下发位图
PAGES = [
    {
        "id": "clock",
        "type": "native",
        "title": "时钟",
        "label": "CLOCK",
        "desc": "设备本地渲染的翻页钟，断网也能显示，不消耗服务端。",
        "fields": ["device_title"],
    },
    {
        "id": "timer",
        "type": "timer",
        "title": "计时器",
        "label": "TIMER",
        "desc": "设备本地倒计时。预设固定在固件里，不消耗服务端；"
                "短按启停、双击换预设、长按重置。",
        "fields": [],
    },
    {
        "id": "weather",
        "type": "bitmap",
        "title": "天气",
        "label": "WEATHER",
        "desc": "服务端取 Open-Meteo 的当前天气和三天预报，渲染成位图下发。",
        "fields": ["city"],
    },
    {
        "id": "calendar",
        "type": "bitmap",
        "title": "月历",
        "label": "CALENDAR",
        "desc": "当月日历，服务端渲染成位图下发。当天日期反白高亮。",
        "fields": [],
    },
]

# 渲染缓存：key = (page_id, 缓存键)，值 = (图片, 失效时间戳)
_cache = {}
_cache_lock = threading.Lock()


def _cache_key(page_id):
    if page_id == "weather":
        # 天气缓存的取数时间是缓存键：数据没更新就不重画
        return (page_id, "weather", weather.get_weather_stamp())
    if page_id == "calendar":
        return (page_id, "calendar", datetime.now().strftime("%Y%m%d"))
    return (page_id, "static", "")


def render_page(page_id):
    """渲染指定页面，返回 (清晰层, 图标列表)。只读缓存，不碰网络。

    图标列表每项是 (ox, oy, 局部清晰层, 局部灰阶层)，
    量化时叠进页面（见 renderer.page_mask）。
    """
    key = _cache_key(page_id)
    now = datetime.now().timestamp()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and hit[1] > now:
            return hit[0]
    if page_id == "weather":
        cfg = config_store.get_config()
        layers = pages.render_weather(weather.get_weather(), cfg["city"])
    elif page_id == "calendar":
        layers = pages.render_calendar()
    else:
        raise KeyError(page_id)
    with _cache_lock:
        _cache[key] = (layers, now + 60)
    return layers


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
    w = weather.get_weather()
    features = []
    for p in PAGES:
        features.append(
            {
                "id": p["id"],
                "title": p["title"],
                "label": p["label"],
                "type": p["type"],
                "desc": p["desc"],
                "fields": [
                    {
                        "key": k,
                        "label": CONFIG_FIELDS[k]["label"],
                        "hint": CONFIG_FIELDS[k]["hint"],
                        "value": cfg.get(k, ""),
                    }
                    for k in p["fields"]
                    if k in CONFIG_FIELDS
                ],
            }
        )
    native_meta = {
        p["id"]: native_render.get_meta(p["id"])
        for p in PAGES
        if p["type"] in ("native", "timer")
    }
    return render_template(
        "index.html",
        features=features,
        config=cfg,
        device=state,
        device_online=device_state.is_online(state),
        weather=w,
        weather_at=weather.get_weather_at(),
        native_meta=native_meta,
    )


def _native_preview(page_id):
    """native 页（时钟 / 计时器）的预览。

    走后台线程的落盘缓存 —— 请求里不编译、不跑子进程。
    """
    state = request.args.get("state")
    if state:
        # 临时态：按需渲染，不落缓存（只有点那几个状态链接时才走）
        try:
            img = native_render.render_timer_state(state)
        except KeyError:
            return Response(status=404)
        except Exception:
            return Response(status=503)
        return Response(renderer.image_to_png(img), mimetype="image/png")
    png = native_render.get_preview_png(page_id)
    if not png:
        return Response(status=503)
    return Response(png, mimetype="image/png")


@app.route("/api/health")
def health():
    return jsonify({"ok": True, "service": "eink-mini", "time": datetime.now().isoformat()})


def _page_version(page_id):
    """页面内容指纹：内容不变则版本不变。

    只用便宜的输入算，绝不在这里渲染页面 —— 渲染会拖慢清单接口，
    而设备等不了。
    """
    entry = _page_entry(page_id)
    if not entry:
        return 0
    cfg = config_store.get_config()
    if page_id == "weather":
        seed = "weather|%s|%.4f|%.4f|%d" % (
            cfg["city"], cfg["lat"], cfg["lon"], weather.get_weather_stamp()
        )
    elif page_id == "calendar":
        seed = "calendar|%s" % datetime.now().strftime("%Y%m%d")
    else:
        seed = "clock|%s" % cfg.get("device_title", "")
    return int(hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8], 16)


def _manifest_version():
    payload = json.dumps([_page_version(p["id"]) for p in PAGES], sort_keys=True)
    return int(hashlib.sha1(payload.encode("utf-8")).hexdigest()[:8], 16)


@app.route("/api/manifest.json")
def manifest():
    cfg = config_store.get_config()
    pages_out = []
    for i, p in enumerate(PAGES[:MAX_PAGES]):
        # native 页由设备本地渲染，标题直接用配置里的 device_title，
        # 这样控制台改标题才会真的出现在屏上
        label = p["label"]
        # 只有 clock 页用配置里的 device_title。timer 是另一种 native 页，
        # 标题固定 —— 用 device_title 会把时钟标题套到计时器上。
        if p["type"] == "native" and p["id"] == "clock":
            label = cfg.get("device_title") or p["label"]
        pages_out.append(
            {
                "id": p["id"],
                "type": p["type"],
                "title": label,
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


@app.route("/api/page/<page_id>.bin")
def page_bin(page_id):
    entry = _page_entry(page_id)
    if not entry:
        return Response(status=404)
    if entry["type"] != "bitmap":
        return Response(status=400)
    try:
        crisp, icon_specs = render_page(page_id)
    except KeyError:
        return Response(status=404)
    data = renderer.frame_from_page(crisp, icon_specs)
    resp = Response(data, mimetype="application/octet-stream")
    resp.headers["Content-Length"] = str(len(data))
    device_state.record(
        "page/" + page_id + ".bin",
        ip=request.remote_addr,
        user_agent=request.headers.get("User-Agent"),
    )
    return resp


# 预览 = 设备真正收到的那张 1bpp 位图。
# 加 ?view=gray 拿量化前的灰度图，只为调试用，不占界面。
@app.route("/preview/<page_id>.png")
def preview_png(page_id):
    entry = _page_entry(page_id)
    if not entry:
        return Response(status=404)
    if entry["type"] in ("native", "timer"):
        return _native_preview(page_id)
    try:
        crisp, icon_specs = render_page(page_id)
    except KeyError:
        return Response(status=404)
    if request.args.get("view") == "gray":
        # 量化前的灰度中间态，只为调试
        return Response(renderer.image_to_png(crisp), mimetype="image/png")
    return Response(
        renderer.image_to_png(renderer.page_view(crisp, icon_specs)),
        mimetype="image/png",
    )


@app.route("/api/config", methods=["GET"])
def get_cfg():
    return jsonify(config_store.get_config())


def _validate_field(key, raw):
    """校验一个配置项，返回 (值, 错误信息)。"""
    value = str(raw).strip()
    if key == "city":
        if not value:
            return None, "城市不能为空"
        hit = weather.geocode(value)
        if not hit:
            return None, "查不到这个城市：" + value
        return {"city": value, "lat": hit[0], "lon": hit[1]}, ""
    if key == "device_title":
        if not value:
            return None, "标题不能为空"
        if not value.isascii():
            return None, "标题只能用 ASCII（设备屏没有中文字库）"
        return {"device_title": value[:16]}, ""
    return None, "未知配置项：" + key


@app.route("/api/config", methods=["POST"])
def set_cfg():
    data = request.get_json(silent=True) or {}
    patch = {}
    for key, raw in data.items():
        if key not in CONFIG_FIELDS:
            continue
        values, err = _validate_field(key, raw)
        if err:
            return jsonify({"ok": False, "error": err}), 400
        patch.update(values)
    if not patch:
        return jsonify({"ok": False, "error": "没有可更新的字段"}), 400
    cfg = config_store.update_config(patch)
    # 改了城市要重取天气，但别让这个请求等着 —— 后台线程去取
    if "city" in patch:
        threading.Thread(
            target=weather.refresh, kwargs={"force": True}, daemon=True
        ).start()
    return jsonify({"ok": True, "config": cfg})


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


# 天气后台取数线程。gunicorn 每个 worker 各起一个，靠 flock 去重实际取数。
weather.start_background()

# native 页（时钟 / 计时器）后台渲染线程。控制台预览读它的落盘缓存。
native_render.start_background()


if __name__ == "__main__":
    import os

    port = int(os.environ.get("EINK_MINI_PORT", "18842"))
    app.run(host="127.0.0.1", port=port, threaded=True)
