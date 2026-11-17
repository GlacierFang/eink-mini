#pragma once
#include <stdint.h>

enum InkKey : uint8_t { INK_KEY_A = 0, INK_KEY_B = 1, INK_KEY_COUNT = 2 };

enum InkKeyEvent : uint8_t {
  INK_EV_NONE = 0,
  INK_EV_SHORT,
  INK_EV_DOUBLE,
  INK_EV_LONG
};

// 两键手势引擎。
//
//   长按 >= 600ms 优先；一旦判定长按，就不再产生短按/双击。
//   短按后等 250ms 确认窗：窗内再来一次 -> 双击；窗到期 -> 单击。
//   消抖 25ms。
class InkKeys {
public:
  void begin();
  // 有事件返回 true。
  bool poll(InkKey& key, InkKeyEvent& event);

private:
  struct State {
    uint8_t  raw = 1;
    uint8_t  stable = 1;
    uint32_t changedAt = 0;
    uint32_t pressedAt = 0;
    bool     down = false;
    bool     longFired = false;
    uint32_t pendingClickAt = 0;  // 单击待确认到期时间，0 = 无
    uint8_t  pendingEvent = 0;    // 已就绪待取走的事件
    uint8_t  pendingKey = 0;
  };
  State st_[INK_KEY_COUNT];

  void update(int idx, int pin);
};
