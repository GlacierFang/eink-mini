"""各页面渲染：天气、月历。

页面内容用 PIL 画成灰度图，再量化成设备 1bpp 帧。

**在 3 倍超采样画布上画**，最后 BOX 降采样回 296x128。
这样小字和图标的边缘有真正的抗锯齿 —— 灰度让画面更精细就靠这一步。

**图标不在页面上画**：图标在自己的 28x28 局部画布上画好、量化成掩码，
再按位置叠进页面（见 icons.py 的说明）。

中文在这里渲染（设备零中文字库，只出 ASCII）。
"""

import calendar
from datetime import datetime

import almanac
import icons
import renderer
from weather import describe_short

W = renderer.W
H = renderer.H

WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"]


def _ink_top(draw, text, font, top, x):
    """把文字的**墨迹顶部**对齐到 top，而不是把 ascender 线对齐到 top。"""
    b = draw.textbbox((0, 0), text, font=font)
    draw.text((x - b[0], top - b[1]), text, font=font, fill=0)


def _ink_right(draw, text, font, top, right_x):
    """把文字的墨迹右缘对齐到 right_x。"""
    b = draw.textbbox((0, 0), text, font=font)
    draw.text((right_x - b[2], top - b[1]), text, font=font, fill=0)


def _ink_center(draw, text, font, top, cx):
    b = draw.textbbox((0, 0), text, font=font)
    draw.text((cx - (b[0] + b[2]) / 2, top - b[1]), text, font=font, fill=0)


# 天气页的小三角箭头。
#
# 不用字体自带的 arrow 符号：12px 下那条竖线只有 1px 宽，
# 超采样 -> 降采样 -> 硬阈值之后会被吃掉，出来是一个孤零零的小黑点。
# 实心三角是实心块，1bpp 上不会退化。
# 三角箭头的每行宽度（尖端 2px 宽，保证降采样后还在）。
# 上尖：2 4 6 7 7   下尖：7 7 6 4 2
_ARROW_ROWS_UP = (2, 4, 6, 7, 7)
_ARROW_ROWS_DOWN = (7, 7, 6, 4, 2)
_ARROW_PX = 7


def _arrow_tri(d, cx, top, down):
    """在 (cx, top) 画一个实心小三角箭头。

    **每行画一个实心横条**，不画多边形、不画细尖角。
    超采样 -> 降采样 -> 硬阈值这条链会把「部分覆盖」的行直接吃掉：
    多边形画的尖角只有 1px 宽，降采样后覆盖率不到阈值，尖没了，
    出来是一个缺角的方块。整行实心（覆盖率 100%）才扛得住。
    """
    widths = _ARROW_ROWS_DOWN if down else _ARROW_ROWS_UP
    for i, w in enumerate(widths):
        x0 = cx - w / 2.0
        d.rectangle((x0, top + i, x0 + w - 1, top + i + 1), fill=0)


def _temp_row(d, down, value, font, top, cx):
    """一行「三角箭头 + 温度」，整组在 cx 处居中。"""
    txt = value + chr(176)
    tw = renderer.text_width(d, txt, font)
    gap = 2
    total = _ARROW_PX + gap + tw
    x = cx - total / 2.0
    _arrow_tri(d, x + _ARROW_PX / 2.0, top + 2, down)
    b = d.textbbox((0, 0), txt, font=font)
    d.text((x + _ARROW_PX + gap - b[0], top - b[1]), txt, font=font, fill=0)

def render_weather(weather, fallback_city="城市"):
    """天气页。返回 (清晰层 296x128, 图标列表)。

    图标列表每项是 (ox, oy, 局部清晰层, 局部灰阶层)，
    由 renderer.page_mask 叠进页面。

    版式：没有顶栏。大温度是全屏唯一的锚点，右侧城市 / 天气 / 湿度；
    下半区三天预报：手绘图标 + 高低温两行 + 日期。

    温度等数字都是**字符串**：取不到就是空串，不是 0。
    屏上不显示 0 度的假数据 —— 和 petd 的做法一致。
    """
    crisp = renderer.new_canvas()
    d = renderer.draw_on(crisp)
    weather = weather or {}
    city = weather.get("city") or fallback_city
    temp = str(weather.get("temp") or "")
    code = weather.get("code")
    hum = str(weather.get("humidity") or "")

    # ---- 上半区 ----
    # 大温度是全屏唯一的锚点：数字宽度随温度变化，单位做右上角上标，
    # 数字太长自动降一档字号。右栏（城市 / 天气 / 湿度）右对齐到边，
    # 两边各占一头，中间留白，不堆在左边。
    num = temp if temp else "--"
    unit_font = renderer.load_font(15)
    uw = d.textbbox((0, 0), "°C", font=unit_font)[2]
    num_top = 5
    # 大温度是锚点：字号往大里顶，受两个约束卡住 ——
    # 墨迹高度不能压过分隔线（52），横向不能撞到右栏（150 之前）。
    big = renderer.load_font(30, bold=True)
    for size in (58, 54, 50, 46, 42, 38, 34, 30):
        f = renderer.load_font(size, bold=True)
        nb = d.textbbox((0, 0), num, font=f)
        if (nb[3] - nb[1]) <= 42 and 8 + (nb[2] - nb[0]) + 4 + uw <= 150:
            big = f
            break
    nb = d.textbbox((0, 0), num, font=big)
    d.text((8 - nb[0], num_top - nb[1]), num, font=big, fill=0)
    ink_right = 8 + (nb[2] - nb[0])
    ub = d.textbbox((0, 0), "°C", font=unit_font)
    d.text((ink_right + 4, num_top + 4 - ub[1]), "°C", font=unit_font, fill=0)

    # 右栏：城市 + 天气简称。
    #
    # 大温度是全屏锚点，右栏绝不能压上去。城市名长（乌鲁木齐）加
    # 天气描述长时会撞 —— 这里量了再画：
    # 先算出温度块（含单位）右缘，右栏左缘必须留 8px 间隙。
    # 放不下就让城市名先让位（天气信息量比地名大），再逐档缩字号，
    # 还放不下就截断。城市名是用户可改的，长度不设上限，所以必须防。
    desc = describe_short(code)
    line1 = (city + " " + desc).strip() if desc else city
    temp_right = ink_right + 4 + uw           # 温度块（含单位）右缘
    min_left = temp_right + 8                 # 右栏左缘下限
    max_width = max(24, (W - 8) - min_left)   # 右栏可用宽度

    f_city = renderer.load_font(16)
    if renderer.text_width(d, line1, f_city) > max_width:
        line1 = desc or city                  # 城市名先让位
    for size in (16, 15, 14, 13, 12):
        f = renderer.load_font(size)
        if renderer.text_width(d, line1, f) <= max_width:
            f_city = f
            break
    else:
        f_city = renderer.load_font(12)
        while line1 and renderer.text_width(d, line1, f_city) > max_width:
            line1 = line1[:-1]

    if line1:
        _ink_right(d, line1, f_city, num_top, W - 8)
    if hum:
        _ink_right(d, "湿度 " + hum + "%", renderer.load_font(12), num_top + 22, W - 8)

    # ---- 分隔线 ----
    d.line([(0, 50), (W, 50)], fill=0, width=1)

    # ---- 下半区：三天预报 ----
    days = weather.get("days") or []
    f = renderer.load_font(12)
    margin = 8
    col_w = (W - 2 * margin) / 3.0
    icon_specs = []
    for i, day in enumerate(days[:3]):
        cx = margin + col_w * (i + 0.5)
        kind = icons.kind_for(day.get("code"))
        if kind:
            icrisp, itone = icons.render(kind)
            if icrisp is not None:
                icon_specs.append(
                    (int(round(cx - icons.SIZE / 2)), 52, icrisp, itone))

        tmax = str(day.get("tmax") or "")
        tmin = str(day.get("tmin") or "")
        if tmax:
            _temp_row(d, False, tmax, f, 82, cx)
        if tmin:
            _temp_row(d, True, tmin, f, 94, cx)

        date = str(day.get("date") or "")
        label = (date[8:10] + "日") if len(date) >= 10 else date
        if label:
            _ink_center(d, label, f, 106, cx)
    return renderer.downsample(crisp), icon_specs, None


def render_calendar(now=None):
    """月历页。返回 (清晰层, [], 灰阶层) —— 周末列用网点浅灰打底。

    版式三段：顶栏给结论（几月 + 今天几号星期几），表头给星期，
    网格给位置。一屏之内读完「现在是什么时候」和「今天落在哪儿」。

    今天用描边框不用反白填充 —— 反白会把数字整个吞掉（原来是块黑）。
    周末的浅灰走**灰阶层**（bayer4 网点），但数字本身画在清晰层：
    抖动会把 12px 小字的笔画打断，读不出来。
    """
    now = now or datetime.now()
    crisp = renderer.new_canvas()
    tone = renderer.new_tone_canvas()
    d = renderer.draw_on(crisp)
    td = renderer.draw_on(tone)

    # ---- 顶栏 ----
    f_month = renderer.load_font(19, bold=True)
    f_year = renderer.load_font(11)
    f_today = renderer.load_font(13)
    mtxt = "%d月" % now.month
    _ink_top(d, mtxt, f_month, 3, 6)
    # 年份小字对齐月标题的**墨迹底**（3 + 19 = 22），不压分割线。
    _ink_top(d, "%d年" % now.year, f_year, 11, 6 + renderer.text_width(d, mtxt, f_month) + 5)
    _ink_right(d, "今天 %d %s" % (now.day, WEEKDAYS[now.weekday()]), f_today, 5, W - 6)
    d.line([(0, 23), (W, 23)], fill=0, width=1)

    # ---- 星期表头 ----
    f_wd = renderer.load_font(12)
    cell_w = W / 7.0
    for i, name in enumerate(WEEKDAYS):
        _ink_center(d, name, f_wd, 27, int(i * cell_w + cell_w / 2))

    # ---- 网格 ----
    weeks = calendar.Calendar(firstweekday=0).monthdayscalendar(now.year, now.month)

    # 行高按周数自适应：五周宽松，六周收紧，但**两种都不切字**。
    # 六周时行高 14、字号 12，末行落在 y=112，字到 y=124，底留 4px。
    grid_top = 42
    bottom = 126
    cell_h = (bottom - grid_top) / float(len(weeks))
    fnum = renderer.load_font(14 if len(weeks) <= 5 else 12)

    # 周末两列打浅灰网点底（只有网格区，不盖表头）。
    #
    # 网点密度由灰度值决定（bayer4 阈值 128）：越接近 255 网点越稀。
    # 实测密度（网格区黑像素占比）：
    #   205 -> 约 19%   周末的 8 和 9 被网点围着，发闷
    #   222 -> 约 12.5% 还是抢眼
    #   235 -> 约 6.25% 只留一层薄纱，能看出是周末列，数字清楚
    for col in (5, 6):
        td.rectangle([int(col * cell_w), grid_top, int((col + 1) * cell_w), bottom],
                     fill=235)

    for row, week in enumerate(weeks):
        for col, day in enumerate(week):
            if day == 0:
                continue
            x = int(col * cell_w + cell_w / 2)
            y = int(grid_top + row * cell_h)
            txt = str(day)
            tw = renderer.text_width(d, txt, fnum)
            tx = x - tw // 2
            b = d.textbbox((0, 0), txt, font=fnum)
            if day == now.day:
                # 描边框：罩住墨迹本身，留 3px 余量，一眼认出今天。
                d.rectangle([tx + b[0] - 3, y + b[1] - 2,
                             tx + b[2] + 3, y + b[3] + 2], outline=0, width=1)
            d.text((tx, y), txt, font=fnum, fill=0)
    return renderer.downsample(crisp), [], renderer.downsample(tone)


def render_almanac(now=None):
    """单日黄历页。返回 (清晰层 296x128, []) —— 整页都是文字。

    只画**当天**：公历日期、年干支、农历月日、日/月/年干支、节气。

    不画农历月历，不画宜忌 —— 屏就那么大，一天塞得下，一个月塞不下。
    """
    now = now or datetime.now()
    f = almanac.day_fields(now.date())

    crisp = renderer.new_canvas()
    d = renderer.draw_on(crisp)

    f_h = renderer.load_font(15, bold=True)
    f_s = renderer.load_font(12)
    f_m = renderer.load_font(14)
    f_big = renderer.load_font(26, bold=True)

    # ---- 顶部：公历日期 + 星期 | 年干支 + 生肖 ----
    d.text((6, 3), "%d月%d日 %s" % (f["date"].month, f["date"].day, f["week"]),
           font=f_h, fill=0)
    rt = "%s %s" % (f["ganzhi_year"], f["shengxiao"])
    d.text((W - 6 - renderer.text_width(d, rt, f_s), 5), rt, font=f_s, fill=0)
    d.line([(0, 21), (W, 21)], fill=0, width=1)

    # ---- 中部左：大号农历月日 + "农历"标签 ----
    # 大号字的墨迹从 y=35 起、到 y=61 止（26px 字体的 ascender 有偏移）。
    # "农历"标签必须让开这段：画在 y=57 会和大号字压在一起。
    d.text((8, 28), f["lunar_month"] + "月" + f["lunar_day"], font=f_big, fill=0)
    d.text((10, 64), "农历", font=f_s, fill=0)

    # ---- 中部右：日 / 月 / 年 三行干支 ----
    rx = 152
    for i, pair in enumerate((("日", f["ganzhi_day"]),
                              ("月", f["ganzhi_month"]),
                              ("年", f["ganzhi_year"]))):
        yy = 29 + i * 17
        d.text((rx, yy), pair[0], font=f_s, fill=0)
        d.text((rx + 18, yy - 2), pair[1], font=f_m, fill=0)

    d.line([(0, 86), (W, 86)], fill=0, width=1)

    # ---- 底部：节气 ----
    if f["jieqi_today"]:
        # 今天是节气：节气本身占主位，右下补一句下个节气。
        d.text((6, 92), "今日节气  " + f["jieqi_today"], font=f_m, fill=0)
        nd = f["jieqi_next_date"]
        d.text((6, 110), "下个 %s 还有 %d 天" % (f["jieqi_next"], f["days_to_next"]),
               font=f_s, fill=0)
    else:
        nd = f["jieqi_next_date"]
        d.text((6, 92), "下个节气  %s  %d月%d日"
               % (f["jieqi_next"], nd.month, nd.day), font=f_m, fill=0)
        d.text((6, 110), "还有 %d 天" % f["days_to_next"], font=f_s, fill=0)

    pd = f["jieqi_prev_date"]
    pg = "上个 %s %d月%d日" % (f["jieqi_prev"], pd.month, pd.day)
    d.text((W - 6 - renderer.text_width(d, pg, f_s), 110), pg, font=f_s, fill=0)

    return renderer.downsample(crisp), [], None

def render_hourly(weather_data, fallback_city="城市"):
    """逐小时天气页。返回 (清晰层, 图标列表, None)。

    版式（12 小时）：
      顶栏   标题 + 城市
      读数行 体感温度 / 相对湿度 / 风速（当前这一小时的值）
      上半   天气图标 + 温度折线
      下半   降水概率黑柱，≥40% 的在柱顶标数字
      横轴   每 3 小时一个时间标签

    图标为什么画在折线上方而不是叠在曲线上：曲线是温度的**位置**编码，
    图标是**类别**编码。两者叠一起，看不出这个点的温度是 3 度还是 5 度。

    图标为什么 22x22 不是 28x28：12 列要塞进 296px，一列只有 24px。
    从超采样画布直接降采样到 22，不是缩 28 缩来的 —— 后者会把 1px 的
    雨丝糊成灰点（见 icons.render 的 size 参数）。

    折线为什么是纯黑而不是灰阶：墨水屏只有黑白，灰阶靠 bayer4 网点
    模拟，1px 细线被抖成网点就断了。宁可纯黑硬边。
    """
    w = weather_data or {}
    rows = w.get("hourly") or []
    # 城市名以**配置**为准，不以缓存为准。
    # 缓存里的 city 是上次取数时的城市 —— 用户刚改完配置、后台还在
    # 刷新时的那几十秒里，缓存城市和配置城市不是一回事。
    # 用配置城市当标题、数据是稍旧的，比标题和数据对不上要好。
    city = fallback_city or w.get("city") or "城市"

    crisp = renderer.new_canvas()
    d = renderer.draw_on(crisp)
    icon_specs = []

    f_title = renderer.load_font(14, bold=True)
    f_sub = renderer.load_font(11)
    f_axis = renderer.load_font(10)
    f_read = renderer.load_font(12)

    _ink_top(d, "逐小时预报", f_title, 2, 6)
    _ink_right(d, city, f_sub, 5, W - 6)
    d.line([(0, 20), (W, 20)], fill=0, width=1)

    if not rows:
        _ink_center(d, "暂无逐小时数据", f_sub, 60, W // 2)
        return renderer.downsample(crisp), [], None

    def _f(row, key):
        try:
            return float(row.get(key))
        except (TypeError, ValueError):
            return None

    temps = [_f(r, "temp") for r in rows]
    valid = [t for t in temps if t is not None]
    if not valid:
        _ink_center(d, "暂无温度数据", f_sub, 60, W // 2)
        return renderer.downsample(crisp), [], None

    tmin, tmax = min(valid), max(valid)
    if tmax - tmin < 1.0:
        tmax = tmin + 1.0

    n = len(rows)
    plot_x0, plot_x1 = 26, 290
    slot = (plot_x1 - plot_x0) / float(n)
    xs = [plot_x0 + slot * (i + 0.5) for i in range(n)]

    pops = [_f(r, "pop") for r in rows]
    real_pops = [p for p in pops if p is not None]
    max_pop = max(real_pops) if real_pops else 0.0
    has_rain = max_pop > 0

    # ---- 读数行：体感 / 湿度 / 风速 ----
    #
    # 只放当前这一小时的值（rows[0]），不是 12 小时的范围 ——
    # 范围值没有时间锚点，看的人不知道是几点的范围。
    first = rows[0]
    reads = []
    ap = _f(first, "apparent")
    if ap is not None:
        reads.append(("体感", "%d°" % round(ap)))
    hum = _f(first, "humidity")
    if hum is not None:
        reads.append(("湿度", "%d%%" % round(hum)))
    wind = _f(first, "wind")
    if wind is not None:
        reads.append(("风", "%dkm/h" % round(wind)))
    rx = 6
    for label, value in reads:
        lw = renderer.text_width(d, label, f_read)
        vw = renderer.text_width(d, value, f_read)
        d.text((rx, 22), label, font=f_read, fill=0)
        d.text((rx + lw + 3, 22), value, font=f_read, fill=0)
        rx += lw + vw + 14

    # ---- 天气图标：每个整点一个，画在折线上方 ----
    #
    # 图标放在曲线**上方**，不叠在曲线上：曲线是位置编码，
    # 图标是类别编码，叠在一起两边都读不出来。
    #
    # 尺寸 22：12 列要塞进 296px，一列只有 24px，28 宽放不下。
    # 从超采样画布直接降采样到 22，不是缩 28 缩来的（后者会把
    # 1px 雨丝糊成灰点，见 icons.render 的 size 参数）。
    #
    # **太阳例外**：sun 的 ☀ 字形是 28px 原生渲染的，缩到 22 后
    # 光芒和圆环粘连成一坨实心黑（实测整个外圈全黑）。
    # 晴天改画圆环 + 四道短光芒，线条缩放不会糊。
    #
    # 垂直分层：读数行 y=22..34、图标行 y=36..58、曲线区 y=60 起。
    # 三层不重叠 —— 挤在一行里第一个图标会贴着读数，第二个会压住数字。
    icon_size = 22
    icon_y = 36
    for i, row in enumerate(rows):
        kind = icons.kind_for(row.get("code"))
        if not kind:
            continue
        # 只画隔一个的点 —— 12 个全画会挤成一团，看不出变化。
        if i % 2 != 0 and i != n - 1:
            continue
        cx = xs[i]
        if kind == "sun":
            cy = icon_y + icon_size // 2
            d.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], outline=0, width=2)
            for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                d.line([(cx + dx * 5, cy + dy * 5),
                        (cx + dx * 8, cy + dy * 8)], fill=0, width=2)
            continue
        icrisp, itone = icons.render(kind, icon_size)
        if icrisp is None:
            continue
        ox = int(cx - icon_size / 2)
        if ox < 0 or ox + icon_size > W:
            continue
        icon_specs.append((ox, icon_y, icrisp, itone))

    chart_top = 60
    base_y, max_bar = 104, 26
    chart_bottom = 82 if has_rain else 88

    def ty(t):
        return chart_bottom - (t - tmin) / (tmax - tmin) * (chart_bottom - chart_top)

    # ---- 温度折线 ----
    pts = [(xs[i], ty(temps[i])) for i in range(n) if temps[i] is not None]
    if len(pts) >= 2:
        d.line(pts, fill=0, width=2)
    for (px, py) in pts:
        d.rectangle([px - 1.5, py - 1.5, px + 1.5, py + 1.5], fill=0)

    # 左轴：最高 / 最低
    _ink_right(d, "%d" % round(tmax), f_axis, chart_top - 1, 22)
    _ink_right(d, "%d" % round(tmin), f_axis, chart_bottom - 9, 22)

    # ---- 降水概率柱 ----
    d.line([(0, chart_bottom + 2), (W, chart_bottom + 2)], fill=0, width=1)
    if has_rain:
        for i, pop in enumerate(pops):
            if pop is None:
                continue
            pop = max(0.0, min(100.0, pop))
            h = pop / 100.0 * max_bar
            if pop > 0 and h < 1:
                h = 1
            cx = xs[i]
            d.rectangle([cx - 5.5, base_y - h, cx + 5.5, base_y], fill=0)
            if pop >= 40:
                _ink_center(d, "%d" % round(pop), f_axis, base_y - h - 10, cx)
    else:
        # 没降水就写清楚，不让下半屏空着。
        # 放在分隔线和横轴之间 —— 不能压曲线（曲线最低到 chart_bottom），
        # 也不能压时间轴（时间轴在 y=110）。无雨时 chart_bottom=88，
        # 文字墨迹 12px 高，落在 90..102，离时间轴还有 8px。
        _ink_center(d, "未来 12 小时无降水", f_sub, chart_bottom + 4, W // 2)

    # ---- 横轴时间 ----
    marks = list(range(0, n, 3))
    if n - 1 not in marks:
        marks.append(n - 1)
    for i in marks:
        hh = rows[i].get("hour")
        if hh is None:
            continue
        _ink_center(d, "%d时" % hh, f_axis, 110, xs[i])

    return renderer.downsample(crisp), icon_specs, None
