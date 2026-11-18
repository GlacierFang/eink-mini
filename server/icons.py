"""天气图标。

1bpp 小图标的三条命门（踩过才知道）：

1. **字形可以直接用，但别缩放**。Noto Sans CJK 自带 ☀（U+2600），
   实心圆盘 + 12 根等长短方块光芒，是专业设计的形状。
   手画试了五版：光芒一长就变成四尖星，一断就成了噪点，
   腐蚀描边又变成圆顶土面包 —— 都不如字形。
   但字形从 96px 缩到 24px 再阈值化，光芒会被筛成断点，出来是虚线圆。
   所以：**按目标字号原生渲染进画布，不缩放**。
   ❄（U+2744）cmap 里有但渲染是豆腐块，所以雪花还是手绘。
2. **1px 细斜线在点阵上碎成阶梯**，远看就是噪点。
   只用横、竖、2x2 方块、多边形。
3. **剪影要一眼不同**。雨雪雷都带云时，靠"竖条 / 实心十字 / Z 形折线"
   三种骨架区分；云的圆弧高度也要不同，一样高就成了面包。

**每个图标在自己的 28x28 局部画布上画**，不直接画到页面画布上。

为什么不在页面上画：页面画布 296x128，图标要落在 (ox, oy)。直接在
页面上画，形状代码就得带偏移，偏移算错一次就飞 —— 试过，
太阳飞到左上角压住了大温度。局部画布把这个 bug 消灭在结构里。

**细致化靠负空间和构图，不靠灰度抖动**（2026-11-18 实测）：

| 变体          | 孤立噪点% | 1x 实际尺寸观感     |
|---------------|-----------|--------------------|
| A 实心剪影     | 0.10      | 清楚，但没细节      |
| **B 掏白高光** | **0.11**  | **清楚 + 有细节**   |
| C 纯灰阶抖动   | 14.71     | 云变成噪点团       |
| E 轮廓 + 灰阶  | 23.67     | 最差                |

28x28 上抖动出来的不是灰度，是**纹理** —— 一堆散点。所以图标全走
清晰层（硬阈值），用负空间做体积感。

**云上掏白试过三种，全是坑**（1x 实测）：
  掏个洞      -> 读作破洞
  白块压顶    -> 轮廓断成两座山峰
  底部横槽    -> 读作一条横线
所以云**不掏白**。体积感改用两处：
  太阳掏空成环（比实心圆盘多一层信息）
  太阳画在云**后面**，云盖住下半 -> 太阳从云后探出来
另外把云的弧从 3 段加到 4 段（真云是多瓣的），雨丝长短不一，
雾中间一条虚线（浓度低）。
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

# 每种图标里云的包围盒 (x0, x1, top, bottom)
_CLOUD_BOX = {
    "cloud": (3, 25, 6, 20),
    "sun_cloud": (8, 27, 13, 26),
    "overcast": (8, 26, 6, 20),
    "rain": (3, 25, 3, 17),
    "rain_heavy": (3, 25, 3, 17),
    "sleet": (3, 25, 3, 17),
    "snow": (3, 25, 3, 17),
    "thunder": (3, 25, 0, 11),
    "hail": (3, 25, 0, 11),
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
    """局部超采样画布：0 = 黑，255 = 白。"""
    return Image.new("L", (SIZE * renderer.SCALE, SIZE * renderer.SCALE), 255)


def _sun_glyph(d, px, cx, cy):
    """把 ☀ 字形按 px 号原生渲染进画布，居中在 (cx, cy)。

    不缩放：缩小会把光芒筛成断点。
    """
    font = renderer.load_font(px, bold=True)
    bb = d.textbbox((0, 0), SUN_GLYPH, font=font)
    d.text((cx - (bb[0] + bb[2]) / 2, cy - (bb[1] + bb[3]) / 2),
           SUN_GLYPH, font=font, fill=0)
    return True


def _cloud(d, x0=3, x1=25, top=6, bottom=20, fill=0):
    """实心云：**四段高度不同的圆弧** + 平底。

    三段弧顶在 top+10 / top / top+12 —— 一样高就成了面包。
    加第四段小鼓包：真云是多瓣的，三段看着还是一块砖。
    """
    d.ellipse((x0, bottom - 10, x0 + 11, bottom + 1), fill=fill)      # 左弧
    d.ellipse((x0 + 2, top + 4, x0 + 10, bottom + 1), fill=fill)       # 左上鼓包
    d.ellipse((x0 + 5, top, x0 + 18, bottom + 1), fill=fill)           # 中弧（最高）
    d.ellipse((x1 - 10, bottom - 8, x1 + 1, bottom + 1), fill=fill)    # 右弧
    d.rectangle((x0, bottom - 5, x1, bottom + 1), fill=fill)           # 平底


def _star(d, cx, cy, r=3):
    """实心小雪花：粗十字，臂宽 2px。1px 细十字在小图上认不出来。

    六角星试过：三条 60 度斜线在点阵上碎成乱线，比十字难认。
    """
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


def render(kind):
    """画一个图标，返回 (清晰层 28x28, None)。

    局部画布 -> 降采样回 28x28。灰阶层不用 —— 28x28 上抖动出来
    是纹理不是灰度（见文件头实测表）。返回 None 是为了以后
    有大块连续色调区域时还能用上这条通路。
    """
    if kind not in set(_KIND.values()):
        return None, None

    img = _blank()
    d = renderer.ScaledDraw(ImageDraw.Draw(img), renderer.SCALE)

    box = _CLOUD_BOX.get(kind)

    # ---- sun_cloud：太阳先画，云后画 ----
    # 云盖住太阳下半 = 太阳从云后探出来。
    # 画反了（云先太阳后）太阳光芒会压在云上，读作"太阳在云前面"，
    # 天气含义就错了。
    if kind == "sun_cloud":
        if not _sun_glyph(d, 18, 8, 8):
            d.ellipse((3, 3, 13, 13), fill=0)
        _cloud(d, *box, fill=0)

    # ---- 其余带云的图标 ----
    elif box:
        _cloud(d, *box, fill=0)

    # ---- 骨架 ----
    if kind == "sun":
        if not _sun_glyph(d, 26, 14, 14):
            d.ellipse((7, 7, 21, 21), fill=0)
        # 掏空圆心 -> 环 + 光芒。比实心圆盘多一层信息。
        # 环留 3px 宽：太薄会在 1bpp 上断成两段。
        d.ellipse((10, 10, 18, 18), fill=255)
    elif kind == "overcast":
        # 第二朵小云在左下，两朵分开摆。
        # 叠在正上方会连成一个雪人。
        _cloud(d, 0, 14, 12, 23, fill=0)
    elif kind == "fog":
        # 雾没有云 —— 雾本来就是横的。
        # 两条实线夹一条虚线：中间的虚线读作浓度低。
        d.rectangle((2, 6, 25, 8), fill=0)
        for x in (6, 10, 14, 18, 22):
            d.rectangle((x, 12, x + 1, 14), fill=0)
        d.rectangle((2, 18, 25, 20), fill=0)
    elif kind == "rain":
        # 雨丝长短不一
        for x, h in ((8, 4), (14, 6), (20, 5)):
            d.rectangle((x, 20, x + 1, 20 + h), fill=0)
    elif kind == "rain_heavy":
        for x, h in ((5, 5), (10, 7), (15, 6), (21, 7)):
            d.rectangle((x, 20, x + 1, 20 + h), fill=0)
    elif kind == "sleet":
        d.rectangle((6, 20, 7, 25), fill=0)
        d.rectangle((20, 20, 21, 25), fill=0)
        _star(d, 13, 23)
    elif kind == "snow":
        for cx in (7, 14, 21):
            _star(d, cx, 23)
    elif kind == "thunder":
        _bolt(d)
    elif kind == "hail":
        _bolt(d)
        d.rectangle((2, 24, 4, 27), fill=0)
        d.rectangle((23, 24, 26, 27), fill=0)

    return renderer.downsample(img, size=(SIZE, SIZE)), None
