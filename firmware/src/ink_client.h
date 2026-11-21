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

  // 上报设备自己的状态（当前页 + 计时器 + 功德）：GET /api/device/state?...
  // 计时器状态只存在设备 RAM 里，功德数只存在设备 NVS 里 ——
  // 服务端不猜、不推断，设备报什么就是什么。
  //
  // hasMerit=false 时不带功德参数（第一次开机、还没定下初始计数时）。
  bool reportDeviceState(const char* pageId, const char* timerState,
                         uint32_t timerRemain, uint32_t timerPreset,
                         bool hasMerit, uint32_t meritCount, uint32_t meritStrike);

  // 取服务器上的功德计数（只读）：GET /api/merit
  // 只在第一次开机时用一次 —— 把已有的数接过来，之后设备自己是权威。
  bool fetchMeritCount(uint32_t* count, uint32_t* strike);

  // 返回实际读到的字节数；0 表示失败。
  // timeoutMs：给「小而不重要」的请求用短超时 ——
  // 阻塞 loop 的代价与超时成正比（按键会被吞）。
  size_t fetchText(const char* path, uint8_t* dst, size_t dstLen,
                   uint16_t timeoutMs = INK_HTTP_TIMEOUT_MS);
};
