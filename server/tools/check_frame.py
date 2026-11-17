"""位序自检：把服务端 .bin 帧解回图，确认 1=黑 / MSB first / 4736 字节。"""
import sys

from PIL import Image

W, H, ROW = 296, 128, 37


def decode(path):
    data = open(path, "rb").read()
    assert len(data) == ROW * H, (path, len(data))
    img = Image.new("L", (W, H), 255)
    px = img.load()
    for y in range(H):
        row = data[y * ROW:(y + 1) * ROW]
        for x in range(W):
            bit = (row[x // 8] >> (7 - (x % 8))) & 1
            if bit:
                px[x, y] = 0
    out = path.rsplit(".", 1)[0] + "_check.png"
    img.save(out)
    black = sum(1 for p in img.getdata() if p == 0)
    total = W * H
    pct = 100.0 * black / total
    print("%-16s 帧长=%d 黑像素=%d/%d (%.1f%%) -> %s" % (path, len(data), black, total, pct, out))


for p in sys.argv[1:]:
    decode(p)
