// ink_merit.h - 赛博木鱼页的本地渲染
//
// 这一页**完全本地**，不碰服务器：
//   - 三帧位图烘焙在固件里（ink_merit_assets.cpp，离线生成）
//   - 功德数字用字模自己画（数字随功德变，帧不变）
//   - 计数存在 NVS 里（ink_merit_store）
//
// 服务器只是这个计数的**只读镜像**，不是权威 —— 敲没敲由设备说了算。
#pragma once
#include <stdint.h>
#include "ink_canvas.h"

// 帧序。和服务端 merit.FRAME_* 一致。
enum InkMeritFrame : uint8_t {
  INK_MERIT_FRAME_IDLE = 0,    // 静息
  INK_MERIT_FRAME_STRIKE = 1,  // 击打
  INK_MERIT_FRAME_SWING = 2,   // 挥过
};

// 画整页：烘焙帧 + 当前功德数字。
void inkRenderMeritPage(InkCanvas& c, uint32_t count, int frame);
