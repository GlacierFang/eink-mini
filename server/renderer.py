"""把画面渲染成设备能吃的 1bpp 帧。

帧格式（与固件 ink_config.h 对齐）：
  - 296x128，1bpp
  - MSB first
  - bit 1 = 黑，bit 0 = 白
  - 每行 37 字节（296/8），整帧 4736 字节

三层结构：

**渲染** —— 在 SCALE 倍大的灰度画布上画，再 BOX 降采样回 296x128。
小字和图标的边缘因此有真正的抗锯齿。

**分层** —— 画到两张画布上：
  清晰层（crisp）必须实心的骨架：文字、太阳、云、雨丝、雪花、闪电。
  灰阶层（tone）需要保留明暗的色块。

**量化** —— 清晰层硬阈值，灰阶层有序抖动，黑像素取并集。

为什么分层：12px 小字被有序抖动会把笔画打断，字读不出来；
而灰色色块被硬阈值会把灰全砍成黑，就没有层次了。

图标不走页面画布 —— 图标在自己的 28x28 局部画布上画，
单独量化成掩码后按位置叠进页面。理由见 icons.py。

设备帧格式（长度、位序、极性）与旧实现完全一致。
"""

import io
import math

from PIL import Image, ImageDraw, ImageFont

W = 296
H = 128
ROW_BYTES = (W + 7) // 8
FRAME_BYTES = ROW_BYTES * H

# 超采样倍数。渲染在 SCALE 倍画布上做，最后 BOX 降采样回 296x128。
SCALE = 3

FONT_REGULAR = "/usr/share/fonts/opentype/unifont/unifont.otf"
FONT_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"

_font_cache = {}

DITHER_MODES = ("hard", "bayer2", "bayer4", "floyd")

# 清晰层的量化策略：硬阈值。
#
# tools/eval_quant.py 在真实页面上量过（参考 = 6 倍超采样渲染）：
#
#   策略      PSNR    噪点%    文字1px笔画%
#   floyd     36.3    8.95     78
#   bayer4    33.0   14.81     80
#   hard 128  32.1    2.11     75
#   hard 165  29.5    0.44     53
#
# dither 的色调保真（PSNR）最高，但噪点会把 12px 小字的笔画打断 ——
# 墨水屏上字读不出来，色调再准也没用。
#
# 阈值高 = 墨多 = 笔画粗。165 是拐点：噪点几乎清零，笔画还连着。
#
# 改版式就要重跑 tools/eval_quant.py。
DEFAULT_MODE = "hard"
DEFAULT_THRESHOLD = 165

# 灰阶层（图标填充、背景块）的量化策略：有序抖动。
#
# 硬阈值会把灰色全砍成黑，就没有层次了。有序抖动用网点疏密编码灰阶 ——
# 这就是报纸网点纸的原理：油墨只有黑、纸只有白，靠空间密度换灰阶。
#
# bayer4 而不是 bayer2：bayer2 只有 4 级灰，最小非零灰阶就是 50%，
# 根本表达不出 25% 浅灰。bayer4 有 16 级。
#
# bayer4 的 50% 是实测最干净的一档（30cm 视距，纹理 sd）：
#   bayer4 50% -> 3.01    bayer4 25% -> 6.89    bayer4 75% -> 8.31
# 50% 最甜：4x4 矩阵正好半亮半暗、分布最均匀；25% 稀疏会成团。
TONE_DITHER_MODE = "bayer4"
TONE_DITHER_THRESHOLD = 128

# Bayer 阈值矩阵。M 越大 -> 该位置阈值越低 -> 越容易判黑。
BAYER2 = ((0, 2), (3, 1))
BAYER4 = (
    (0, 8, 2, 10),
    (12, 4, 14, 6),
    (3, 11, 1, 9),
    (15, 7, 13, 5),
)


class ScaledDraw:
    """把逻辑坐标的绘制调用放大到超采样画布。

    pages.py / icons.py 全用逻辑坐标（296x128 那套）写，这里负责
    乘上 SCALE。textbbox / textlength 返回逻辑单位，所以上层算版式
    不用改一个字。
    """

    def __init__(self, draw, scale):
        self._d = draw
        self._s = scale

    def _p(self, xy):
        s = self._s
        return (int(round(xy[0] * s)), int(round(xy[1] * s)))

    def _pts(self, xy):
        s = self._s
        return [(int(round(x * s)), int(round(y * s))) for x, y in xy]

    def text(self, xy, text, font=None, fill=0, **kw):
        return self._d.text(self._p(xy), text, font=font, fill=fill, **kw)

    def textbbox(self, xy, text, font=None, **kw):
        b = self._d.textbbox(self._p(xy), text, font=font, **kw)
        s = float(self._s)
        return (b[0] / s, b[1] / s, b[2] / s, b[3] / s)

    def textlength(self, text, font=None, **kw):
        return self._d.textlength(text, font=font, **kw) / float(self._s)

    def line(self, xy, fill=0, width=1, **kw):
        return self._d.line(self._pts(xy), fill=fill,
                            width=int(round(width * self._s)), **kw)

    def rectangle(self, xy, fill=None, outline=None, width=1, **kw):
        x0, y0 = self._p((xy[0], xy[1]))
        x1, y1 = self._p((xy[2], xy[3]))
        return self._d.rectangle((x0, y0, x1, y1), fill=fill, outline=outline,
                                  width=int(round(width * self._s)), **kw)

    def ellipse(self, xy, fill=None, outline=None, width=1, **kw):
        x0, y0 = self._p((xy[0], xy[1]))
        x1, y1 = self._p((xy[2], xy[3]))
        return self._d.ellipse((x0, y0, x1, y1), fill=fill, outline=outline,
                                width=int(round(width * self._s)), **kw)

    def polygon(self, xy, fill=None, outline=None, **kw):
        return self._d.polygon(self._pts(xy), fill=fill, outline=outline, **kw)


def load_font(size, bold=False):
    """超采样字体的字号。逻辑 size -> 实际 size * SCALE。"""
    key = (int(size), bool(bold))
    if key not in _font_cache:
        path = FONT_BOLD if bold else FONT_REGULAR
        try:
            _font_cache[key] = ImageFont.truetype(path, int(size) * SCALE)
        except OSError:
            _font_cache[key] = ImageFont.load_default()
    return _font_cache[key]


def new_canvas():
    """清晰层超采样画布。逻辑 296x128，实际 888x384。"""
    return Image.new("L", (W * SCALE, H * SCALE), 255)


def new_tone_canvas():
    """灰阶层超采样画布。"""
    return Image.new("L", (W * SCALE, H * SCALE), 255)


def draw_on(img):
    """给超采样画布套一层逻辑坐标的绘图接口。"""
    return ScaledDraw(ImageDraw.Draw(img), SCALE)


def downsample(img, size=(W, H)):
    """超采样画布 -> 逻辑尺寸灰度图（BOX = 面积平均）。"""
    if img.size == tuple(size):
        return img
    return img.resize(size, Image.BOX)


def _area_downsample(gray, block):
    """灰度图按 block x block 面积平均降采样。"""
    w, h = gray.size
    cols = w // block
    rows = h // block
    out = Image.new("L", (cols, rows), 255)
    op = out.load()
    src = gray.load()
    area = float(block * block)
    for by in range(rows):
        for bx in range(cols):
            s = 0
            for y in range(by * block, by * block + block):
                for x in range(bx * block, bx * block + block):
                    s += src[x, y]
            op[bx, by] = int(round(s / area))
    return out


def to_mask(img, mode=None, threshold=None, size=None, phase=(0, 0)):
    """灰度图 -> 布尔掩码（True = 黑），逐行 list。

    判据统一是 black if gray < threshold(x, y)：
      hard    threshold 恒定
      bayer2  2x2 有序抖动，4 级灰
      bayer4  4x4 有序抖动，16 级灰
      floyd   误差扩散，threshold 恒定

    phase 是抖动矩阵的相位偏移。图标在自己的 28x28 局部画布上量化，
    但它落在页面的哪个位置决定了该用矩阵的哪一格 —— 不对齐的话，
    图案在页面上的连续性就断了。
    """
    if mode is None:
        mode = DEFAULT_MODE
    if threshold is None:
        threshold = DEFAULT_THRESHOLD
    g = img.convert("L")
    if size is None:
        size = (W, H)
    if g.size != tuple(size):
        g = g.resize(size)
    src = g.load()
    w, h = size
    mask = [[False] * w for _ in range(h)]

    if mode == "floyd":
        buf = [[float(src[x, y]) for x in range(w)] for y in range(h)]
        for y in range(h):
            row = buf[y]
            nrow = buf[y + 1] if y + 1 < h else None
            for x in range(w):
                old = row[x]
                black = old < threshold
                mask[y][x] = black
                new = 0.0 if black else 255.0
                err = old - new
                if x + 1 < w:
                    row[x + 1] += err * 7.0 / 16.0
                if nrow is not None:
                    if x > 0:
                        nrow[x - 1] += err * 3.0 / 16.0
                    nrow[x] += err * 5.0 / 16.0
                    if x + 1 < w:
                        nrow[x + 1] += err * 1.0 / 16.0
        return mask

    if mode in ("bayer2", "bayer4"):
        mtx = BAYER2 if mode == "bayer2" else BAYER4
        n = len(mtx)
        px, py = int(phase[0]), int(phase[1])
        for y in range(h):
            row = mask[y]
            my = mtx[(y + py) % n]
            for x in range(w):
                m = my[(x + px) % n]
                # 标准 Bayer 阈值，再整体平移到 threshold 这个中心。
                t = 255.0 - 255.0 * (m + 0.5) / (n * n)
                t = threshold + (t - 128.0)
                if t < 0.0:
                    t = 0.0
                elif t > 255.0:
                    t = 255.0
                row[x] = src[x, y] < t
        return mask

    for y in range(h):
        row = mask[y]
        for x in range(w):
            row[x] = src[x, y] < threshold
    return mask


def page_mask(crisp, icons=None, mode=None, threshold=None,
              dither_mode=None, dither_threshold=None, tone=None):
    """页面清晰层 + 图标 -> 一张掩码。

    icons 是 (ox, oy, crisp_local, tone_local) 的列表。
    图标在局部 28x28 上量化（它的屏上尺寸就是 28x28），
    再按 (ox, oy) 叠进页面。抖动相位按图标在页面上的位置对齐。
    """
    if mode is None:
        mode = DEFAULT_MODE
    if threshold is None:
        threshold = DEFAULT_THRESHOLD
    if dither_mode is None:
        dither_mode = TONE_DITHER_MODE
    if dither_threshold is None:
        dither_threshold = TONE_DITHER_THRESHOLD

    mask = to_mask(crisp, mode, threshold, size=(W, H))

    for (ox, oy, icrisp, itone) in (icons or []):
        iw, ih = icrisp.size
        cm = to_mask(icrisp, mode, threshold, size=(iw, ih))
        tm = None
        if itone is not None:
            tm = to_mask(itone, dither_mode, dither_threshold,
                         size=(iw, ih), phase=(ox, oy))
        for y in range(ih):
            py = oy + y
            if py < 0 or py >= H:
                continue
            prow = mask[py]
            crow = cm[y]
            trow = tm[y] if tm is not None else None
            for x in range(iw):
                px = ox + x
                if px < 0 or px >= W:
                    continue
                if crow[x] or (trow is not None and trow[x]):
                    prow[px] = True

    # 页面级灰阶层：整页一块灰度画布，走有序抖动。
    # 图标的灰阶层只能待在 28x28 的局部框里 —— 页面级的浅色元素
    # （比如周末的浅灰日号）没有别的入口。
    if tone is not None:
        tmask = to_mask(tone, dither_mode, dither_threshold,
                        size=(W, H), phase=(0, 0))
        for y in range(H):
            prow = mask[y]
            trow = tmask[y]
            for x in range(W):
                if trow[x]:
                    prow[x] = True
    return mask


def mask_to_frame(mask):
    """布尔掩码 -> 设备帧字节（1 = 黑，MSB first，每行 37 字节）。"""
    data = bytearray(ROW_BYTES * H)
    for y in range(H):
        row = mask[y]
        base = y * ROW_BYTES
        for x in range(W):
            if row[x]:
                data[base + (x >> 3)] |= 0x80 >> (x & 7)
    return bytes(data)


def frame_from_page(crisp, icons=None, **kw):
    """页面 -> 设备帧字节。"""
    return mask_to_frame(page_mask(crisp, icons, **kw))


def image_to_1bpp(img, mode=None, threshold=None):
    """PIL 图 -> 设备 1bpp 帧（1=黑，MSB first，行跨度 37 字节）。"""
    mask = to_mask(img, mode, threshold, size=(W, H))
    return mask_to_frame(mask)


def frame_bytes(img, mode=None, threshold=None):
    """灰度图 -> 设备帧字节。"""
    return image_to_1bpp(img, mode, threshold)


def _mask_to_image(mask):
    out = Image.new("L", (len(mask[0]), len(mask)), 255)
    op = out.load()
    for y in range(len(mask)):
        row = mask[y]
        for x in range(len(row)):
            if row[x]:
                op[x, y] = 0
    return out


def device_view(img, mode=None, threshold=None):
    """单张灰度图 -> 1bpp 画面（设备真正收到的）。"""
    return _mask_to_image(to_mask(img, mode, threshold, size=(W, H)))


def page_view(crisp, icons=None, **kw):
    """页面 -> 1bpp 画面。"""
    return _mask_to_image(page_mask(crisp, icons, **kw))


def average_view(img, block=4):
    """参考灰度图按 block x block 面积平均。"""
    g = img.convert("L")
    if g.size != (W, H):
        g = g.resize((W, H))
    return _area_downsample(g, block)


def perceived_view(img, mode=None, threshold=None, block=4):
    """1bpp 帧按 block x block 面积平均降采样 —— 眼睛在屏上看到的灰。

    墨水屏的黑色像素之间有物理缝隙，一整片黑读作深灰；
    抖动图案在看不清单像素的距离上会积分成连续灰。
    """
    return _area_downsample(device_view(img, mode, threshold), block)


def page_perceived(crisp, icons=None, block=4, **kw):
    """页面的 1bpp 画面按 block x block 面积平均。"""
    return _area_downsample(page_view(crisp, icons, **kw), block)


def psnr(a, b):
    """两张同尺寸灰度图的 PSNR（MAX=255）。"""
    pa = a.load()
    pb = b.load()
    w, h = a.size
    s = 0.0
    for y in range(h):
        for x in range(w):
            d = pa[x, y] - pb[x, y]
            s += d * d
    mse = s / float(w * h)
    if mse <= 1e-9:
        return 99.0
    return 10.0 * math.log10(255.0 * 255.0 / mse)


def image_to_png(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def text_width(draw, text, font):
    return int(draw.textlength(text, font=font))


def wrap_text(draw, text, font, max_width):
    """按像素宽度折行，返回行列表。"""
    lines = []
    cur = ""
    for ch in text or "":
        if ch == chr(10):
            lines.append(cur)
            cur = ""
            continue
        probe = cur + ch
        if cur and draw.textlength(probe, font=font) > max_width:
            lines.append(cur)
            cur = ch
        else:
            cur = probe
    if cur:
        lines.append(cur)
    return lines


def draw_header(draw, title, subtitle=""):
    draw.text((8, 5), title, font=load_font(20, bold=True), fill=0)
    if subtitle:
        f = load_font(13)
        w = text_width(draw, subtitle, f)
        draw.text((W - 8 - w, 11), subtitle, font=f, fill=0)
    draw.line([(0, 31), (W, 31)], fill=0, width=2)


def draw_footer(draw, text):
    draw.line([(0, H - 15), (W, H - 15)], fill=0, width=1)
    draw.text((8, H - 13), text, font=load_font(11), fill=0)
