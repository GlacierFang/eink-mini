// ink_merit_store.h - 功德计数存在设备本地（NVS）
//
// 计数只增不减 —— 除非用户在木鱼页长按 B 清零。掉电不丢。
//
// 设备是权威：敲没敲只有设备知道，服务器只是只读镜像。
// 「服务器权威 + 设备影子计数 + 断网补报」那套已经废除 ——
// 两个计数路径同时命中同一次敲击，就是「一次敲击被算成两次」的根源。
#pragma once
#include <stdint.h>

void inkMeritLoad(void);          // 从 NVS 读计数。setup 里调一次。

uint32_t inkMeritCount(void);     // 当前功德
uint32_t inkMeritStrike(void);    // 累计敲击次数（清零也不清它）

// 计数是不是已经定下来（接过服务器的数，或本地已经敲过）。
// 没定下来之前不往服务器报 —— 免得用半截数把服务器的值盖掉。
bool inkMeritSeeded(void);

// 接一次服务器上已有的计数。只在「本地一次没敲过」时接 ——
// 本地已经敲过就以本地为准（设备是权威）。
void inkMeritSeed(uint32_t count, uint32_t strike);

void inkMeritTap(void);           // 敲一下：功德 +1，累计敲击次数 +1
void inkMeritClear(void);         // 清零：功德归零，累计敲击次数保留
