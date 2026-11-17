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

// 从 JSON 文本里挑出最多 3 条消息
static void collectStrings(const JDoc& doc, int nodeIdx, char* l0, size_t s0, char* l1, size_t s1, char* l2, size_t s2)
{
  int used = 0;
  char* slots[3] = { l0, l1, l2 };
  size_t sizes[3] = { s0, s1, s2 };
  if (nodeIdx < 0) return;

  const JNode& n = doc.node(nodeIdx);
  if (n.type == J_STR) {
    if (used < 3) {
      strncpy(slots[used], doc.str(n), sizes[used] - 1);
      slots[used][sizes[used] - 1] = 0;
      used++;
    }
    return;
  }
  if (n.type == J_ARR) {
    int c = doc.childCount(nodeIdx);
    for (int i = 0; i < c && used < 3; i++) {
      int ch = doc.childAt(nodeIdx, i);
      if (ch < 0) break;
      if (doc.node(ch).type == J_STR) {
        strncpy(slots[used], doc.str(doc.node(ch)), sizes[used] - 1);
        slots[used][sizes[used] - 1] = 0;
        used++;
      } else if (doc.node(ch).type == J_OBJ) {
        int t = doc.findKey(ch, "text");
        if (t < 0) t = doc.findKey(ch, "content");
        if (t < 0) t = doc.findKey(ch, "message");
        if (t >= 0 && doc.node(t).type == J_STR) {
          strncpy(slots[used], doc.str(doc.node(t)), sizes[used] - 1);
          slots[used][sizes[used] - 1] = 0;
          used++;
        }
      }
    }
    return;
  }
  if (n.type == J_OBJ) {
    const char* keys[5] = { "message", "lines", "messages", "items", "text" };
    for (int k = 0; k < 5; k++) {
      int c = doc.findKey(nodeIdx, keys[k]);
      if (c < 0) continue;
      if (doc.node(c).type == J_STR && used == 0) {
        strncpy(slots[used], doc.str(doc.node(c)), sizes[used] - 1);
        slots[used][sizes[used] - 1] = 0;
        used++;
      } else {
        collectStrings(doc, c, l0, s0, l1, s1, l2, s2);
        return;
      }
    }
  }
}

bool InkClient::fetchMessage(char* l0, size_t s0, char* l1, size_t s1, char* l2, size_t s2)
{
  if (l0) l0[0] = 0;
  if (l1) l1[0] = 0;
  if (l2) l2[0] = 0;
  if (!g_net || !g_net->connected()) return false;

  char url[256];
  g_net->makeUrl("/api/message", url, sizeof(url));

  HTTPClient http;
  http.setTimeout(INK_HTTP_TIMEOUT_MS);
  http.setConnectTimeout(8000);
  if (!http.begin(url)) return false;
  int code = http.GET();
  bool ok = false;
  if (code == 200) {
    String body = http.getString();
    static JDoc doc;
    if (doc.parse(body.c_str(), body.length())) {
      collectStrings(doc, doc.root(), l0, s0, l1, s1, l2, s2);
      ok = true;
    }
  }
  http.end();
  return ok;
}
