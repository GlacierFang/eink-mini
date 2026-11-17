"""各页面渲染：天气、月历。

页面内容用 PIL 画成 296x128 的灰度图，再转成设备 1bpp 帧。
中文在这里渲染（设备零中文字库，只出 ASCII）。
"""

import calendar
from datetime import datetime

from PIL import ImageDraw

import renderer
from weather import describe, describe_short

W = renderer.W
H = renderer.H

WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"]


def render_weather(weather, fallback_city="城市"):
    """天气页。

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

    renderer.draw_header(d, city, "WEATHER")

    big = renderer.load_font(46, bold=True)
    t = (temp + "°C") if temp else "--"
    d.text((8, 38), t, font=big, fill=0)
    desc = describe(code)
    if desc:
        d.text((8 + renderer.text_width(d, t, big) + 6, 54),
               desc, font=renderer.load_font(20), fill=0)

    if hum:
        hum_text = "湿度 " + hum + "%"
        f_h = renderer.load_font(14)
        d.text((W - 8 - renderer.text_width(d, hum_text, f_h), 42),
               hum_text, font=f_h, fill=0)

    d.line([(0, 90), (W, 90)], fill=0, width=1)

    days = weather.get("days") or []
    f = renderer.load_font(13)
    fb = renderer.load_font(14, bold=True)
    fsmall = renderer.load_font(12)
    col_w = 92
    for i, day in enumerate(days[:3]):
        x = 8 + i * col_w
        date = str(day.get("date") or "")
        d.text((x, 92), date[5:] if len(date) >= 10 else date, font=fb, fill=0)

        tmax = str(day.get("tmax") or "")
        tmin = str(day.get("tmin") or "")
        rng = ("%s°/%s°" % (tmax, tmin)) if (tmax and tmin) else ""
        desc = describe_short(day.get("code"))

        # 描述在左、气温在右，两边都不许越过本列的边界
        rw = renderer.text_width(d, rng, fsmall) if rng else 0
        room = col_w - 14 - rw - (6 if rng else 0)
        desc = renderer.clip_text(d, desc, fsmall, room)
        if desc:
            d.text((x, 108), desc, font=fsmall, fill=0)
        if rng:
            d.text((x + col_w - 8 - rw, 108), rng, font=fsmall, fill=0)
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
