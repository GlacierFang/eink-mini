#include "ink_keys.h"
#include "ink_config.h"
#include <Arduino.h>

static const int PINS[INK_KEY_COUNT] = { INK_PIN_KEY_A, INK_PIN_KEY_B };

void InkKeys::begin()
{
  for (int i = 0; i < INK_KEY_COUNT; i++) {
    pinMode(PINS[i], INPUT_PULLUP);
    st_[i].raw = (uint8_t)digitalRead(PINS[i]);
    st_[i].stable = st_[i].raw;
    st_[i].changedAt = millis();
    st_[i].down = (st_[i].stable == 0);
    st_[i].pressedAt = millis();
    st_[i].longFired = false;
    st_[i].pendingEvent = 0;
    st_[i].pendingKey = 0;
  }
}

void InkKeys::update(int idx, int pin)
{
  State& s = st_[idx];
  uint32_t now = millis();
  uint8_t r = (uint8_t)digitalRead(pin);

  if (r != s.raw) {
    s.raw = r;
    s.changedAt = now;
  }

  if (r != s.stable && (now - s.changedAt) >= INK_KEY_DEBOUNCE_MS) {
    s.stable = r;
    bool nowDown = (r == 0);
    if (nowDown && !s.down) {
      s.down = true;
      s.pressedAt = now;
      s.longFired = false;
    } else if (!nowDown && s.down) {
      s.down = false;
      if (!s.longFired) {
        // 短按：松开即刻发。没有确认窗 —— 确认窗（双击）已废除，
        // 留着只会让每次轻点都晚 250ms 才生效。
        if (s.pendingEvent == INK_EV_NONE) {
          s.pendingEvent = INK_EV_SHORT;
          s.pendingKey = (uint8_t)idx;
        }
      }
    }
  }

  // 长按：按住满阈值当场判定，屏蔽后续短按。
  //
  // **必须再看一眼物理引脚**：采样不是连续的 —— loop 里只要有一次阻塞
  // （网络请求、面板刷新），按键就有一段时间没被采样。这段时间里用户
  // 松了手，s.down 还是旧的 true，而 now - pressedAt 已经过了阈值，
  // 于是这一下轻点被判成长按（长按在计时器页是 reset —— 倒计时被
  // 自己的手指重置）。
  //
  // 所以判长按时直接读引脚：引脚已经松开就不判。
  if (s.down && !s.longFired && (now - s.pressedAt) >= INK_KEY_LONG_MS) {
    if (digitalRead(PINS[idx]) == 0) {
      s.longFired = true;
      if (s.pendingEvent == INK_EV_NONE) {
        s.pendingEvent = INK_EV_LONG;
        s.pendingKey = (uint8_t)idx;
      }
    }
  }
}

bool InkKeys::poll(InkKey& key, InkKeyEvent& event)
{
  // 先采样引脚。
  //
  // 这里原来漏了这一步：update() 写好了但从来没人调，poll() 只读
  // pendingEvent —— 那个字段只由 update() 写。结果是按键永远不产生
  // 事件，整机没有任何交互。
  for (int i = 0; i < INK_KEY_COUNT; i++) {
    update(i, PINS[i]);
  }

  for (int i = 0; i < INK_KEY_COUNT; i++) {
    if (st_[i].pendingEvent != INK_EV_NONE) {
      key = (InkKey)i;
      event = (InkKeyEvent)st_[i].pendingEvent;
      st_[i].pendingEvent = INK_EV_NONE;
      return true;
    }
  }
  return false;
}
