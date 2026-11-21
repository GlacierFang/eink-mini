#pragma once
#include <stdint.h>

#define INK_FW_VERSION "1.0.0"

// ================================================================ 接线
// ESP32-C3 Pro mini + GDEH029A1 (2.9" 黑白 296x128)
#define INK_PIN_SCK   6
#define INK_PIN_MISO  8    // 面板只写不读，MISO 随便接一个空闲脚
#define INK_PIN_MOSI  7
#define INK_PIN_CS    1    // CS1；CS2 与 CS1 短接
#define INK_PIN_DC    4
#define INK_PIN_RST   10
#define INK_PIN_BUSY  3
#define INK_PIN_KEY_A 5
// B 键：第二颗**外接**微动开关，一脚接 GPIO2、一脚接 GND。
// 和 A 键（GPIO5）完全一样 —— 两只键都是外接的。
//
// 为什么不用 GPIO16：ESP32-C3 的 GPIO11~17 内部接 Flash，模块上
// 根本没引出来。配成 GPIO16 会让固件连烧都烧不进去。
//
// 为什么不用板载 BOOT（GPIO9）：BOOT 键是启动采样脚，复位时按住
// 会进下载模式。GPIO9 留给下载，不当交互键。
//
// GPIO2 也是启动采样脚：固件开内部上拉，复位时保持高电平正常启动；
// 复位那一瞬间按住 B 会进下载模式 —— 上电和复位时别按 B。
#ifndef INK_PIN_KEY_B
#define INK_PIN_KEY_B 2
#endif

// 引脚冲突在编译期拦住。
// 配错一个脚的现象是「屏不亮」或「按键乱跳」，烧进去再查很费时间。
#if (INK_PIN_KEY_A == INK_PIN_KEY_B)
#error "INK_PIN_KEY_A 和 INK_PIN_KEY_B 不能是同一个脚"
#endif
#if (INK_PIN_KEY_A == INK_PIN_SCK) || (INK_PIN_KEY_A == INK_PIN_MISO) || \
    (INK_PIN_KEY_A == INK_PIN_MOSI) || (INK_PIN_KEY_A == INK_PIN_CS) || \
    (INK_PIN_KEY_A == INK_PIN_DC) || (INK_PIN_KEY_A == INK_PIN_RST) || \
    (INK_PIN_KEY_A == INK_PIN_BUSY)
#error "INK_PIN_KEY_A 和屏的引脚冲突"
#endif
#if (INK_PIN_KEY_B == INK_PIN_SCK) || (INK_PIN_KEY_B == INK_PIN_MISO) || \
    (INK_PIN_KEY_B == INK_PIN_MOSI) || (INK_PIN_KEY_B == INK_PIN_CS) || \
    (INK_PIN_KEY_B == INK_PIN_DC) || (INK_PIN_KEY_B == INK_PIN_RST) || \
    (INK_PIN_KEY_B == INK_PIN_BUSY)
#error "INK_PIN_KEY_B 和屏的引脚冲突"
#endif

// ================================================================ 翻页钟极性
//
// 翻页钟有两种极性，结构完全一样，只是黑白反过来：
//
//   INK_FLIP_INVERTED = 0  白卡片 + 黑数字 + 白色翻页缝
//   INK_FLIP_INVERTED = 1  黑卡片 + 白数字 + 黑色翻页缝（参考图那种）
//
// 墨水屏是白纸黑字：黑卡片 = 卡片区域打墨，白数字 = 数字区域不打墨。
// 两种极性**局刷难度相同** —— 数字变了总会有像素要由黑变白，
// 所以选哪个不影响刷新策略，只影响观感。
//
// 想换极性改这一行重编即可。
#ifndef INK_FLIP_INVERTED
#define INK_FLIP_INVERTED 1
#endif

// ================================================================ 画面几何
// 业务画布：横屏 296x128。面板原生：竖屏 128x296。
#define INK_W            296
#define INK_H            128
#define INK_ROW_BYTES    37                 // 296 / 8
#define INK_FRAME_BYTES  (INK_ROW_BYTES * INK_H)   // 4736

#define INK_PANEL_W      128
#define INK_PANEL_H      296
#define INK_PANEL_ROW_BYTES 16             // 128 / 8

// 业务坐标 -> 面板坐标的旋转方向：1 = 顺时针 90 度。
// 真机若整体转了方向，改这里重新编译即可。
#ifndef INK_ROT_CW
#define INK_ROT_CW 1
#endif

// 位极性：面板侧 1 = 白、0 = 黑（GxEPD2 的 clearScreen(0xFF) 为全白）。
// 服务端下发的帧是 1 = 黑，固件在收帧时统一翻转成面板约定。
#define INK_SERVER_BIT1_IS_BLACK 1

// ================================================================ 服务端
#define INK_DEFAULT_HOST   "ruohan.site"
#define INK_DEFAULT_BASE   "/eink-mini"
#define INK_DEFAULT_PORT   80
#define INK_HTTP_TIMEOUT_MS 15000
#define INK_MAX_PAGES      12

// ================================================================ 心跳与轮询
//
// 清单拉取就是设备的心跳 —— 每 INK_HEARTBEAT_PERIOD_MS 一次。
// 服务端据此判设备在不在线，离线阈值按这个周期推（server/device_state.py）。
//
// 位图不再定时拉：清单里每页带版本号，版本变了才重新拉、才刷屏。
// 设备停在时钟页时，除了这份清单，一个字节都不用多拉。
#define INK_HEARTBEAT_PERIOD_MS (60UL * 1000UL)

// 设备状态上报周期（当前页 + 计时器）。控制台靠它显示真实倒计时。
#define INK_STATE_REPORT_PERIOD_MS (60UL * 1000UL)

// ================================================================ 按键手势
#define INK_KEY_LONG_MS      600   // 长按阈值
#define INK_KEY_DEBOUNCE_MS   25

// ================================================================ 时钟
#define INK_TZ_OFFSET_SEC (8 * 3600)
// 局刷累计到该时长做一次全刷，清掉残影
#define INK_FULL_REFRESH_INTERVAL_MS (10UL * 60UL * 1000UL)
// 翻页钟整点后强制一次全刷
#define INK_CLOCK_HOUR_FULL_REFRESH 1
