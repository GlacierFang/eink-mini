// ink_merit_assets.h - 赛博木鱼的三帧位图 + 数字字模（1bpp，1 = 黑）
//
// 由 tools/gen_merit_assets.py 从 images/1.png 2.png 3.png 离线生成，**别手改**。
// 换素材或字号就重跑：
//   python3 tools/gen_merit_assets.py --out-header src/ink_merit_assets.h \
//       --out-source src/ink_merit_assets.cpp

#pragma once
#include <stdint.h>

#define INK_MERIT_FRAME_COUNT   3
#define INK_MERIT_FRAME_BYTES   4736
#define INK_MERIT_DIGIT_SETS    7

// 数字排版（和服务端 render_merit 同一套口径）
#define INK_MERIT_DIGIT_RIGHT   284
#define INK_MERIT_DIGIT_TOP     44
#define INK_MERIT_DIGIT_MAX_W   150

// 一个数字字形的描述。
typedef struct {
    uint8_t  w;        // 墨迹宽（像素）
    uint8_t  h;        // 墨迹高（像素）
    uint8_t  rowBytes; // 每行字节数 = ceil(w/8)
    int8_t   dx;       // 墨迹左上角相对文字原点的 x 偏移
    int8_t   dy;       // 墨迹左上角相对文字原点的 y 偏移
    uint8_t  advance;  // 前进宽度（像素）
    uint16_t offset;   // 在 inkMeritDigitData 里的字节偏移
} InkMeritDigitMeta;

// 三帧整屏位图。帧序：0 静息 / 1 击打 / 2 挥过。
const uint8_t* inkMeritFrame(int idx);

// 数字字模元数据：[档位][数字 0-9]
const InkMeritDigitMeta* inkMeritDigitMeta(int set);

// 数字字模数据（所有档位首尾相接）。
const uint8_t* inkMeritDigitData(void);
