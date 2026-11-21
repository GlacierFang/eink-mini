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

  // 带帧号取帧：GET /api/page/<id>.bin?f=N
  // 木鱼敲击一次要播三帧（击打/挥过/静息），帧号由固件指定。
  bool fetchPageFrameAt(const char* id, int frame, uint8_t* dst, size_t dstLen);
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
