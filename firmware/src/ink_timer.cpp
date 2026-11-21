#include <Arduino.h>
#include "ink_timer.h"

// 预设分钟数。放在固件里，不走服务端 ——
// 改预设要重编固件，但预设这东西本来也不常改。
//
// 数组从小到大排，双击换预设就按这个顺序循环：
// 15 -> 25 -> 30 -> 45 -> 1 -> 3 -> 5 -> 10 -> 15（回到起点）。
//
// 默认索引 4 = 15 分钟。旧注释写的是「默认指向 25」，但 25 在下标 5，
// 代码取的从来都是 15 —— 注释和代码对不上，按代码为准。
const int InkTimer::PRESET_MINUTES[8] = { 1, 3, 5, 10, 15, 25, 30, 45 };
const int InkTimer::PRESET_COUNT = 8;

void InkTimer::init()
{
  state_ = INK_TIMER_READY;
  presetIndex_ = 4;   // 15 分钟
  lastTickMs_ = millis();
  refreshRemain();
}

int InkTimer::presetMinutes() const
{
  return PRESET_MINUTES[presetIndex_];
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
  if (idx < 0) idx = PRESET_COUNT - 1;
  if (idx >= PRESET_COUNT) idx = 0;
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
  // RUNNING 时忽略：倒计时中途换预设没有意义，而且容易误触
  if (state_ == INK_TIMER_RUNNING) return;
  setPreset(presetIndex_ + 1);
  state_ = INK_TIMER_READY;
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
