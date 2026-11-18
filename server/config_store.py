"""配置存储：一个 JSON 文件，带内存缓存。

配置项：
  city          天气城市名（默认 北京）
  lat / lon     城市坐标（改城市时重新地理编码）
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
