"""量化策略评测。改版式后重跑，别靠肉眼猜。

用法（在 server/ 目录下）：
    python3 ../tools/eval_quant.py

指标
----
PSNR    候选灰度图 vs 参考灰度图。参考 = 6 倍超采样渲染后 4x4 面积平均。
        量的是色调保真。
噪点%   孤立黑像素占全部墨迹的比例。四邻域没黑邻居的墨点 = 噪点。
文字1px% 文字区里只有 1px 宽的笔画占全部笔画的比例。越高越碎。

两个指标会打架：dither 的 PSNR 高，但噪点多、文字碎。
墨水屏上字读不出来，色调再准也没用。

图标另算：28x28 上抖动出来的是纹理不是灰度，所以图标只测硬阈值。
"""

import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'server'))

from PIL import Image  # noqa: E402

import renderer  # noqa: E402
import pages  # noqa: E402
import icons  # noqa: E402
import weather  # noqa: E402

REGIONS = {
    'weather': [(26, 38, 200, 281), (104, 118, 18, 92), (80, 96, 20, 280)],
    'calendar': [(50, 120, 10, 286)],
}


def render_at(scale):
    """按指定超采样倍数渲染，随后恢复。

    返回 [(名字, 清晰层, 图标列表), ...]
    """
    old = renderer.SCALE
    renderer.SCALE = scale
    renderer._font_cache.clear()
    try:
        w = weather.get_weather()
        return [
            ('weather',) + pages.render_weather(w, '郑州'),
            ('calendar',) + pages.render_calendar(datetime(2026, 11, 18, 8, 40)),
        ]
    finally:
        renderer.SCALE = old
        renderer._font_cache.clear()


def page_reference(crisp, specs, size=(296, 128)):
    """参考灰度图 = 清晰层 + 图标剪影。

    图标必须进参考图。少了它，PSNR 是在拿「有图标的候选」跟
    「没图标的参考」比 —— 数字会凭空掉 8 dB，读不出好坏。
    """
    g = crisp.convert('L')
    if g.size != tuple(size):
        g = g.resize(size)
    g = g.copy()
    op = g.load()
    for (ox, oy, ic, it) in (specs or []):
        px = ic.convert('L').load()
        iw, ih = ic.size
        for y in range(ih):
            py = oy + y
            if py < 0 or py >= size[1]:
                continue
            for x in range(iw):
                pxx = ox + x
                if pxx < 0 or pxx >= size[0]:
                    continue
                if px[x, y] < 128:
                    op[pxx, py] = 0
    return g


def isolated_ratio(mask):
    h = len(mask)
    w = len(mask[0])
    iso = tot = 0
    for y in range(h):
        row = mask[y]
        up = mask[y - 1] if y > 0 else None
        dn = mask[y + 1] if y < h - 1 else None
        for x in range(w):
            if not row[x]:
                continue
            tot += 1
            near = ((x > 0 and row[x - 1]) or (x < w - 1 and row[x + 1])
                    or (up and up[x]) or (dn and dn[x]))
            if not near:
                iso += 1
    return 100.0 * iso / max(1, tot)


def frag_ratio(mask, regions):
    tot = one = 0
    for (y0, y1, x0, x1) in regions:
        for y in range(y0, y1):
            row = mask[y]
            n = 0
            for x in range(x0, x1):
                if row[x]:
                    n += 1
                elif n:
                    tot += 1
                    if n == 1:
                        one += 1
                    n = 0
            if n:
                tot += 1
                if n == 1:
                    one += 1
    return 100 * one // max(1, tot)


def main():
    p1 = render_at(1)
    p3 = render_at(3)
    p6 = render_at(6)

    print('=== 超采样收益：1x vs 3x，同一量化，参考取 6x ===')
    print('%-9s %-10s %8s %8s %8s' % ('页面', '量化', '1x', '3x', '差'))
    for i, (name, _, _) in enumerate(p3):
        ref = renderer.average_view(page_reference(p6[i][1], p6[i][2]), 4)
        for label, mode, thr in (('hard 128', 'hard', 128), ('hard 150', 'hard', 150),
                                 ('hard 165', 'hard', 165), ('bayer4', 'bayer4', 128)):
            p1v = renderer.psnr(
                renderer.page_perceived(p1[i][1], p1[i][2], mode=mode, threshold=thr, block=4), ref)
            p3v = renderer.psnr(
                renderer.page_perceived(p3[i][1], p3[i][2], mode=mode, threshold=thr, block=4), ref)
            print('%-9s %-10s %8.2f %8.2f %+8.2f' % (name, label, p1v, p3v, p3v - p1v))

    print()
    print('=== 量化策略（3x 渲染）===')
    print('%-9s %-10s %7s %8s %8s %10s' % ('页面', '量化', 'PSNR', '噪点%', '墨量%', '文字1px%'))
    agg = {}
    for i, (name, crisp, specs) in enumerate(p3):
        ref = renderer.average_view(page_reference(p6[i][1], p6[i][2]), 4)
        regions = REGIONS[name]
        for label, mode, thr in (('hard 128', 'hard', 128), ('hard 150', 'hard', 150),
                                 ('hard 165', 'hard', 165), ('bayer2', 'bayer2', 128),
                                 ('bayer4', 'bayer4', 128), ('floyd 128', 'floyd', 128),
                                 ('floyd 140', 'floyd', 140)):
            mask = renderer.page_mask(crisp, specs, mode=mode, threshold=thr)
            cand = renderer.page_perceived(crisp, specs, mode=mode, threshold=thr, block=4)
            psnr = renderer.psnr(cand, ref)
            iso = isolated_ratio(mask)
            ink = 100.0 * sum(1 for r in mask for v in r if v) / (296 * 128)
            frag = frag_ratio(mask, regions)
            agg.setdefault(label, []).append((psnr, iso, frag))
            print('%-9s %-10s %7.2f %8.2f %8.2f %10d' % (name, label, psnr, iso, ink, frag))

    print()
    print('=== 汇总（两页平均）===')
    print('%-10s %8s %8s %10s' % ('量化', 'PSNR', '噪点%', '文字1px%'))
    for k in sorted(agg, key=lambda x: -sum(v[0] for v in agg[x]) / len(agg[x])):
        v = agg[k]
        print('%-10s %8.2f %8.2f %10d' % (
            k, sum(x[0] for x in v) / len(v), sum(x[1] for x in v) / len(v),
            sum(x[2] for x in v) // len(v)))

    print()
    print('=== 阈值扫描（硬阈值）===')
    print('%6s %8s %8s %10s' % ('阈值', 'PSNR', '噪点%', '文字1px%'))
    for thr in range(120, 186, 5):
        ps = iso = fr = 0
        for i, (name, crisp, specs) in enumerate(p3):
            ref = renderer.average_view(page_reference(p6[i][1], p6[i][2]), 4)
            mask = renderer.page_mask(crisp, specs, mode='hard', threshold=thr)
            ps += renderer.psnr(
                renderer.page_perceived(crisp, specs, mode='hard', threshold=thr, block=4), ref)
            iso += isolated_ratio(mask)
            fr += frag_ratio(mask, REGIONS[name])
        n = len(p3)
        print('%6d %8.2f %8.2f %10d' % (thr, ps / n, iso / n, fr // n))

    print()
    print('=== 图标（28x28：轮廓硬边 + 内部 bayer4 抖动）===')
    print('%12s %8s %12s' % ('图标', '墨点', '感知黑度%'))
    from PIL import ImageFilter
    tot = 0
    for k in sorted(set(icons._KIND.values())):
        ic, it = icons.render(k)
        if ic is None:
            continue
        cm = renderer.to_mask(ic, 'hard', renderer.DEFAULT_THRESHOLD,
                              size=(icons.SIZE, icons.SIZE))
        tm = renderer.to_mask(it, renderer.TONE_DITHER_MODE,
                              renderer.TONE_DITHER_THRESHOLD,
                              size=(icons.SIZE, icons.SIZE))
        m = [[cm[y][x] or tm[y][x] for x in range(icons.SIZE)]
             for y in range(icons.SIZE)]
        n = sum(1 for row in m for v in row if v)
        tot += n
        # 感知黑度：模糊 2px 模拟 30cm 视距下的视觉积分，再在形状内求均值。
        img = renderer._mask_to_image(m)
        blur = img.filter(ImageFilter.GaussianBlur(2.0))
        bp = blur.load()
        vals = [bp[x, y] for y in range(icons.SIZE) for x in range(icons.SIZE)
                if m[y][x]]
        mean = sum(vals) / max(1, len(vals))
        print('%12s %8d %11.1f%%'
              % (k, n, 100.0 * (1.0 - mean / 255.0)))
    print('（孤立像素率对抖动填充没有意义 —— 网点本身就是散开的黑点。'
          '该看的指标是感知黑度。）')


if __name__ == '__main__':
    main()
