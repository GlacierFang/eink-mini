#pragma once
#include <stdint.h>
#include <stddef.h>
#include "ink_config.h"

// 业务画布：296x128，1bpp，行主序，每行 37 字节。
// 位约定：1 = 白，0 = 黑（面板原生约定）。
class InkCanvas {
public:
  uint8_t buf[INK_H][INK_ROW_BYTES];

  void clear();                    // 全白
  void fill(bool black);           // 全黑
  void setPx(int x, int y, bool black);
  bool pxIsBlack(int x, int y) const;
  void fillRect(int x, int y, int w, int h, bool black);
  void drawRect(int x, int y, int w, int h, bool black);
  void hLine(int x, int y, int w, bool black);
  void vLine(int x, int y, int h, bool black);
  void drawLine(int x0, int y0, int x1, int y1, bool black);

  int  textWidth(const char* s, int scale = 1) const;
  void drawText(int x, int y, const char* s, bool black = true, int scale = 1);
  // 翻页钟的大号数字。字模在 ink_font_big.h（1 = 黑，MSB first）。
  void drawBigGlyph(int x, int y, char c, bool black = true);
  // 计时器状态词。字模在 ink_font_state.h（1 = 黑，MSB first）。
  void drawStateText(int x, int y, const char* s, bool black = true);
  int  stateTextWidth(const char* s) const;
  // 超出宽度时截断并加省略号，返回实际绘制的字符数
  int  drawTextClipped(int x, int y, int maxW, const char* s, bool black = true, int scale = 1);


  // 把一帧 1bpp 数据（服务端格式，1 = 黑）读进画布并翻转成面板约定
  void loadServerFrame(const uint8_t* data, size_t len);
};
