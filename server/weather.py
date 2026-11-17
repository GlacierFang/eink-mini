"""天气数据：Open-Meteo，带缓存与降级。

本机到 api.open-meteo.com / geocoding-api.open-meteo.com 直连和走代理都通。
"""

import threading
import time

import requests

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"

WMO_TEXT = {
    0: "晴", 1: "晴间多云", 2: "多云", 3: "阴",
    45: "雾", 48: "雾凇", 51: "毛毛雨", 53: "小雨", 55: "中雨",
    56: "冻毛毛雨", 57: "冻雨", 61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "强冻雨", 71: "小雪", 73: "中雪", 75: "大雪",
    77: "雪粒", 80: "阵雨", 81: "强阵雨", 82: "暴雨",
    85: "阵雪", 86: "强阵雪", 95: "雷阵雨", 96: "雷阵雨伴冰雹", 99: "强雷暴冰雹",
}

_cache = {"data": None, "ts": 0.0}
_lock = threading.Lock()
TTL = 600.0


def describe(code):
    if code is None:
        return "--"
    return WMO_TEXT.get(int(code), "WMO" + str(code))


def geocode(city):
    """城市名 -> (lat, lon, 显示名)。查不到返回 None。"""
    if not city:
        return None
    try:
        r = requests.get(
            GEOCODE_URL,
            params={"name": city, "count": 1, "language": "zh", "format": "json"},
            timeout=8,
        )
        r.raise_for_status()
        results = r.json().get("results") or []
    except (requests.RequestException, ValueError):
        return None
    if not results:
        return None
    hit = results[0]
    name = hit.get("name") or city
    admin = hit.get("admin1") or ""
    label = name
    if admin and admin not in name:
        label = name + " " + admin
    return float(hit["latitude"]), float(hit["longitude"]), label


def fetch_weather(lat, lon, city):
    """取当前天气 + 未来 3 天预报。失败返回 None。"""
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,weather_code,relative_humidity_2m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min",
        "forecast_days": 3,
        "timezone": "auto",
    }
    try:
        r = requests.get(FORECAST_URL, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError):
        return None
    cur = data.get("current") or {}
    daily = data.get("daily") or {}
    days = []
    dates = daily.get("time") or []
    codes = daily.get("weather_code") or []
    tmaxs = daily.get("temperature_2m_max") or []
    tmins = daily.get("temperature_2m_min") or []
    for i, day in enumerate(dates):
        days.append(
            {
                "date": day,
                "code": codes[i] if i < len(codes) else None,
                "tmax": tmaxs[i] if i < len(tmaxs) else None,
                "tmin": tmins[i] if i < len(tmins) else None,
            }
        )
    return {
        "city": city,
        "temp": cur.get("temperature_2m"),
        "code": cur.get("weather_code"),
        "humidity": cur.get("relative_humidity_2m"),
        "days": days,
    }


def get_weather(lat, lon, city):
    """带 10 分钟缓存的天气查询。取数失败时沿用上次成功的缓存。"""
    with _lock:
        now = time.time()
        if _cache["data"] and now - _cache["ts"] < TTL:
            return _cache["data"]
    data = fetch_weather(lat, lon, city)
    if data is not None:
        with _lock:
            _cache["data"] = data
            _cache["ts"] = time.time()
        return data
    with _lock:
        # 取数失败时沿用上次成功的缓存，别让屏幕变空白
        return _cache["data"]
