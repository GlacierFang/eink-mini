#pragma once
#include <stdint.h>

// 本地计时器页。
//
// **不用 epoch，用 millis()**。
// millis() 单调递增，不依赖 SNTP 也不依赖 HTTP 校时。
// 结果：没校过时计时器照样能用 —— 比时钟页还独立。
//
// **状态只在 RAM 里**。断电不持久化（2026-11-18 定：不做持久化）。
//
// **零网络流量**。这一页不拉 manifest 之外的东西，也不拉位图。

enum InkTimerState : uint8_t {
  INK_TIMER_READY = 0,   // 已选预设，未开始
  INK_TIMER_RUNNING,     // 正在跑
  INK_TIMER_PAUSED,      // 暂停中
  INK_TIMER_DONE         // 归零，等用户重开
};

class InkTimer {
public:
  void init();

  // 按键操作
  void toggle();       // 短按：开始 / 暂停 / 继续；DONE 时重开
  void cyclePreset();  // 双击：下一个预设（RUNNING 时忽略，防误触）
  void reset();        // 长按：回到 READY，清零

  InkTimerState state() const { return state_; }
  int presetIndex() const { return presetIndex_; }
  int presetMinutes() const;
  int presetCount() const { return PRESET_COUNT; }

  // 剩余秒数。DONE 返回 0。
  uint32_t remainingSec() const;
  // 本轮总秒数（当前预设的满值），用于画进度条
  uint32_t totalSec() const;

  // 每秒调一次。返回 true 表示状态发生了变化（比如刚归零）。
  bool tick();

private:
  static const int PRESET_MINUTES[8];
  static const int PRESET_COUNT;

  InkTimerState state_ = INK_TIMER_READY;
  int presetIndex_ = 4;          // 默认 15 分钟
  uint32_t remainMs_ = 0;        // 剩余毫秒（RUNNING 时是快照值）
  uint32_t lastTickMs_ = 0;      // 上次 tick 的 millis

  void setPreset(int idx);
  void refreshRemain();
};
