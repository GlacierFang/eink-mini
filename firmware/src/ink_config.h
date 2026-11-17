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
// B 键 GPIO 待实物丝印最终确认（候选 GPIO0 / GPIO16 / GPIO17）
#ifndef INK_PIN_KEY_B
#define INK_PIN_KEY_B 16
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

// ================================================================ 按键手势
#define INK_KEY_LONG_MS      600   // 长按阈值
#define INK_KEY_DOUBLE_MS    250   // 双击判定窗 / 单击确认延迟
#define INK_KEY_DEBOUNCE_MS   25

// ================================================================ 时钟
#define INK_TZ_OFFSET_SEC (8 * 3600)
// 局刷累计到该时长做一次全刷，清掉残影
#define INK_FULL_REFRESH_INTERVAL_MS (10UL * 60UL * 1000UL)
// 翻页钟整点后强制一次全刷
#define INK_CLOCK_HOUR_FULL_REFRESH 1
