# eink-mini

2.9 寸黑白电子墨水屏桌面终端：翻页时钟、天气、月历、留言板。

短按切换画面。设备只当哑终端——位图由配套服务端渲染，设备只负责显示。

## 现在做到哪一步了

> 🟡 **第 1 步：仓库已立**。GitHub `GlacierFang/eink-mini`，MIT，README 与固件注释已中文化。
>
> ⛔ **屏幕固件还没写**。当前 `firmware/src/main.cpp` 是占位程序，只验证编译与烧录链路，**不驱动屏幕**。
>
> ⛔ **配套服务端与 Web UI 还没做**。
>
> 🔒 **编译不会自动跑**。GitHub Actions 改成手动触发（`workflow_dispatch`），要编译时自己点一下。

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
- 驱动板 BUSY 极性可能相反，固件不能假设固定电平
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

## 编译（GitHub Actions，手动触发）

Actions 里点 **Run workflow** 手动触发，跑完在 Artifacts 里下载：

- **eink-mini-merged.bin** —— 合并镜像（bootloader + partitions + app），烧录地址 **0x0**
- **bootloader.bin / partitions.bin / boot_app0.bin / firmware.bin** —— 四个独立文件

## 用 Flash Download Tools 烧录

1. USB 接上板子。
2. ChipType **ESP32-C3**，WorkMode **SPI**，SPI Speed **40MHz**，Flash Size **4MB**，SPI Mode **DIO**。
3. 二选一：载入 **eink-mini-merged.bin** 填 **0x0**（勾 DoNotChgBin）；
   或分别填四个文件——bootloader.bin 0x0、partitions.bin 0x8000、boot_app0.bin 0xE000、firmware.bin 0x10000。
4. 按住 BOOT，点一下 RESET，松开 BOOT，再按 START。
5. 烧完固件会让板载 LED 每秒闪一次（占位程序，不驱动屏幕）。

## 配套服务端（第 3 步，还没做）

设备从配套服务端拉 1bpp 帧：

| 路径 | 用途 |
|---|---|
| GET /api/manifest.json | 页面清单：id、标题、类型、顺序、版本 |
| GET /api/page/{id}.bin | 1bpp 帧，296x128，4736 字节 |
| GET /preview/{id}.png | 给人看的预览图 |
| GET /api/message | 写入入口：往屏幕推一条消息 |
| GET / | Web UI |

帧格式：1bpp，MSB first，bit 1 表示黑，行跨度 37 字节，每帧 4736 字节。

设备只说纯 HTTP，所以自部署实例需要挂一个 HTTP 路径前缀（或前面加一层本地 TLS 终结）。

## 路线图

1. 仓库 + 编译流水线（手动触发）——**已完成**
2. 固件：翻页时钟、按键、拉帧、脏矩形局刷、配网
3. 服务端：页面注册表、1bpp 渲染、Web UI、留言写入入口
4. 部署：nginx 路径前缀、端口注册、systemd unit
5. 跑起来，在 Web UI 里验收

> 屏幕显示内容一律英文——设备零中文字库，只能出英文和数字。

## 许可

MIT
