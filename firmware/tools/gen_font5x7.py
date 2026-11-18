# -*- coding: utf-8 -*-
"""生成固件 5x7 ASCII 字模（基线对齐版）。

## 为什么重做

原来那张表（用 TrueType 随手栅格化）有两个真问题：

1. **'A' 顶部糊成一团** —— ..#.. / .##.. / .#.#. / .#.#. / .###. / #...#，
   读出来像小写 a。
2. **基线不统一** —— 大写占 row 0..5，但 'A' 'B' 'K' 'M' 'R' 'T' 'V' 'W'
   'X' 'Y' 'Z' 末行是 5 而不是 6；x 高度字母（a e o r）末行是 4；
   'm v w x' 是 3。整行文字底部参差不齐。

## 做法

**按字符类别定行区间**（经典 5x7 布局），字形在区间内按墨迹等比缩放，
底边对齐基线：

| 类别                              | 行区间      |
|-----------------------------------|-------------|
| 大写 / 数字 / b d f h k l t        | row 0..5    |
| x 高度小写 a c e m n o r s u v w x z | row 2..5 |
| 下伸部 g j p q y                   | row 2..5 + row 6 |

## 三个必须踩准的点

1. **量真实墨迹，不是 advance width**：font.getbbox() 给的是字形墨迹范围，
   但用固定字号量宽度，'1' 会和 '0' 一样宽 —— 窄字必须单独处理。
2. **采样坐标要算「墨迹相对坐标」**：tight 裁剪后的第 (0,0) 像素是墨迹左上角，
   不是绘制原点。少减一次 pad，整列字形会整体偏移。
3. **负坐标要用 floor 不能用 int()**：int(-0.8) == 0，负数被截断到 0。

## 用法

    python3 tools/gen_font5x7.py --font <ttf> --out src/ink_font.h
"""
import argparse
import io
import math

from PIL import Image, ImageDraw, ImageFont

COLS, ROWS = 5, 7
FIRST, LAST = 32, 126

# 各类字形的行区间
ROW_CAP = (0, 5)
ROW_XH = (2, 5)
ROW_DESC_BODY = (2, 5)
ROW_DESC_TAIL = 6

ASCENDER = set("bdfhklt")
XHEIGHT = set("acemnorsuvwxz")
DESCENDER = set("gjpqy")

CAP_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
XH_CHARS = "acemnorsuvwxz"

THRESHOLD = 0.40
SS = 5
RASTER = 64
PAD = 30


def render_char(font, ch):
    """把字形画到画布上，返回采样器。

    返回 (width, height, sample)：
      width/height  墨迹宽高（墨迹单位）
      sample(x, y)  墨迹相对坐标 (x 从左, y 从上) -> 灰度值
    """
    img = Image.new("L", (RASTER * 2 + PAD * 2, RASTER * 2 + PAD * 2), 255)
    d = ImageDraw.Draw(img)
    base = RASTER + PAD
    d.text((PAD, base), ch, font=font, fill=0, anchor="ls")
    px = img.load()

    bb = font.getbbox(ch, anchor="ls")
    if bb is None:
        return None
    x0, y0, x1, y1 = bb
    if x1 <= x0 or y1 <= y0:
        return None

    # 画布上墨迹的绝对范围
    ax0 = PAD + x0
    ax1 = PAD + x1
    ay0 = base + y0
    ay1 = base + y1
    w = ax1 - ax0
    h = ay1 - ay0

    def sample(x, y):
        """墨迹相对坐标 -> 灰度。超出范围返回白。"""
        ix = int(math.floor(ax0 + x))
        iy = int(math.floor(ay0 + y))
        if ix < 0 or iy < 0 or ix >= img.size[0] or iy >= img.size[1]:
            return 255
        return px[ix, iy]

    return w, h, sample


def build(font_path, out_header):
    font = ImageFont.truetype(font_path, RASTER)

    rendered = {}
    for code in range(FIRST, LAST + 1):
        ch = chr(code)
        if ch == " ":
            continue
        r = render_char(font, ch)
        if r:
            rendered[ch] = r

    # 全局基准高度（墨迹单位）
    cap_h = max(-font.getbbox(c, anchor="ls")[1] for c in CAP_CHARS)
    xh_h = max(-font.getbbox(c, anchor="ls")[1] for c in XH_CHARS)

    glyphs = {}
    for code in range(FIRST, LAST + 1):
        ch = chr(code)
        grid = [[0] * COLS for _ in range(ROWS)]
        if ch == " " or ch not in rendered:
            glyphs[ch] = grid
            continue

        w, h, sample = rendered[ch]

        if ch in DESCENDER:
            r0, r1 = ROW_DESC_BODY
            n_body = r1 - r0 + 1
            # 主体：x 高度部分，映射到 row r0..r1
            s_v = n_body / float(xh_h)
            # 尾巴：基线以下，映射到 row 6
            tail_h = h - xh_h
            s_tail = 1.0 / max(0.5, tail_h)
            s_h_scale = s_v
            wide = False
        elif ch in ASCENDER:
            r0, r1 = ROW_CAP
            n = r1 - r0 + 1
            s_v = n / float(cap_h)
            s_h_scale = s_v
            wide = False
        elif ch in XHEIGHT:
            r0, r1 = ROW_XH
            n = r1 - r0 + 1
            s_v = n / float(xh_h)
            # x 高度字形横向铺满 5 列（经典 5x7 就是这么挤的）
            s_h_scale = min(5.0 / float(w), s_v * 1.45)
            wide = True
        else:
            r0, r1 = ROW_CAP
            n = r1 - r0 + 1
            s_v = n / float(cap_h)
            s_h_scale = s_v
            wide = False

        out_w = w * s_h_scale
        if out_w > COLS:
            s_h_scale = COLS / float(w)
            out_w = COLS
        x_off = (COLS - out_w) / 2.0

        # 这个字形自己的「基线以上高度」
        own_h = xh_h if ch in DESCENDER else (xh_h if ch in XHEIGHT else cap_h)

        for r in range(ROWS):
            if ch in DESCENDER:
                if r0 <= r <= r1:
                    y_lo = (r - r0) / float(n_body) * own_h
                    y_hi = (r + 1 - r0) / float(n_body) * own_h
                elif r == ROW_DESC_TAIL:
                    y_lo = own_h
                    y_hi = own_h + max(1.0, tail_h * s_tail)
                else:
                    continue
            else:
                if r < r0 or r > r1:
                    continue
                y_lo = (r - r0) / float(n) * own_h
                y_hi = (r + 1 - r0) / float(n) * own_h

            for c in range(COLS):
                x_lo = x_off + c * (1.0 / s_h_scale) * 1.0
                # 每个输出列对应一段墨迹宽度
                col_w = 1.0 / s_h_scale
                xa = x_off + c * col_w
                xb = xa + col_w
                hit = 0
                tot = 0
                for j in range(SS):
                    for i in range(SS):
                        fx = xa + (i + 0.5) * (xb - xa) / SS
                        fy = y_lo + (j + 0.5) * (y_hi - y_lo) / SS
                        v = sample(fx, fy)
                        tot += 1
                        if v < 200:
                            hit += 1
                if tot and hit / float(tot) >= THRESHOLD:
                    grid[r][c] = 1
        glyphs[ch] = grid

    lines = []
    lines.append("// ink_font.h - 5x7 ASCII 字形表（字符 32..126）")
    lines.append("//")
    lines.append("// 列主序：每字符 5 字节，每字节一列，bit0 = 该列最上面一行。")
    lines.append("// 由 tools/gen_font5x7.py 从 TrueType 字体离线栅格化生成，别手改。")
    lines.append("//")
    lines.append("// 基线对齐（按字符类别定行区间）：")
    lines.append("//   大写 / 数字 / b d f h k l t          row 0..5")
    lines.append("//   x 高度小写 (a c e m n o r s u ...) row 2..5")
    lines.append("//   下伸部 (g j p q y)                 row 2..5 + row 6")
    lines.append("//")
    lines.append("#pragma once")
    lines.append("#include <stdint.h>")
    lines.append("")
    lines.append("#define INK_FONT_FIRST 32")
    lines.append("#define INK_FONT_LAST  126")
    lines.append("#define INK_FONT_W     5")
    lines.append("#define INK_FONT_H     7")
    lines.append("")
    lines.append("static const uint8_t INK_FONT5X7[INK_FONT_LAST - INK_FONT_FIRST + 1][INK_FONT_W] = {")
    for code in range(FIRST, LAST + 1):
        ch = chr(code)
        g = glyphs[ch]
        cols = []
        for c in range(COLS):
            b = 0
            for r in range(ROWS):
                if g[r][c]:
                    b |= (1 << r)
            cols.append("0x%02X" % b)
        label = "/" if ch == chr(92) else ch
        lines.append("  {" + ", ".join(cols) + "}, // 0x%02X %s" % (code, label))
    lines.append("};")
    lines.append('')
    lines.append("// 取字符字形；不可打印字符回退到空格。")
    lines.append("inline const uint8_t* inkGlyph(char c)")
    lines.append("{")
    lines.append("  unsigned char u = (unsigned char)c;")
    lines.append("  if (u < INK_FONT_FIRST || u > INK_FONT_LAST) u = 32;")
    lines.append("  return INK_FONT5X7[u - INK_FONT_FIRST];")
    lines.append("}")
    lines.append('')
    with io.open(out_header, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return glyphs


def render(glyphs, text, scale=4):
    from PIL import Image
    w = (len(text) * 6 - 1) * scale
    h = ROWS * scale
    img = Image.new("L", (w, h), 255)
    px = img.load()
    for i, ch in enumerate(text):
        g = glyphs[ch]
        for r in range(ROWS):
            for c in range(COLS):
                if g[r][c]:
                    for dy in range(scale):
                        for dx in range(scale):
                            px[i * 6 * scale + c * scale + dx, r * scale + dy] = 0
    return img


def charset_sheet(glyphs, path, scale=3):
    from PIL import Image
    chars = [chr(c) for c in range(FIRST, LAST + 1)]
    cw, chh = 6 * scale, 9 * scale
    cols = 16
    rows_n = (len(chars) + cols - 1) // cols
    img = Image.new("L", (cols * cw, rows_n * chh), 255)
    px = img.load()
    for i, ch in enumerate(chars):
        g = glyphs[ch]
        ox, oy = (i % cols) * cw, (i // cols) * chh
        for r in range(ROWS):
            for c in range(COLS):
                if g[r][c]:
                    for dy in range(scale):
                        for dx in range(scale):
                            px[ox + c * scale + dx, oy + r * scale + dy] = 0
    img.save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--font",
                    default="/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf")
    ap.add_argument("--out", default="src/ink_font.h")
    ap.add_argument("--preview-dir", default=None)
    args = ap.parse_args()
    g = build(args.font, args.out)
    if args.preview_dir:
        charset_sheet(g, args.preview_dir + "/f5x7-charset.png")
        render(g, "READY RUN PAUSEDONE 1234567890 ABCXYZ").save(
            args.preview_dir + "/f5x7-words.png")
    for ch in "AREPDYgmno":
        print("=== %r ===" % ch)
        for r in range(ROWS):
            print("  " + "".join("#" if g[ch][r][c] else "." for c in range(COLS)))
    print("written", args.out)


if __name__ == "__main__":
    main()
