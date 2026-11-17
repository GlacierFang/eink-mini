#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include "ink_config.h"

class InkNet {
public:
  void begin();

  bool connected() const { return connected_; }
  bool haveConfig() const { return haveConfig_; }
  const char* ssid() const { return ssid_; }
  const char* host() const { return host_; }
  const char* basePath() const { return base_; }

  // 进入配网模式（SoftAP + 简易表单），阻塞直到退出配网。
  void runConfigPortal();
  void exitConfigPortal();

  // 校时：先用 SNTP，失败则用服务端 HTTP Date 兜底。
  bool syncTime();
  bool timeValid() const { return timeValid_; }
  uint32_t epoch();

  // 组一个完整 URL
  void makeUrl(const char* path, char* out, size_t outLen);

  void saveServer(const char* host, const char* base);

private:
  bool loadConfig();
  void saveConfig();
  bool connectWifi();

  bool connected_ = false;
  bool haveConfig_ = false;
  bool timeValid_ = false;
  char ssid_[33] = "";
  char pass_[65] = "";
  char host_[64] = INK_DEFAULT_HOST;
  char base_[64] = INK_DEFAULT_BASE;
};
