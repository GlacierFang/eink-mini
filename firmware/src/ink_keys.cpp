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
    st_[i].pendingClickAt = 0;
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
        if (s.pendingClickAt != 0) {
          // 确认窗内第二次按下 -> 双击
          s.pendingClickAt = 0;
          s.pendingEvent = INK_EV_DOUBLE;
          s.pendingKey = (uint8_t)idx;
        } else {
          // 第一次按下 -> 挂起，等确认窗
          s.pendingClickAt = now + INK_KEY_DOUBLE_MS;
        }
      }
    }
  }

  // 长按优先：按下持续超过阈值即判定，屏蔽后续短按
  if (s.down && !s.longFired && (now - s.pressedAt) >= INK_KEY_LONG_MS) {
    s.longFired = true;
    s.pendingClickAt = 0;
    s.pendingEvent = INK_EV_LONG;
    s.pendingKey = (uint8_t)idx;
  }
}

bool InkKeys::poll(InkKey& key, InkKeyEvent& event)
{
  // 先采样引脚。
  //
  // 这里原来漏了这一步：update() 写好了但从来没人调，poll() 只读
  // pendingEvent / pendingClickAt —— 那两个字段只由 update() 写。
  // 结果是按键永远不产生事件，整机没有任何交互。
  for (int i = 0; i < INK_KEY_COUNT; i++) {
    update(i, PINS[i]);
  }

  uint32_t now = millis();

  // 先看有没有已就绪的事件（长按/双击优先送出）
  for (int i = 0; i < INK_KEY_COUNT; i++) {
    if (st_[i].pendingEvent != INK_EV_NONE) {
      key = (InkKey)i;
      event = (InkKeyEvent)st_[i].pendingEvent;
      st_[i].pendingEvent = INK_EV_NONE;
      return true;
    }
  }

  // 再把到期的单击放出来
  for (int i = 0; i < INK_KEY_COUNT; i++) {
    if (st_[i].pendingClickAt != 0 && now >= st_[i].pendingClickAt) {
      st_[i].pendingClickAt = 0;
      key = (InkKey)i;
      event = INK_EV_SHORT;
      return true;
    }
  }
  return false;
}
