// ink_merit_store.cpp - 功德计数存在设备本地（NVS）
#include "ink_merit_store.h"

#include <Arduino.h>
#include <Preferences.h>

// 独立命名空间：网络配置用 "ink"（ink_net.cpp），功德计数用 "merit"。
static const char* NVS_NS = "merit";

static uint32_t g_count = 0;
static uint32_t g_strike = 0;
static bool g_seeded = false;

void inkMeritLoad(void)
{
  Preferences p;
  p.begin(NVS_NS, false);
  g_count = p.getUInt("count", 0);
  g_strike = p.getUInt("strike", 0);
  g_seeded = p.getBool("seeded", false);
  p.end();
}

static void save(void)
{
  Preferences p;
  p.begin(NVS_NS, false);
  p.putUInt("count", g_count);
  p.putUInt("strike", g_strike);
  p.putBool("seeded", g_seeded);
  p.end();
}

uint32_t inkMeritCount(void) { return g_count; }
uint32_t inkMeritStrike(void) { return g_strike; }
bool inkMeritSeeded(void) { return g_seeded; }

void inkMeritSeed(uint32_t count, uint32_t strike)
{
  if (g_seeded) return;
  // 服务器上是老固件时代的数（网页端敲的和设备拉位图时算的）。
  // 本地这几个敲击服务器还不知道 —— 叠上去，不能盖掉它。
  uint32_t local = g_strike;
  g_count = count + local;
  g_strike = strike + local;
  g_seeded = true;
  save();
  Serial.printf("[merit] 接服务器的计数: count=%lu strike=%lu（本地另敲 %lu）\n",
                (unsigned long)g_count, (unsigned long)g_strike, (unsigned long)local);
}

void inkMeritTap(void)
{
  g_count++;
  g_strike++;
  save();
}

void inkMeritClear(void)
{
  g_count = 0;
  save();
}
