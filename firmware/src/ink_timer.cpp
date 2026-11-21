#include <Arduino.h>
#include "ink_timer.h"

// 预设分钟数在 ink_presets.h —— 屏幕上的预设条也要读它，所以不能只
// 待在这个文件里（ink_pages.cpp 编译时没有 Arduino.h）。
//
// 数组从小到大排，换预设就按这个顺序循环：
// 15 -> 25 -> 30 -> 45 -> 1 -> 3 -> 5 -> 10 -> 15（回到起点）。
//
// 默认索引 4 = 15 分钟。旧注释写的是「默认指向 25」，但 25 在下标 5，
// 代码取的从来都是 15 —— 注释和代码对不上，按代码为准。

void InkTimer::init()
{
  state_ = INK_TIMER_READY;
  presetIndex_ = 4;   // 15 分钟
  lastTickMs_ = millis();
  refreshRemain();
}

int InkTimer::presetMinutes() const
{
  return INK_TIMER_PRESETS[presetIndex_];
}

uint32_t InkTimer::totalSec() const
{
  return (uint32_t)presetMinutes() * 60UL;
}

void InkTimer::refreshRemain()
{
  remainMs_ = totalSec() * 1000UL;
}

void InkTimer::setPreset(int idx)
{
  if (idx < 0) idx = INK_TIMER_PRESET_COUNT - 1;
  if (idx >= INK_TIMER_PRESET_COUNT) idx = 0;
  presetIndex_ = idx;
  refreshRemain();
}

void InkTimer::toggle()
{
  switch (state_) {
    case INK_TIMER_READY:
    case INK_TIMER_PAUSED:
      state_ = INK_TIMER_RUNNING;
      lastTickMs_ = millis();
      break;
    case INK_TIMER_RUNNING:
      // 暂停：先把已跑的补进剩余，再停。
      //
      // tick() 可能刚好把状态推到 DONE（归零那一刻用户按暂停）。
      // 那时不能覆盖成 PAUSED —— 屏上会出现「PAUSE 00:00」这种自相矛盾的
      // 状态，归零的全刷提醒也一起丢了。tick() 返回 true 就是「刚归零」，
      // 保持 DONE 不动。
      if (tick()) return;
      state_ = INK_TIMER_PAUSED;
      break;
    case INK_TIMER_DONE:
      // DONE 后再按：重新装满并开始
      refreshRemain();
      state_ = INK_TIMER_RUNNING;
      lastTickMs_ = millis();
      break;
  }
}

void InkTimer::cyclePreset()
{
  // 换预设现在走 A 键长按 —— 双击已废除（见 ink_keys.h：双击和短按
  // 结构上就抢同一个动作，第一下轻点已经把计时器启动，双击到达时
  // 它在跑，"运行中忽略换预设"这条规则又把双击吃掉，整条路径走不通）。
  //
  // 语义：**任何状态都生效**，换完剩余 = 新预设满值。
  //   READY：只是换个数字
  //   PAUSE：剩余重算（装满新预设，但仍是暂停的）
  //   RUN：  换预设并按新预设重新开始（继续跑）
  //   DONE：  回到 READY，等用户启动新预设
  setPreset(presetIndex_ + 1);
  if (state_ == INK_TIMER_DONE) state_ = INK_TIMER_READY;
  lastTickMs_ = millis();
}

void InkTimer::reset()
{
  state_ = INK_TIMER_READY;
  refreshRemain();
  lastTickMs_ = millis();
}

bool InkTimer::tick()
{
  if (state_ != INK_TIMER_RUNNING) return false;

  uint32_t now = millis();
  // millis() 约 49 天回绕。用无符号减法，回绕时差值仍然正确。
  uint32_t dt = now - lastTickMs_;
  lastTickMs_ = now;
  if (dt == 0) return false;

  if (dt >= remainMs_) {
    remainMs_ = 0;
    if (state_ != INK_TIMER_DONE) {
      state_ = INK_TIMER_DONE;
      return true;
    }
    return false;
  }
  remainMs_ -= dt;
  return false;
}

uint32_t InkTimer::remainingSec() const
{
  uint32_t ms = remainMs_;
  if (state_ == INK_TIMER_RUNNING) {
    uint32_t dt = millis() - lastTickMs_;
    ms = (dt >= ms) ? 0 : ms - dt;
  }
  // 向上取整：剩 59.5 秒时显示 60，不是 59
  return (ms + 999UL) / 1000UL;
}
