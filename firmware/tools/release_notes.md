## 烧录

```
--chip esp32c3 write_flash -z --flash_mode dio --flash_freq 80m --flash_size 4MB \
  0x0 bootloader.bin 0x8000 partitions.bin 0xE000 boot_app0.bin 0x10000 firmware.bin
```

| 文件 | 烧录地址 | 说明 |
|---|---|---|
| eink-mini-merged.bin | 0x0 | 合并镜像，一步烧完 |
| bootloader.bin | 0x0 | |
| partitions.bin | 0x8000 | |
| boot_app0.bin | 0xE000 | OTA 槽信息（otadata） |
| firmware.bin | 0x10000 | 固件本体 |

`SHA256SUMS` 是各产物的校验和。

烧录步骤详见仓库 README 的「用 Flash Download Tools 烧录」。
