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
#include "ink_timer.h"

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

static InkTimer   g_timer;

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
  // 屏高 128，字高 7。y=126 的话只剩 2 行可见，下半截被切掉。
  c.drawText(196, 118, "GRAY CHECK", true, 1);
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
    // bitmap 页：先拉新帧，拉不到才回退缓存。
    //
    // 原来是「有缓存就直接用缓存」，缓存一旦有了就再也不拉新帧 ——
    // 天气页会永远停在开机那一帧，30 秒刷新形同虚设。
    // 拉取节流在 loop() 里做（30 秒一次），这里不用再管。
    if (g_frameBuf && g_client.fetchPageFrame(curId, g_frameBuf, INK_FRAME_BYTES)) {
      if (!g_pageCache[g_pageIndex]) g_pageCache[g_pageIndex] = (uint8_t*)malloc(INK_FRAME_BYTES);
      if (g_pageCache[g_pageIndex]) {
        memcpy(g_pageCache[g_pageIndex], g_frameBuf, INK_FRAME_BYTES);
        g_pageCached[g_pageIndex] = true;
      }
      g_canvas.loadServerFrame(g_frameBuf, INK_FRAME_BYTES);
      return true;
    }
    Serial.printf("[page] %s 拉取失败，回退缓存\n", curId);
    if (g_pageCached[g_pageIndex] && g_pageCache[g_pageIndex]) {
      g_canvas.loadServerFrame(g_pageCache[g_pageIndex], INK_FRAME_BYTES);
      return true;
    }
    return false;
  }

  // native 页：本地渲染。clock 和 timer 走不同的渲染器。
  if (strcmp(curId, "timer") == 0) {
    // 计时器用 millis()，不依赖校时 —— 没校过时照样能跑。
    const char* st = "READY";
    switch (g_timer.state()) {
      case INK_TIMER_RUNNING: st = "RUN";    break;
      case INK_TIMER_PAUSED:  st = "PAUSE";  break;
      case INK_TIMER_DONE:    st = "DONE";   break;
      default:                st = "READY";  break;
    }
    inkRenderTimerPage(g_canvas, st,
                       g_timer.remainingSec(), g_timer.totalSec(),
                       g_timer.presetMinutes(), g_timer.presetIndex(),
                       g_timer.presetCount(),
                       g_pageIndex, g_pages.count);
    return true;
  }

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
  g_lastClockSec = 0;      // 切回时钟页立刻重画，不等下一秒
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
      // 计时器页上 B 键是计时器专用；其它页是原来的行为。
      bool onTimer = false;
      if (g_pages.count > 0 && g_pageIndex < g_pages.count) {
        onTimer = (strcmp(g_pages.items[g_pageIndex].id, "timer") == 0);
      }
      if (onTimer) {
        switch (ev) {
          case INK_EV_SHORT:
            g_timer.toggle();          // 开始 / 暂停 / 继续 / DONE 后重开
            g_lastClockSec = 0;        // 立刻重画
            Serial.printf("[timer] 短按 -> state=%d 剩余 %lus\n",
                          (int)g_timer.state(), (unsigned long)g_timer.remainingSec());
            break;
          case INK_EV_DOUBLE:
            g_timer.cyclePreset();     // 换预设（RUNNING 时忽略）
            g_lastClockSec = 0;
            Serial.printf("[timer] 双击 -> 预设 %d 分钟\n", g_timer.presetMinutes());
            break;
          case INK_EV_LONG:
            g_timer.reset();            // 重置
            g_lastClockSec = 0;
            Serial.println("[timer] 长按 -> 重置");
            break;
          default: break;
        }
      } else {
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
  g_timer.init();

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
  bool isTimer = false;
  if (g_pages.count > 0 && g_pageIndex < g_pages.count) {
    const char* t = g_pages.items[g_pageIndex].type;
    // timer 是一种 native 子类型 —— 设备本地渲染，不拉位图。
    // 判断只看 type 会把它当 bitmap 页，每 30 秒去拉 /api/page/timer.bin（404）。
    isClock = (strcmp(t, "native") == 0 || strcmp(t, "timer") == 0);
    isTimer = (strcmp(g_pages.items[g_pageIndex].id, "timer") == 0);
  }

  if (isTimer) {
    // 计时器每秒重画，走局刷只脏数字区域。
    //
    // 不依赖 g_timeOk：计时器用 millis()，没校过时照样能跑。
    // 归零那一刻做一次全刷反色提醒（设备没有蜂鸣器，视觉是唯一提醒）。
    bool finished = g_timer.tick();
    uint32_t sec = g_timer.remainingSec();
    if (sec != g_lastClockSec || finished) {
      g_lastClockSec = sec;
      renderCurrentPage();
      g_display.push(g_canvas, finished);
      if (finished) Serial.println("[timer] 计时结束");
    }
  } else if (isClock && g_timeOk) {
    // 翻页钟每秒重画一次，走局刷只脏数字区域
    uint32_t sec = g_net.epoch();
    if (sec != g_lastClockSec) {
      g_lastClockSec = sec;
      renderCurrentPage();
      g_display.push(g_canvas, false);
    }
  } else if (now - g_lastPageFetchMs > 30000UL) {
    // bitmap 页：30 秒拉一次
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
