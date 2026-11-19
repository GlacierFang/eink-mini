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
// 时钟页按**分钟**重画。
//
// 原来按秒重画 —— 但屏上只显示 HH:MM，每秒的画面完全一样。
// 等于每秒触发一次局刷，墨水屏残影会一直累积。
static uint32_t g_lastClockMin = 0;
static uint32_t g_lastPageFetchMs = 0;
static bool     g_timeOk = false;
// 切页 / 配网完成 / 首次上电时置 true，立即重绘。
//
// 以前靠 g_lastPageFetchMs = 0 凑「毫秒差 > 30 秒」，那个条件在开机
// 前 30 秒内恒为假 —— 那时切到天气页毫无反应。非 bitmap 页更是完全
// 不走那条分支，状态一变就没画面。
static bool     g_dirtyPage = true;
// 计时器页的秒数单独记。跟时钟页共用一个变量时两边语义不同
// （一个是 epoch，一个是剩余秒），切页容易漏画。
static uint32_t g_lastTimerSec = 0;

// 当前时间。没校时返回 0，渲染器会画成 --:--。
//
// 不用 g_net.timeValid() 判断 —— 那个标志只反映 syncTime() 那 12 秒
// 窗口内有没有成功。lwIP 的 SNTP 之后自己还会重试，time() 一旦被同步
// 就是对的。所以直接看 epoch 是否合理（2020-01-01 之后）。
static uint32_t currentEpoch()
{
  uint32_t ep = g_net.epoch();
  return (ep > 1700000000UL) ? ep : 0UL;
}

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
  if (g_pages.count > 0 && g_pageIndex < g_pages.count) {
    curId = g_pages.items[g_pageIndex].id;
    curType = g_pages.items[g_pageIndex].type;
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
    inkRenderTimerPage(g_canvas, st, g_timer.remainingSec());
    return true;
  }

  // 用 currentEpoch()，不是 g_net.epoch()。
  // 未校时时 lwIP 的 time() 返回开机秒数（很小，比如 120），加上东八区会渲染成
  // 08:01 这种假时间。currentEpoch() 把 < 1700000000 的值过滤成 0，渲染器画成 --:--。
  uint32_t ep = currentEpoch();
  inkRenderClockPage(g_canvas, ep);
  return true;
}

static void gotoPage(int idx)
{
  if (g_pages.count <= 0) { g_pageIndex = 0; return; }
  if (idx < 0) idx = g_pages.count - 1;
  if (idx >= g_pages.count) idx = 0;
  g_pageIndex = idx;
  g_lastPageFetchMs = 0;   // 立即刷新
  g_lastClockMin = 0;      // 切回时钟页立刻重画，不等下一分钟
  g_lastTimerSec = 0;
  g_dirtyPage = true;      // 立刻重绘
}

static void refreshManifestIfDue()
{
  uint32_t now = millis();
  // g_lastManifestMs == 0 表示「还没拉过」—— 必须放行。
  //
  // 原来是 now - g_lastManifestMs < 30000 就跳过。开机时 g_lastManifestMs
  // 是 0 而 millis() 也才几十，差值 < 30000，于是第一次拉取被跳过，
  // 之后要等 30 秒才拉。开机那 30 秒屏上是自检画面。
  if (g_lastManifestMs != 0 && (now - g_lastManifestMs) < 30000UL) return;
  g_lastManifestMs = now;
  if (!g_net.connected()) return;
  if (g_client.fetchManifest(g_pages)) {
    if (g_pageIndex >= g_pages.count) g_pageIndex = 0;
    g_dirtyPage = true;   // 清单可能变了，重画一次当前页
  }
}

// 木鱼敲击的帧序：击打 -> 挥过 -> 静息。
// 帧号与服务端 merit.FRAME_* 一致：0=静息 1=击打 2=挥过。
// 三帧之间的额外间隔。局刷本身约 420ms，push() 是阻塞的，
// 所以这个值只是视觉留白，不是节奏主体。
static const uint32_t MERIT_FRAME_GAP_MS = 120;
static const int MERIT_FRAME_SEQ[3] = {1, 2, 0};

// 在木鱼页上敲一下：一次按键播三帧。
//
// 服务端按 ?f=N 决定显示哪一帧，只有击打帧计一次功德，
// 所以三帧请求加起来仍然算敲一下、功德 +1。
//
// 帧间隔 450ms：局刷一次约 420ms（GxEPD2_290 partial_refresh_time），
// 太密会互相覆盖，太疏就不像敲一下。
static bool knockMeritOnMeritPage()
{
  if (g_pages.count <= 0 || g_pageIndex >= g_pages.count) return false;
  if (strcmp(g_pages.items[g_pageIndex].id, "merit") != 0) return false;
  if (!g_frameBuf) return false;
  for (int i = 0; i < 3; i++) {
    if (!g_client.fetchPageFrameAt("merit", MERIT_FRAME_SEQ[i], g_frameBuf, INK_FRAME_BYTES)) {
      Serial.println("[merit] 取帧失败");
      break;
    }
    g_canvas.loadServerFrame(g_frameBuf, INK_FRAME_BYTES);
    g_display.push(g_canvas, false);
    // push() 内部已经等面板刷完（局刷约 420ms），这里只留一点间隔
    // 让三帧在视觉上分得开；再多等就是白白拖慢节奏。
    delay(MERIT_FRAME_GAP_MS);
  }
  return true;
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
            g_lastTimerSec = 0;        // 立刻重画
            g_dirtyPage = true;
            Serial.printf("[timer] 短按 -> state=%d 剩余 %lus\n",
                          (int)g_timer.state(), (unsigned long)g_timer.remainingSec());
            break;
          case INK_EV_DOUBLE:
            g_timer.cyclePreset();     // 换预设（RUNNING 时忽略）
            g_lastTimerSec = 0;        // 立刻重画
            g_dirtyPage = true;
            Serial.printf("[timer] 双击 -> 预设 %d 分钟\n", g_timer.presetMinutes());
            break;
          case INK_EV_LONG:
            g_timer.reset();            // 重置
            g_lastTimerSec = 0;        // 立刻重画
            g_dirtyPage = true;
            Serial.println("[timer] 长按 -> 重置");
            break;
          default: break;
        }
      } else {
        switch (ev) {
          case INK_EV_SHORT:
            if (knockMeritOnMeritPage()) break;                  // 木鱼页：一次按键播三帧
            g_lastPageFetchMs = 0;                                // 短按：刷新当前页
            g_dirtyPage = true;                                  // 立刻重绘
            break;
          case INK_EV_DOUBLE:
            gotoPage(0);                                           // 双击：回第一页
            break;
          case INK_EV_LONG:
            Serial.println("[key] B 长按：进入配置模式");
            g_net.runConfigPortal();
            g_net.begin();
            g_lastManifestMs = 0;
          // 配网完必须重新校时。原来只在 setup 里校过一次，
          // 配完网 g_timeOk 还是 false，时钟页会一直停在 --:--。
          g_timeOk = g_net.syncTime();
          g_dirtyPage = true;
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

  // 页面类型判断。
  //
  // timer 是 native 的子类型 —— 设备本地渲染，不拉位图。只看
  // type == "native" 会把它当 bitmap 页，每 30 秒去拉 /api/page/timer.bin（404）。
  //
  // g_pages.count == 0 表示 manifest 还没拉到（没配网、或拉失败）。
  // 这时也要显示时钟页，不能停在自检画面。
  bool isLocal = true;
  bool isTimer = false;
  if (g_pages.count > 0 && g_pageIndex < g_pages.count) {
    const char* t = g_pages.items[g_pageIndex].type;
    isTimer = (strcmp(g_pages.items[g_pageIndex].id, "timer") == 0);
    isLocal = (strcmp(t, "native") == 0 || strcmp(t, "timer") == 0);
  }

  bool doRender = false;
  bool doFull = false;

  if (isTimer) {
    // 计时器每秒重画，走局刷只脏数字区域。
    //
    // 不依赖校时：计时器用 millis()，没校过时照样能跑。
    // 归零那一刻做一次全刷反色提醒（设备没有蜂鸣器，视觉是唯一提醒）。
    bool finished = g_timer.tick();
    uint32_t sec = g_timer.remainingSec();
    if (sec != g_lastTimerSec || finished) {
      g_lastTimerSec = sec;
      doRender = true;
      doFull = finished;
      if (finished) Serial.println("[timer] 计时结束");
    }
  } else if (isLocal) {
    // 时钟页按分钟重画，走局刷只脏数字区域。
    //
    // 不看 g_timeOk，看 epoch 本身：没校时时 currentEpoch() 返回 0，
    // 渲染器画成 --:--。这样即使 SNTP 在 syncTime() 的 12 秒窗口之后
    // 才成功，设备也能自己活过来，不用重启。
    uint32_t ep = currentEpoch();
    uint32_t minute = ep / 60UL;
    if (minute != g_lastClockMin) {
      g_lastClockMin = minute;
      doRender = true;
    }
  } else {
    // bitmap 页：30 秒拉一次
    if (g_dirtyPage || (now - g_lastPageFetchMs) > 30000UL) {
      g_lastPageFetchMs = now;
      doRender = true;
    }
  }

  // 切页、配网完成、首次上电等状态变化：立刻重绘。
  if (g_dirtyPage) {
    g_dirtyPage = false;
    doRender = true;
  }

  if (doRender && renderCurrentPage()) {
    g_display.push(g_canvas, doFull);
  }

  // 局刷累计到一定时长，做一次全刷清残影
  if (g_display.dueForFullRefresh(now)) {
    renderCurrentPage();
    g_display.push(g_canvas, true);
    Serial.println("[display] 定期全刷");
  }

  delay(10);
}
