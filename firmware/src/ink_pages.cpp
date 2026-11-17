#include <Arduino.h>
#include <stdio.h>
#include "ink_pages.h"
#include "ink_canvas.h"
#include <string.h>
#include <time.h>

static const char* WEEKDAY[7] = { "SUN","MON","TUE","WED","THU","FRI","SAT" };

void inkRenderClockPage(InkCanvas& c, uint32_t epoch, const char* pageLabel,
                         int pageIndex, int pageCount)
{
  c.clear();

  // epoch 一律按 UTC 存；本地时间由固件自己加时区偏移，不依赖系统 TZ 设置
  time_t t = (time_t)(epoch + INK_TZ_OFFSET_SEC);
  struct tm tmv;
  gmtime_r(&t, &tmv);

  int hh = tmv.tm_hour;
  int mm = tmv.tm_min;
  int wd = tmv.tm_wday;

  // 顶部：日期 + 星期
  char top[48];
  snprintf(top, sizeof(top), "%04d-%02d-%02d  %s", tmv.tm_year + 1900, tmv.tm_mon + 1, tmv.tm_mday, WEEKDAY[wd]);
  c.drawText(6, 5, top, true, 1);

  // 中部：七段大字时间
  int dw = 40, dh = 62, gap = 6, colonW = 10;
  int total = 4 * dw + 3 * gap + colonW + 8;
  int x0 = (INK_W - total) / 2;
  int y0 = 30;

  int digits[4] = { hh / 10, hh % 10, mm / 10, mm % 10 };
  int x = x0;
  for (int i = 0; i < 4; i++) {
    c.drawSevenDigit(x, y0, digits[i], dw, dh, true);
    x += dw + gap;
    if (i == 1) {
      c.drawSevenColon(x + 2, y0, dh, true);
      x += colonW + 2;
    }
  }

  // 右侧：秒 + 标签
  char lab[48];
  snprintf(lab, sizeof(lab), "%02dS", tmv.tm_sec);
  c.drawText(INK_W - 46, y0 + 2, lab, true, 2);
  if (pageLabel && pageLabel[0]) {
    c.drawTextClipped(INK_W - 78, y0 + 26, 72, pageLabel, true, 1);
  }

  inkRenderPageFooter(c, pageIndex, pageCount, NULL);
}

void inkRenderMessagePage(InkCanvas& c, const char* line0, const char* line1, const char* line2)
{
  c.clear();
  c.drawText(6, 4, "MESSAGE", true, 1);
  c.hLine(0, 15, INK_W, true);

  c.drawTextClipped(6, 22, INK_W - 12, line0 ? line0 : "", true, 2);
  c.drawTextClipped(6, 52, INK_W - 12, line1 ? line1 : "", true, 1);
  c.drawTextClipped(6, 70, INK_W - 12, line2 ? line2 : "", true, 1);
}

void inkRenderPageFooter(InkCanvas& c, int pageIndex, int pageCount, const char* label)
{
  c.hLine(0, INK_H - 18, INK_W, true);
  if (label && label[0]) {
    c.drawTextClipped(4, INK_H - 13, 150, label, true, 1);
  }
  // 右侧页码点
  int n = (pageCount > 0) ? pageCount : 1;
  int dot = 4;
  int gap = 5;
  int total = n * dot + (n - 1) * gap;
  int x = INK_W - 4 - total;
  for (int i = 0; i < n; i++) {
    bool cur = (i == pageIndex);
    if (cur) c.fillRect(x + i * (dot + gap), INK_H - 12, dot, dot, true);
    else      c.drawRect(x + i * (dot + gap), INK_H - 12, dot, dot, true);
  }
}
