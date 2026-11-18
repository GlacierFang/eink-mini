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
            _ink_center(d, "↑" + tmax + "°", f, 82, cx)
        if tmin:
            _ink_center(d, "↓" + tmin + "°", f, 94, cx)

        date = str(day.get("date") or "")
        label = (date[8:10] + "日") if len(date) >= 10 else date
        if label:
            _ink_center(d, label, f, 106, cx)
    return renderer.downsample(crisp), icon_specs


def render_calendar(now=None):
    """月历页。返回 (清晰层 296x128, []) —— 整页都是文字，没有图标。"""
    now = now or datetime.now()
    crisp = renderer.new_canvas()
    d = renderer.draw_on(crisp)
    renderer.draw_header(d, "%d年%d月" % (now.year, now.month), "CALENDAR")

    f_wd = renderer.load_font(14)
    cell_w = W / 7.0
    for i, name in enumerate(WEEKDAYS):
        x = int(i * cell_w + cell_w / 2 - renderer.text_width(d, name, f_wd) / 2)
        d.text((x, 34), name, font=f_wd, fill=0)

    fnum = renderer.load_font(15)
    cell_h = 15
    weeks = calendar.Calendar(firstweekday=0).monthdayscalendar(now.year, now.month)
    for row, week in enumerate(weeks):
        for col, day in enumerate(week):
            if day == 0:
                continue
            x = int(col * cell_w + cell_w / 2)
            y = 52 + row * cell_h
            txt = str(day)
            tw = renderer.text_width(d, txt, fnum)
            tx = x - tw // 2
            if day == now.day:
                # 反白块必须罩住**墨迹本身**。按固定 cell_h 算块高，
                # 会切掉数字底部 —— 18 里的 8 只剩上半圈。
                b = d.textbbox((0, 0), txt, font=fnum)
                d.rectangle([tx + b[0] - 2, y + b[1] - 1,
                             tx + b[2] + 2, y + b[3] + 1], fill=0)
                d.text((tx, y), txt, font=fnum, fill=255)
            else:
                d.text((tx, y), txt, font=fnum, fill=0)
    return renderer.downsample(crisp), []
