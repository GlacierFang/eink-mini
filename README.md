# eink-mini

2.9 inch black/white e-paper desk terminal: flip clock, weather, month calendar, message board.
Short press cycles through the pages. The device is a dumb display -- the companion server
renders bitmaps, the device only draws them.

Status: **step 1 of 5** (repository + build pipeline). Display firmware lands in step 2.

## Hardware

| Part | Spec |
|---|---|
| Panel | GDEH029A1, 2.9 inch, 296x128, SSD1680 controller, black/white only (no red, no yellow) |
| MCU | ESP32-C3 Pro mini, USB powered, always on |
| E-paper driver board | v1.4 universal board, FPC socket for 24P / 26P / 34P |
| FPC cable | 24P |
| Button | 12x12x12mm tactile switch, 4 pins (two pairs internally paralleled) |

Panel notes:

- SSD1680 has hardware fast refresh: full refresh about 3s, partial refresh about 0.3s
- The driver board exposes CS1 and CS2 for dual-controller panels -- a single-controller panel needs CS1 and CS2 tied together
- The driver board BUSY polarity may be inverted, so firmware must not assume a level
- The panel has no grayscale: every pixel is black or white

## Wiring (ESP32-C3 Pro mini)

| Driver board | C3 |
|---|---|
| GND | GND |
| 3V3 | 3V3 |
| SCK | GPIO6 |
| SDA | GPIO7 |
| CS1 | GPIO1 (tie CS2 to CS1) |
| DC | GPIO4 |
| RST | GPIO10 |
| BUSY | GPIO3 |

Button: one leg to GPIO5, the other to GND. The firmware uses the internal pull-up.

## Build (GitHub Actions)

Push to main and the workflow compiles the firmware and uploads the artifacts.

- **eink-mini-merged.bin** -- merged image (bootloader + partitions + app), flash at address **0x0**
- **bootloader.bin / partitions.bin / boot_app0.bin / firmware.bin** -- the four separate files

Download them from the Actions tab: latest build run -> Artifacts -> eink-mini-firmware.

## Flash with Flash Download Tools

1. Plug the board in over USB.
2. ChipType **ESP32-C3**, WorkMode **SPI**, SPI Speed **40MHz**, Flash Size **4MB**, SPI Mode **DIO**.
3. Either load **eink-mini-merged.bin** at **0x0** (tick DoNotChgBin),
   or fill the four files: bootloader.bin 0x0, partitions.bin 0x8000, boot_app0.bin 0xE000, firmware.bin 0x10000.
4. Hold BOOT, tap RESET, release BOOT, then press START.
5. When it finishes, the stub blinks the onboard LED once per second.

## Companion server (step 3, not implemented yet)

The device pulls 1bpp frames from a companion server:

| Path | Purpose |
|---|---|
| GET /api/manifest.json | page list: id, title, type, order, version |
| GET /api/page/{id}.bin | 1bpp frame, 296x128, 4736 bytes |
| GET /preview/{id}.png | human-readable preview |
| GET /api/message | write entry: push a message to the screen |
| GET / | web UI |

Frame format: 1bpp, MSB first, bit 1 means black, stride 37 bytes, 4736 bytes per frame.

The device speaks plain HTTP only, so a self-hosted instance needs an HTTP path prefix
(or a local TLS terminator in front of it).

## Roadmap

1. Repository and build pipeline (done)
2. Firmware: flip clock, button, frame pull, dirty-rect partial refresh, provisioning
3. Server: page registry, 1bpp renderer, web UI, message write entry
4. Deployment: nginx path prefix, port registration, systemd unit
5. Run on the host and verify in the web UI

## License

MIT
