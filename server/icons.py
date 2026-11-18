"""天气图标：程序化手绘的像素画。

点阵字体里没有 ☀ 🌧 ☁ 这类符号，Unicode 渲染出来是豆腐块，
所以图标全部用 PIL 在 20x20 的 1bpp 画布上按像素手绘。

每种图标占满 20x20，同一套比例：云在上、降水在下、闪电居中偏下。
闪电是逐像素点阵画的 —— 用多边形画出来是一条斜杠，不像闪电。
"""

from PIL import Image, ImageDraw, ImageOps

SIZE = 20

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

# 闪电点阵：6 宽 8 高，(x, y) 相对左上角
_BOLT = [
    (4, 0), (5, 0),
    (4, 1), (5, 1),
    (3, 2), (4, 2), (5, 2),
    (2, 3), (3, 3), (4, 3),
    (3, 4), (4, 4),
    (4, 5), (5, 5),
    (3, 6), (4, 6),
    (2, 7), (3, 7),
]


def kind_for(code):
    """WMO 码 -> 图标种类。取不到就空串。"""
    if code is None:
        return ""
    try:
        return _KIND.get(int(code), "")
    except (TypeError, ValueError):
        return ""


def _canvas():
    # mode "1"：1 = 白，0 = 黑
    return Image.new("1", (SIZE, SIZE), 1)


def _sun(d, cx, cy, r, ray=3):
    """太阳：实心圆 + 8 条光芒。"""
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=0)
    for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0), (-1, -1), (1, -1), (-1, 1), (1, 1)):
        d.line(
            (cx + dx * (r + 1), cy + dy * (r + 1), cx + dx * (r + ray), cy + dy * (r + ray)),
            fill=0,
            width=1,
        )


def _cloud(d, x0=2, x1=18, top=3):
    """云：三段圆弧 + 补底，形成一朵实心云。"""
    d.ellipse((x0, top + 3, x0 + 9, top + 11), fill=0)
    d.ellipse((x1 - 11, top, x1, top + 8), fill=0)
    d.rectangle((x0, top + 7, x1, top + 11), fill=0)


def _drops(d, xs, y0, y1):
    for x in xs:
        d.line((x, y0, x - 1, y1), fill=0, width=1)


def _flakes(d, xs, cy):
    for x in xs:
        d.line((x - 2, cy, x + 2, cy), fill=0, width=1)
        d.line((x, cy - 2, x, cy + 2), fill=0, width=1)


def _bolt(d, x=8, y=12):
    for dx, dy in _BOLT:
        d.point((x + dx, y + dy), fill=0)


def _draw(kind):
    img = _canvas()
    d = ImageDraw.Draw(img)
    if kind == "sun":
        _sun(d, 10, 10, 4, ray=3)
    elif kind == "sun_cloud":
        # 太阳躲在小云后面，只露出左上角
        _sun(d, 5, 5, 2, ray=2)
        _cloud(d, x0=4, x1=19, top=9)
    elif kind == "cloud":
        _cloud(d)
    elif kind == "overcast":
        # 阴：压得很低的一片厚云，没有起伏的轮廓
        d.ellipse((0, 4, 20, 12), fill=0)
        d.rectangle((0, 8, 20, 12), fill=0)
    elif kind == "fog":
        _cloud(d, x0=2, x1=17, top=1)
        d.line((4, 15, 16, 15), fill=0, width=1)
        d.line((6, 18, 16, 18), fill=0, width=1)
    elif kind == "rain":
        _cloud(d)
        _drops(d, (4, 10, 16), 15, 19)
    elif kind == "rain_heavy":
        _cloud(d)
        _drops(d, (3, 8, 13, 17), 15, 19)
    elif kind == "sleet":
        _cloud(d)
        _drops(d, (4, 16), 15, 19)
        _flakes(d, (10,), 17)
    elif kind == "snow":
        _cloud(d)
        _flakes(d, (4, 10, 16), 17)
    elif kind == "thunder":
        # 云抬高一点，给闪电腾出位置
        _cloud(d, x0=2, x1=18, top=0)
        _bolt(d)
    elif kind == "hail":
        _cloud(d, x0=2, x1=18, top=0)
        _bolt(d)
        d.ellipse((1, 16, 4, 19), fill=0)
        d.ellipse((15, 16, 18, 19), fill=0)
    else:
        return None
    return img


def draw_icon(canvas, kind, x, y):
    """把图标贴到灰度画布上。图标是纯黑像素，贴完不会有灰边。"""
    img = _draw(kind)
    if img is None:
        return False
    mask = ImageOps.invert(img.convert("L"))
    canvas.paste(Image.new("L", (SIZE, SIZE), 0), (int(x), int(y)), mask)
    return True
