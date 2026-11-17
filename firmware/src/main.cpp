// eink-mini firmware -- step 1 stub.
//
// This file only proves the build pipeline and the flash procedure work.
// The real firmware (flip clock, button, partial refresh, provisioning) lands in step 2.
#include <Arduino.h>

static const uint8_t LED_PIN = 8;

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println();
  Serial.println("[eink-mini] firmware stub (step 1) -- display not driven yet");
  Serial.print("[eink-mini] chip: ");
  Serial.println(ESP.getChipModel());
  Serial.print("[eink-mini] flash: ");
  Serial.println(ESP.getFlashChipSize() / 1024 / 1024);
  Serial.println("[eink-mini] expect panel GDEH029A1 296x128 SSD1680 once step 2 lands");
  pinMode(LED_PIN, OUTPUT);
}

void loop() {
  digitalWrite(LED_PIN, HIGH);
  delay(200);
  digitalWrite(LED_PIN, LOW);
  delay(800);
}
