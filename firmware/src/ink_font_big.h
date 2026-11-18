// ink_font_big.h - 翻页钟大号数字字模（1bpp，1 = 黑，MSB first）
//
// 由 tools/gen_fonts.py 从 TrueType 字体离线生成，**别手改**。
// 换字体或改尺寸就重跑：
//   python3 tools/gen_fonts.py --font /usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf \
//       --height 84 --out-header src/ink_font_big.h \
//       --out-source src/ink_font_big.cpp
//
// 每个字形占同样宽的一格（翻页钟的卡片一样宽），字形居中 ——
// '1' 保持窄，不被拉胖。

#pragma once
#include <stdint.h>

#define INK_BIG_W         57
#define INK_BIG_H         88
#define INK_BIG_ROW_BYTES 8
#define INK_BIG_INK_TOP   2
#define INK_BIG_INK_H     84
#define INK_BIG_COUNT     11

// 取字形数据（INK_BIG_H * INK_BIG_ROW_BYTES 字节，1 = 黑）；
// 不在表里返回 0。第 row 行的起始字节是 g + row * INK_BIG_ROW_BYTES。
const uint8_t* inkBigGlyph(char c);
