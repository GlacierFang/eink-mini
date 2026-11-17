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
  // 拉消息：{base}/api/message  -> 最多 3 行
  bool fetchMessage(char* line0, size_t l0, char* line1, size_t l1, char* line2, size_t l2);
  // 返回实际读到的字节数；0 表示失败。
  size_t fetchText(const char* path, uint8_t* dst, size_t dstLen);
};
