"""各页面渲染：天气、月历。

页面内容用 PIL 画成 296x128 的灰度图，再转成设备 1bpp 帧。
中文在这里渲染（设备零中文字库，只出 ASCII）。
"""

import calendar
from datetime import datetime

from PIL import ImageDraw

import icons
import renderer
from weather import describe

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
    """天气页。

    版式：没有顶栏。大温度是全屏唯一的锚点，右侧城市 / 天气 / 湿度；
    下半区三天预报：手绘图标 + 高低温两行 + 日期。

    温度等数字都是**字符串**：取不到就是空串，不是 0。
    屏上不显示 0 度的假数据 —— 和 petd 的做法一致。
    """
    img = renderer.new_canvas()
    d = ImageDraw.Draw(img)
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

    f_city = renderer.load_font(16)
    desc = describe(code)
    line1 = (city + " " + desc).strip() if desc else city
    if line1:
        _ink_right(d, line1, f_city, num_top, W - 8)
    if hum:
        _ink_right(d, "湿度 " + hum + "%", renderer.load_font(12), num_top + 22, W - 8)

    # ---- 分隔线 ----
    d.line([(0, 52), (W, 52)], fill=0, width=1)

    # ---- 下半区：三天预报 ----
    days = weather.get("days") or []
    f = renderer.load_font(12)
    margin = 8
    col_w = (W - 2 * margin) / 3.0
    for i, day in enumerate(days[:3]):
        cx = margin + col_w * (i + 0.5)
        kind = icons.kind_for(day.get("code"))
        if kind:
            icons.draw_icon(img, kind, cx - icons.SIZE / 2, 58)

        tmax = str(day.get("tmax") or "")
        tmin = str(day.get("tmin") or "")
        if tmax:
            _ink_center(d, "↑" + tmax + "°", f, 82, cx)
        if tmin:
            _ink_center(d, "↓" + tmin + "°", f, 96, cx)

        date = str(day.get("date") or "")
        label = (date[8:10] + "日") if len(date) >= 10 else date
        if label:
            _ink_center(d, label, f, 110, cx)
    return img


def render_calendar(now=None):
    now = now or datetime.now()
    img = renderer.new_canvas()
    d = ImageDraw.Draw(img)
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
            if day == now.day:
                d.rectangle([x - tw // 2 - 3, y - 2, x + tw // 2 + 3, y + cell_h - 3],
                            fill=0)
                d.text((x - tw // 2, y), txt, font=fnum, fill=255)
            else:
                d.text((x - tw // 2, y), txt, font=fnum, fill=0)
    return img
