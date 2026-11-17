#pragma once
#include <stdint.h>
#include "ink_config.h"
#include "ink_canvas.h"

enum InkPageType : uint8_t { INK_PAGE_NATIVE = 0, INK_PAGE_BITMAP = 1, INK_PAGE_MESSAGE = 2 };

struct InkPageEntry {
  char id[40];
  char type[16];
  char title[48];
};

struct InkPageList {
  InkPageEntry items[INK_MAX_PAGES];
  int  count = 0;
};

// 本地翻页钟页
void inkRenderClockPage(InkCanvas& c, uint32_t epoch, const char* pageLabel,
                         int pageIndex, int pageCount);

// 消息页：最新一条大字 + 下面两条小字，超长截断
void inkRenderMessagePage(InkCanvas& c, const char* line0, const char* line1, const char* line2);

// 页脚指示条
void inkRenderPageFooter(InkCanvas& c, int pageIndex, int pageCount, const char* label);
