"""天气图标：字形 + 手绘混合。

1bpp 小图标的三条命门（踩过才知道）：

1. **字形可以直接用，但别缩放**。Noto Sans CJK 自带 ☀（U+2600），
   实心圆盘 + 12 根等长短方块光芒，是专业设计的形状。
   手画试了五版：光芒一长就变成四尖星，一断就成了噪点，
   腐蚀描边又变成圆顶土面包 —— 都不如字形。
   但字形从 96px 缩到 24px 再阈值化，光芒会被筛成断点，出来是虚线圆。
   所以：**按目标字号原生渲染进画布，不缩放**，
   最终的黑白判定交给量化层统一做。
   ❄（U+2744）cmap 里有但渲染是豆腐块，所以雪花还是手绘。
2. **1px 细斜线在点阵上碎成阶梯**，远看就是噪点。
   只用横、竖、2x2 方块、多边形。
3. **剪影要一眼不同**。雨雪雷都带云时，靠"竖条 / 实心十字 / Z 形折线"
   三种骨架区分；云的圆弧高度也要不同，一样高就成了面包。

图标在**超采样画布**上画（renderer.SCALE 倍），整幅画完再降采样，
所以边缘有真正的抗锯齿 —— 这正是灰度要的东西。
"""

from PIL import Image, ImageDraw

import renderer

SIZE = 28

SUN_GLYPH = "☀"

# WMO 天气码 -> 图标种类
_KIND = {
    0: "sun",
    1: "sun_cloud",
    2: "cloud",
    3: "overcast",
    45: "fog",
    48: "fog",
    51: "rain",
    53: "rain",
    55: "rain_heavy",
    56: "sleet",
    57: "sleet",
    61: "rain",
    63: "rain",
    65: "rain_heavy",
    66: "sleet",
    67: "sleet",
    71: "snow",
    73: "snow",
    75: "snow",
    77: "snow",
    80: "rain",
    81: "rain_heavy",
    82: "rain_heavy",
    85: "snow",
    86: "snow",
    95: "thunder",
    96: "hail",
    99: "hail",
}


def kind_for(code):
    """WMO 码 -> 图标种类。取不到就空串。"""
    if code is None:
        return ""
    try:
        return _KIND.get(int(code), "")
    except (TypeError, ValueError):
        return ""


def _blank():
    """超采样画布：0 = 黑，255 = 白。"""
    return Image.new("L", (SIZE * renderer.SCALE, SIZE * renderer.SCALE), 255)


def _sun_glyph(d, px, cx, cy):
    """把 ☀ 字形按 px 号原生渲染进画布，居中在 (cx, cy)。

    不缩放：缩小会把光芒筛成断点。取不到字形就返回 False。
    """
    font = renderer.load_font(px, bold=True)
    bb = d.textbbox((0, 0), SUN_GLYPH, font=font)
    d.text((cx - (bb[0] + bb[2]) / 2, cy - (bb[1] + bb[3]) / 2),
           SUN_GLYPH, font=font, fill=0)
    return True


def _cloud(d, x0=3, x1=25, top=6, bottom=20):
    """实心云：三段**高度不同**的圆弧 + 平底。

    三段弧顶分别在 top+10 / top / top+12 —— 一样高就成了面包。
    """
    d.ellipse((x0, bottom - 10, x0 + 11, bottom + 1), fill=0)      # 左弧
    d.ellipse((x0 + 3, top, x0 + 17, bottom + 1), fill=0)           # 中弧（最高）
    d.ellipse((x1 - 10, bottom - 8, x1 + 1, bottom + 1), fill=0)    # 右弧
    d.rectangle((x0, bottom - 5, x1, bottom + 1), fill=0)           # 平底


def _star(d, cx, cy, r=2):
    """实心小雪花：粗十字，臂宽 2px。1px 细十字在小图上认不出来。"""
    d.rectangle((cx - r, cy - 1, cx + r, cy), fill=0)
    d.rectangle((cx - 1, cy - r, cx, cy + r), fill=0)


def _bolt(d, x=8, y=12):
    """闪电：一次多边形画成的 Z 字。

    矩形一笔一笔画会碎成一串小方块；多边形一次成形才连贯。
    下端收成尖 —— 收成弧就读成钩子。
    """
    d.polygon(
        [
            (x + 7, y), (x + 12, y),        # 上横条
            (x + 7, y + 7), (x + 11, y + 7),  # 中段
            (x + 1, y + 15), (x + 5, y + 9),  # 收尖的下端
            (x + 1, y + 9),
        ],
        fill=0,
    )


def _draw(kind):
    """画一个图标，返回超采样灰度图。"""
    img = _blank()
    d = renderer.ScaledDraw(ImageDraw.Draw(img), renderer.SCALE)

    if kind == "sun":
        if not _sun_glyph(d, 26, 14, 14):
            d.ellipse((7, 7, 21, 21), fill=0)
    elif kind == "sun_cloud":
        if not _sun_glyph(d, 15, 8, 8):
            d.ellipse((4, 4, 12, 12), fill=0)
        _cloud(d, x0=8, x1=27, top=13, bottom=26)
    elif kind == "cloud":
        _cloud(d)
    elif kind == "overcast":
        # 两朵云左右分置：主云在右，左边露一朵小云。
        # 叠在正上方会连成一个雪人。
        _cloud(d, x0=8, x1=26, top=6, bottom=20)
        _cloud(d, x0=0, x1=14, top=12, bottom=23)
    elif kind == "fog":
        # 雾没有云 —— 雾本来就是横的，三道横线最像
        d.rectangle((2, 6, 25, 8), fill=0)
        d.rectangle((5, 12, 22, 14), fill=0)
        d.rectangle((2, 18, 25, 20), fill=0)
    elif kind == "rain":
        _cloud(d, x0=3, x1=25, top=3, bottom=17)
        for x in (8, 14, 20):
            d.rectangle((x, 20, x + 1, 25), fill=0)
    elif kind == "rain_heavy":
        _cloud(d, x0=3, x1=25, top=3, bottom=17)
        for x in (5, 11, 17, 22):
            d.rectangle((x, 20, x + 1, 25), fill=0)
    elif kind == "sleet":
        _cloud(d, x0=3, x1=25, top=3, bottom=17)
        for x in (6, 20):
            d.rectangle((x, 20, x + 1, 25), fill=0)
        _star(d, 13, 23)
    elif kind == "snow":
        _cloud(d, x0=3, x1=25, top=3, bottom=17)
        for x in (7, 14, 21):
            _star(d, x, 23)
    elif kind == "thunder":
        _cloud(d, x0=3, x1=25, top=0, bottom=11)
        _bolt(d)
    elif kind == "hail":
        _cloud(d, x0=3, x1=25, top=0, bottom=11)
        _bolt(d)
        d.rectangle((2, 24, 4, 27), fill=0)
        d.rectangle((23, 24, 26, 27), fill=0)
    else:
        return None
    return img


def draw_icon(canvas, kind, x, y):
    """把图标贴到**超采样**灰度画布上。x / y 是逻辑坐标。

    用反相当 alpha 贴：墨迹处不透明，白底处完全透明，
    所以既保留抗锯齿的灰边，又不会盖掉画布上已有的东西。
    """
    img = _draw(kind)
    if img is None:
        return False
    alpha = img.point(lambda v: 255 - v)
    black = Image.new("L", img.size, 0)
    canvas.paste(black, (int(round(x * renderer.SCALE)), int(round(y * renderer.SCALE))), alpha)
    return True
