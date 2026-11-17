#!/usr/bin/env python3
# 把 PlatformIO 产物合并成单块整片镜像（ESP32-C3）。
#
# 分区布局（偏移从 partitions.csv 读，不写死）：
#   0x0000  bootloader.bin
#   0x8000  partitions.bin
#   0xE000  boot_app0.bin（otadata，OTA 槽信息；缺了 bootloader 找不到可启动分区）
#   0x10000 firmware.bin
#
# 用法: python3 tools/merge_bin.py <build_dir> <out.bin> <partitions.csv>

import glob
import os
import pathlib
import shutil
import sys

BOOTLOADER_OFFSET = 0x0
PARTITIONS_OFFSET = 0x8000


def parse_partitions(csv_path):
    # 返回 (app 偏移, otadata 偏移或 None)
    app_off = None
    ota_off = None
    for line in csv_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        fields = [x.strip() for x in line.split(',')]
        if len(fields) < 4:
            continue
        ptype = fields[1]
        psub = fields[2]
        off = fields[3]
        if ptype == 'app' and app_off is None:
            app_off = int(off, 16)
        elif ptype == 'data' and psub == 'ota' and ota_off is None:
            ota_off = int(off, 16)
    if app_off is None:
        raise SystemExit('分区表里找不到 app 分区')
    return app_off, ota_off


def find_boot_app0():
    # 在 PlatformIO 的 Arduino framework 包里找 boot_app0.bin
    roots = []
    core = os.environ.get('PLATFORMIO_CORE_DIR')
    if core:
        roots.append(core)
    roots.append(os.path.expanduser('~/.platformio'))
    for root in roots:
        pattern = os.path.join(root, 'packages', 'framework-*', 'tools', 'partitions', 'boot_app0.bin')
        hits = sorted(glob.glob(pattern))
        if hits:
            return pathlib.Path(hits[0])
    return None


def main():
    build = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else '.')
    out = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else 'eink-mini-merged.bin')
    csv_path = pathlib.Path(sys.argv[3] if len(sys.argv) > 3 else 'partitions.csv')
    app_off, ota_off = parse_partitions(csv_path)
    parts = [
        (BOOTLOADER_OFFSET, build / 'bootloader.bin'),
        (PARTITIONS_OFFSET, build / 'partitions.bin'),
    ]
    if ota_off is not None:
        boot_app0 = find_boot_app0()
        if boot_app0 is not None:
            shutil.copy(boot_app0, build / 'boot_app0.bin')
            parts.append((ota_off, build / 'boot_app0.bin'))
        else:
            # 找不到就补 8 字节 0xFF：等价于 otadata 未初始化，
            # bootloader 会退回 app0。能启动，但没有 OTA 槽信息。
            parts.append((ota_off, None))
    parts.append((app_off, build / 'firmware.bin'))
    end = 0
    chunks = []
    for off, path in parts:
        if path is None:
            data = bytes([0xff]) * 8
            label = 'otadata(空)'
        else:
            if not path.exists():
                raise SystemExit('缺少产物: ' + str(path))
            data = path.read_bytes()
            label = path.name
        chunks.append((off, data, label))
        end = max(end, off + len(data))
        print('  0x%06X  %-16s %9d 字节' % (off, label, len(data)))
    buf = bytearray([0xff] * end)
    for off, data, _ in chunks:
        buf[off:off + len(data)] = data
    out.write_bytes(bytes(buf))
    print('已合并 %s: %d 字节 (0x%X)' % (out, len(buf), end))
    cmd = '--chip esp32c3 write_flash -z --flash_mode dio --flash_freq 80m --flash_size 4MB'
    for off, _, label in chunks:
        name = 'boot_app0.bin' if label.startswith('otadata') else label
        cmd += ' 0x%X %s' % (off, name)
    print('烧录命令: ' + cmd)
    (build / 'flash_args.txt').write_text(cmd + chr(10))


if __name__ == '__main__':
    main()
