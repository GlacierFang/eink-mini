"""把画面渲染成设备能吃的 1bpp 帧。

帧格式（与固件 ink_config.h 对齐）：
  - 296x128，1bpp
  - MSB first
  - bit 1 = 黑，bit 0 = 白
  - 每行 37 字节（296/8），整帧 4736 字节

固件收到后按 INK_SERVER_BIT1_IS_BLACK 翻成面板约定（1=白），这里只管 1=黑。

四种量化策略（给 12px 小字选，见 render_check 页）：
  hard   硬阈值。阈值低 = 笔画加粗，转折处不容易断
  bayer  2x2 有序抖动。规则图案，笔画连续性比误差扩散好
  floyd  Floyd-Steinberg 误差扩散。噪点密，墨水屏上代价大

另外提供两种**看图方式**：
  device  设备实际收到的 1bpp 像素
  eye     人眼在屏上看到的灰 —— 面积平均降采样后的结果
墨水屏的黑色像素之间有物理缝隙，整片黑在屏上读作深灰；
抖动图案在看不清单像素的距离上会积分成连续灰。
所以「屏上实际什么样」不是 1bpp 位图，是降采样灰度。
"""

from PIL import Image, ImageDraw, ImageFont

W = 296
H = 128
ROW_BYTES = (W + 7) // 8
FRAME_BYTES = ROW_BYTES * H

FONT_REGULAR = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
FONT_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"

_font_cache = {}

# 量化策略名
DITHER_MODES = ("hard", "bayer", "floyd")

# 默认阈值。**比 128 高**：阈值高 = 更多像素判黑 = 笔画更粗。
# 12px 小字在 128 下 61% 的笔画只有 1px 宽，转折处会断成虚线；
# 165 降到 31%，「18日」「湿度 31%」这类小字笔画能连上。
# 190 开始发糊，不采用。
DEFAULT_THRESHOLD = 165


def load_font(size, bold=False):
    key = (int(size), bool(bold))
    if key not in _font_cache:
        path = FONT_BOLD if bold else FONT_REGULAR
        try:
            _font_cache[key] = ImageFont.truetype(path, int(size))
        except OSError:
            _font_cache[key] = ImageFont.load_default()
    return _font_cache[key]


def new_canvas():
    """白底画布。"""
    return Image.new("L", (W, H), 255)


def to_mask(img, mode="hard", threshold=None):
    """灰度图 -> 布尔掩码（True = 黑），逐行 list。

    mode:
      hard   硬阈值，v < threshold 判黑
      bayer  2x2 有序抖动
      floyd  Floyd-Steinberg 误差扩散
    """
    if threshold is None:
        threshold = DEFAULT_THRESHOLD
    g = img.convert("L")
    if g.size != (W, H):
        g = g.resize((W, H))
    src = g.load()
    mask = [[False] * W for _ in range(H)]

    if mode == "floyd":
        buf = [[float(src[x, y]) for x in range(W)] for y in range(H)]
        for y in range(H):
            row = buf[y]
            nrow = buf[y + 1] if y + 1 < H else None
            for x in range(W):
                old = row[x]
                black = old < threshold
                new = 0.0 if black else 255.0
                mask[y][x] = black
                err = old - new
                if x + 1 < W:
                    row[x + 1] += err * 7.0 / 16.0
                if nrow is not None:
                    if x > 0:
                        nrow[x - 1] += err * 3.0 / 16.0
                    nrow[x] += err * 5.0 / 16.0
                    if x + 1 < W:
                        nrow[x + 1] += err * 1.0 / 16.0
        return mask

    if mode == "bayer":
        # 标准 2x2 Bayer：归一化矩阵 [[0,2],[3,1]]/4
        bayer = (0, 2, 3, 1)
        for y in range(H):
            row = mask[y]
            by = (y & 1) * 2
            for x in range(W):
                row[x] = src[x, y] < bayer[by + (x & 1)] * 64
        return mask

    for y in range(H):
        row = mask[y]
        for x in range(W):
            row[x] = src[x, y] < threshold
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


def frame_bytes(img, mode="hard", threshold=None):
    """灰度图 -> 设备帧字节。"""
    return mask_to_frame(to_mask(img, mode, threshold))


def image_to_1bpp(img):
    """PIL 图 -> 设备 1bpp 帧（1=黑，MSB first，行跨度 37 字节）。"""
    return frame_bytes(img, "hard", DEFAULT_THRESHOLD)


def device_view(img, mode="hard", threshold=None):
    """设备实际收到的画面：纯黑纯白的 L 图，1 像素对 1 像素。"""
    mask = to_mask(img, mode, threshold)
    out = Image.new("L", (W, H), 255)
    op = out.load()
    for y in range(H):
        row = mask[y]
        for x in range(W):
            if row[x]:
                op[x, y] = 0
    return out


def perceived_view(img, mode="hard", threshold=None, block=4):
    """人眼视图：1bpp 帧按 block x block 面积平均降采样。

    墨水屏上整片黑读作深灰，抖动图案积分成连续灰 ——
    降采样后的灰度才是眼睛看到的层次。
    """
    mask = to_mask(img, mode, threshold)
    cols = W // block
    rows = H // block
    out = Image.new("L", (cols, rows), 255)
    op = out.load()
    area = float(block * block)
    for by in range(rows):
        for bx in range(cols):
            black = 0
            for y in range(by * block, by * block + block):
                row = mask[y]
                for x in range(bx * block, bx * block + block):
                    if row[x]:
                        black += 1
            op[bx, by] = 255 - int(round(255.0 * black / area))
    return out


def perceived_view_full(img, mode="hard", threshold=None, block=4):
    """人眼视图放大回 296x128：每格一个均匀灰块，1 像素对 1 像素。"""
    small = perceived_view(img, mode, threshold, block)
    return small.resize((W, H), Image.NEAREST)


def image_to_png(img):
    import io

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
