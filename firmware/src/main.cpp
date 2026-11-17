// eink-mini 固件 —— 第 1 步占位程序。
//
// 这个文件只用来验证编译链路和烧录流程能不能跑通。
// 真正的固件（翻页时钟、按键、局刷、配网）在第 2 步。
#include <Arduino.h>

static const uint8_t LED_PIN = 8;

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println();
  Serial.println("[eink-mini] 固件占位程序（第 1 步）—— 尚未驱动屏幕");
  Serial.print("[eink-mini] 芯片: ");
  Serial.println(ESP.getChipModel());
  Serial.print("[eink-mini] flash: ");
  Serial.println(ESP.getFlashChipSize() / 1024 / 1024);
  Serial.println("[eink-mini] 第 2 步落地后应自检面板 GDEH029A1 296x128 SSD1680");
  pinMode(LED_PIN, OUTPUT);
}

void loop() {
  digitalWrite(LED_PIN, HIGH);
  delay(200);
  digitalWrite(LED_PIN, LOW);
  delay(800);
}
