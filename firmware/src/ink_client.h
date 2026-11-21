#pragma once
#include <stdint.h>
#include <stddef.h>
#include "ink_config.h"
#include "ink_pages.h"

class InkClient {
public:
  // 拉 manifest：{base}/api/manifest.json
  bool fetchManifest(InkPageList& out);
  // 拉 1bpp 帧：{base}/api/page/{id}.bin
  bool fetchPageFrame(const char* id, uint8_t* dst, size_t dstLen);

  // 一次取多帧：GET /api/page/{id}.bin?f=1,2,0
  // 服务端把各帧依次拼在一起返回，一次往返拿全部。
  //
  // 木鱼敲击一次要播三帧（击打/挥过/静息），用这个一次拿完 ——
  // 设备走公网链路，分三次请求就是 1 秒多的纯等待。
  //
  // 只有击打帧（f=1）计一次功德：请求里带了 f=1 才算敲了一下，
  // 其余帧是同一次敲击的后续画面。
  bool fetchPageFrames(const char* id, const int* frames, int frameCount,
                       uint8_t* dst, size_t frameLen);

  // 上报设备自己的状态（当前页 + 计时器）：GET /api/device/state?...
  // 计时器状态只存在设备 RAM 里，服务端不猜 —— 设备报什么就是什么。
  bool reportDeviceState(const char* pageId, const char* timerState,
                         uint32_t timerRemain, uint32_t timerPreset);

  // 返回实际读到的字节数；0 表示失败。
  // timeoutMs：给「小而不重要」的请求用短超时 ——
  // 阻塞 loop 的代价与超时成正比（按键会被吞）。
  size_t fetchText(const char* path, uint8_t* dst, size_t dstLen,
                   uint16_t timeoutMs = INK_HTTP_TIMEOUT_MS);
};
