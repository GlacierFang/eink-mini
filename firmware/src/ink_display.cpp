#include "ink_display.h"

#include <Arduino.h>
#include <SPI.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <string.h>

#include <GxEPD2_EPD.h>
#include <epd/GxEPD2_290.h>

// ---------------------------------------------------------------- BUSY 探测
// 驱动板 BUSY 极性不固定，不能写死。做法：
//   1) 上电后先读一次空闲电平，作为 idle 基准；
//   2) 在一次刷新期间用独立任务以 1ms 采样 BUSY；
//   3) 若采样到与 idle 不同的电平，那个电平就是"忙"电平；
//   4) 采样不到就退回延时模式（busy = -1），此时库内部按固定时长等待，
//      配合库自带的 10s 超时兜底，不会卡死。
namespace {
volatile uint8_t g_busySample = 0;
volatile uint8_t g_busyHaveDiff = 0;
volatile uint8_t g_busyOther = 0;
volatile uint8_t g_busyRunning = 0;

void busySamplerTask(void* arg)
{
  (void)arg;
  while (g_busyRunning) {
    uint8_t v = (uint8_t)digitalRead(INK_PIN_BUSY);
    if (v != g_busySample) {
      g_busyHaveDiff = 1;
      g_busyOther = v;
    }
    vTaskDelay(1);
  }
  vTaskDelete(NULL);
}
}  // namespace

// GxEPD2_290 的构造函数把 BUSY 电平写死成 HIGH；这里派生一层，
// 把探测出来的极性传给基类，从而真正做到"不写死"。
class InkEPD : public GxEPD2_290 {
public:
  InkEPD(int16_t cs, int16_t dc, int16_t rst, int16_t busy, int16_t busy_level,
         uint32_t busy_timeout_ms)
    : GxEPD2_EPD(cs, dc, rst, busy, busy_level, busy_timeout_ms * 1000UL,
                 GxEPD2_290::WIDTH, GxEPD2_290::HEIGHT, GxEPD2_290::panel,
                 GxEPD2_290::hasColor, GxEPD2_290::hasPartialUpdate,
                 GxEPD2_290::hasFastPartialUpdate) {}
};

static InkEPD* g_panel = nullptr;

// ---------------------------------------------------------------- 坐标映射
// 业务坐标 (x: 0..295, y: 0..127) -> 面板坐标 (px: 0..127, py: 0..295)
#if INK_ROT_CW
// 顺时针 90 度：px = 127 - y, py = x
static inline int inkPanelX(int y) { return INK_PANEL_W - 1 - y; }
static inline int inkPanelY(int x) { return x; }
#else
// 逆时针 90 度：px = y, py = 127 - x
static inline int inkPanelX(int y) { return y; }
static inline int inkPanelY(int x) { return INK_PANEL_W - 1 - x; }
#endif

bool InkDisplay::buildPanelFrame(const InkCanvas& c, uint8_t* out) const
{
  memset(out, 0xFF, INK_FRAME_BYTES);   // 全白
  for (int x = 0; x < INK_W; x++) {
    for (int y = 0; y < INK_H; y++) {
      int px = inkPanelX(y);
      int py = inkPanelY(x);
      uint8_t* row = out + (size_t)py * INK_PANEL_ROW_BYTES;
      int byte = px >> 3;
      uint8_t mask = (uint8_t)(0x80 >> (px & 7));
      if (c.pxIsBlack(x, y)) row[byte] &= (uint8_t)~mask;
      else                 row[byte] |= mask;
    }
  }
  return true;
}

// 在面板空间逐字节比较新旧两帧，找脏矩形。
bool InkDisplay::detectDirty(int& px, int& py, int& pw, int& ph) const
{
  if (!havePrev_) return false;
  int minX = INK_PANEL_W, maxX = -1, minY = INK_PANEL_H, maxY = -1;
  for (int row = 0; row < INK_PANEL_H; row++) {
    const uint8_t* a = newFrame_ + (size_t)row * INK_PANEL_ROW_BYTES;
    const uint8_t* b = prevFrame_ + (size_t)row * INK_PANEL_ROW_BYTES;
    if (memcmp(a, b, INK_PANEL_ROW_BYTES) == 0) continue;
    if (row < minY) minY = row;
    if (row > maxY) maxY = row;
    for (int byte = 0; byte < INK_PANEL_ROW_BYTES; byte++) {
      if (a[byte] == b[byte]) continue;
      int x0 = byte * 8;
      for (int k = 0; k < 8; k++) {
        uint8_t mask = (uint8_t)(0x80 >> k);
        if ((a[byte] & mask) == (b[byte] & mask)) continue;
        if (x0 + k < minX) minX = x0 + k;
        if (x0 + k > maxX) maxX = x0 + k;
      }
    }
  }
  if (maxY < 0) return false;
  if (minX < 0) minX = 0;
  if (maxX > INK_PANEL_W - 1) maxX = INK_PANEL_W - 1;
  // x 与 w 必须 8 像素对齐
  int x0 = minX & ~7;
  int x1 = (maxX | 7) + 1;
  if (x1 > INK_PANEL_W) x1 = INK_PANEL_W;
  px = x0;
  py = minY;
  pw = x1 - x0;
  ph = maxY - minY + 1;
  if (pw <= 0 || ph <= 0) return false;
  return true;
}

bool InkDisplay::writeFullFrame(const uint8_t* frame)
{
  if (!g_panel) return false;
  g_panel->writeImage(frame, 0, 0, INK_PANEL_W, INK_PANEL_H);
  g_panel->writeImageToPrevious(frame, 0, 0, INK_PANEL_W, INK_PANEL_H);
  g_panel->refresh(false);
  return true;
}

bool InkDisplay::writePartialFrame(const uint8_t* frame, int px, int py, int pw, int ph)
{
  if (!g_panel) return false;
  // 用 writeImagePart 直接从整帧里取子区域，省掉一次拷贝
  g_panel->writeImagePart(frame, px, py, INK_PANEL_W, INK_PANEL_H, px, py, pw, ph);
  g_panel->writeImagePartToPrevious(prevFrame_, px, py, INK_PANEL_W, INK_PANEL_H, px, py, pw, ph);
  g_panel->refresh(px, py, pw, ph);
  // 刷新完成：把 RAM2 的同一窗口同步成新内容，保证 RAM2 与 RAM 处处相等，
  // 否则下一次差分刷新时控制器会认为窗口外也变了，把窗口外一起刷一遍。
  g_panel->writeImagePartToPrevious(frame, px, py, INK_PANEL_W, INK_PANEL_H, px, py, pw, ph);
  return true;
}

const char* InkDisplay::polarityName() const
{
  if (busyLevel_ == -2) return "unprobed";
  if (busyLevel_ == -1) return "delay-mode";
  return busyLevel_ ? "busy-high" : "busy-low";
}

bool InkDisplay::dueForFullRefresh(uint32_t nowMs) const
{
  if (!havePrev_) return true;
  return (uint32_t)(nowMs - lastFullMs_) >= INK_FULL_REFRESH_INTERVAL_MS;
}

bool InkDisplay::begin()
{
  Serial.begin(115200);
  delay(50);

  // SPI 必须先按我们的引脚初始化：GxEPD2 内部调 SPI.begin() 无参版本，
  // 若我们已经初始化过，库会直接返回，我们的引脚不会被改掉。
  SPI.begin(INK_PIN_SCK, INK_PIN_MISO, INK_PIN_MOSI, INK_PIN_CS);

  pinMode(INK_PIN_BUSY, INPUT);

  // ---- 探测 BUSY 极性 ----
  g_busyHaveDiff = 0;
  g_busyOther = 0;
  g_busyRunning = 1;
  uint8_t idle = (uint8_t)digitalRead(INK_PIN_BUSY);
  g_busySample = idle;

  xTaskHandle_t task = NULL;
  xTaskCreate(busySamplerTask, "busySamp", 2048, NULL, 1, &task);

  // 先用"忙=高"试一次（多数驱动板是这个极性）
  if (g_panel) delete g_panel;
  // 探测阶段用 3 秒超时：万一极性猜错，最多等 3 秒而不是 10 秒
  g_panel = new InkEPD(INK_PIN_CS, INK_PIN_DC, INK_PIN_RST, INK_PIN_BUSY, HIGH, 3000);
  g_panel->init(115200, true, 10, false);
  g_panel->clearScreen(0xFF);

  // 探测期间再采样一次极性
  uint32_t t0 = millis();
  while (millis() - t0 < 1200) {
    uint8_t v = (uint8_t)digitalRead(INK_PIN_BUSY);
    if (v != idle) { g_busyHaveDiff = 1; g_busyOther = v; }
    delay(1);
  }

  g_busyRunning = 0;
  if (task) {
    vTaskDelay(20);
    if (g_busyRunning == 0) { /* 任务自行退出 */ }
  }

  if (g_busyHaveDiff) {
    busyLevel_ = g_busyOther ? HIGH : LOW;
  } else {
    busyLevel_ = -1;   // 采不到变化 -> 延时模式
  }

  // 用探测出来的极性重建面板实例
  if (g_panel) delete g_panel;
  g_panel = new InkEPD(INK_PIN_CS, INK_PIN_DC, INK_PIN_RST,
                       (busyLevel_ < 0) ? -1 : INK_PIN_BUSY,
                       busyLevel_ < 0 ? HIGH : busyLevel_,
                       10000);
  g_panel->init(115200, true, 10, false);
  g_panel->clearScreen(0xFF);

  // RAM2（0x26）初始化成白色，让后续差分刷新有正确的"旧帧"基准
  static uint8_t white[INK_FRAME_BYTES];
  memset(white, 0xFF, sizeof(white));
  g_panel->writeImageToPrevious(white, 0, 0, INK_PANEL_W, INK_PANEL_H);

  havePrev_ = false;
  lastFullMs_ = millis();
  Serial.printf("[display] BUSY 极性: %s\n", polarityName());
  return true;
}

bool InkDisplay::forceFullRefresh()
{
  if (!g_panel) return false;
  bool ok = writeFullFrame(newFrame_);
  lastFullMs_ = millis();
  return ok;
}

bool InkDisplay::push(const InkCanvas& canvas, bool forceFull)
{
  if (!g_panel) return false;
  buildPanelFrame(canvas, newFrame_);

  bool ok;
  if (!havePrev_ || forceFull) {
    ok = writeFullFrame(newFrame_);
    lastFullMs_ = millis();
  } else {
    int px, py, pw, ph;
    if (detectDirty(px, py, pw, ph)) {
      ok = writePartialFrame(newFrame_, px, py, pw, ph);
    } else {
      ok = true;   // 内容没变，不刷
    }
  }

  memcpy(prevFrame_, newFrame_, INK_FRAME_BYTES);
  havePrev_ = true;
  return ok;
}
