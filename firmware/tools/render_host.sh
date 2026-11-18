#!/bin/sh
# 主机端渲染固件的 native 页并出图。
#
# 用法： tools/render_host.sh [输出目录]   默认 ../tmp-preview
#
# 装好 g++ 和 python3-pil 就能跑。不需要 PlatformIO，不需要硬件。
set -e
cd "$(dirname "$0")/.."

OUT="${1:-}"
if [ -z "$OUT" ]; then
  OUT="$(cd .. && pwd)/tmp-preview"
else
  OUT="$(mkdir -p "$OUT" && cd "$OUT" && pwd)"
fi

echo "编译主机渲染器..."
g++ -std=c++11 -O2 -I src \
    src/ink_canvas.cpp src/ink_pages.cpp tools/host_render.cpp \
    -o /tmp/ink_host_render

echo "渲染到 $OUT"
/tmp/ink_host_render "$OUT"

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
