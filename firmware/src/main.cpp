// eink-mini 固件入口
//
// 设备是哑终端：本地只渲染翻页钟与消息页，其余页面的位图由服务端渲染后
// 下发 1bpp 帧。设备负责按键手势、翻页、局刷、配网与校时。

#include <Arduino.h>
#include <string.h>
#include <WiFi.h>

#include "ink_config.h"
#include "ink_canvas.h"
#include "ink_display.h"
#include "ink_keys.h"
#include "ink_net.h"
#include "ink_client.h"
#include "ink_pages.h"

void inkClientBindNet(InkNet* n);

static InkDisplay g_display;
static InkKeys    g_keys;
static InkNet     g_net;
static InkClient  g_client;

static InkCanvas  g_canvas;

// 每个 bitmap 页缓存一帧，源故障时回落显示最后一次成功缓存
static uint8_t* g_pageCache[INK_MAX_PAGES] = {nullptr};
static bool     g_pageCached[INK_MAX_PAGES] = {false};
static uint8_t* g_frameBuf = nullptr;

static InkPageList g_pages;
static int      g_pageIndex = 0;
static uint32_t g_lastManifestMs = 0;
static uint32_t g_lastClockSec = 0;
static uint32_t g_lastPageFetchMs = 0;
static bool     g_timeOk = false;

// 上电自检：画一张带信息与黑白棋格的测试画面，肉眼确认不反色
static void renderSelfTest(InkCanvas& c)
{
  c.clear();
  c.drawRect(2, 2, INK_W - 4, INK_H - 4, true);
  c.drawText(10, 12, "EINK-MINI SELF TEST", true, 2);
  c.drawText(10, 36, "FW ", true, 1);
  c.drawText(32, 36, INK_FW_VERSION, true, 1);
  c.drawText(10, 50, "BUSY ", true, 1);
  c.drawText(44, 50, g_display.polarityName(), true, 1);
  c.drawText(10, 64, "WIFI ", true, 1);
  c.drawText(44, 64, g_net.connected() ? "OK" : "OFF", true, 1);
  c.drawText(10, 78, "IP ", true, 1);
  c.drawText(32, 78, g_net.connected() ? WiFi.localIP().toString().c_str() : "-", true, 1);
  c.drawText(10, 92, "TIME ", true, 1);
  c.drawText(44, 92, g_timeOk ? "OK" : "NO", true, 1);

  for (int i = 0; i < 8; i++) {
    for (int j = 0; j < 8; j++) {
      bool black = ((i + j) & 1) != 0;
      c.fillRect(196 + i * 11, 40 + j * 11, 11, 11, black);
    }
  }
  c.drawText(196, 126, "GRAY CHECK", true, 1);
}

// 把当前页画进画布
static bool renderCurrentPage()
{
  const char* curId = "";
  const char* curType = "native";
  const char* curTitle = "";
  if (g_pages.count > 0 && g_pageIndex < g_pages.count) {
    curId = g_pages.items[g_pageIndex].id;
    curType = g_pages.items[g_pageIndex].type;
    curTitle = g_pages.items[g_pageIndex].title;
  }

  if (strcmp(curType, "bitmap") == 0) {
    // bitmap 页：优先用缓存；缓存没有才去拉
    if (g_pageCached[g_pageIndex] && g_pageCache[g_pageIndex]) {
      g_canvas.loadServerFrame(g_pageCache[g_pageIndex], INK_FRAME_BYTES);
      return true;
    }
    if (!g_frameBuf) return false;
    if (!g_client.fetchPageFrame(curId, g_frameBuf, INK_FRAME_BYTES)) {
      Serial.printf("[page] %s 拉取失败\n", curId);
      return false;
    }
    if (!g_pageCache[g_pageIndex]) g_pageCache[g_pageIndex] = (uint8_t*)malloc(INK_FRAME_BYTES);
    if (g_pageCache[g_pageIndex]) {
      memcpy(g_pageCache[g_pageIndex], g_frameBuf, INK_FRAME_BYTES);
      g_pageCached[g_pageIndex] = true;
    }
    g_canvas.loadServerFrame(g_frameBuf, INK_FRAME_BYTES);
    return true;
  }

  if (strcmp(curType, "message") == 0) {
    char l0[128] = {0}, l1[128] = {0}, l2[128] = {0};
    g_client.fetchMessage(l0, sizeof(l0), l1, sizeof(l1), l2, sizeof(l2));
    inkRenderMessagePage(g_canvas, l0, l1, l2);
    return true;
  }

  // native 页：本地翻页钟
  uint32_t ep = g_net.epoch();
  inkRenderClockPage(g_canvas, ep, curTitle, g_pageIndex, g_pages.count);
  return true;
}

static void gotoPage(int idx)
{
  if (g_pages.count <= 0) { g_pageIndex = 0; return; }
  if (idx < 0) idx = g_pages.count - 1;
  if (idx >= g_pages.count) idx = 0;
  g_pageIndex = idx;
  g_lastPageFetchMs = 0;   // 立即刷新
}

static void refreshManifestIfDue()
{
  uint32_t now = millis();
  if (now - g_lastManifestMs < 30000UL) return;
  g_lastManifestMs = now;
  if (!g_net.connected()) return;
  if (g_client.fetchManifest(g_pages)) {
    if (g_pageIndex >= g_pages.count) g_pageIndex = 0;
  }
}

static void handleKeys()
{
  InkKey key;
  InkKeyEvent ev;
  while (g_keys.poll(key, ev)) {
    Serial.printf("[key] %c event=%d\n", (key == INK_KEY_A) ? 'A' : 'B', (int)ev);
    if (key == INK_KEY_A) {
      switch (ev) {
        case INK_EV_SHORT:  gotoPage(g_pageIndex + 1); break;   // 短按：下一页
        case INK_EV_DOUBLE: gotoPage(g_pageIndex - 1); break;   // 双击：上一页
        case INK_EV_LONG:
          g_display.forceFullRefresh();                          // 长按：立即全刷
          Serial.println("[key] A 长按：全刷");
          break;
        default: break;
      }
    } else if (key == INK_KEY_B) {
      switch (ev) {
        case INK_EV_SHORT:
          g_lastPageFetchMs = 0;                                // 短按：刷新当前页
          break;
        case INK_EV_DOUBLE:
          gotoPage(0);                                           // 双击：回第一页
          break;
        case INK_EV_LONG:
          Serial.println("[key] B 长按：进入配置模式");
          g_net.runConfigPortal();
          g_net.begin();
          g_lastManifestMs = 0;
          break;
        default: break;
      }
    }
  }
}

void setup()
{
  Serial.begin(115200);
  delay(50);
  Serial.println();
  Serial.println("=== eink-mini firmware start ===");

  g_frameBuf = (uint8_t*)malloc(INK_FRAME_BYTES);
  if (!g_frameBuf) {
    Serial.println("[fatal] 内存不足");
    return;
  }

  inkClientBindNet(&g_net);

  g_keys.begin();
  g_display.begin();

  g_net.begin();
  g_timeOk = g_net.syncTime();

  // 上电自检，全刷一次
  renderSelfTest(g_canvas);
  g_display.push(g_canvas, true);
  delay(1200);

  refreshManifestIfDue();
}

void loop()
{
  handleKeys();

  uint32_t now = millis();
  refreshManifestIfDue();

  bool isClock = true;
  if (g_pages.count > 0 && g_pageIndex < g_pages.count) {
    isClock = (strcmp(g_pages.items[g_pageIndex].type, "native") == 0);
  }

  if (isClock && g_timeOk) {
    // 翻页钟每秒重画一次，走局刷只脏数字区域
    uint32_t sec = g_net.epoch();
    if (sec != g_lastClockSec) {
      g_lastClockSec = sec;
      renderCurrentPage();
      g_display.push(g_canvas, false);
    }
  } else if (now - g_lastPageFetchMs > 30000UL) {
    // bitmap / message 页：30 秒拉一次
    g_lastPageFetchMs = now;
    if (renderCurrentPage()) {
      g_display.push(g_canvas, false);
    }
  }

  // 局刷累计到一定时长，做一次全刷清残影
  if (g_display.dueForFullRefresh(now)) {
    renderCurrentPage();
    g_display.push(g_canvas, true);
    Serial.println("[display] 定期全刷");
  }

  delay(10);
}
