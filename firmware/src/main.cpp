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
// 用户手动要求重拉当前位图（B 短按）。
static bool     g_forceRefresh = false;
// 计时器刚归零 —— 等一次全刷（设备没蜂鸣器，视觉是唯一提醒）。
static bool     g_timerJustDone = false;
// 切页：下一次重绘做一次全刷。
//
// 切页是整屏内容都变了。局刷只重写脏矩形，窗口外的上一页内容会留在
// 屏上（翻页钟 -> 位图页尤其明显），差分局刷的残影也会一次次叠上去。
// 切页是低频事件，全刷一次最划算。
static bool     g_fullRefresh = false;
// 设备状态上报节流（当前页 + 计时器）。
static uint32_t g_lastStateReportMs = 0;
// 上次按键事件的时间。用户刚按过键时别发网络请求 —— 阻塞会吞掉按键。
static uint32_t g_lastKeyEventMs = 0;
// 状态变了，等着上报（延后 2 秒，给用户的手指让路）。
static bool     g_stateReportDirty = false;
static uint32_t g_stateReportAtMs = 0;
// 时钟页按**分钟**重画。
//
// 原来按秒重画 —— 但屏上只显示 HH:MM，每秒的画面完全一样。
// 等于每秒触发一次局刷，墨水屏残影会一直累积。
static uint32_t g_lastClockMin = 0;
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

// 当前页是不是服务端下发位图的页
static bool currentIsBitmap()
{
  if (g_pages.count <= 0 || g_pageIndex >= g_pages.count) return false;
  return strcmp(g_pages.items[g_pageIndex].type, "bitmap") == 0;
}

// 当前页的位图要不要重新拉：
//   - 从没拉过
//   - 服务端版本变了（内容变了）
//   - 用户手动要求刷新
// 版本没变就不拉 —— 设备停在天气页时，一天也拉不了几次位图。
static bool currentPageNeedsFetch()
{
  if (!currentIsBitmap()) return false;
  const InkPageEntry& e = g_pages.items[g_pageIndex];
  if (!g_pageCached[g_pageIndex] || !g_pageCache[g_pageIndex]) return true;
  if (g_forceRefresh) return true;
  if (!e.hasApplied) return true;
  return e.version != e.appliedVersion;
}

// 计时器状态词。服务端和主机渲染器用同一套名字。
static const char* timerStateLabel()
{
  switch (g_timer.state()) {
    case INK_TIMER_RUNNING: return "RUN";
    case INK_TIMER_PAUSED:  return "PAUSE";
    case INK_TIMER_DONE:    return "DONE";
    default:                return "READY";
  }
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
    // bitmap 页：版本变了才拉新帧，拉不到才回退缓存。
    //
    // 原来是「每 30 秒拉一次」—— 内容没变也照拉照推。现在清单里每页带
    // 版本号，只有版本变了才重新拉。
    //
    // 拉取节流在 loop() 里做，这里只管「这一页要不要重新拉」。
    const InkPageEntry& e = g_pages.items[g_pageIndex];
    bool cached = g_pageCached[g_pageIndex] && g_pageCache[g_pageIndex] != nullptr;
    bool needFetch = !cached || g_forceRefresh || !e.hasApplied || e.version != e.appliedVersion;
    if (needFetch && g_frameBuf && g_client.fetchPageFrame(curId, g_frameBuf, INK_FRAME_BYTES)) {
      if (!g_pageCache[g_pageIndex]) g_pageCache[g_pageIndex] = (uint8_t*)malloc(INK_FRAME_BYTES);
      if (g_pageCache[g_pageIndex]) {
        memcpy(g_pageCache[g_pageIndex], g_frameBuf, INK_FRAME_BYTES);
        g_pageCached[g_pageIndex] = true;
      }
      g_canvas.loadServerFrame(g_frameBuf, INK_FRAME_BYTES);
      // 真拉到并上屏了，才记下这个版本 —— 拉失败下一轮还会再试。
      g_pages.items[g_pageIndex].appliedVersion = e.version;
      g_pages.items[g_pageIndex].hasApplied = true;
      g_forceRefresh = false;
      return true;
    }
    if (needFetch) {
      Serial.printf("[page] %s 拉取失败，回退缓存\n", curId);
    }
    if (cached) {
      g_canvas.loadServerFrame(g_pageCache[g_pageIndex], INK_FRAME_BYTES);
      return true;
    }
    return false;
  }

  // native 页：本地渲染。clock 和 timer 走不同的渲染器。
  if (strcmp(curId, "timer") == 0) {
    // 计时器用 millis()，不依赖校时 —— 没校过时照样能跑。
    inkRenderTimerPage(g_canvas, timerStateLabel(), g_timer.remainingSec(),
                       g_timer.presetIndex());
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
  g_lastClockMin = 0;      // 切回时钟页立刻重画，不等下一分钟
  g_lastTimerSec = 0;
  g_dirtyPage = true;      // 立刻重绘
  g_fullRefresh = true;    // 切页做一次全刷
}

static void refreshManifestIfDue()
{
  uint32_t now = millis();
  // g_lastManifestMs == 0 表示「还没拉过」—— 必须放行。
  //
  // 清单拉取就是心跳：每 INK_HEARTBEAT_PERIOD_MS 一次，服务端靠它判在线。
  if (g_lastManifestMs != 0 && (now - g_lastManifestMs) < INK_HEARTBEAT_PERIOD_MS) return;
  g_lastManifestMs = now;
  if (!g_net.connected()) return;

  // 拉之前先记下当前是第几页、什么 id —— 拉完要判断「当前页变没变」。
  char beforeId[40];
  beforeId[0] = 0;
  if (g_pages.count > 0 && g_pageIndex < g_pages.count) {
    strncpy(beforeId, g_pages.items[g_pageIndex].id, sizeof(beforeId) - 1);
  }
  int beforeCount = g_pages.count;

  if (g_client.fetchManifest(g_pages)) {
    if (g_pageIndex >= g_pages.count) g_pageIndex = 0;
    char afterId[40];
    afterId[0] = 0;
    if (g_pageIndex < g_pages.count) {
      strncpy(afterId, g_pages.items[g_pageIndex].id, sizeof(afterId) - 1);
    }
    // 清单变了才重画当前页 —— 版本没变说明内容没变，重画只是把同一帧
    // 再推一遍（一次空拉 + 一次局刷判断）。
    if (beforeCount != g_pages.count ||
        strcmp(beforeId, afterId) != 0 ||
        currentPageNeedsFetch()) {
      g_dirtyPage = true;
    }
  }
}

// 把设备自己的状态报给服务端：当前页 + 计时器。
//
// 计时器状态只存在设备 RAM 里，服务端不猜、不假装看得到 ——
// 控制台要显示真实倒计时，只能靠设备报上来。
//
// **绝不在按键处理里发这个请求。** 一次 HTTP 可能阻塞好几秒，阻塞期间
// loop 不跑，按键不会被采样：轻点被整个吞掉，松开没被采样还会被判成
// 长按（长按 = reset）—— 倒计时被用户自己的手指重置。
//
// 所以：按键处理只置 g_stateReportDirty，真正的请求放到 loop 末尾发，
// 并且延后 2 秒；周期上报遇到用户刚按过键也让路。
static void reportDeviceStateIfDue(bool force)
{
  uint32_t now = millis();
  if (!force) {
    if (g_lastStateReportMs != 0 && (now - g_lastStateReportMs) < INK_STATE_REPORT_PERIOD_MS) return;
    // 用户刚按过键就让路：这时发请求等于拿手指的响应去换网络往返。
    if ((uint32_t)(now - g_lastKeyEventMs) < 3000UL) return;
  }
  g_lastStateReportMs = now;
  if (!g_net.connected()) return;
  const char* pageId = "";
  if (g_pages.count > 0 && g_pageIndex < g_pages.count) pageId = g_pages.items[g_pageIndex].id;
  if (!g_client.reportDeviceState(pageId, timerStateLabel(),
                                  g_timer.remainingSec(),
                                  (uint32_t)g_timer.presetMinutes())) {
    Serial.println("[state] 上报失败");
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
// 帧间隔 120ms：局刷一次约 420ms（GxEPD2_290 partial_refresh_time，
// push() 内部已等刷完），这里只补一点视觉留白。
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
    g_lastKeyEventMs = millis();   // 用户正在操作：别在这时候发网络请求
    // 当前是不是计时器页 —— 决定 A 长按是「换预设」还是「全刷」。
    bool onTimer = false;
    if (g_pages.count > 0 && g_pageIndex < g_pages.count) {
      onTimer = (strcmp(g_pages.items[g_pageIndex].id, "timer") == 0);
    }
    if (key == INK_KEY_A) {
      switch (ev) {
        case INK_EV_SHORT:
          gotoPage(g_pageIndex + 1);        // 短按：下一页
          break;
        case INK_EV_LONG:
          if (onTimer) {
            // 计时器页：A 长按换下一个预设。
            //
            // 换预设原来走 B 双击，但双击和 B 短按（启停）结构上抢同一个
            // 动作：双击必须等第二次松开才判定，那时短按已经把计时器启动
            // 了。双击已废除，预设改挂到 A 键长按上。
            g_timer.cyclePreset();
            g_lastTimerSec = 0;
            g_dirtyPage = true;
            g_stateReportDirty = true;
            g_stateReportAtMs = millis() + 2000;
            Serial.printf("[timer] A 长按 -> 预设 %d 分钟\n", g_timer.presetMinutes());
          } else {
            g_display.forceFullRefresh();  // 其它页：长按立即全刷
            Serial.println("[key] A 长按：全刷");
          }
          break;
        default: break;
      }
    } else if (key == INK_KEY_B) {
      // 计时器页上 B 键是计时器专用；其它页是原来的行为。
      if (onTimer) {
        switch (ev) {
          case INK_EV_SHORT:
            g_timer.toggle();          // 开始 / 暂停 / 继续 / DONE 后重开
            g_lastTimerSec = 0;        // 立刻重画
            g_dirtyPage = true;
            g_stateReportDirty = true; // 上报挪到 loop 末尾，别在这里阻塞
            g_stateReportAtMs = millis() + 2000;
            Serial.printf("[timer] 短按 -> state=%d 剩余 %lus\n",
                          (int)g_timer.state(), (unsigned long)g_timer.remainingSec());
            break;
          case INK_EV_LONG:
            g_timer.reset();            // B 长按：重置
            g_lastTimerSec = 0;        // 立刻重画
            g_dirtyPage = true;
            g_stateReportDirty = true;
            g_stateReportAtMs = millis() + 2000;
            Serial.println("[timer] 长按 -> 重置");
            break;
          default: break;
        }
      } else {
        switch (ev) {
          case INK_EV_SHORT:
            if (knockMeritOnMeritPage()) break;                  // 木鱼页：一次按键播三帧
            g_forceRefresh = true;                                // 短按：强制重拉当前页
            g_dirtyPage = true;                                  // 立刻重绘
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
  reportDeviceStateIfDue(false);

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

  // 计时器每一轮都推进，跟当前在哪一页无关。
  //
  // 以前只有停在计时器页时才 tick() —— 离开页面倒计时就不推进，状态卡在
  // RUNNING，回来时靠一次大 dt 补算，屏上是「突然就结束了」。现在离开页面
  // 也照常走完，归零那一刻的状态变化不会丢。
  bool timerFinished = g_timer.tick();
  if (timerFinished) g_timerJustDone = true;

  if (isTimer) {
    // 计时器每秒重画，走局刷只脏数字区域。
    //
    // 不依赖校时：计时器用 millis()，没校过时照样能跑。
    // 归零那一刻做一次全刷提醒（设备没有蜂鸣器，视觉是唯一提醒）。
    uint32_t sec = g_timer.remainingSec();
    if (sec != g_lastTimerSec || timerFinished || g_timerJustDone) {
      g_lastTimerSec = sec;
      doRender = true;
      doFull = g_timerJustDone;
      g_timerJustDone = false;
      if (timerFinished) Serial.println("[timer] 计时结束");
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
    // bitmap 页：版本变了才重新拉，别的什么都不做。
    if (currentPageNeedsFetch()) doRender = true;
  }

  // 切页、配网完成、首次上电等状态变化：立刻重绘。
  if (g_dirtyPage) {
    g_dirtyPage = false;
    doRender = true;
    // 切页做一次全刷：整屏内容都变了，局刷只重写脏矩形，
    // 窗口外的上一页内容会留在屏上。
    if (g_fullRefresh) {
      doFull = true;
      g_fullRefresh = false;
    }
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

  // 状态变了要上报服务端 —— 放在 loop 末尾，且延后 2 秒。
  // 绝不能在按键处理里发：网络往返的阻塞会把按键吞掉。
  if (g_stateReportDirty && (int32_t)(millis() - g_stateReportAtMs) >= 0) {
    g_stateReportDirty = false;
    reportDeviceStateIfDue(true);
  }

  delay(10);
}
