#include <string.h>
#include "ink_canvas.h"
#include "ink_font.h"

void InkCanvas::clear()
{
  for (int y = 0; y < INK_H; y++)
    for (int b = 0; b < INK_ROW_BYTES; b++) buf[y][b] = 0xFF;
}

void InkCanvas::fill(bool black)
{
  uint8_t v = black ? 0x00 : 0xFF;
  for (int y = 0; y < INK_H; y++)
    for (int b = 0; b < INK_ROW_BYTES; b++) buf[y][b] = v;
}

void InkCanvas::setPx(int x, int y, bool black)
{
  if (x < 0 || x >= INK_W || y < 0 || y >= INK_H) return;
  uint8_t mask = (uint8_t)(0x80 >> (x & 7));
  if (black) buf[y][x >> 3] &= (uint8_t)~mask;
  else       buf[y][x >> 3] |= mask;
}

bool InkCanvas::pxIsBlack(int x, int y) const
{
  if (x < 0 || x >= INK_W || y < 0 || y >= INK_H) return false;
  uint8_t mask = (uint8_t)(0x80 >> (x & 7));
  return (buf[y][x >> 3] & mask) == 0;
}

void InkCanvas::fillRect(int x, int y, int w, int h, bool black)
{
  // 循环轴原来是反的：for j < h 每次画一列 w 像素高，
  // 结果画出来是 1 像素宽的竖条，不是 w 宽 h 高的矩形。
  //
  // drawRect 用的是 hLine + vLine，语义是对的 —— 两个函数不一致，
  // fillRect 这边是错的。后果：数码管的 7 根段全成竖线，
  // 时钟页数字、冒号、页脚方块、自检棋格全是竖条。
  //
  // 主机上编译 ink_canvas.cpp + ink_pages.cpp 渲染出图发现的。
  // CI 编译查不出 —— 语法没错，逻辑错。
  for (int j = 0; j < w; j++) vLine(x + j, y, h, black);
}

void InkCanvas::drawRect(int x, int y, int w, int h, bool black)
{
  if (w <= 0 || h <= 0) return;
  hLine(x, y, w, black);
  hLine(x, y + h - 1, w, black);
  vLine(x, y, h, black);
  vLine(x + w - 1, y, h, black);
}

void InkCanvas::hLine(int x, int y, int w, bool black)
{
  for (int i = 0; i < w; i++) setPx(x + i, y, black);
}

void InkCanvas::vLine(int x, int y, int h, bool black)
{
  for (int i = 0; i < h; i++) setPx(x, y + i, black);
}

void InkCanvas::drawLine(int x0, int y0, int x1, int y1, bool black)
{
  int dx = (x1 > x0) ? (x1 - x0) : (x0 - x1);
  int dy = (y1 > y0) ? (y1 - y0) : (y0 - y1);
  int sx = (x0 < x1) ? 1 : -1;
  int sy = (y0 < y1) ? 1 : -1;
  int err = dx - dy;
  while (true) {
    setPx(x0, y0, black);
    if (x0 == x1 && y0 == y1) break;
    int e2 = err << 1;
    if (e2 > -dy) { err -= dy; x0 += sx; }
    if (e2 < dx)  { err += dx; y0 += sy; }
  }
}

int InkCanvas::textWidth(const char* s, int scale) const
{
  if (!s) return 0;
  int n = 0;
  while (s[n]) n++;
  if (n == 0) return 0;
  if (scale < 1) scale = 1;
  return n * (INK_FONT_W + 1) * scale - scale;
}

void InkCanvas::drawText(int x, int y, const char* s, bool black, int scale)
{
  if (!s) return;
  if (scale < 1) scale = 1;
  int cx = x;
  for (int i = 0; s[i]; i++) {
    const uint8_t* g = inkGlyph(s[i]);
    for (int col = 0; col < INK_FONT_W; col++) {
      for (int row = 0; row < INK_FONT_H; row++) {
        if ((g[col] >> row) & 1) {
          for (int dy = 0; dy < scale; dy++)
            for (int dx = 0; dx < scale; dx++)
              setPx(cx + col * scale + dx, y + row * scale + dy, black);
        }
      }
    }
    cx += (INK_FONT_W + 1) * scale;
  }
}

int InkCanvas::drawTextClipped(int x, int y, int maxW, const char* s, bool black, int scale)
{
  if (!s || maxW <= 0) return 0;
  if (scale < 1) scale = 1;
  int cw = (INK_FONT_W + 1) * scale;
  int maxChars = maxW / cw;
  if (maxChars <= 0) return 0;

  int len = 0;
  while (s[len]) len++;

  char tmp[128];
  int use = (len > maxChars) ? maxChars : len;
  memcpy(tmp, s, (size_t)use);
  tmp[use] = 0;

  if (len > maxChars && use >= 3) {
    use = use - 3;
    memcpy(tmp, s, (size_t)use);
    tmp[use] = '.'; tmp[use + 1] = '.'; tmp[use + 2] = 0;
    drawText(x, y, tmp, black, scale);
    return use + 3;
  }
  drawText(x, y, tmp, black, scale);
  return use;
}

// 七段位序：A B C D E F G
static const uint8_t SEG_7SEG[10] = {
  0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07, 0x7F, 0x6F
};

void InkCanvas::drawSevenDigit(int x, int y, int digit, int w, int h, bool black)
{
  if (digit < 0 || digit > 9) digit = 8;
  if (w < 7 || h < 11) return;
  uint8_t seg = SEG_7SEG[digit];
  int t = h / 12;
  if (t < 2) t = 2;
  int midY = y + h / 2 - t / 2;
  int halfH = h / 2 - t;
  if (halfH < 1) halfH = 1;

  if (seg & 0x01) fillRect(x + t, y, w - 2 * t, t, black);                // A
  if (seg & 0x02) fillRect(x + w - t, y + t, t, halfH, black);             // B
  if (seg & 0x04) fillRect(x + w - t, midY + t / 2 + 1, t, halfH, black);  // C
  if (seg & 0x08) fillRect(x + t, y + h - t, w - 2 * t, t, black);         // D
  if (seg & 0x10) fillRect(x, midY + t / 2 + 1, t, halfH, black);          // E
  if (seg & 0x20) fillRect(x, y + t, t, halfH, black);                     // F
  if (seg & 0x40) fillRect(x + t, midY, w - 2 * t, t, black);              // G
}

void InkCanvas::drawSevenColon(int x, int y, int h, bool black)
{
  int d = h / 14;
  if (d < 2) d = 2;
  fillRect(x, y + h / 4 - d / 2, d, d, black);
  fillRect(x, y + (h * 3) / 4 - d / 2, d, d, black);
}

void InkCanvas::loadServerFrame(const uint8_t* data, size_t len)
{
  clear();
  if (!data) return;
  size_t need = (size_t)INK_FRAME_BYTES;
  if (len < need) need = len;
#if INK_SERVER_BIT1_IS_BLACK
  for (size_t i = 0; i < need; i++) buf[i / INK_ROW_BYTES][i % INK_ROW_BYTES] = (uint8_t)~data[i];
#else
  for (size_t i = 0; i < need; i++) buf[i / INK_ROW_BYTES][i % INK_ROW_BYTES] = data[i];
#endif
}
