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
  // 返回实际读到的字节数；0 表示失败。
  size_t fetchText(const char* path, uint8_t* dst, size_t dstLen);
};
