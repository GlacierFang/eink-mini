"""把画面渲染成设备能吃的 1bpp 帧。

帧格式（与固件 ink_config.h 对齐）：
  - 296x128，1bpp
  - MSB first
  - bit 1 = 黑，bit 0 = 白
  - 每行 37 字节（296/8），整帧 4736 字节

固件收到后按 INK_SERVER_BIT1_IS_BLACK 翻成面板约定（1=白），这里只管 1=黑。
"""

from PIL import Image, ImageDraw, ImageFont

W = 296
H = 128
ROW_BYTES = (W + 7) // 8
FRAME_BYTES = ROW_BYTES * H

FONT_REGULAR = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
FONT_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"

_font_cache = {}


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


def image_to_1bpp(img):
    """PIL 图 -> 设备 1bpp 帧（1=黑，MSB first，行跨度 37 字节）。"""
    if img.size != (W, H):
        img = img.resize((W, H))
    bw = img.convert("L").convert("1", dither=Image.Dither.NONE)
    data = bytearray(bw.tobytes())
    # PIL 的 mode "1" 里 1 表示白；我们要 1=黑，所以整字节取反。行内 MSB 优先不变。
    for i in range(len(data)):
        data[i] ^= 0xFF
    if len(data) < FRAME_BYTES:
        data.extend(bytes([0xFF]) * (FRAME_BYTES - len(data)))
    return bytes(data[:FRAME_BYTES])


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


def clip_text(draw, text, font, max_width):
    """按像素宽度裁掉超出部分。

    屏上放不下就截断 —— 宁可少一个字，也不要叠到隔壁列上去。
    """
    text = text or ""
    if not text or max_width <= 0:
        return ""
    if draw.textlength(text, font=font) <= max_width:
        return text
    out = ""
    for ch in text:
        if draw.textlength(out + ch, font=font) > max_width:
            break
        out += ch
    return out
