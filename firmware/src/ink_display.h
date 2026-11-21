#pragma once
#include <stdint.h>
#include "ink_config.h"
#include "ink_canvas.h"

class GxEPD2_290;

// 屏幕驱动层。
//
// 面板原生 128x296（竖屏），业务画布 296x128（横屏），两者差一个 90 度旋转。
// 位约定：面板侧 1 = 白、0 = 黑（GxEPD2 的 clearScreen(0xFF) 为全白）。
//
// 局刷走 GxEPD2 的双缓冲：
//   writeImagePart()            -> RAM  0x24（当前帧）
//   writeImagePartToPrevious()  -> RAM2 0x26（上一帧）
//   refresh(x, y, w, h)         -> 局部刷新
// 窗口的 x 与 w 必须按 8 像素对齐（GxEPD2 内部也会再对齐一次）。
class InkDisplay {
public:
  // 初始化屏、探测 BUSY 极性。成功返回 true。
  bool begin();

  // 把画布推上屏。forceFull=true 时强制全刷（清残影）。
  bool push(const InkCanvas& canvas, bool forceFull);

  // 距离上次全刷是否已超过间隔。
  bool dueForFullRefresh(uint32_t nowMs) const;

  const char* polarityName() const;
  int  busyLevel() const { return busyLevel_; }

private:
  bool buildPanelFrame(const InkCanvas& c, uint8_t* out) const;
  bool detectDirty(int& px, int& py, int& pw, int& ph) const;
  bool writeFullFrame(const uint8_t* frame);
  bool writePartialFrame(const uint8_t* frame, int px, int py, int pw, int ph);
  int   busyLevel_ = -2;          // -2=未探测，-1=延时模式，0/1=实测极性
  bool  havePrev_ = false;
  uint32_t lastFullMs_ = 0;
  uint8_t newFrame_[INK_FRAME_BYTES];
  uint8_t prevFrame_[INK_FRAME_BYTES];
};
