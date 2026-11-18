#pragma once
#include <stdint.h>
#include "ink_config.h"
#include "ink_canvas.h"

enum InkPageType : uint8_t { INK_PAGE_NATIVE = 0, INK_PAGE_BITMAP = 1 };

struct InkPageEntry {
  char id[40];
  char type[16];
  char title[48];
};

struct InkPageList {
  InkPageEntry items[INK_MAX_PAGES];
  int  count = 0;
};

// 本地翻页钟页。
//
// 屏上只有 HH:MM —— 没有日期、没有页码、没有状态文字。
void inkRenderClockPage(InkCanvas& c, uint32_t epoch);

// 本地计时器页：状态词 + MM:SS。没有预设分钟数，没有进度条。
void inkRenderTimerPage(InkCanvas& c, const char* stateLabel,
                        uint32_t remainingSec);
