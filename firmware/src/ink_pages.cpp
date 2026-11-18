// 不用 <Arduino.h>：这个文件只用到 snprintf / gmtime_r / memset / uint32_t，
// 全在标准头里。去掉它之后，主机上能直接编译这份渲染代码，
// 输出和设备上逐像素一致（见 tools/host_render.cpp）。
#include <stdio.h>
#include "ink_pages.h"
#include "ink_canvas.h"
#include <string.h>
#include <time.h>

static const char* WEEKDAY[7] = { "SUN","MON","TUE","WED","THU","FRI","SAT" };

// 数码管减号（中横一段）。
// 没校时时用它画 --:--，不要画 1970-01-01。
static void drawSevenDash(InkCanvas& c, int x, int y, int w, int h)
{
  int t = h / 12;
  if (t < 2) t = 2;
  int midY = y + h / 2 - t / 2;
  c.fillRect(x + t, midY, w - 2 * t, t, true);
}

void inkRenderClockPage(InkCanvas& c, uint32_t epoch, const char* pageLabel,
                         int pageIndex, int pageCount)
{
  c.clear();

  // epoch == 0 表示还没校时（SNTP 和 HTTP Date 都没成功）。
  // 这时候画 --:-- 和 NO TIME 提示，不要画 1970-01-01。
  bool noTime = (epoch == 0);

  // epoch 一律按 UTC 存；本地时间由固件自己加时区偏移，不依赖系统 TZ 设置
  time_t t = (time_t)(epoch + INK_TZ_OFFSET_SEC);
  struct tm tmv;
  gmtime_r(&t, &tmv);

  int hh = tmv.tm_hour;
  int mm = tmv.tm_min;
  int wd = tmv.tm_wday;

  // 顶部：日期 + 星期（没校时改成提示）
  char top[48];
  if (noTime) {
    snprintf(top, sizeof(top), "NO TIME - CHECK WIFI");
  } else {
    snprintf(top, sizeof(top), "%04d-%02d-%02d  %s", tmv.tm_year + 1900, tmv.tm_mon + 1, tmv.tm_mday, WEEKDAY[wd]);
  }
  c.drawText(6, 5, top, true, 1);

  // 中部：七段大字时间
  int dw = 40, dh = 62, gap = 6, colonW = 10;
  int total = 4 * dw + 3 * gap + colonW + 8;
  int x0 = (INK_W - total) / 2;
  int y0 = 30;

  int digits[4] = { hh / 10, hh % 10, mm / 10, mm % 10 };
  int x = x0;
  for (int i = 0; i < 4; i++) {
    if (noTime) drawSevenDash(c, x, y0, dw, dh);
    else        c.drawSevenDigit(x, y0, digits[i], dw, dh, true);
    x += dw + gap;
    if (i == 1) {
      c.drawSevenColon(x + 2, y0, dh, true);
      x += colonW + 2;
    }
  }

  // 右侧：秒 + 标签
  char lab[48];
  if (noTime) snprintf(lab, sizeof(lab), "--");
  else        snprintf(lab, sizeof(lab), "%02dS", tmv.tm_sec);
  c.drawText(INK_W - 46, y0 + 2, lab, true, 2);
  if (pageLabel && pageLabel[0]) {
    c.drawTextClipped(INK_W - 78, y0 + 26, 72, pageLabel, true, 1);
  }

  inkRenderPageFooter(c, pageIndex, pageCount, NULL);
}



// 本地计时器页。
//
// 版式：
//   顶部左：状态（READY / RUN / PAUSE / DONE），5x7 字库放大 2 倍
//   顶部右：当前预设分钟数
//   中部：七段数码管 MM:SS
//   下部：进度条（随剩余时间收缩）
//
// 数码管能显示的只有数字和冒号，所以状态词用 ASCII ——
// 设备原生字库只有 5x7 ASCII，没有中文字模。
void inkRenderTimerPage(InkCanvas& c, const char* stateLabel,
                        uint32_t remainingSec, uint32_t totalSec,
                        int presetMinutes, int presetIndex, int presetCount,
                        int pageIndex, int pageCount)
{
  c.clear();

  // ---- 顶部：状态 + 预设 ----
  // 状态放大 2 倍 -> 10x14，是这一页最大的文字，一眼能读。
  c.drawText(6, 4, stateLabel, true, 2);

  char presetLab[24];
  snprintf(presetLab, sizeof(presetLab), "%d MIN", presetMinutes);
  int pw = c.textWidth(presetLab, 2);
  c.drawText(INK_W - 6 - pw, 4, presetLab, true, 2);

  // 预设档位指示：几个小方块，当前档反白。
  // 比文字「1/8」直观 —— 一眼看出还有几档。
  int dot = 6, pdotGap = 4;
  int total = presetCount * dot + (presetCount - 1) * pdotGap;
  int dx = INK_W - 6 - total;
  int dy = 22;
  for (int i = 0; i < presetCount; i++) {
    if (i == presetIndex) c.fillRect(dx + i * (dot + pdotGap), dy, dot, dot, true);
    else                  c.drawRect(dx + i * (dot + pdotGap), dy, dot, dot, true);
  }

  c.hLine(0, 34, INK_W, true);

  // ---- 中部：七段数码管 MM:SS ----
  uint32_t mm = remainingSec / 60UL;
  uint32_t ss = remainingSec % 60UL;
  if (mm > 99) mm = 99;

  int dw = 52, dh = 50, gap = 6, colonW = 12;
  int totalW = 4 * dw + 3 * gap + colonW + 8;
  int x0 = (INK_W - totalW) / 2;
  int y0 = 44;

  int digits[4] = {
    (int)(mm / 10), (int)(mm % 10),
    (int)(ss / 10), (int)(ss % 10)
  };
  int x = x0;
  for (int i = 0; i < 4; i++) {
    c.drawSevenDigit(x, y0, digits[i], dw, dh, true);
    x += dw + gap;
    if (i == 1) {
      c.drawSevenColon(x + 2, y0, dh, true);
      x += colonW + 2;
    }
  }

  // ---- 下部：进度条 ----
  // 剩余比例。剩下的越多，条越长 —— 扫一眼就知道还剩多少。
  int barY = INK_H - 30;
  int barH = 8;
  int barW = INK_W - 12;
  int bx = 6;
  c.drawRect(bx, barY, barW, barH, true);
  if (totalSec > 0) {
    uint32_t left = remainingSec > totalSec ? totalSec : remainingSec;
    int fillW = (int)((uint64_t)barW * left / totalSec);
    if (fillW > 0) c.fillRect(bx + 1, barY + 1, fillW - 2, barH - 2, true);
  }

  inkRenderPageFooter(c, pageIndex, pageCount, NULL);
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
