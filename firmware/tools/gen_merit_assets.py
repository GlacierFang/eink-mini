#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成固件里的赛博木鱼资源：三帧整屏位图 + 数字字模。

输出的两个文件（**别手改**，改素材或字号就重跑本脚本）：

    src/ink_merit_assets.h
    src/ink_merit_assets.cpp

## 为什么要在固件里烘焙

木鱼页要能断网敲。三帧位图从服务器拉就做不到 —— 服务器不在，页面就是空的。

素材还是同一套（images/1.png 抬槌 / 2.png 击打 / 3.png 挥过），
版式还是原来那套（木鱼占满屏高，右边「功德」+ 大号数字），
只是**渲染一次、烧进固件**，运行时不再需要服务器。

## 位序

1 = 黑，MSB first，行跨度 37 字节（296/8）。和设备帧、和固件画布一致。

## 数字字模

设备没有中文字库，「功德」两个字烘焙在帧里；数字是 ASCII，用字模画。

字模从 TrueType 离线栅格化，方法和服务端画数字一样：
3 倍超采样 -> BOX 降采样 -> 硬阈值。每个数字记三个量：

    dx / dy   墨迹左上角相对**文字原点**（左边、ascender 线）的偏移
    advance  前进宽度

固件按这些量把数字排成一行，**墨迹右缘对齐到 x=284** ——
和服务端 render_merit 的排版口径一样。

字号阶梯和服务端一致（52→20），从大到小取第一个宽度放得下的。

## 用法

    python3 tools/gen_merit_assets.py --out-header src/ink_merit_assets.h \\
        --out-source src/ink_merit_assets.cpp
"""

import argparse
import os
import sys

from PIL import Image, ImageDraw, ImageFont

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
SERVER_DIR = os.path.join(REPO, "server")
sys.path.insert(0, SERVER_DIR)

import renderer  # noqa: E402

IMAGE_DIR = os.path.join(REPO, "images")

# 帧序：0 静息 / 1 击打 / 2 挥过。
FRAME_IDLE = 0
FRAME_STRIKE = 1
FRAME_SWING = 2
FRAME_FILES = {FRAME_IDLE: "1.png", FRAME_STRIKE: "2.png", FRAME_SWING: "3.png"}
FRAMES = [FRAME_IDLE, FRAME_STRIKE, FRAME_SWING]

# 数字字模的字号阶梯（逻辑像素）—— 和服务端 render_merit 完全一致。
DIGIT_SIZES = [52, 46, 40, 34, 28, 24, 20]

# 版式常量（逻辑像素，和服务端 render_merit 对齐）
FISH_PX = 372            # 木鱼素材放大到的实际像素（= 124 逻辑像素）
FISH_POS = (18, 6)       # 木鱼贴左上（实际像素）
LABEL_TEXT = "功德"
LABEL_SIZE = 18          # 逻辑像素
LABEL_Y = 16             # 逻辑像素
DIGIT_RIGHT = 284        # 数字墨迹右缘
DIGIT_TOP = 44           # 数字 ascender 线
DIGIT_MAX_W = 150        # 数字最多占这么宽（右半屏，木鱼占左边 130）

# 栅格化时的画布边距（必须是 3 的倍数 —— 降采样的网格要和整页对齐）
_PAD = 60
_ORIGIN = 90             # 文字原点在实际像素画布上的位置（3 的倍数）


def _threshold_mask(img, threshold):
    """灰度图 -> 布尔行（True = 黑）。和 renderer.to_mask 的 hard 模式一致。"""
    g = img.convert("L")
    w, h = g.size
    src = g.load()
    return [[src[x, y] < threshold for x in range(w)] for y in range(h)]


def _mask_to_bytes(mask):
    """布尔行 -> 1bpp 字节（1 = 黑，MSB first，行跨度 ceil(w/8)）。"""
    row_bytes = (len(mask[0]) + 7) // 8
    out = bytearray(row_bytes * len(mask))
    for y, row in enumerate(mask):
        base = y * row_bytes
        for x, black in enumerate(row):
            if black:
                out[base + (x >> 3)] |= 0x80 >> (x & 7)
    return bytes(out), row_bytes


def _fish_gray(frame):
    """素材帧 -> 灰度图（白底，FISH_PX 见方）。"""
    path = os.path.join(IMAGE_DIR, FRAME_FILES[frame])
    rgba = Image.open(path).convert("RGBA")
    if rgba.size != (FISH_PX, FISH_PX):
        rgba = rgba.resize((FISH_PX, FISH_PX), Image.LANCZOS)
    gray = Image.new("L", (FISH_PX, FISH_PX), 255)
    gray.paste(rgba.convert("L"), (0, 0), rgba.split()[3])
    return gray


def render_frames():
    """三帧整屏位图（不含数字 —— 数字随功德变，固件自己画）。"""
    frames = []
    for frame in FRAMES:
        canvas = Image.new("L", (renderer.W * renderer.SCALE, renderer.H * renderer.SCALE), 255)
        canvas.paste(_fish_gray(frame), FISH_POS)

        d = ImageDraw.Draw(canvas)
        font = ImageFont.truetype(renderer.FONT_BOLD, LABEL_SIZE * renderer.SCALE)
        bbox = d.textbbox((0, 0), LABEL_TEXT, font=font)
        d.text((renderer.W * renderer.SCALE - 12 * renderer.SCALE - (bbox[2] - bbox[0]),
                LABEL_Y * renderer.SCALE),
               LABEL_TEXT, font=font, fill=0)

        # 3 倍超采样 -> BOX 降采样，和服务端 renderer.downsample 同一条路。
        small = renderer.downsample(canvas)
        # 挥过帧的残影是浅色虚线，硬阈值 165 会吃掉它 —— 这帧放宽到 190。
        thr = 190 if frame == FRAME_SWING else renderer.DEFAULT_THRESHOLD
        mask = renderer.to_mask(small, renderer.DEFAULT_MODE, thr, size=(renderer.W, renderer.H))
        frames.append(renderer.mask_to_frame(mask))
    return frames


def _digit_glyph(font, ch):
    """渲染一个数字，量出位图和排版需要的数。

    返回 (位图字节, 墨迹宽, 墨迹高, 行字节, dx, dy, advance)。

    dx / dy 是墨迹左上角相对**文字原点**（左边、ascender 线）的偏移。

    降采样按 3 的倍数裁剪：BOX 是 3x3 面积平均，裁剪框不在网格上，
    同一个字在页面上和在单独字模里会长得不一样。
    """
    bbox = font.getbbox(ch, anchor="la")
    if bbox is None:
        return None
    x0, y0, x1, y1 = bbox

    canvas = Image.new("L", (600, 600), 255)
    d = ImageDraw.Draw(canvas)
    d.text((_ORIGIN, _ORIGIN), ch, font=font, fill=0, anchor="la")

    # 墨迹框对齐到 3 的网格。
    cx0 = ((_ORIGIN + x0) // 3) * 3
    cy0 = ((_ORIGIN + y0) // 3) * 3
    cx1 = -(-(_ORIGIN + x1) // 3) * 3
    cy1 = -(-(_ORIGIN + y1) // 3) * 3
    crop = canvas.crop((cx0, cy0, cx1, cy1)).resize(
        ((cx1 - cx0) // 3, (cy1 - cy0) // 3), Image.BOX)

    # 降采样后再量一次墨迹，裁到墨迹 —— 边缘的半灰像素不算墨迹。
    mask = _threshold_mask(crop, renderer.DEFAULT_THRESHOLD)
    minx, miny, maxx, maxy = -1, -1, -1, -1
    for y, row in enumerate(mask):
        for x, black in enumerate(row):
            if black:
                if minx < 0 or x < minx:
                    minx = x
                if maxx < 0 or x > maxx:
                    maxx = x
                if miny < 0 or y < miny:
                    miny = y
                if maxy < 0 or y > maxy:
                    maxy = y
    if minx < 0:
        return None
    mask = [row[minx:maxx + 1] for row in mask[miny:maxy + 1]]

    data, row_bytes = _mask_to_bytes(mask)

    # 墨迹左上角相对文字原点的偏移（逻辑像素）。
    dx = cx0 // 3 + minx - _ORIGIN // 3
    dy = cy0 // 3 + miny - _ORIGIN // 3
    advance = int(round(font.getlength(ch) / float(renderer.SCALE)))
    return (data, len(mask[0]), len(mask), row_bytes, dx, dy, advance)


def render_digit_set(size_logical):
    """一档字号的 10 个数字字模。"""
    font = ImageFont.truetype(renderer.FONT_BOLD, int(size_logical) * renderer.SCALE)
    entries = []
    blob = bytearray()
    for ch in "0123456789":
        g = _digit_glyph(font, ch)
        if g is None:
            continue
        data, w, h, row_bytes, dx, dy, advance = g
        entries.append({
            "ch": ch, "w": w, "h": h, "row_bytes": row_bytes,
            "dx": dx, "dy": dy, "advance": advance,
            "offset": len(blob),
        })
        blob += data
    return entries, bytes(blob)


def _c_array(name, data, per_line=16, indent="    "):
    out = ["const uint8_t %s[%d] = {" % (name, len(data))]
    for i in range(0, len(data), per_line):
        chunk = data[i:i + per_line]
        out.append(indent + " ".join("0x%02x," % b for b in chunk))
    out.append("};")
    return "\n".join(out)


def emit(frames, digit_sets, header_path, source_path):
    frame_bytes = len(frames[0])

    header = [
        "// ink_merit_assets.h - 赛博木鱼的三帧位图 + 数字字模（1bpp，1 = 黑）",
        "//",
        "// 由 tools/gen_merit_assets.py 从 images/1.png 2.png 3.png 离线生成，**别手改**。",
        "// 换素材或字号就重跑：",
        "//   python3 tools/gen_merit_assets.py --out-header src/ink_merit_assets.h \\",
        "//       --out-source src/ink_merit_assets.cpp",
        "",
        "#pragma once",
        "#include <stdint.h>",
        "",
        "#define INK_MERIT_FRAME_COUNT   %d" % len(frames),
        "#define INK_MERIT_FRAME_BYTES   %d" % frame_bytes,
        "#define INK_MERIT_DIGIT_SETS    %d" % len(digit_sets),
        "",
        "// 数字排版（和服务端 render_merit 同一套口径）",
        "#define INK_MERIT_DIGIT_RIGHT   %d" % DIGIT_RIGHT,
        "#define INK_MERIT_DIGIT_TOP     %d" % DIGIT_TOP,
        "#define INK_MERIT_DIGIT_MAX_W   %d" % DIGIT_MAX_W,
        "",
        "// 一个数字字形的描述。",
        "typedef struct {",
        "    uint8_t  w;        // 墨迹宽（像素）",
        "    uint8_t  h;        // 墨迹高（像素）",
        "    uint8_t  rowBytes; // 每行字节数 = ceil(w/8)",
        "    int8_t   dx;       // 墨迹左上角相对文字原点的 x 偏移",
        "    int8_t   dy;       // 墨迹左上角相对文字原点的 y 偏移",
        "    uint8_t  advance;  // 前进宽度（像素）",
        "    uint16_t offset;   // 在 inkMeritDigitData 里的字节偏移",
        "} InkMeritDigitMeta;",
        "",
        "// 三帧整屏位图。帧序：0 静息 / 1 击打 / 2 挥过。",
        "const uint8_t* inkMeritFrame(int idx);",
        "",
        "// 数字字模元数据：[档位][数字 0-9]",
        "const InkMeritDigitMeta* inkMeritDigitMeta(int set);",
        "",
        "// 数字字模数据（所有档位首尾相接）。",
        "const uint8_t* inkMeritDigitData(void);",
        "",
    ]
    with open(header_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(header))

    names = {FRAME_IDLE: "IDLE", FRAME_STRIKE: "STRIKE", FRAME_SWING: "SWING"}
    src = [
        "// ink_merit_assets.cpp - 由 tools/gen_merit_assets.py 生成，别手改。",
        "",
        '#include "ink_merit_assets.h"',
        "",
        "static const uint8_t INK_MERIT_FRAME_DATA[INK_MERIT_FRAME_COUNT][INK_MERIT_FRAME_BYTES] = {",
    ]
    for idx, frame in enumerate(frames):
        src.append("    {  // %s" % names.get(FRAMES[idx], str(FRAMES[idx])))
        for i in range(0, len(frame), 16):
            src.append("        " + " ".join("0x%02x," % b for b in frame[i:i + 16]))
        src.append("    },")
    src.append("};")
    src.append("")

    src.append("static const InkMeritDigitMeta INK_MERIT_DIGIT_META[INK_MERIT_DIGIT_SETS][10] = {")
    for entries, _blob in digit_sets:
        src.append("    {")
        by_char = {e["ch"]: e for e in entries}
        for ch in "0123456789":
            e = by_char.get(ch)
            if e is None:
                src.append("        { 0, 0, 0, 0, 0, 0, 0 },")
            else:
                src.append("        { %d, %d, %d, %d, %d, %d, %d }," % (
                    e["w"], e["h"], e["row_bytes"], e["dx"], e["dy"],
                    e["advance"], e["offset"]))
        src.append("    },")
    src.append("};")
    src.append("")

    blob = b"".join(blob for _entries, blob in digit_sets)
    src.append(_c_array("INK_MERIT_DIGIT_DATA", blob))
    src.append("")
    src.append("const uint8_t* inkMeritFrame(int idx)")
    src.append("{")
    src.append("    if (idx < 0 || idx >= INK_MERIT_FRAME_COUNT) return 0;")
    src.append("    return INK_MERIT_FRAME_DATA[idx];")
    src.append("}")
    src.append("")
    src.append("const InkMeritDigitMeta* inkMeritDigitMeta(int set)")
    src.append("{")
    src.append("    if (set < 0 || set >= INK_MERIT_DIGIT_SETS) return 0;")
    src.append("    return INK_MERIT_DIGIT_META[set];")
    src.append("}")
    src.append("")
    src.append("const uint8_t* inkMeritDigitData(void)")
    src.append("{")
    src.append("    return INK_MERIT_DIGIT_DATA;")
    src.append("}")
    src.append("")

    with open(source_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(src))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-header", default="src/ink_merit_assets.h")
    ap.add_argument("--out-source", default="src/ink_merit_assets.cpp")
    args = ap.parse_args()

    frames = render_frames()
    digit_sets = [render_digit_set(size) for size in DIGIT_SIZES]

    emit(frames, digit_sets, args.out_header, args.out_source)

    print("三帧位图：%d 帧 x %d 字节 = %d 字节" % (
        len(frames), len(frames[0]), len(frames) * len(frames[0])))
    total = 0
    for size, (entries, blob) in zip(DIGIT_SIZES, digit_sets):
        total += len(blob)
        detail = " ".join("%s:%dx%d adv%d dx%d dy%d" % (
            e["ch"], e["w"], e["h"], e["advance"], e["dx"], e["dy"]) for e in entries)
        print("数字字模 %dpx：%d 个，%d 字节（%s）" % (
            size, len(entries), len(blob), detail))
    print("字模合计 %d 字节" % total)
    print("写出：%s / %s" % (args.out_header, args.out_source))


if __name__ == "__main__":
    main()
