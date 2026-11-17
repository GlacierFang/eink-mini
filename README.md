# eink-mini

2.9 寸黑白电子墨水屏桌面终端：翻页时钟、天气、月历、留言板。

短按切换画面。设备只当哑终端——位图由配套服务端渲染，设备只负责显示。

## 现在做到哪一步了

> 🟢 **固件写完，CI 编译通过**（run 44103056290 全绿）。产物在 `fw-bin` 分支，国内网络可直接 `git clone` 拿到。
>
> 🟡 **还没上过真机**。接线、B 键 GPIO、旋转方向、BUSY 极性都要实物核对。
>
> 🟢 **配套服务端已上线**：`http://ruohan.site/eink-mini/`（后端 18842，nginx 路由 `/eink-mini/`）。
>
> 🔒 **编译不会自动跑**。GitHub Actions 手动触发（`workflow_dispatch`），要编译时自己点一下。

## 硬件

| 部件 | 规格 |
|---|---|
| 屏 | GDEH029A1，2.9 寸，296x128，SSD1680 驱动，纯黑白（无红、无黄） |
| 主控 | ESP32-C3 Pro mini，USB 供电，常亮 |
| 墨水屏驱动板 | v1.4 通用板，24P / 26P / 34P FPC 座 |
| FPC 排线 | 24P |
| 按键 | 12x12x12mm 微动开关，4 脚（内部两两并联） |

屏的硬事实：

- SSD1680 有硬件快速刷新：全刷约 3s，局刷约 0.3s
- 驱动板引出 CS1 / CS2 供双控制器屏使用——单控制器屏要把 CS1 和 CS2 短接一起
- 驱动板 BUSY 极性可能相反，固件不能假设固定电平（代码里上电探测 + 超时兜底）
- 屏没有灰度：每个像素非黑即白

## 接线（ESP32-C3 Pro mini）

| 驱动板 | C3 |
|---|---|
| GND | GND |
| 3V3 | 3V3 |
| SCK | GPIO6 |
| SDA | GPIO7 |
| CS1 | GPIO1（CS2 与 CS1 短接） |
| DC | GPIO4 |
| RST | GPIO10 |
| BUSY | GPIO3 |

按键：一脚接 GPIO5，另一脚接 GND。固件用内部上拉。

第二颗按键（B 键）默认接 **GPIO16**，⚠️ 尚未按实物丝印确认（候选 GPIO0 / GPIO16 / GPIO17）。
烧录前请量一下丝印，不对就改 `firmware/src/ink_config.h` 的 `INK_PIN_KEY_B` 重编。

## 编译（GitHub Actions，手动触发）

Actions 里点 **Run workflow** 手动触发。产物两处都能拿：

- **Artifacts**：`eink-mini-firmware`（国内网络常常下不动）
- **`fw-bin` 分支**（推荐，国内可走 git）：
  ```bash
  git clone --depth 1 --branch fw-bin git@github.com:GlacierFang/eink-mini.git
  ```

产物清单：

| 文件 | 烧录地址 | 说明 |
|---|---|---|
| eink-mini-merged.bin | 0x0 | 合并镜像，一步烧完 |
| bootloader.bin | 0x0 | |
| partitions.bin | 0x8000 | |
| boot_app0.bin | 0xE000 | OTA 槽信息（otadata） |
| firmware.bin | 0x10000 | 固件本体 |

## 用 Flash Download Tools 烧录

1. USB 接上板子。
2. ChipType **ESP32-C3**，WorkMode **SPI**，SPI Speed **40MHz**，Flash Size **4MB**，SPI Mode **DIO**。
3. 二选一：载入 **eink-mini-merged.bin** 填 **0x0**（勾 DoNotChgBin）；
   或分别填文件——bootloader.bin 0x0、partitions.bin 0x8000、boot_app0.bin 0xE000、firmware.bin 0x10000。
4. 按住 BOOT，点一下 RESET，松开 BOOT，再按 START。

用 esptool 也行，命令写在 `flash_args.txt`：

```bash
esptool.py --chip esp32c3 write_flash -z --flash_mode dio --flash_freq 80m --flash_size 4MB \\
  0x0 bootloader.bin 0x8000 partitions.bin 0xE000 boot_app0.bin 0x10000 firmware.bin
```

## 固件结构

```
firmware/src/
  ink_config.h     引脚、尺寸、服务端地址
  ink_canvas.*     296x128 1bpp 画布 + 绘图原语
  ink_font.h       5x7 ASCII 字库（设备零中文字库）
  ink_display.*    面板封装：旋转、双帧、局刷/全刷、BUSY 探测
  ink_keys.*       A/B 键：短按、双击、长按
  ink_net.*        NVS、WiFi、SoftAP 配网页、SNTP 校时
  ink_json.*       最小 JSON 解析
  ink_client.*     manifest / 位图页 / 消息接口
  ink_pages.*      翻页钟、天气月历位图页、消息页
  main.cpp         设备状态机与页面调度
firmware/tools/merge_bin.py   合并整片镜像
firmware/lib/GxEPD2/          vendored GxEPD2 最小子集（见许可）
```

位图协议：1bpp，MSB first，bit 1 表示黑，行跨度 37 字节，每帧 4736 字节。
局刷窗口按 8 像素对齐，完整旧帧写 RAM2、完整新帧写 RAM，再刷脏区窗口。

## 配套服务端

已上线：`http://ruohan.site/eink-mini/`（Flask + gunicorn，后端端口 18842，user scope systemd）。

```
server/
  app.py            Flask 应用与路由
  renderer.py       1bpp 帧编码（296x128，MSB first，1=黑，4736 字节）
  pages.py          天气 / 月历 / 留言板页面渲染
  weather.py        Open-Meteo 取数（10 分钟缓存，失败沿用上次结果）
  store.py          留言存储（最近 50 条，JSON 落盘）
  config_store.py   配置存储（城市、坐标、写入令牌）
  templates/        Web UI
  tools/check_frame.py  位序自检：把 .bin 解回图验证 1=黑
server/openclaw-eink-mini.service
```

设备侧接口：

| 路径 | 用途 |
|---|---|
| GET /api/manifest.json | 页面清单：id、type、标题、顺序、版本（最多 12 页） |
| GET /api/page/{id}.bin | 1bpp 帧，296x128，4736 字节 |
| GET /api/message | 留言列表（字符串数组，最新在前） |
| POST /api/message | 写留言（需 token，默认关闭） |

浏览器侧：

| 路径 | 用途 |
|---|---|
| GET / | Web UI（页面预览 + 留言板） |
| GET /preview/{id}.png | 页面预览图 |
| GET /api/config | 读配置 |
| POST /api/config | 改城市 / 标题 |

页面清单里 `type` 的含义：`native` = 设备本地渲染（翻页钟），`bitmap` = 服务端下发位图，
`message` = 消息页。当前四个页：clock（native）、weather、calendar、message。

写入令牌：服务端 `write_token` 非空时才允许写入，也可用环境变量 `EINK_MINI_WRITE_TOKEN` 注入。
为空时 POST 一律 403。设备只说纯 HTTP，所以实例挂在 HTTP 路径前缀 `/eink-mini/` 下。

## 许可

仓库代码 MIT。`firmware/lib/GxEPD2/` 是 vendored 的 GxEPD2 最小子集，
沿用上游 **GPL-3.0** 许可（该目录下的 LICENSE 文件），与仓库根目录的 MIT 并存。
