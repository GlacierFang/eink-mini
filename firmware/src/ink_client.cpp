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

size_t InkClient::fetchText(const char* path, uint8_t* dst, size_t dstLen)
{
  if (!g_net || !g_net->connected()) return false;
  char url[256];
  g_net->makeUrl(path, url, sizeof(url));

  HTTPClient http;
  http.setTimeout(INK_HTTP_TIMEOUT_MS);
  http.setConnectTimeout(8000);
  http.setReuse(false);
  if (!http.begin(url)) return false;
  int code = http.GET();
  size_t got = 0;
  if (code == 200) {
    WiFiClient* stream = http.getStreamPtr();
    unsigned long t0 = millis();
    unsigned long lastData = t0;
    while (got < dstLen && millis() - t0 < INK_HTTP_TIMEOUT_MS) {
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

bool InkClient::fetchManifest(InkPageList& out)
{
  out.count = 0;
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
        for (int i = 0; i < n && out.count < INK_MAX_PAGES; i++) {
          int c = doc.childAt(arr, i);
          if (c < 0) break;
          InkPageEntry& e = out.items[out.count];
          memset(&e, 0, sizeof(e));
          int idn = doc.findKey(c, "id");
          int tn = doc.findKey(c, "type");
          int tt = doc.findKey(c, "title");
          if (idn >= 0 && doc.node(idn).type == J_STR) {
            strncpy(e.id, doc.str(doc.node(idn)), sizeof(e.id) - 1);
          }
          if (tn >= 0 && doc.node(tn).type == J_STR) {
            strncpy(e.type, doc.str(doc.node(tn)), sizeof(e.type) - 1);
          }
          if (tt >= 0 && doc.node(tt).type == J_STR) {
            strncpy(e.title, doc.str(doc.node(tt)), sizeof(e.title) - 1);
          }
          if (e.id[0]) out.count++;
        }
      }
    } else {
      ok = false;
    }
  }
  free(buf);
  if (ok) Serial.printf("[http] manifest: %d 页\n", out.count);
  return ok;
}
