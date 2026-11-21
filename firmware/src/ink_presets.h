#pragma once

// 计时器预设分钟数。
//
// 放头文件而不是 ink_timer.cpp：屏幕上的预设条（ink_pages.cpp）也要读它，
// 而 ink_pages.cpp 是刻意不依赖 Arduino.h 的 —— 主机渲染器要能单独编它
// （firmware/tools/render_host.sh），ink_timer.cpp 带了 Arduino.h 进不来。
//
// `static` 是内部链接：每个翻译单元一份副本，不会违反 ODR。
static const int INK_TIMER_PRESETS[8] = { 1, 3, 5, 10, 15, 25, 30, 45 };
static const int INK_TIMER_PRESET_COUNT = 8;
