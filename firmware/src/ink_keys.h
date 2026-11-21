#pragma once
#include <stdint.h>

enum InkKey : uint8_t { INK_KEY_A = 0, INK_KEY_B = 1, INK_KEY_COUNT = 2 };

enum InkKeyEvent : uint8_t {
  INK_EV_NONE = 0,
  INK_EV_SHORT,
  INK_EV_LONG
};

// 两键手势引擎（2026-11-21 改版）。
//
// 原来有 SHORT / DOUBLE / LONG 三种。DOUBLE 和 SHORT 结构上就抢同一个
// 动作：双击必须等第二次松开才能判定，而那时第一次轻按的副作用已经
// 发生了。于是「短按=开始倒计时、双击=换预设」永远不可能同时成立 ——
// 第一下轻点已经把计时器启动，双击到达时它在跑，而「运行中忽略换预设」
// 这条规则又把双击吃掉。整条路径走不通，不是判定写得不准的问题。
//
// 现在只有 SHORT / LONG 两种，语义互斥、与顺序无关：
//   短按：松开即刻发（按住时长 < 600ms）
//   长按：按住满 600ms 当场发，之后松开不再补发短按
// 消抖 25ms。
//
// 选预设改走 A 键长按（见 main.cpp），不再占用双击。
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
    uint8_t  pendingEvent = 0;
    uint8_t  pendingKey = 0;
  };
  State st_[INK_KEY_COUNT];

  void update(int idx, int pin);
};
