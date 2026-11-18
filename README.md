# eink-mini

2.9 寸黑白电子墨水屏桌面终端：翻页时钟、天气、月历。

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

**两颗都是外接微动开关**，一脚接引脚、一脚接 GND，固件用内部上拉：

| 键 | 引脚 | 短按 | 双击 | 长按 |
|---|---|---|---|---|
| A | GPIO5 | 下一页 | 上一页 | 立即全刷清残影 |
| B | GPIO2 | 刷新当前页 | 回第一页 | 进入配网 |

计时器页上 B 键是计时器专用：短按 启停 · 双击 换预设 · 长按 重置。

`ink_config.h` 里加了**编译期引脚冲突检查**：按键和屏的引脚撞车直接
`#error`，不用烧进去才发现屏不亮。

> ⚠️ 之前配的 GPIO16 是错的：ESP32-C3 的 GPIO11~17 内部接 Flash，
> 模块上根本没引出来，配成 16 固件连烧都烧不进去。
>
> 板载 BOOT 键（GPIO9）**不做交互键** —— 它是启动采样脚，复位时按住
> 会进下载模式，留给下载用。
>
> GPIO2 也是启动采样脚。固件开内部上拉，复位时保持高电平正常启动；
> 但上电和复位的那一瞬间别按住 B 键。

## 主机端渲染（不用硬件就能看画面）

```bash
firmware/tools/render_host.sh [输出目录]     # 默认 ../tmp-preview
```

`ink_canvas.cpp` + `ink_pages.cpp` 是纯逻辑，不依赖 Arduino API，
所以能在 PC / Pi 上直接编译运行，画出来的就是设备上会显示的像素 ——
逐像素一致，不是「长得像」。

**用途**：

- 版式验证：改完版式立刻出图，不用等硬件到货
- 抓逻辑错：`fillRect` 那种语法没错但画错的 bug，只有出图才看得见
- 回归对比：每次改渲染代码出一组图，肉眼比对

输出 6 张：时钟（已校时 / 没校时）、计时器（READY / RUN / PAUSE / DONE）。

自检画面在 `main.cpp` 里（依赖 `g_display` / `g_net` 全局状态），这个工具不渲染它。

---

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
  ink_client.*     manifest / 位图页
  ink_pages.*      翻页钟、天气月历位图页
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
  pages.py          天气 / 月历页面渲染
  weather.py        Open-Meteo 取数（后台线程 + 落盘缓存，渲染路径只读缓存）
  device_state.py   设备在线状态（最后活动、来源、计数，落盘）
  config_store.py   配置存储（城市、坐标、屏幕标题）
  templates/        控制台页面
  static/console.css 控制台样式（深色主题，沿用 petd 设计令牌）
  tools/check_frame.py  位序自检：把 .bin 解回图验证 1=黑
server/openclaw-eink-mini.service
```

设备侧接口：

| 路径 | 用途 |
|---|---|
| GET /api/manifest.json | 页面清单：id、type、标题、顺序、版本（最多 12 页） |
| GET /api/page/{id}.bin | 1bpp 帧，296x128，4736 字节 |

浏览器侧：

| 路径 | 用途 |
|---|---|
| GET / | 控制台（功能预览 + 配置 + 设备状态） |
| GET /preview/{id}.png | 页面预览图 |
| GET /api/config | 读配置 |
| POST /api/config | 改城市 / 屏幕标题 |
| GET /api/device | 设备在线状态 |

页面清单里 `type` 的含义：`native` = 设备本地渲染（翻页钟），`bitmap` = 服务端下发位图。
当前三个页：clock（native）、weather、calendar。

清单里的 `version` 按页面内容算指纹：配置或日期变了才变，设备据此决定要不要重下位图。
（早期版本用时间戳，导致设备每次轮询都认为页面全变，反复重下全部位图。）

控制台分区：设备状态（在线 / 最后活动 / 来源 / 拉取次数）、各功能页面预览、
功能配置（天气城市、时钟屏标题，标题限 ASCII —— 设备屏没有中文字库）。
新增功能时，服务端多一个渲染页 → 清单多一页 → 控制台多一个分区，设备端不用改。

设备只说纯 HTTP，所以实例挂在 HTTP 路径前缀 `/eink-mini/` 下。

## 天气取数

照 ai-agent-pet 的 petd 做法：**后台线程取数，渲染路径只读缓存**。
设备 HTTP 超时 15 秒，服务端在请求处理里同步取数会直接把这一页拉挂 ——
实测改之前首次拉天气位图要 10 秒以上，改之后稳定在 30-80 毫秒。

- 缓存落盘 `server/data/weather_cache.json`，30 分钟 TTL
- gunicorn 起 2 个 worker，各有后台线程；实际取数靠 flock 去重
- 取数失败沿用上次成功的数据，不让屏变空白
- 内置 60 多个常见城市坐标表：地理编码只认地级市（「杭州市西湖区」查不到），
  内置能省一次请求也省一次猜错
- WMO 天气码用中国气象的观测术语。当前天气用文字描述，三天预报用
  **手绘像素图标**（`icons.py`，20x20）—— 点阵字体里没有 ☀ 🌧 ☁，
  Unicode 渲染出来是豆腐块

## 天气页版式

没有顶栏 —— 这屏没有浏览器 chrome，296x128 就是全部世界，
加一条顶栏只是把网页截图的框搬过来。

- 上半区：大温度是全屏唯一的锚点。字号自动在 30-58 之间挑，
  受两个约束卡住：墨迹高度不压过分隔线，横向不撞到右栏。
  单位 `°C` 做成右上角上标
- 右上：城市 + 当前天气（16px），下面湿度（12px），右对齐到边
- 分隔线下面：三天预报。图标 + 高低温两行（`↑13°` / `↓4°`）+ 日期
- 文字对齐按**墨迹**算（`textbbox`），不是按 ascender 线 ——
  否则同一行里大小不同的字看起来会错位

## 画面怎么渲染成 1bpp

面板是 GDEH029A1（2.9 寸黑白 296x128），**单色，没有灰阶**。
所以「灰色」只能靠两件事拿到：**渲染时留灰度，量化时决定怎么编码**。

### 第一段：3 倍超采样渲染

页面在 3 倍画布（888x384）上画，再 BOX 降采样回 296x128。
小字和图标的边缘因此有真正的抗锯齿 —— 1x 直接画的话，12px 汉字的
边缘只有半个像素可用，量化之后转折处必断。

| 渲染 | 量化 | PSNR |
|---|---|---|
| 1x | hard 128 | 28.97 |
| **3x** | **hard 128** | **32.39** |

**1x -> 3x 一致 +3.2 ~ +7.9 dB，且不增加噪点。** 这是灰度真正兑现的地方。

### 第二段：量化，**不用 dither**

判据不能只看一个指标。PSNR 量的是色调保真，但墨水屏上字读不出来
就没意义。三个指标一起看：

| 策略 | PSNR | 噪点% | 文字 1px 笔画% |
|---|---|---|---|
| floyd 140 | 34.97 | 5.67 | 64 |
| bayer4 | 30.94 | 13.73 | 72 |
| hard 128 | 31.26 | 2.56 | 64 |
| **hard 165** | **28.06** | **0.22** | **38** |

dither 的 PSNR 最高，但噪点把 12px 小字的笔画打断。页面里没有连续色调区域，
dither 那点灰阶收益换不来小字可读性，所以**默认硬阈值 165**。

### 第三段：阈值 165，不是 128

阈值高 = 更多像素判黑 = 笔画更粗。

| 阈值 | 噪点% | 文字 1px 笔画% |
|---|---|---|
| 128 | 2.56 | 64 |
| 150 | 0.58 | 46 |
| **165** | **0.22** | **38** |
| 175 | 0.12 | 32 |

165 是拐点：噪点几乎清零，笔画还连着。175 往上小字开始糊。

想试别的：@@BT@renderer.DITHER_MODES@@BT@ 里有 bayer2 / bayer4 / floyd，
改 @@BT@renderer.DEFAULT_MODE@@BT@ 就行。**改版式要重跑 tools/eval_quant.py。**

## 天气图标怎么画的

**每个图标在自己的 28x28 局部画布上画**，量化成掩码后按位置叠进页面。

不在页面画布上直接画：那样形状代码就得带偏移，偏移算错一次图标就飞 ——
试过，太阳飞到左上角压住了大温度。局部画布把这个 bug 消灭在结构里。

### 细致化靠负空间，**不靠灰度抖动**

| 变体 | 孤立噪点% | 1x 实际尺寸观感 |
|---|---|---|
| A 实心剪影 | 0.10 | 清楚，但没细节 |
| **B 掏白高光** | **0.11** | **清楚 + 有细节** |
| C 纯灰阶抖动 | 14.71 | 云变成噪点团 |
| E 轮廓 + 灰阶 | 23.67 | 最差 |

**28x28 上抖动出来的不是灰度，是纹理** —— 一堆散点。
所以图标全走清晰层（硬阈值），用负空间和构图做体积感。

### 云上掏白试过三种，全是坑

| 做法 | 1x 实际尺寸读作 |
|---|---|
| 掏个洞 | 破洞 |
| 白块压顶 | 轮廓断成两座山峰 |
| 底部横槽 | 一条横线 |

所以云**不掏白**。体积感改用三处：

1. **太阳掏空成环** —— 比实心圆盘多一层信息
2. **太阳画在云后面** —— 云盖住下半，读作「太阳从云后探出来」。
   画反了读作「太阳在云前面」，天气含义就错了
3. **云的弧从 3 段加到 4 段** —— 真云是多瓣的，三段看着还是一块砖

另外：雨丝长短不一，雾中间一条虚线（浓度低），雪花是粗十字
（六角星试过，三条 60 度斜线在点阵上碎成乱线，比十字难认）。

全图标孤立噪点 0.13%。

## 控制台

深色单页，标签页布局，设计令牌沿用 petd 后台：

- 标签页：设备 / 时钟 / 天气 / 月历 —— **一个功能一区，配置和预览同区**
- 设备页：在线状态、最后活动、来源 IP、UA、拉取次数、设备连接参数
- 功能区：左侧设备画面预览，右侧该功能的配置项
- 配置项由服务端的 `CONFIG_FIELDS` 表长出来：加一个可配置项 = 加一行，前后端都跟着长
- 地址栏 `#weather` 这类 hash 可以直接落到对应功能页
- 静态资源用相对路径（`static/console.css`），公网访问不会掉到站点根

## 许可

仓库代码 MIT。`firmware/lib/GxEPD2/` 是 vendored 的 GxEPD2 最小子集，
沿用上游 **GPL-3.0** 许可（该目录下的 LICENSE 文件），与仓库根目录的 MIT 并存。
