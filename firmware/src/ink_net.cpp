#include "ink_net.h"

#include <Arduino.h>
#include <WiFi.h>
#include <Preferences.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <HTTPClient.h>
#include <WebServer.h>
#include <time.h>
#include <sys/time.h>

static const char* NVS_NS = "ink";
static WebServer* g_cfgServer = nullptr;
static char g_cfgSsid[33] = "";
static char g_cfgPass[65] = "";
static char g_cfgHost[64] = "";
static char g_cfgBase[64] = "";

static void nvsSetStr(const char* key, const char* val)
{
  Preferences p;
  p.begin(NVS_NS, false);
  p.putString(key, val);
  p.end();
}

static String nvsGetStr(const char* key, const char* def = "")
{
  Preferences p;
  p.begin(NVS_NS, true);
  String v = p.getString(key, def);
  p.end();
  return v;
}

// 把 NVS 里的字符串安全地拷进定长缓冲
static void copyStr(char* dst, size_t dstLen, const String& src)
{
  if (!dst || dstLen == 0) return;
  strncpy(dst, src.c_str(), dstLen - 1);
  dst[dstLen - 1] = 0;
}

bool InkNet::loadConfig()
{
  copyStr(ssid_, sizeof(ssid_), nvsGetStr("ssid"));
  copyStr(pass_, sizeof(pass_), nvsGetStr("pass"));
  copyStr(host_, sizeof(host_), nvsGetStr("host", INK_DEFAULT_HOST));
  copyStr(base_, sizeof(base_), nvsGetStr("base", INK_DEFAULT_BASE));
  if (host_[0] == 0) copyStr(host_, sizeof(host_), String(INK_DEFAULT_HOST));
  if (base_[0] == 0) copyStr(base_, sizeof(base_), String(INK_DEFAULT_BASE));
  haveConfig_ = (ssid_[0] != 0);
  return haveConfig_;
}

void InkNet::saveConfig()
{
  nvsSetStr("ssid", ssid_);
  nvsSetStr("pass", pass_);
  nvsSetStr("host", host_);
  nvsSetStr("base", base_);
  haveConfig_ = (ssid_[0] != 0);
}

// 供配网页提交时写入
void InkNet::saveNetwork(const char* ssid, const char* pass)
{
  copyStr(ssid_, sizeof(ssid_), String(ssid ? ssid : ""));
  copyStr(pass_, sizeof(pass_), String(pass ? pass : ""));
  nvsSetStr("ssid", ssid_);
  nvsSetStr("pass", pass_);
  haveConfig_ = (ssid_[0] != 0);
}

void InkNet::saveServer(const char* host, const char* base)
{
  if (host && host[0]) copyStr(host_, sizeof(host_), String(host));
  if (base && base[0]) copyStr(base_, sizeof(base_), String(base));
  nvsSetStr("host", host_);
  nvsSetStr("base", base_);
}

bool InkNet::connectWifi()
{
  if (ssid_[0] == 0) return false;
  Serial.printf("[wifi] 连接 %s ...\n", ssid_);
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid_, pass_);
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 20000) {
    delay(200);
  }
  connected_ = (WiFi.status() == WL_CONNECTED);
  if (connected_) Serial.printf("[wifi] 已连接，IP %s\n", WiFi.localIP().toString().c_str());
  else Serial.println("[wifi] 连接失败");
  return connected_;
}

void InkNet::begin()
{
  loadConfig();
  if (!connectWifi() && haveConfig_) {
    Serial.println("[wifi] 尝试重连一次");
    connectWifi();
  }
}

void InkNet::makeUrl(const char* path, char* out, size_t outLen)
{
  snprintf(out, outLen, "http://%s%s%s", host_, base_, path ? path : "");
}

// ---- 简易 HTTP Date -> epoch（不依赖时区库）----
static bool parseHttpDate(const char* s, uint32_t& outEpoch)
{
  // 形如: Tue, 17 Nov 2026 21:00:00 GMT
  if (!s) return false;
  const char* p = strstr(s, ", ");
  if (!p) return false;
  p += 2;
  int day = 0, year = 0;
  char mon[8] = {0};
  int hh = 0, mm = 0, ss = 0;
  if (sscanf(p, "%d %3s %d %d:%d:%d", &day, mon, &year, &hh, &mm, &ss) != 6) return false;

  static const char* MON[12] = { "Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec" };
  int mi = -1;
  for (int i = 0; i < 12; i++) if (strncmp(mon, MON[i], 3) == 0) { mi = i; break; }
  if (mi < 0) return false;

  // civil -> days since epoch
  int y = year;
  int m = mi + 1;
  int d = day;
  y -= (m <= 2) ? 1 : 0;
  int era = (y >= 0 ? y : y - 399) / 400;
  unsigned yoe = (unsigned)(y - era * 400);
  unsigned doy = (unsigned)((153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1);
  unsigned doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
  int days = (int)(era * 146097 + (int)doe - 719468);
  outEpoch = (uint32_t)(((int64_t)days * 86400) + hh * 3600 + mm * 60 + ss);
  return true;
}

bool InkNet::syncTime()
{
  if (!connected_) return false;

  // 1) SNTP 双源
  configTime(INK_TZ_OFFSET_SEC, 0, "pool.ntp.org", "ntp.aliyun.com");
  uint32_t t0 = millis();
  time_t now = 0;
  while (millis() - t0 < 12000) {
    time(&now);
    if (now > 1700000000) break;
    delay(500);
  }
  if (now > 1700000000) {
    timeValid_ = true;
    Serial.println("[time] SNTP 校时成功");
    return true;
  }

  // 2) HTTP Date 兜底
  char url[192];
  makeUrl("/api/manifest.json", url, sizeof(url));
  HTTPClient http;
  http.setTimeout(INK_HTTP_TIMEOUT_MS);
  http.setConnectTimeout(8000);
  if (http.begin(url)) {
    int code = http.GET();
    String dateHdr = http.header("Date");
    if (code > 0 && dateHdr.length() > 0) {
      uint32_t ep = 0;
      if (parseHttpDate(dateHdr.c_str(), ep) && ep > 1700000000) {
        struct timeval tv;
        tv.tv_sec = (time_t)ep;
        tv.tv_usec = 0;
        settimeofday(&tv, nullptr);
        timeValid_ = true;
        Serial.printf("[time] HTTP Date 兜底校时成功: %lu\n", (unsigned long)ep);
        http.end();
        return true;
      }
    }
    http.end();
  }
  Serial.println("[time] 校时失败");
  return false;
}

uint32_t InkNet::epoch()
{
  time_t now = 0;
  time(&now);
  return (uint32_t)now;
}

// ---------------------------------------------------------------- 配网页
static void handleRoot()
{
  String html =
    "<!doctype html><meta charset='utf-8'><title>eink-mini setup</title>"
    "<style>body{font-family:sans-serif;max-width:420px;margin:40px auto}"
    "input,button{width:100%;padding:9px;margin:5px 0;box-sizing:border-box}"
    "label{font-size:13px;color:#555}</style>"
    "<h3>eink-mini 配网</h3>"
    "<form action='/save' method='POST'>"
    "<label>WiFi 名称</label><input name='ssid' value='" + String(g_cfgSsid) + "'>"
    "<label>WiFi 密码</label><input name='pass' type='password' value='" + String(g_cfgPass) + "'>"
    "<label>服务器域名</label><input name='host' value='" + String(g_cfgHost) + "'>"
    "<label>服务路径前缀</label><input name='base' value='" + String(g_cfgBase) + "'>"
    "<button type='submit'>保存并重启</button>"
    "</form>";
  g_cfgServer->send(200, "text/html", html);
}

static void handleSave()
{
  if (g_cfgServer->hasArg("ssid")) strncpy(g_cfgSsid, g_cfgServer->arg("ssid").c_str(), sizeof(g_cfgSsid) - 1);
  if (g_cfgServer->hasArg("pass")) strncpy(g_cfgPass, g_cfgServer->arg("pass").c_str(), sizeof(g_cfgPass) - 1);
  if (g_cfgServer->hasArg("host")) strncpy(g_cfgHost, g_cfgServer->arg("host").c_str(), sizeof(g_cfgHost) - 1);
  if (g_cfgServer->hasArg("base")) strncpy(g_cfgBase, g_cfgServer->arg("base").c_str(), sizeof(g_cfgBase) - 1);

  // 落盘，重启后生效
  nvsSetStr("ssid", g_cfgSsid);
  nvsSetStr("pass", g_cfgPass);
  nvsSetStr("host", g_cfgHost);
  nvsSetStr("base", g_cfgBase);

  g_cfgServer->send(200, "text/html", "<h3>已保存，正在重启...</h3>");
  delay(800);
  ESP.restart();
}

void InkNet::runConfigPortal()
{
  WiFi.mode(WIFI_AP);
  WiFi.softAP("eink-mini-setup");
  IPAddress ip = WiFi.softAPIP();

  if (!g_cfgServer) g_cfgServer = new WebServer(80);
  g_cfgServer->on("/", HTTP_GET, handleRoot);
  g_cfgServer->on("/save", HTTP_POST, handleSave);
  g_cfgServer->on("/done", HTTP_GET, []() {
    if (g_cfgServer) g_cfgServer->send(200, "text/html", "<h3>配置完成</h3>");
  });
  g_cfgServer->begin();

  Serial.printf("[cfg] 配网页已启动，请连 WiFi eink-mini-setup，浏览器打开 http://%s\n", ip.toString().c_str());

  uint32_t holdSince = 0;
  while (true) {
    if (g_cfgServer) g_cfgServer->handleClient();
    // 按住 B 键 3 秒退出配网
    if (digitalRead(INK_PIN_KEY_B) == LOW) {
      if (holdSince == 0) holdSince = millis();
      else if (millis() - holdSince >= 3000) {
        Serial.println("[cfg] 检测到 B 键长按，退出配网");
        break;
      }
    } else {
      holdSince = 0;
    }
    delay(20);
  }
  exitConfigPortal();
}

void InkNet::exitConfigPortal()
{
  if (g_cfgServer) { g_cfgServer->stop(); delete g_cfgServer; g_cfgServer = nullptr; }
  WiFi.softAPdisconnect(true);
  WiFi.mode(WIFI_STA);
}
