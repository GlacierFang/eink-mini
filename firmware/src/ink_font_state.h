// ink_font_state.h - 计时器状态词字模（1bpp，1 = 黑，MSB first）
//
// 由 tools/gen_font_state.py 从 TrueType 字体离线生成，**别手改**。
// 换字体或改尺寸就重跑：
//   python3 tools/gen_font_state.py --font /usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf --height 13 \
//       --out-header src/ink_font_state.h --out-source src/ink_font_state.cpp
//
// 大写字母，比例宽度（每个字形存自己的墨迹宽度，'I' 不被拉胖）。
// 取字形数据（INK_STATE_H 行，每行 ceil(宽/8) 字节，1 = 黑）；
// 不在表里返回 0。宽度写进 *w。

#pragma once
#include <stdint.h>

#define INK_STATE_H       13
#define INK_STATE_INK_TOP 0
#define INK_STATE_COUNT   26
#define INK_STATE_SPACING 2
#define INK_STATE_MAX_W   14

// 取字形数据；不在表里返回 0。
const uint8_t* inkStateGlyph(char c, int* w);
