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

**灰阶用空间密度换**（2026-11-18 复核，前面那版结论是错的）：

SSD1608 是严格 1bpp，但油墨只有黑、纸只有白，报纸照样能印出明暗层次 ——
靠的不是把油墨调淡，是**空间密度换灰阶**（半色调/网点纸原理）。
人眼在正常视距下看不清孤立的黑白点，会对局部区域做积分平均：
100% 黑 = 纯黑，50% 网点 = 中灰，25% 网点 = 浅灰。

屏幕 296x128 = 111 PPI，30cm 视距下单像素 2.6 角分。
眼模型实测（高斯模糊模拟视觉积分，30cm）：

| 变体                 | 感知黑度 | 纹理 sd |
|---------------------|---------|---------|
| 实心 100%            | 97.4%   | 14.89   |
| **bayer4 50%**       | **50.5%** | **3.01** |
| bayer4 25%           | 32.9%   | 6.89    |
| bayer4 75%           | 73.8%   | 8.31    |

实心填充的纹理噪声是 50% 抖动的 5 倍 —— 这就是"大面积黑块视觉压迫感强"
的量化版。bayer4 的 50% 是最甜的一档：4x4 矩阵正好半亮半暗、分布最均匀。

**但有三条硬边界**（实测，不是估计）：

1. **面积下限 16x16 px**：8x8 读出的是"点"不是"调子"（sd 10.98），
   16x16 才干净（sd 2.09）。
2. **笔画下限 2px**：1px 横条在 bayer4 下有 50% 的列是断的。
   所以文字、1px 细箭头、细线必须硬边，绕开抖动。
3. **bayer2 不够用**：只有 4 级灰，最小非零灰阶就是 50%，
   表达不出 25% 浅灰。要 16 级就得 bayer4。

**本文件的做法**：轮廓留清晰层（硬边，2px 宽），内部填灰走抖动。
轮廓保持形状，内部才有灰阶层次 —— 这正是报纸网点的做法。

细笔画自动留在清晰层：雨丝 2px、雪花十字、雾的横条、太阳环 3px，
腐蚀 2px 之后什么都不剩，整根还是实心硬边。抖动不会碰它们。

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

from PIL import Image, ImageDraw, ImageFilter

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


def _erode(mask, k):
    """二值掩码（白 = 形状）腐蚀 k 像素。"""
    return mask.filter(ImageFilter.MinFilter(k))


def _components(mask):
    """连通域 -> [[(x, y), ...]]。四邻接。"""
    seen = [[False] * SIZE for _ in range(SIZE)]
    out = []
    for y in range(SIZE):
        for x in range(SIZE):
            if mask.getpixel((x, y)) > 127 and not seen[y][x]:
                stack = [(x, y)]
                seen[y][x] = True
                cells = []
                while stack:
                    cx, cy = stack.pop()
                    cells.append((cx, cy))
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nx, ny = cx + dx, cy + dy
                        if 0 <= nx < SIZE and 0 <= ny < SIZE:
                            if not seen[ny][nx] and mask.getpixel((nx, ny)) > 127:
                                seen[ny][nx] = True
                                stack.append((nx, ny))
                out.append(cells)
    return out


def _split_layers(crisp):
    """画好的图标 -> (轮廓清晰层 28x28, 内部灰阶层 28x28)。

    轮廓 = 形状外 2px，留在清晰层硬边输出，形状边界不糊。
    内部 = 腐蚀 2px 后的厚块，填 50% 灰交给有序抖动（bayer4）。

    细笔画腐蚀后什么都不剩，自动整根留在清晰层 ——
    1px 线在抖动下会断成虚线（实测 50% 的列断掉）。

    内部连通域太小也退回清晰层：
      - 面积 < 64px
      - 包围盒宽或高 < 8px（放不下完整的 4x4 抖动周期）
    那点面积抖出来是散点不是灰 —— 实测 sun 的 30px 内块抖完
    texture_sd 40.55，是 cloud（19.63）的两倍，就是散点噪。
    """
    size = (SIZE, SIZE)
    # 用页面清晰层同一套阈值（165），保证轮廓宽度和以前的实心剪影一致。
    shape = crisp.point(lambda v: 255 if v < 165 else 0)
    inner = _erode(shape, 5)

    keep = Image.new("L", size, 0)
    for cells in _components(inner):
        if len(cells) < 64:
            continue
        xs = [c[0] for c in cells]
        ys = [c[1] for c in cells]
        if (max(xs) - min(xs) + 1) < 8 or (max(ys) - min(ys) + 1) < 8:
            continue
        for (x, y) in cells:
            keep.putpixel((x, y), 255)

    outline = Image.new("L", size, 255)
    op = outline.load()
    sp = shape.load()
    kp = keep.load()
    for y in range(SIZE):
        for x in range(SIZE):
            if sp[x, y] > 127 and kp[x, y] <= 127:
                op[x, y] = 0

    tone = Image.new("L", size, 255)
    tp = tone.load()
    for y in range(SIZE):
        for x in range(SIZE):
            if kp[x, y] > 127:
                tp[x, y] = 128

    return outline, tone


def render(kind):
    """画一个图标，返回 (轮廓清晰层 28x28, 内部灰阶层 28x28)。

    局部画布 -> 降采样回 28x28 -> 拆成轮廓层和内部灰阶层。
    轮廓走硬阈值，内部走 bayer4 抖动，量化时取并集（见 renderer.page_mask）。
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

    return _split_layers(renderer.downsample(img, size=(SIZE, SIZE)))
