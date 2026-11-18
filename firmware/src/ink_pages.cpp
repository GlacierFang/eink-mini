// 不用 <Arduino.h>：这个文件只用到 snprintf / gmtime_r / memset / uint32_t，
// 全在标准头里。去掉它之后，主机上能直接编译这份渲染代码，
// 输出和设备上逐像素一致（见 tools/host_render.cpp）。
#include <stdio.h>
#include "ink_pages.h"
#include "ink_canvas.h"
#include "ink_font_big.h"
#include <string.h>
#include <time.h>

// ================================================================
// 翻页钟的大数字
//
// 参照真实的翻页钟：每个数字一张卡片，**卡片一样宽**，数字居中。
// 卡片中间有一道横向的翻页缝，数字在缝处断开。
//
// 为什么不用七段数码管：七段是计算器和仪表的形态，不是钟的形态。
// 翻页钟用印刷体数字 —— 比例自然、笔画有粗细变化、一眼可读。
//
// 缝的位置：数字墨迹高度的 51%。实测参考图（亮区 113-367，缝在 243-245）。
// 下半不做错位 —— 参考图实测中心偏移 ±2px / 137px，是噪声不是设计。
// ================================================================

#define INK_FLIP_SEAM_H    2
#define INK_FLIP_SEAM_ROW  (INK_BIG_INK_TOP + (INK_BIG_INK_H * 51) / 100)

// 面板结构（照参考图）：
//
//   [ 2 3 ]      [ 4 3 ]
//   ▔▔▔▔▔▔       ▔▔▔▔▔▔   <- 缝横穿整个面板，不是一个数字一条缝
//
// 每个面板装**两位数字**（小时 / 分钟），缝横穿面板。
// 面板之间留一道宽缝代替冒号 —— 少一个符号，干净。
#define INK_FLIP_PANEL_DIGIT_GAP  6    // 面板内两位数字之间的距离
#define INK_FLIP_PANEL_GAP       24   // 两个面板之间的距离
#define INK_FLIP_PANEL_W  (INK_BIG_W * 2 + INK_FLIP_PANEL_DIGIT_GAP)

// 一个面板：两位数字 + 一道横穿面板的翻页缝。
//
// 两种极性：
//   反白（INK_FLIP_INVERTED=1）—— 卡片打墨变黑，数字留白，缝是黑线
//   正白（INK_FLIP_INVERTED=0）—— 卡片留白，数字打墨，缝是白线
//
// 白数字 = 那一块不打墨。墨水屏只能「把像素变黑」，
// 所以反白版是「先铺黑卡片，再把数字位置擦白」。
static void drawFlipPanel(InkCanvas& c, int x, int y, const char* two)
{
  int inkTop = y + INK_BIG_INK_TOP;

#if INK_FLIP_INVERTED
  // 黑卡片
  c.fillRect(x, inkTop, INK_FLIP_PANEL_W, INK_BIG_INK_H, true);
  // 白数字（不打墨 = 留白）
  c.drawBigGlyph(x, y, two[0], false);
  c.drawBigGlyph(x + INK_BIG_W + INK_FLIP_PANEL_DIGIT_GAP, y, two[1], false);
  // 铰链线：黑线，穿过白数字
  int seamY = y + INK_FLIP_SEAM_ROW;
  c.fillRect(x, seamY, INK_FLIP_PANEL_W, INK_FLIP_SEAM_H, true);
#else
  // 白卡片
  c.fillRect(x, inkTop, INK_FLIP_PANEL_W, INK_BIG_INK_H, false);
  // 黑数字
  c.drawBigGlyph(x, y, two[0], true);
  c.drawBigGlyph(x + INK_BIG_W + INK_FLIP_PANEL_DIGIT_GAP, y, two[1], true);
  // 铰链线：白线，穿过黑数字
  int seamY = y + INK_FLIP_SEAM_ROW;
  c.fillRect(x, seamY, INK_FLIP_PANEL_W, INK_FLIP_SEAM_H, false);
#endif
}

// 一组时间：两个面板（HH / MM），整体在屏上居中。
static void drawFlipTime(InkCanvas& c, int y, const char* d4)
{
  int total = INK_FLIP_PANEL_W * 2 + INK_FLIP_PANEL_GAP;
  int x0 = (INK_W - total) / 2;

  drawFlipPanel(c, x0, y, d4);
  drawFlipPanel(c, x0 + INK_FLIP_PANEL_W + INK_FLIP_PANEL_GAP, y, d4 + 2);
}

// 把两个数写成两位数字串。超过 99 就截（计时器最大 99:59）。
static void twoDigits(char* out, uint32_t v)
{
  if (v > 99) v = 99;
  out[0] = (char)('0' + (v / 10));
  out[1] = (char)('0' + (v % 10));
  out[2] = 0;
}

void inkRenderClockPage(InkCanvas& c, uint32_t epoch)
{
  c.clear();

  // epoch == 0 表示还没校时（SNTP 和 HTTP Date 都没成功）。
  // 这时候画 --:--，不要画 1970-01-01。
  bool noTime = (epoch == 0);

  // epoch 一律按 UTC 存；本地时间由固件自己加时区偏移，不依赖系统 TZ 设置
  time_t t = (time_t)(epoch + INK_TZ_OFFSET_SEC);
  struct tm tmv;
  gmtime_r(&t, &tmv);

  // 屏上只有一件事：现在几点。
  // 日期、页码、状态都不画 —— 数字够大够清楚，别拿别的东西挤它。
  char digits[8];
  if (noTime) {
    digits[0] = '-'; digits[1] = '-';
    digits[2] = '-'; digits[3] = '-';
    digits[4] = 0;
  } else {
    twoDigits(digits, (uint32_t)tmv.tm_hour);
    twoDigits(digits + 2, (uint32_t)tmv.tm_min);
  }

  // y=20：卡片墨迹落在 22..105，屏上下各留 22px，视觉居中。
  drawFlipTime(c, 20, digits);
}


// 本地计时器页。
//
// 版式：
//   顶部左：状态（READY / RUN / PAUSE / DONE），专用小号字模
//   中部：翻页钟大字 MM:SS
//
// 数字用字库不用七段：倒计时也是翻页钟的用法，和时钟页保持一套形态。
//
// 状态词用 ASCII —— 设备原生字库只有 5x7 ASCII，没有中文字模。
//
// 预设分钟数和进度条都不画：数字已经把剩余量说精确了，
// 进度条只是把同一件事画粗一遍，白占一大块面积。
void inkRenderTimerPage(InkCanvas& c, const char* stateLabel,
                        uint32_t remainingSec)
{
  c.clear();

  // ---- 顶部左：状态 ----
  // RUN 和 PAUSE 的数字画面完全一样，不写状态就分不清在跑还是停着。
  //
  // 状态词用专用字模（13px 高），不是 5x7 ASCII：后者画出来 PAUSE
  // 只有 24x7 px，在 296x128 的屏上几乎看不见。
  c.drawStateText(6, 3, stateLabel, true);

  // ---- 中部：翻页钟大字 MM:SS ----
  uint32_t mm = remainingSec / 60UL;
  uint32_t ss = remainingSec % 60UL;
  char digits[8];
  twoDigits(digits, mm);
  twoDigits(digits + 2, ss);
  drawFlipTime(c, 20, digits);
}


