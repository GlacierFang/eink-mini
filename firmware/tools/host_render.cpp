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
//   - 控制台预览：输出设备帧格式，和设备真正收到的一致
//
// 用法：
//   host_render sheet <输出目录>
//       出 6 张图（PGM）：时钟（已校时/没校时）、计时器四态
//
//   host_render frame <clock|timer> <输出文件> [键=值 ...]
//       出设备帧（4736 字节，1=黑，MSB first，每行 37 字节）。
//       可用键：epoch, label, state, remaining, total, preset,
//               presetIndex, pageIndex, pageCount
//
// 注意：自检画面在 main.cpp 里（依赖 g_display / g_net 全局状态），
// 这个工具不渲染它。

#include "ink_canvas.h"
#include "ink_pages.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// 固定 epoch，sheet 模式用这个，输出才可复现。
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

// 设备帧格式：1=黑，MSB first，每行 37 字节，共 4736 字节。
//
// 画布的位约定是面板侧的 1=白，设备帧是 1=黑 —— 所以这里取反。
// 服务端下发的帧也是 1=黑（INK_SERVER_BIT1_IS_BLACK），两边一致。
static void writeFrame(const char* path, const InkCanvas& c)
{
  FILE* f = fopen(path, "wb");
  if (!f) {
    fprintf(stderr, "open %s failed\n", path);
    return;
  }
  uint8_t row[INK_ROW_BYTES];
  for (int y = 0; y < INK_H; y++) {
    memset(row, 0, sizeof(row));
    for (int x = 0; x < INK_W; x++) {
      if (c.pxIsBlack(x, y)) {
        row[x >> 3] |= (uint8_t)(0x80 >> (x & 7));
      }
    }
    fwrite(row, 1, INK_ROW_BYTES, f);
  }
  fclose(f);
  printf("  %s (%d bytes)\n", path, INK_FRAME_BYTES);
}

static void renderSheet(const char* out)
{
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
}

// 键=值 解析
static uint32_t getU32(const char* key, uint32_t def)
{
  const char* p = strstr(key, "=");
  if (!p) return def;
  return (uint32_t)strtoul(p + 1, NULL, 10);
}

// 多个字符串参数要同时活着（label 和 state 都是），所以用一组轮换的
// 缓冲区 —— 单个 static buf 会被后一次调用覆盖，label 会变成 state 的值。
static const char* getStr(const char* key, const char* def)
{
  const char* p = strstr(key, "=");
  if (!p) return def;
  static char bufs[4][128];
  static int next = 0;
  char* buf = bufs[next];
  next = (next + 1) % 4;
  size_t i = 0;
  p++;
  while (*p && *p != ' ' && i < sizeof(buf) - 1) buf[i++] = *p++;
  buf[i] = 0;
  return buf;
}

static int renderFrame(const char* page, const char* out, int argc, char** argv)
{
  uint32_t epoch    = getU32("epoch", 0);
  const char* label = getStr("label", "CLOCK");
  const char* state = getStr("state", "READY");
  uint32_t remain   = getU32("remaining", 900);
  uint32_t total    = getU32("total", 900);
  int preset        = (int)getU32("preset", 15);
  int presetIndex   = (int)getU32("presetIndex", 4);
  int pageIndex     = (int)getU32("pageIndex", 0);
  int pageCount     = (int)getU32("pageCount", 4);

  // 未传的键从命令行尾部收
  for (int i = 0; i < argc; i++) {
    const char* a = argv[i];
    if (strncmp(a, "epoch=", 6) == 0)          epoch = getU32(a, epoch);
    else if (strncmp(a, "label=", 6) == 0)     label = getStr(a, label);
    else if (strncmp(a, "state=", 6) == 0)     state = getStr(a, state);
    else if (strncmp(a, "remaining=", 10) == 0) remain = getU32(a, remain);
    else if (strncmp(a, "total=", 6) == 0)      total = getU32(a, total);
    else if (strncmp(a, "preset=", 7) == 0)    preset = (int)getU32(a, preset);
    else if (strncmp(a, "presetIndex=", 12) == 0) presetIndex = (int)getU32(a, presetIndex);
    else if (strncmp(a, "pageIndex=", 10) == 0)  pageIndex = (int)getU32(a, pageIndex);
    else if (strncmp(a, "pageCount=", 10) == 0)  pageCount = (int)getU32(a, pageCount);
  }

  InkCanvas c;
  if (strcmp(page, "clock") == 0) {
    inkRenderClockPage(c, epoch, label, pageIndex, pageCount);
  } else if (strcmp(page, "timer") == 0) {
    inkRenderTimerPage(c, state, remain, total, preset, presetIndex, 8,
                       pageIndex, pageCount);
  } else {
    fprintf(stderr, "unknown page: %s\n", page);
    return 2;
  }
  writeFrame(out, c);
  return 0;
}

int main(int argc, char** argv)
{
  if (argc < 2) {
    fprintf(stderr,
            "usage:\n"
            "  host_render sheet <outdir>\n"
            "  host_render frame <clock|timer> <outfile> [k=v ...]\n");
    return 1;
  }

  if (strcmp(argv[1], "sheet") == 0 && argc >= 3) {
    renderSheet(argv[2]);
    return 0;
  }
  if (strcmp(argv[1], "frame") == 0 && argc >= 4) {
    return renderFrame(argv[2], argv[3], argc - 4, argv + 4);
  }

  fprintf(stderr, "bad arguments\n");
  return 1;
}
