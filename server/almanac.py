# -*- coding: utf-8 -*-
"""单日黄历的数据层：把公历日期换算成农历、干支和节气。

只做**当天**。不做农历月历，不做宜忌 —— 屏就那么大，
一天的信息塞得下，一个月塞不下。

## 四条必须算对的规则

1. **年干支按立春换年，立春当天就换。**
   2026 立春是 02-04 04:02。用 getYearInGanZhiExact() 的话，
   02-04 当天算出来还是「乙巳」，要等到 02-05 才变 —— 差一整天。
   黄历按天看，立春当天就该是丙午年，所以用 getYearInGanZhiByLiChun()。
   生肖同理用 getYearShengXiaoByLiChun()。

2. **月干支按节气换月，节气当天就换。**
   2026 立冬是 11-07 17:52。getMonthInGanZhiExact() 在 11-07 当天
   仍给「戊戌」，11-08 才变「己亥」。同样差一天。
   用 getMonthInGanZhi()（按节气日算，不按时刻）。

3. **"上个节气"是今天的 00:00 之前最后一个。**
   从今天算：昨天正好是节气日时，它仍然算「上个」——
   用 d-1 去查会把昨天的节气漏掉。

4. **"下个节气"是明天 00:00 之后的第一个。**
   从明天算：今天正好是节气日时，今天这个不算「下个」，
   要再往后一个。

数据来自 vendored 的 lunar-python（MIT，见同目录 LICENSE）。
"""

from datetime import date, timedelta

from lunar_python import Solar


def _lunar(d):
    return Solar.fromYmd(d.year, d.month, d.day).getLunar()


def _jieqi_date(jq):
    """JieQi -> 公历日期。"""
    s = jq.getSolar()
    return date(s.getYear(), s.getMonth(), s.getDay())


def day_fields(d=None):
    """返回某一天的黄历字段。d 缺省是今天。

    返回 dict：
      date / week / lunar_month / lunar_day / lunar_text
      ganzhi_year / ganzhi_month / ganzhi_day / shengxiao
      jieqi_today（今天节气，没有就是空串）
      jieqi_next / jieqi_next_date / days_to_next
      jieqi_prev / jieqi_prev_date
    """
    d = d or date.today()
    lunar = _lunar(d)

    # 上个节气：今天 00:00 之前最后一个。
    prev_jq = lunar.getPrevJieQi()
    # 下个节气：明天 00:00 之后的第一个（今天正好是节气时不算今天这个）。
    next_jq = _lunar(d + timedelta(days=1)).getNextJieQi()

    prev_date = _jieqi_date(prev_jq)
    next_date = _jieqi_date(next_jq)

    return {
        "date": d,
        "week": lunar.getWeekInChinese(),
        "lunar_month": lunar.getMonthInChinese(),
        "lunar_day": lunar.getDayInChinese(),
        "lunar_text": lunar.getMonthInChinese() + lunar.getDayInChinese(),
        # 立春当天就换年 —— 见文件头规则 1
        "ganzhi_year": lunar.getYearInGanZhiByLiChun(),
        # 节气当天就换月 —— 见文件头规则 2
        "ganzhi_month": lunar.getMonthInGanZhi(),
        "ganzhi_day": lunar.getDayInGanZhi(),
        "shengxiao": lunar.getYearShengXiaoByLiChun(),
        # 今天的节气名，没有就是空串
        "jieqi_today": lunar.getJieQi(),
        "jieqi_next": next_jq.getName(),
        "jieqi_next_date": next_date,
        "jieqi_prev": prev_jq.getName(),
        "jieqi_prev_date": prev_date,
        "days_to_next": (next_date - d).days,
    }
