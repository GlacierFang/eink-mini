#!/bin/sh
# 主机端渲染固件的 native 页。
#
# 用法：
#   tools/render_host.sh [输出目录]              出 6 张图（PGM + PNG）
#   tools/render_host.sh frame <clock|timer> <输出.bin> [k=v ...]
#
# 装好 g++ 和 python3-pil 就能跑。不需要 PlatformIO，不需要硬件。
set -e
cd "$(dirname "$0")/.."

BIN=/tmp/ink_host_render

build() {
  echo "编译主机渲染器..."
  g++ -std=c++11 -O2 -I src \
      src/ink_canvas.cpp src/ink_pages.cpp src/ink_font_big.cpp \
      tools/host_render.cpp \
      -o "$BIN"
}

# ---- frame 模式：出设备帧 ----
if [ "$1" = "frame" ]; then
  shift
  build
  "$BIN" frame "$@"
  exit 0
fi

# ---- sheet 模式：出一组图 ----
OUT="${1:-}"
if [ -z "$OUT" ]; then
  OUT="$(cd .. && pwd)/tmp-preview"
else
  OUT="$(mkdir -p "$OUT" && cd "$OUT" && pwd)"
fi

build

echo "渲染到 $OUT"
"$BIN" sheet "$OUT"

echo "转 PNG..."
python3 - "$OUT" <<'PYEOF'
import os, sys
from PIL import Image

out = sys.argv[1]
for f in sorted(os.listdir(out)):
    if not f.endswith('.pgm'):
        continue
    p = os.path.join(out, f)
    Image.open(p).save(p[:-4] + '.png')
    os.remove(p)
    print('  ' + p[:-4] + '.png')
PYEOF

echo "完成。"
