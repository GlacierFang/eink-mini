"""配置存储：一个 JSON 文件，带内存缓存。

配置项：
  city          天气城市名（默认 北京）
  lat / lon     城市坐标（改城市时重新地理编码）
  write_token   留言写入令牌；为空 = 写入接口关闭
  device_title  设备标题
"""

import json
import os
import pathlib
import threading

DATA_DIR = pathlib.Path(__file__).resolve().parent / "data"
CONFIG_PATH = DATA_DIR / "config.json"

DEFAULTS = {
    "city": "北京",
    "lat": 39.9075,
    "lon": 116.39723,
    "write_token": "",
    "device_title": "EINK-MINI",
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
    # 环境变量优先于文件，方便部署时用 systemd Environment 注入令牌
    env_token = os.environ.get("EINK_MINI_WRITE_TOKEN")
    if env_token is not None:
        merged["write_token"] = env_token
    return merged


def get_config():
    with _lock:
        return _read()


def update_config(patch):
    with _lock:
        cur = _read()
        for k, v in patch.items():
            if k in cur and k != "write_token":
                cur[k] = v
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return cur
