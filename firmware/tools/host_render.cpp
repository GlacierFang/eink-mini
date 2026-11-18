// 主机端渲染器 —— 在 PC / Pi 上编译固件的渲染代码，输出屏上画面。
//
// ink_canvas.cpp + ink_pages.cpp 是纯逻辑，不依赖 Arduino API。
// 在主机上编译它们，画出来的就是设备上会显示的像素 —— 逐像素一致，
// 不是「长得像」。
//
// 用途：
//   - 版式验证：改完版式立刻出图，不用等硬件到货
//   - 回归对比：每次改渲染代码出一组图，肉眼比对
//   - 抓逻辑错：fillRect 那种语法没错但画错的 bug，只有出图才看得见
//
// 用法： firmware/tools/render_host.sh [输出目录]
//
// 注意：自检画面在 main.cpp 里（依赖 g_display / g_net 全局状态），
// 这个工具不渲染它。

#include "ink_canvas.h"
#include "ink_pages.h"

#include <stdio.h>

// 固定 epoch，输出才可复现。
static const uint32_t FIXED_EPOCH = 1763500000UL;

static void writePGM(const char* path, const InkCanvas& c)
{
  FILE* f = fopen(path, "wb");
  if (!f) {
    fprintf(stderr, "open %s failed\n", path);
    return;
  }
  fprintf(f, "P5\n%d %d\n255\n", INK_W, INK_H);
  for (int y = 0; y < INK_H; y++) {
    for (int x = 0; x < INK_W; x++) {
      fputc(c.pxIsBlack(x, y) ? 0 : 255, f);
    }
  }
  fclose(f);
  printf("  %s\n", path);
}

int main(int argc, char** argv)
{
  const char* out = (argc > 1) ? argv[1] : ".";
  char path[512];

  // 时钟页（已校时）
  {
    InkCanvas c;
    inkRenderClockPage(c, FIXED_EPOCH, "CLOCK", 0, 4);
    snprintf(path, sizeof(path), "%s/host-clock.pgm", out);
    writePGM(path, c);
  }

  // 时钟页（没校时）—— epoch == 0 时渲染成 --:--
  {
    InkCanvas c;
    inkRenderClockPage(c, 0, "CLOCK", 0, 4);
    snprintf(path, sizeof(path), "%s/host-clock-notime.pgm", out);
    writePGM(path, c);
  }

  // 计时器四种状态
  {
    const char* labels[4] = { "READY", "RUN", "PAUSE", "DONE" };
    const char* names[4]  = { "ready", "run", "pause", "done" };
    uint32_t secs[4]      = { 900, 754, 754, 0 };
    for (int i = 0; i < 4; i++) {
      InkCanvas c;
      inkRenderTimerPage(c, labels[i], secs[i], 900, 15, 4, 8, 1, 4);
      snprintf(path, sizeof(path), "%s/host-timer-%s.pgm", out, names[i]);
      writePGM(path, c);
    }
  }

  return 0;
}
