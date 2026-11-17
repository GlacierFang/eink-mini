#!/usr/bin/env python3
"""把 PlatformIO 产物合并成单块整片镜像（ESP32-C3）。

分区布局：
  0x0000  bootloader
  0x8000  分区表
  0xE000  otadata（C3 不需要 boot_app0，那是 ESP32 原版 OTA 才用的）
  0x10000 app0（固件本体，偏移从 partitions.csv 读，不写死）

用法: python3 tools/merge_bin.py <build_dir> <out.bin> <partitions.csv>
"""
import pathlib
import sys

BOOTLOADER_OFFSET = 0x0
PARTITIONS_OFFSET = 0x8000


def app_offset(csv_path: pathlib.Path) -> int:
    for line in csv_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        fields = [x.strip() for x in line.split(',')]
        if len(fields) >= 4 and fields[1] == 'app':
            return int(fields[3], 16)
    raise SystemExit('分区表里找不到 app 分区')


def main() -> None:
    build = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else '.')
    out = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else 'eink-mini-merged.bin')
    csv_path = pathlib.Path(sys.argv[3] if len(sys.argv) > 3 else 'partitions.csv')
    parts = [
        (BOOTLOADER_OFFSET, build / 'bootloader.bin'),
        (PARTITIONS_OFFSET, build / 'partitions.bin'),
        (app_offset(csv_path), build / 'firmware.bin'),
    ]
    end = 0
    chunks = []
    for off, path in parts:
        if not path.exists():
            raise SystemExit(f'缺少产物: {path}')
        data = path.read_bytes()
        chunks.append((off, data))
        end = max(end, off + len(data))
        print(f'  0x{off:06X}  {path.name:16s} {len(data):>9d} 字节')
    buf = bytearray(b'\xff' * end)
    for off, data in chunks:
        buf[off:off + len(data)] = data
    out.write_bytes(bytes(buf))
    print(f'已合并 {out}: {len(buf)} 字节 (0x{end:X})')
    cmd = '--chip esp32c3 write_flash -z --flash_mode dio --flash_freq 80m --flash_size 4MB'
    for off, path in parts:
        cmd += f' 0x{off:X} {path.name}'
    print('烧录命令:' + cmd)
    (build / 'flash_args.txt').write_text(cmd + '\n')


if __name__ == '__main__':
    main()
