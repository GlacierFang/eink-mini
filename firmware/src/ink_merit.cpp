#include "ink_merit.h"
#include "ink_merit_assets.h"

#include <stdio.h>
#include <string.h>

// 画一个数字字模。字模位序 1 = 黑（和设备帧一致）。
static void drawDigit(InkCanvas& c, const InkMeritDigitMeta& m, int x, int y)
{
  const uint8_t* g = inkMeritDigitData() + m.offset;
  for (int row = 0; row < m.h; row++) {
    const uint8_t* r = g + row * m.rowBytes;
    for (int col = 0; col < m.w; col++) {
      if ((r[col >> 3] >> (7 - (col & 7))) & 1) {
        c.setPx(x + col, y + row, true);
      }
    }
  }
}

// 一串数字的墨迹宽度。
//
// 墨迹左缘在第一个字的左边距处，右缘在最后一个字的右边。
// 中间每个字只贡献前进宽度 —— 这和服务端 render_merit 里 d.textbbox
// 的口径一致，换档判断才能和它一样。
static int stringInkWidth(const char* s, int n, const InkMeritDigitMeta* meta)
{
  int width = 0;
  for (int i = 0; i < n - 1; i++) {
    width += meta[s[i] - '0'].advance;
  }
  const InkMeritDigitMeta& last = meta[s[n - 1] - '0'];
  width += last.dx + last.w - meta[s[0] - '0'].dx;
  return width;
}

// 把 count 画在右半屏。
//
// 排版和服务端 render_merit 同一套：文字原点在 ascender 线（y=44），
// 后面每个字按自己的前进宽度接上，整串的**墨迹右缘**对齐到 x=284。
// 放不下就换小一号 —— 功德只增不减，迟早到五位、六位。
static void drawCount(InkCanvas& c, uint32_t count)
{
  char buf[12];
  snprintf(buf, sizeof(buf), "%lu", (unsigned long)count);
  int n = (int)strlen(buf);
  if (n <= 0 || n > 10) return;

  int set = 0;
  const InkMeritDigitMeta* meta = inkMeritDigitMeta(set);
  while (set < INK_MERIT_DIGIT_SETS - 1 &&
         stringInkWidth(buf, n, meta) > INK_MERIT_DIGIT_MAX_W) {
    set++;
    meta = inkMeritDigitMeta(set);
  }

  // 整串文字的原点：和服务端 render_merit 同一个口径 ——
  // 原点 x = 右边界 - 墨迹宽度（墨迹右缘因此落在右边界 + 第一个字的左边距）。
  int pen = INK_MERIT_DIGIT_RIGHT - stringInkWidth(buf, n, meta);

  for (int i = 0; i < n; i++) {
    const InkMeritDigitMeta& m = meta[buf[i] - '0'];
    drawDigit(c, m, pen + m.dx, INK_MERIT_DIGIT_TOP + m.dy);
    pen += m.advance;
  }
}

void inkRenderMeritPage(InkCanvas& c, uint32_t count, int frame)
{
  const uint8_t* f = inkMeritFrame(frame);
  if (!f) return;
  // 烘焙帧是设备帧格式（1 = 黑），loadServerFrame 会翻成画布的极性。
  c.loadServerFrame(f, INK_MERIT_FRAME_BYTES);
  drawCount(c, count);
}
