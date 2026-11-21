#include "ink_client.h"
#include "ink_net.h"
#include "ink_json.h"

#include <Arduino.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include <string.h>
#include <stdlib.h>
#include <stdio.h>

static InkNet* g_net = nullptr;
void inkClientBindNet(InkNet* n) { g_net = n; }

size_t InkClient::fetchText(const char* path, uint8_t* dst, size_t dstLen, uint16_t timeoutMs)
{
  if (!g_net || !g_net->connected()) return false;
  char url[256];
  g_net->makeUrl(path, url, sizeof(url));

  HTTPClient http;
  http.setTimeout(timeoutMs);
  // 连接超时也不能超过请求超时的一半：连接卡住时阻塞 loop 的时间
  // 全部算在用户按键的头上。
  http.setConnectTimeout(timeoutMs > 4000 ? (timeoutMs / 2) : timeoutMs);
  http.setReuse(false);
  if (!http.begin(url)) return false;
  int code = http.GET();
  size_t got = 0;
  if (code == 200) {
    WiFiClient* stream = http.getStreamPtr();
    unsigned long t0 = millis();
    unsigned long lastData = t0;
    while (got < dstLen && millis() - t0 < timeoutMs) {
      size_t avail = stream->available();
      if (avail == 0) {
        // 服务端可能已发完但保持连接：空闲 500ms 视为传输结束
        if (millis() - lastData > 500) break;
        delay(5);
        continue;
      }
      size_t n = stream->readBytes(dst + got, (avail > (dstLen - got)) ? (dstLen - got) : avail);
      if (n == 0) break;
      got += n;
      lastData = millis();
    }
  } else {
    Serial.printf("[http] %s -> %d\n", url, code);
  }
  http.end();
  return got;
}

bool InkClient::fetchPageFrame(const char* id, uint8_t* dst, size_t dstLen)
{
  char path[96];
  snprintf(path, sizeof(path), "/api/page/%s.bin", id);
  return fetchText(path, dst, dstLen) == dstLen;
}

bool InkClient::reportDeviceState(const char* pageId, const char* timerState,
                                 uint32_t timerRemain, uint32_t timerPreset,
                                 bool hasMerit, uint32_t meritCount, uint32_t meritStrike)
{
  char path[224];
  int n = snprintf(path, sizeof(path),
                   "/api/device/state?page=%s&state=%s&remain=%lu&preset=%lu",
                   (pageId && pageId[0]) ? pageId : "-",
                   (timerState && timerState[0]) ? timerState : "READY",
                   (unsigned long)timerRemain,
                   (unsigned long)timerPreset);
  // 功德：设备本地记着的数，报绝对值。服务器只存不算。
  if (hasMerit) {
    n += snprintf(path + n, sizeof(path) - n, "&merit=%lu&merit_strike=%lu",
                  (unsigned long)meritCount, (unsigned long)meritStrike);
  }
  // 响应体不看，只要请求到了就算上报成功。
  // 超时给 3 秒：这是个小请求，而且它阻塞的是用户的按键响应。
  uint8_t sink[8];
  return fetchText(path, sink, sizeof(sink), 3000) > 0;
}

bool InkClient::fetchMeritCount(uint32_t* count, uint32_t* strike)
{
  if (!g_net || !g_net->connected()) return false;
  uint8_t* buf = (uint8_t*)malloc(256);
  if (!buf) return false;
  size_t got = fetchText("/api/merit", buf, 255, 3000);
  bool ok = false;
  if (got > 0) {
    buf[got < 255 ? got : 254] = 0;
    static JDoc doc;
    if (doc.parse((const char*)buf, got)) {
      int root = doc.root();
      int cn = doc.findKey(root, "count");
      int sn = doc.findKey(root, "strike");
      if (cn >= 0 && doc.node(cn).type == J_NUM) {
        double v = doc.node(cn).num;
        if (v >= 0.0 && v < 4294967296.0) {
          if (count) *count = (uint32_t)v;
          ok = true;
        }
      }
      if (sn >= 0 && doc.node(sn).type == J_NUM) {
        double v = doc.node(sn).num;
        if (v >= 0.0 && v < 4294967296.0 && strike) *strike = (uint32_t)v;
      }
    }
  }
  free(buf);
  return ok;
}

bool InkClient::fetchManifest(InkPageList& out)
{
  // 解析到一份新清单，再按 id 把「已经上屏的版本」继承过来。
  //
  // 清单每 60 秒来一次，位图只在版本变了才重拉 —— 「上屏版本」必须跨
  // 清单刷新活下来，否则每次都被当成「没拉过」，等于又回到定时拉位图。
  //
  // 拉失败不动 out：一次网络抖动不该把整份页面清单清空。
  static InkPageList fresh;
  fresh.count = 0;
  uint8_t* buf = (uint8_t*)malloc(4096);
  if (!buf) return false;
  char path[64];
  snprintf(path, sizeof(path), "/api/manifest.json");
  bool ok = false;
  size_t got = fetchText(path, buf, 4096);
  if (got > 0) {
    ok = true;
    // JDoc 约 16KB，不能放栈上（Arduino loopTask 栈只有 8KB）
    static JDoc doc;
    if (doc.parse((const char*)buf, got)) {
      int root = doc.root();
      // manifest 可能是数组，也可能是 {"pages":[...]}
      int arr = root;
      if (doc.node(root).type == J_OBJ) {
        int p = doc.findKey(root, "pages");
        if (p < 0) p = doc.findKey(root, "items");
        if (p >= 0) arr = p;
      }
      if (arr >= 0 && doc.node(arr).type == J_ARR) {
        int n = doc.childCount(arr);
        for (int i = 0; i < n && fresh.count < INK_MAX_PAGES; i++) {
          int c = doc.childAt(arr, i);
          if (c < 0) break;
          InkPageEntry& e = fresh.items[fresh.count];
          memset(&e, 0, sizeof(e));
          int idn = doc.findKey(c, "id");
          int tn = doc.findKey(c, "type");
          int tt = doc.findKey(c, "title");
          int vn = doc.findKey(c, "version");
          if (idn >= 0 && doc.node(idn).type == J_STR) {
            strncpy(e.id, doc.str(doc.node(idn)), sizeof(e.id) - 1);
          }
          if (tn >= 0 && doc.node(tn).type == J_STR) {
            strncpy(e.type, doc.str(doc.node(tn)), sizeof(e.type) - 1);
          }
          if (tt >= 0 && doc.node(tt).type == J_STR) {
            strncpy(e.title, doc.str(doc.node(tt)), sizeof(e.title) - 1);
          }
          // 版本号：内容指纹。设备靠它判断「这一页要不要重新拉」。
          if (vn >= 0 && doc.node(vn).type == J_NUM) {
            double v = doc.node(vn).num;
            if (v >= 0.0 && v < 4294967296.0) e.version = (uint32_t)v;
          }
          if (e.id[0]) fresh.count++;
        }
      }
    } else {
      ok = false;
    }
  }
  free(buf);
  if (!ok) return false;

  // 按 id 继承「已经上屏的版本」
  for (int i = 0; i < fresh.count; i++) {
    for (int j = 0; j < out.count; j++) {
      if (strcmp(out.items[j].id, fresh.items[i].id) == 0) {
        fresh.items[i].appliedVersion = out.items[j].appliedVersion;
        fresh.items[i].hasApplied = out.items[j].hasApplied;
        break;
      }
    }
  }
  out = fresh;

  Serial.printf("[http] manifest: %d 页\n", out.count);
  return true;
}
