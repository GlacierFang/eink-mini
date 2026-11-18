"""天气数据：Open-Meteo，后台线程取数，渲染路径只读缓存。

和 ai-agent-pet 的 petd 做法一致：取数放在后台线程，设备请求和预览渲染
都只读缓存，不碰网络 —— 设备 HTTP 超时 15 秒，服务端在请求里取数会
直接把这一页拉挂。

缓存落盘 + flock：gunicorn 起 2 个 worker，内存缓存各算各的会重复取数，
而且 worker 换了内存态就没了。落盘一份，谁抢到 flock 谁去取。
"""

import json
import logging
import os
import pathlib
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

log = logging.getLogger("eink-mini.weather")

DATA_DIR = pathlib.Path(__file__).resolve().parent / "data"
CACHE_PATH = DATA_DIR / "weather_cache.json"
LOCK_PATH = DATA_DIR / "weather_cache.lock"

TTL_SEC = 1800        # 天气 30 分钟不变
GEO_TTL_SEC = 86400   # 城市名 -> 坐标，一天内不重复查
POLL_SEC = 300        # 后台线程多久醒一次

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"

# 天气城市。地理编码只认地级市（「杭州市西湖区」查不到），
# 所以常见城市直接内置，省一次请求也省一次猜错。
CITY_COORDINATES = {
    "北京": (39.90, 116.40), "上海": (31.23, 121.47),
    "广州": (23.13, 113.26), "深圳": (22.54, 114.06),
    "杭州": (30.27, 120.15), "南京": (32.06, 118.80),
    "成都": (30.57, 104.07), "重庆": (29.56, 106.55),
    "武汉": (30.59, 114.31), "西安": (34.26, 108.94),
    "苏州": (31.30, 120.62), "天津": (39.13, 117.20),
    "长沙": (28.23, 112.94), "郑州": (34.75, 113.65),
    "青岛": (36.07, 120.38), "大连": (38.91, 121.60),
    "厦门": (24.48, 118.09), "昆明": (25.04, 102.68),
    "合肥": (31.82, 117.23), "福州": (26.07, 119.30),
    "哈尔滨": (45.75, 126.65), "沈阳": (41.80, 123.43),
    "济南": (36.65, 116.99), "石家庄": (38.04, 114.51),
    "长春": (43.88, 125.32), "南昌": (28.68, 115.86),
    "贵阳": (26.65, 106.63), "南宁": (22.82, 108.32),
    "太原": (37.87, 112.55), "兰州": (36.06, 103.83),
    "海口": (20.04, 110.35), "银川": (38.49, 106.23),
    "西宁": (36.62, 101.78), "呼和浩特": (40.84, 111.75),
    "乌鲁木齐": (43.83, 87.62), "拉萨": (29.65, 91.13),
    "香港": (22.32, 114.17), "澳门": (22.20, 113.55),
    "台北": (25.03, 121.57), "东京": (35.68, 139.69),
    "首尔": (37.57, 126.98), "新加坡": (1.35, 103.82),
    "纽约": (40.71, -74.01), "伦敦": (51.51, -0.13),
    "巴黎": (48.86, 2.35), "悉尼": (-33.87, 151.21),
    "温哥华": (49.28, -123.12), "旧金山": (37.77, -122.42),
}

DEFAULT_CITY = "北京"

# WMO 天气码 -> 中文。用中国气象的观测术语，不是自造的译法。
WMO_CN = {
    0: "晴", 1: "晴间多云", 2: "多云", 3: "阴", 45: "雾", 48: "雾凇",
    51: "小毛毛雨", 53: "毛毛雨", 55: "强毛毛雨",
    56: "轻冻毛毛雨", 57: "强冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨", 66: "轻冻雨", 67: "强冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "米雪",
    80: "阵雨", 81: "强阵雨", 82: "暴雨",
    85: "阵雪", 86: "强阵雪",
    95: "雷阵雨", 96: "雷阵雨伴冰雹", 99: "强雷阵雨伴冰雹",
}

# 屏上用的简称。
#
# 屏只有 296 像素宽，右栏还要给大温度让路。
# 所以这里刻意用短名 —— 不是把长描述截断（那会切出「强毛毛」这种怪词），
# 而是每个天气码单独设计一个短名。
#
# 长描述 WMO_CN 仍然保留，控制台和接口用完整的。
WMO_SHORT = {
    0: "晴", 1: "晴多云", 2: "多云", 3: "阴", 45: "雾", 48: "雾凇",
    51: "毛毛雨", 53: "毛毛雨", 55: "强雨",
    56: "冻雨", 57: "强冻雨",
    61: "小雨", 63: "中雨", 65: "大雨", 66: "冻雨", 67: "强冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "米雪",
    80: "阵雨", 81: "强阵雨", 82: "暴雨",
    85: "阵雪", 86: "强阵雪",
    95: "雷阵雨", 96: "雷雹", 99: "雷暴",
}

_geo_cache = {}
_geo_lock = threading.Lock()


def _num(value):
    """取个整数出来。取不到就空字符串 —— 屏上不显示 0 度的假数据。"""
    try:
        return str(int(round(float(value))))
    except (TypeError, ValueError):
        return ""


def describe_short(code):
    """WMO 天气码 -> 屏上用的简称。取不到就空字符串。

    屏上空间紧，长描述会撞到大温度，所以用每个码单独设计的短名。
    """
    if code is None:
        return ""
    try:
        return WMO_SHORT.get(int(code), "")
    except (TypeError, ValueError):
        return ""


def describe(code):
    """WMO 天气码 -> 中文描述。取不到就空字符串。"""
    if code is None:
        return ""
    try:
        return WMO_CN.get(int(code), "")
    except (TypeError, ValueError):
        return ""


def _get_json(url, params=None, timeout=8):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "eink-mini/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _geocode(name):
    """城市名 -> (lat, lon, 显示名)。先查国内，再查全球。"""
    for extra in ({"countryCode": "CN"}, {}):
        params = {"name": name, "count": 1, "language": "zh", "format": "json"}
        params.update(extra)
        try:
            data = _get_json(GEOCODING_URL, params)
        except Exception as exc:
            log.warning("地理编码失败 %s: %s", name, exc)
            return None
        results = data.get("results") or []
        if results:
            r = results[0]
            label = str(r.get("name") or name)
            admin = r.get("admin1") or ""
            if admin and admin not in label:
                label = label + " " + admin
            return float(r["latitude"]), float(r["longitude"]), label
    return None


def _resolve(city):
    """城市名 -> (lat, lon, 显示名)。查不到就用默认城市。"""
    name = str(city or "").strip()
    if not name:
        name = DEFAULT_CITY
    if name in CITY_COORDINATES:
        lat, lon = CITY_COORDINATES[name]
        return lat, lon, name
    # 「杭州市」这种带后缀的，剥掉再试
    simple = name[:-1] if name.endswith("市") else name
    if simple in CITY_COORDINATES:
        lat, lon = CITY_COORDINATES[simple]
        return lat, lon, simple
    with _geo_lock:
        hit = _geo_cache.get(name)
    if hit and time.time() - hit[2] < GEO_TTL_SEC:
        return hit[0], hit[1], hit[3]
    found = _geocode(name)
    if not found:
        lat, lon = CITY_COORDINATES[DEFAULT_CITY]
        return lat, lon, DEFAULT_CITY
    lat, lon, label = found
    with _geo_lock:
        _geo_cache[name] = (lat, lon, time.time(), label)
    return lat, lon, label


def geocode(city):
    """对外：城市名 -> (lat, lon, 显示名)。查不到返回 None。"""
    return _resolve(city) if str(city or "").strip() else None


def _fetch(lat, lon, city):
    """Open-Meteo：当前天气 + 未来 3 天预报。失败返回 None。"""
    data = _get_json(
        FORECAST_URL,
        {
            "latitude": round(float(lat), 4),
            "longitude": round(float(lon), 4),
            "current": "temperature_2m,weather_code,relative_humidity_2m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min",
            # 逐小时页要的数据：温度曲线 + 降水概率。
            "hourly": "temperature_2m,precipitation_probability",
            "forecast_days": 3,
            "forecast_hours": 24,
            "timezone": "auto",
        },
        timeout=12,
    )
    cur = data.get("current") or {}
    daily = data.get("daily") or {}
    dates = daily.get("time") or []
    codes = daily.get("weather_code") or []
    tmaxs = daily.get("temperature_2m_max") or []
    tmins = daily.get("temperature_2m_min") or []
    days = []
    for i, day in enumerate(dates):
        days.append(
            {
                "date": day,
                "code": codes[i] if i < len(codes) else None,
                "tmax": _num(tmaxs[i]) if i < len(tmaxs) else "",
                "tmin": _num(tmins[i]) if i < len(tmins) else "",
            }
        )
    # ---- 逐小时：从「当前这一小时」起取 12 个点 ----
    #
    # open-meteo 的 hourly.time 是当地时间的 ISO 串（timezone=auto）。
    # 起点按**本机当前小时**找，而不是取数组开头 —— 数组头是当天 00:00，
    # 拿 00:00 起 12 个点等于「过去 12 小时」，不是预报。
    hourly = data.get("hourly") or {}
    h_times = hourly.get("time") or []
    h_temps = hourly.get("temperature_2m") or []
    h_pops = hourly.get("precipitation_probability") or []
    hourly_rows = []
    if h_times:
        now_h = datetime.now().replace(minute=0, second=0, microsecond=0)
        start = 0
        for i, t in enumerate(h_times):
            try:
                dt = datetime.strptime(str(t)[:13], "%Y-%m-%dT%H")
            except (TypeError, ValueError):
                continue
            if dt >= now_h:
                start = i
                break
        for i in range(start, min(start + 12, len(h_times))):
            try:
                dt = datetime.strptime(str(h_times[i])[:13], "%Y-%m-%dT%H")
            except (TypeError, ValueError):
                continue
            hourly_rows.append({
                "time": str(h_times[i]),
                "hour": dt.hour,
                "temp": _num(h_temps[i]) if i < len(h_temps) else "",
                "pop": _num(h_pops[i]) if i < len(h_pops) else "",
            })

    return {
        "city": city,
        "temp": _num(cur.get("temperature_2m")),
        "code": cur.get("weather_code"),
        "humidity": _num(cur.get("relative_humidity_2m")),
        "days": days,
        "hourly": hourly_rows,
    }


def _read_cache():
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _write_cache(payload):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(CACHE_PATH))


def get_weather():
    """只读缓存，瞬时返回。拿不到返回 None —— 屏上显示占位，不显示假数据。"""
    payload = _read_cache()
    if not payload or not payload.get("data"):
        return None
    return payload["data"]


def get_weather_stamp():
    """缓存取数时间戳。页面版本号靠它：天气更新了版本才变。"""
    payload = _read_cache()
    if not payload:
        return 0
    return int(payload.get("at") or 0)


def refresh(force=False):
    """取一次数写进缓存。抢 flock，别的 worker 直接返回 False。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    lock_fh = None
    try:
        if fcntl is not None:
            lock_fh = open(str(LOCK_PATH), "w")
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        payload = _read_cache()
        if not force and payload and (time.time() - float(payload.get("at") or 0)) < TTL_SEC:
            return False
        import config_store

        cfg = config_store.get_config()
        lat, lon, label = _resolve(cfg.get("city"))
        data = _fetch(lat, lon, label)
        if data is None:
            # 取数失败：保留上次成功的数据，只更新城市标签
            if payload and payload.get("data"):
                old = dict(payload["data"])
                old["city"] = label
                _write_cache({"at": payload.get("at"), "data": old})
            return False
        _write_cache({"at": time.time(), "data": data})
        return True
    except Exception as exc:
        log.warning("天气取数失败: %s", exc)
        return False
    finally:
        if lock_fh is not None:
            try:
                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            lock_fh.close()


def _loop():
    while True:
        try:
            refresh()
        except Exception as exc:
            log.warning("天气后台线程异常: %s", exc)
        time.sleep(POLL_SEC)


_started = False
_start_lock = threading.Lock()


def start_background():
    """起后台取数线程。gunicorn 每个 worker 会各起一个，靠 flock 去重。"""
    global _started
    with _start_lock:
        if _started:
            return
        _started = True
    t = threading.Thread(target=_loop, name="weather-poll", daemon=True)
    t.start()


# 预报行用的短描述，控制在 3 个字以内。
# 三列并排，列宽有限 —— 描述写长了会被裁，切一半的词更难认。
# 用中国气象的规范简称：晴多云 / 毛毛雨 / 雷阵雨 / 冰雹。
def get_weather_at():
    """缓存取数时间，人类可读格式。取不到就空串。"""
    stamp = get_weather_stamp()
    if not stamp:
        return ""
    try:
        return datetime.fromtimestamp(stamp).strftime("%Y-%m-%d %H:%M")
    except (OSError, OverflowError, ValueError):
        return ""
