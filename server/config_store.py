"""配置存储：一个 JSON 文件，带内存缓存。

配置项：
  city          天气城市名（默认 北京）
  lat / lon     城市坐标（改城市时重新地理编码）
  hourly_city   逐小时页的城市（默认空 = 跟随天气页）
  hourly_lat / hourly_lon   逐小时页的城市坐标
"""

import json
import pathlib
import threading

DATA_DIR = pathlib.Path(__file__).resolve().parent / "data"
CONFIG_PATH = DATA_DIR / "config.json"

DEFAULTS = {
    "city": "北京",
    "lat": 39.9075,
    "lon": 116.39723,
    # 逐小时页的城市独立。空 = 没单独设过，运行时跟随天气页的城市。
    "hourly_city": "",
    "hourly_lat": None,
    "hourly_lon": None,
}

_lock = threading.Lock()


def _read():
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    merged = dict(DEFAULTS)
    if isinstance(data, dict):
        for k, v in data.items():
            if k in merged:
                merged[k] = v
    return merged


def get_config():
    with _lock:
        return _read()


def resolve_hourly(cfg=None):
    """逐小时页实际生效的城市 -> (city, lat, lon)。

    没单独设置过 hourly_city 就跟随天气页的城市 —— 第一次打开逐小时页
    显示的就是当前城市，不用先去设置一次。设过之后就彻底独立，
    天气页改城市不再影响逐小时页。
    """
    if cfg is None:
        cfg = get_config()
    city = str(cfg.get("hourly_city") or "").strip()
    if not city:
        return cfg["city"], cfg["lat"], cfg["lon"]
    lat = cfg.get("hourly_lat")
    lon = cfg.get("hourly_lon")
    if lat is None or lon is None:
        # 有城市名但没坐标（不该发生），退回天气页坐标，别拿错的坐标取数。
        return city, cfg["lat"], cfg["lon"]
    return city, lat, lon


def update_config(patch):
    with _lock:
        cur = _read()
        for k, v in patch.items():
            if k in cur:
                cur[k] = v
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return cur
