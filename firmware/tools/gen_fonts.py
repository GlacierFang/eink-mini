#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成固件用的大号数字字模（1bpp）。

翻页钟的大数字不能用 5x7 ASCII 字库放大 —— 5x7 放大就是一堆方块。
这里从 TrueType 字体离线栅格化成 1bpp 点阵，生成 C 源文件烧进固件。

**位序**：MSB first，**1 = 黑**（和设备帧一致）。

## 三个必须做对的地方

1. **基线要画在画布里面。**
   数字的字高约 0.71 em。基线画在画布顶部，字的上半截直接被裁掉 ——
   量出来的墨迹高度只剩一半，字模全是残的。

2. **量真实墨迹，不是 getbbox。**
   font.getbbox() 返回的是 **advance width** 包络，含左右边距。
   用它量宽度，'1' 会算成和 '0' 一样宽 —— 渲染出来是个胖 1。
   正确做法：先画出来，再对**画出来的像素**求 bbox。

3. **翻页钟的卡片一样宽，数字居中。**
   所有字形用**同一个缩放系数**（高度定标 + 统一横缩），
   各自居中放进同样宽的格子里。'1' 就该窄，不该被拉胖。

## 比例由参考图定

参考图的数字墨迹宽高比约 0.543（Helvetica Bold 味）。
Liberation Sans Bold 天然约 0.78，胖 —— 横向要单独缩。

## 用法

    python3 tools/gen_fonts.py --font <ttf> --height 84 --aspect 0.543 \\
        --out-header src/ink_font_big.h --out-source src/ink_font_big.cpp
"""

import argparse
import os
import sys

from PIL import Image, ImageDraw, ImageFont

# 参与生成的字形：10 个数字 + 横杠（没校时时占位）
CHARS = "0123456789-"

# 源字体的栅格化尺寸。够大，缩放时不掉细节。
RASTER = 240

# 量化阈值：低于它算黑。墨水屏宁可笔画粗也不要断，阈值偏高的。
THRESHOLD = 160


def _render_ink(font, ch):
    """把字形画到大画布上，**裁到真实墨迹**。

    两个坑：
    - 基线必须在画布内（y = RASTER），否则字的上半截被裁掉。
    - 不用 font.getbbox()：它给的是 advance width 包络，含左右边距，
      用它量宽度，'1' 会和 '0' 一样宽 —— 渲染出来是个胖 1。
      这里对画出来的像素求 bbox，那才是真实墨迹。
    """
    pad = 40
    img = Image.new("L", (RASTER * 2, RASTER * 2), 255)
    d = ImageDraw.Draw(img)
    d.text((pad, RASTER), ch, font=font, fill=0, anchor="ls")
    bbox = img.point(lambda v: 255 if v < 128 else 0).getbbox()
    if bbox is None:
        return Image.new("L", (1, 1), 255)
    return img.crop(bbox)


def build_font(font_path, ink_h, aspect=0.543, pad_x=3, pad_v=2, xscale=None):
    """生成字模格子。返回 (cells, cell_w, cell_h, metrics)。"""
    font = ImageFont.truetype(font_path, RASTER)
    inks = {ch: _render_ink(font, ch) for ch in CHARS}

    widths = {ch: inks[ch].size[0] for ch in CHARS}
    heights = {ch: inks[ch].size[1] for ch in CHARS}
    max_h = max(heights.values())

    # 横向缩放：让最宽的那个字（'4'/'8'）达到目标宽高比。
    if xscale is None:
        natural = widths["0"] / float(heights["0"])
        xscale = aspect / natural

    scale = float(ink_h) / max_h
    sx = float(xscale)

    scaled_w = {ch: widths[ch] * scale * sx for ch in CHARS}
    cell_w = int(round(max(scaled_w.values()))) + 2 * pad_x
    real_ink_h = int(round(max_h * scale))
    cell_h = real_ink_h + 2 * pad_v
    ink_top = (cell_h - real_ink_h) // 2

    cells = []
    for ch in CHARS:
        ink = inks[ch]
        tw = max(1, int(round(widths[ch] * scale * sx)))
        th = max(1, int(round(heights[ch] * scale)))
        if ink.size != (tw, th):
            ink = ink.resize((tw, th), Image.LANCZOS)
        cell = Image.new("L", (cell_w, cell_h), 255)
        cell.paste(ink, ((cell_w - tw) // 2, (cell_h - th) // 2))
        cells.append(cell)

    metrics = {
        "xscale": sx,
        "scale": scale,
        "cell_w": cell_w,
        "cell_h": cell_h,
        "ink_h": real_ink_h,
        "ink_top": ink_top,
    }
    return cells, cell_w, cell_h, metrics


def quantize(cell, threshold=THRESHOLD):
    """灰度 -> 1bpp。返回每行的字节。1 = 黑。"""
    w, h = cell.size
    rb = (w + 7) // 8
    rows = []
    px = cell.load()
    for y in range(h):
        row = bytearray(rb)
        for x in range(w):
            if px[x, y] < threshold:
                row[x >> 3] |= (0x80 >> (x & 7))
        rows.append(bytes(row))
    return rows, rb


def mask_to_image(rows, w, h):
    """1bpp 行 -> 灰度图。1 = 黑。"""
    img = Image.new("L", (w, h), 255)
    px = img.load()
    for y in range(h):
        r = rows[y]
        for x in range(w):
            if (r[x >> 3] >> (7 - (x & 7))) & 1:
                px[x, y] = 0
    return img


def emit_files(cells, cell_w, cell_h, m, header_path, source_path, font_path,
               threshold=THRESHOLD):
    rb = (cell_w + 7) // 8

    h = []
    h.append("// ink_font_big.h - 翻页钟大号数字字模（1bpp，1 = 黑，MSB first）")
    h.append("//")
    h.append("// 由 tools/gen_fonts.py 从 TrueType 字体离线生成，**别手改**。")
    h.append("// 换字体或改尺寸就重跑：")
    h.append("//   python3 tools/gen_fonts.py --font %s \\" % font_path)
    h.append("//       --height %d --out-header src/ink_font_big.h \\" % m["ink_h"])
    h.append("//       --out-source src/ink_font_big.cpp")
    h.append("//")
    h.append("// 每个字形占同样宽的一格（翻页钟的卡片一样宽），字形居中 ——")
    h.append("// '1' 保持窄，不被拉胖。")
    h.append("")
    h.append("#pragma once")
    h.append("#include <stdint.h>")
    h.append("")
    h.append("#define INK_BIG_W         %d" % cell_w)
    h.append("#define INK_BIG_H         %d" % cell_h)
    h.append("#define INK_BIG_ROW_BYTES %d" % rb)
    h.append("#define INK_BIG_INK_TOP   %d" % m["ink_top"])
    h.append("#define INK_BIG_INK_H     %d" % m["ink_h"])
    h.append("#define INK_BIG_COUNT     %d" % len(CHARS))
    h.append("")
    h.append("// 取字形数据（INK_BIG_H * INK_BIG_ROW_BYTES 字节，1 = 黑）；")
    h.append("// 不在表里返回 0。第 row 行的起始字节是 g + row * INK_BIG_ROW_BYTES。")
    h.append("const uint8_t* inkBigGlyph(char c);")
    h.append("")
    with open(header_path, "w", encoding="utf-8") as f:
        f.write("\n".join(h))

    c = []
    c.append("// ink_font_big.cpp - 翻页钟大号数字字模（由 tools/gen_fonts.py 生成，别手改）")
    c.append("")
    c.append('#include "ink_font_big.h"')
    c.append("")
    c.append("static const char INK_BIG_CHARS[INK_BIG_COUNT + 1] = \"%s\";" % CHARS)
    c.append("")
    c.append("static const uint8_t INK_BIG_GLYPHS[INK_BIG_COUNT][INK_BIG_H][INK_BIG_ROW_BYTES] = {")
    for ch, cell in zip(CHARS, cells):
        rows, _ = quantize(cell, threshold)
        c.append("  { /* '%s' */" % ch)
        for r in rows:
            c.append("    {" + ",".join("0x%02X" % b for b in r) + "},")
        c.append("  },")
    c.append("};")
    c.append("")
    c.append("const uint8_t* inkBigGlyph(char c)")
    c.append("{")
    c.append("  for (int i = 0; i < INK_BIG_COUNT; i++) {")
    c.append("    if (INK_BIG_CHARS[i] == c) return &INK_BIG_GLYPHS[i][0][0];")
    c.append("  }")
    c.append("  return 0;")
    c.append("}")
    c.append("")
    with open(source_path, "w", encoding="utf-8") as f:
        f.write("\n".join(c))

    return len("\n".join(h)), len("\n".join(c))


def preview(cells, cell_w, cell_h, out_path):
    """预览图：一排数字 + 一个 23:47 的样子。"""
    strip = Image.new("L", (cell_w * len(CHARS), cell_h), 255)
    for i, cell in enumerate(cells):
        strip.paste(cell, (i * cell_w, 0))
    sample = Image.new("L", (cell_w * 4 + 30, cell_h), 255)
    for i, ch in enumerate("2347"):
        sample.paste(cells[CHARS.index(ch)], (i * (cell_w + 10), 0))
    w = max(strip.width, sample.width)
    sheet = Image.new("L", (w, strip.height + sample.height + 20), 255)
    sheet.paste(strip, (0, 0))
    sheet.paste(sample, (0, strip.height + 20))
    sheet.save(out_path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--font", required=True)
    ap.add_argument("--height", type=int, default=84, help="字形墨迹高度（px）")
    ap.add_argument("--aspect", type=float, default=0.543, help="数字宽高比")
    ap.add_argument("--pad-x", type=int, default=3)
    ap.add_argument("--pad-v", type=int, default=2)
    ap.add_argument("--xscale", type=float, default=None)
    ap.add_argument("--threshold", type=int, default=THRESHOLD)
    ap.add_argument("--out-header", required=True)
    ap.add_argument("--out-source", required=True)
    ap.add_argument("--preview")
    args = ap.parse_args()

    if not os.path.exists(args.font):
        print("字体不存在: %s" % args.font, file=sys.stderr)
        return 1

    cells, cw, chh, m = build_font(
        args.font, args.height, args.aspect,
        args.pad_x, args.pad_v, args.xscale,
    )
    hs, cs = emit_files(cells, cw, chh, m, args.out_header,
                        args.out_source, args.font, args.threshold)
    print("生成 %s (%d 字节) + %s (%d 字节)：格子 %dx%d，墨迹 %dx%d，横缩 %.3f"
          % (args.out_header, hs, args.out_source, cs,
             cw, chh, m["ink_h"], m["ink_w"] if "ink_w" in m else m["ink_h"],
             m["xscale"]))
    for c in "0123456789":
        bb = cells[CHARS.index(c)].point(lambda v: 255 if v < THRESHOLD else 0).getbbox()
        if bb is None:
            print("  '%s' 无墨迹（异常）" % c)
            continue
        bw = bb[2] - bb[0]
        bh = bb[3] - bb[1]
        print("  '%s' 墨迹 %dx%d  宽高比 %.3f" % (c, bw, bh, bw / float(bh)))
    if args.preview:
        preview(cells, cw, chh, args.preview)
        print("预览 %s" % args.preview)
    return 0


if __name__ == "__main__":
    sys.exit(main())
