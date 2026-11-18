#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成固件用的小号状态词字模（1bpp，1 = 黑，MSB first）。

计时器顶部那行状态词（READY / RUN / PAUSE / DONE）用 5x7 ASCII 字库太小：
PAUSE 只有 24x7 px，在 296x128 的墨水屏上几乎看不见。
而计时器在跑和暂停时数字画面完全一样，状态词是唯一的区分手段，
它必须一眼可读。

这里从 TrueType 字体离线栅格化成 1bpp 点阵，生成 C 源文件烧进固件。

**位序**：MSB first，**1 = 黑**（和设备帧一致）。

## 三个必须做对的地方

1. **基线要画在画布里面。** 和 gen_fonts.py 同一个坑：锚点用 baseline，
   基线落在画布内部，字的上半截才不会被裁掉。

2. **量真实墨迹，不是 getbbox。** getbbox 给的是 advance width 包络，
   含左右边距。用它量宽度，每个字都会被算成一样宽。

3. **所有大写字母共用一条垂直带。** 每个字裁自己的左右，
   上下用**全体字形墨迹的并集**裁 —— 竖直方向基线统一，
   矮一点的字（'E' 比 'O' 矮）顶上自然留白。

## 为什么是比例宽度

状态词长度差别大（RUN 三个字，READY 五个字）。等宽格子会让 RUN 看起来松垮，
READY 看起来挤。这里每个字形存自己的墨迹宽度，绘制时逐字推进。

## 用法

    python3 tools/gen_font_state.py --font <ttf> --height 13 --out-header src/ink_font_state.h --out-source src/ink_font_state.cpp
"""

import argparse
import os
import sys

from PIL import Image, ImageDraw, ImageFont

# 只做状态词用得到的大写字母。
CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# 源字体的栅格化尺寸。够大，缩放时不掉细节。
RASTER = 240

# 量化阈值：低于它算黑。墨水屏宁可笔画粗也不要断，阈值偏高的。
THRESHOLD = 160


def _render_ink(font, ch):
    """把字形画到大画布上，返回 (图像, 墨迹bbox)。

    基线用 anchor="ls" 落在画布内部：字的上半截才不会被裁掉。
    宽度按**画出来的像素**量，不用 font.getbbox()。
    """
    pad = 40
    img = Image.new("L", (RASTER * 2, RASTER * 2), 255)
    d = ImageDraw.Draw(img)
    d.text((pad, RASTER), ch, font=font, fill=0, anchor="ls")
    bbox = img.point(lambda v: 255 if v < 128 else 0).getbbox()
    if bbox is None:
        return None, None
    return img, bbox


def build_font(font_path, ink_h):
    """生成字形。返回 {字符: 灰度图}。"""
    font = ImageFont.truetype(font_path, RASTER)
    raw = {}
    top = None
    bottom = None
    for ch in CHARS:
        img, bbox = _render_ink(font, ch)
        if bbox is None:
            continue
        raw[ch] = (img, bbox)
        if top is None or bbox[1] < top:
            top = bbox[1]
        if bottom is None or bbox[3] > bottom:
            bottom = bbox[3]

    band_h = bottom - top
    scale = float(ink_h) / band_h

    cells = {}
    for ch, (img, bbox) in raw.items():
        cropped = img.crop((bbox[0], top, bbox[2], bottom))
        w = max(1, int(round(cropped.size[0] * scale)))
        h = max(1, int(round(cropped.size[1] * scale)))
        cells[ch] = cropped.resize((w, h), Image.LANCZOS)
    return cells


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
    return rows


def emit(cells, header_path, source_path, font_path, threshold=THRESHOLD):
    chars = [c for c in CHARS if c in cells]
    max_w = max(cells[c].size[0] for c in chars)
    ink_h = max(cells[c].size[1] for c in chars)

    data = bytearray()
    offsets = []
    widths = []
    for ch in chars:
        offsets.append(len(data))
        widths.append(cells[ch].size[0])
        for r in quantize(cells[ch], threshold):
            data += r

    h = []
    h.append("// ink_font_state.h - 计时器状态词字模（1bpp，1 = 黑，MSB first）")
    h.append("//")
    h.append("// 由 tools/gen_font_state.py 从 TrueType 字体离线生成，**别手改**。")
    h.append("// 换字体或改尺寸就重跑：")
    h.append("//   python3 tools/gen_font_state.py --font %s --height %d \\" % (font_path, ink_h))
    h.append("//       --out-header src/ink_font_state.h --out-source src/ink_font_state.cpp")
    h.append("//")
    h.append("// 大写字母，比例宽度（每个字形存自己的墨迹宽度，'I' 不被拉胖）。")
    h.append("// 取字形数据（INK_STATE_H 行，每行 ceil(宽/8) 字节，1 = 黑）；")
    h.append("// 不在表里返回 0。宽度写进 *w。")
    h.append("")
    h.append("#pragma once")
    h.append("#include <stdint.h>")
    h.append("")
    h.append("#define INK_STATE_H       %d" % ink_h)
    h.append("#define INK_STATE_INK_TOP 0")
    h.append("#define INK_STATE_COUNT   %d" % len(chars))
    h.append("#define INK_STATE_SPACING 2")
    h.append("#define INK_STATE_MAX_W   %d" % max_w)
    h.append("")
    h.append("// 取字形数据；不在表里返回 0。")
    h.append("const uint8_t* inkStateGlyph(char c, int* w);")
    h.append("")
    with open(header_path, "w", encoding="utf-8") as f:
        f.write(chr(10).join(h))

    c = []
    c.append("// ink_font_state.cpp - 计时器状态词字模（由 tools/gen_font_state.py 生成，别手改）")
    c.append("")
    c.append('#include "ink_font_state.h"')
    c.append("")
    c.append('static const char INK_STATE_CHARS[INK_STATE_COUNT + 1] = "%s";' % "".join(chars))
    c.append("")
    c.append("static const uint8_t INK_STATE_WIDTHS[INK_STATE_COUNT] = {")
    c.append("  " + ", ".join(str(w) for w in widths))
    c.append("};")
    c.append("")
    c.append("static const uint32_t INK_STATE_OFFSETS[INK_STATE_COUNT] = {")
    c.append("  " + ", ".join(str(o) for o in offsets))
    c.append("};")
    c.append("")
    c.append("static const uint8_t INK_STATE_DATA[] = {")
    line = "  "
    for b in data:
        tok = "0x%02X, " % b
        if len(line) + len(tok) > 96:
            c.append(line.rstrip())
            line = "  "
        line += tok
    if line.strip():
        c.append(line.rstrip())
    c.append("};")
    c.append("")
    c.append("const uint8_t* inkStateGlyph(char c, int* w)")
    c.append("{")
    c.append("  for (int i = 0; i < INK_STATE_COUNT; i++) {")
    c.append("    if (INK_STATE_CHARS[i] == c) {")
    c.append("      if (w) *w = INK_STATE_WIDTHS[i];")
    c.append("      return &INK_STATE_DATA[INK_STATE_OFFSETS[i]];")
    c.append("    }")
    c.append("  }")
    c.append("  if (w) *w = 0;")
    c.append("  return 0;")
    c.append("}")
    c.append("")
    with open(source_path, "w", encoding="utf-8") as f:
        f.write(chr(10).join(c))

    return len(chr(10).join(h)), len(chr(10).join(c)), len(data)


def preview(cells, out_path):
    """预览图：拼出 PAUSE / READY / RUN 三个状态词的样子。"""
    strip = Image.new("L", (200, 40), 255)
    x = 2
    for word in ("PAUSE", "READY", "RUN", "DONE"):
        for ch in word:
            if ch not in cells:
                continue
            c = cells[ch]
            strip.paste(c, (x, 2))
            x += c.size[0] + 2
        x += 8
        if x > 190:
            break
    strip.save(out_path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--font", required=True)
    ap.add_argument("--height", type=int, default=13, help="字形墨迹高度（px）")
    ap.add_argument("--threshold", type=int, default=THRESHOLD)
    ap.add_argument("--out-header", required=True)
    ap.add_argument("--out-source", required=True)
    ap.add_argument("--preview")
    args = ap.parse_args()

    if not os.path.exists(args.font):
        print("字体不存在: %s" % args.font, file=sys.stderr)
        return 1

    cells = build_font(args.font, args.height)
    hs, cs, ds = emit(cells, args.out_header, args.out_source, args.font, args.threshold)
    print("生成 %s (%d 字节) + %s (%d 字节)：字高 %d，数据 %d 字节"
          % (args.out_header, hs, args.out_source, cs, args.height, ds))
    for ch in "READYRUNPSO":
        if ch in cells:
            w, h = cells[ch].size
            print("  '%s' 墨迹 %dx%d" % (ch, w, h))
    if args.preview:
        preview(cells, args.preview)
        print("预览 %s" % args.preview)
    return 0


if __name__ == "__main__":
    sys.exit(main())
