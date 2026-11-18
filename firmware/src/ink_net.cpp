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
    // HTTPClient 默认不收集响应头。不声明要哪个头，http.header() 永远
    // 返回空串 —— 下面这条兜底校时路径从来没生效过。
    const char* hdrKeys[] = {"Date"};
    http.collectHeaders(hdrKeys, 1);
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
//
// 配网页能扫周围的 2.4GHz 热点直接选，不用手打名字。
//
// 为什么值得做：ESP32-C3 只有 2.4GHz 射频。手打名字有两个坑 ——
// 大小写/空格打错，以及打了一个 5GHz 的名字（扫不到、连不上，
// 现象是"一直转圈"）。扫出来的天然全是 C3 能连的。
//
// 手输框保留：隐藏 SSID 扫不到，只能手打。

// 扫到的热点缓存成 <option> 列表，渲染 / 时拼进 HTML。
static String g_wifiOptionsHtml = "";

// SSID 可能带引号、& 等字符，直接塞进 HTML 属性会把页面结构冲掉。
static String htmlEscape(const char* s)
{
  String out;
  if (!s) return out;
  for (const char* p = s; *p; p++) {
    switch (*p) {
      case '&':  out += "&amp;";  break;
      case '"':  out += "&quot;"; break;
      case '\'': out += "&#39;";  break;
      case '<':  out += "&lt;";   break;
      case '>':  out += "&gt;";   break;
      default:   out += *p;       break;
    }
  }
  return out;
}

// 扫一遍周围热点，生成下拉列表。
//
// 同名 SSID 去重（Mesh 组网一个名字能扫出好几条），留信号最强的。
// 读完必须 scanDelete()，否则扫描缓存一直占着堆。
static void scanWifiOptions()
{
  Serial.println("[cfg] 正在扫描周围 2.4GHz WiFi ...");
  g_wifiOptionsHtml = "";
  int n = WiFi.scanNetworks(false, false);
  if (n <= 0) {
    WiFi.scanDelete();
    Serial.println("[cfg] 没扫到热点，可手输");
    return;
  }

  // 按信号强度降序。扫到的数量不封顶，但只取前 32 个 ——
  // 弱信号那几十个用户不会选，塞进页面只会让它变长。
  int idx[32];
  int cnt = (n > 32) ? 32 : n;
  for (int i = 0; i < cnt; i++) idx[i] = i;
  for (int i = 0; i < cnt - 1; i++) {
    for (int j = i + 1; j < cnt; j++) {
      if (WiFi.RSSI(idx[j]) > WiFi.RSSI(idx[i])) {
        int t = idx[i]; idx[i] = idx[j]; idx[j] = t;
      }
    }
  }

  // 去重：同名只留第一条 —— 上面已按 RSSI 降序，第一条就是最强的。
  String seen[32];
  int seenCnt = 0;
  for (int i = 0; i < cnt; i++) {
    String s = WiFi.SSID(idx[i]);
    if (s.length() == 0) continue;
    bool dup = false;
    for (int k = 0; k < seenCnt; k++) {
      if (seen[k] == s) { dup = true; break; }
    }
    if (dup) continue;
    seen[seenCnt++] = s;

    String esc = htmlEscape(s.c_str());
    String sel = (s == String(g_cfgSsid)) ? " selected" : "";
    g_wifiOptionsHtml += "<option value='" + esc + "'" + sel + ">" +
                         esc + " (" + String(WiFi.RSSI(idx[i])) + "dBm)</option>";
  }
  WiFi.scanDelete();
  Serial.printf("[cfg] 扫描完成，共 %d 个可用热点\n", seenCnt);
}

static void handleRoot()
{
  String curSsid = htmlEscape(g_cfgSsid);
  String curPass = htmlEscape(g_cfgPass);
  String curHost = htmlEscape(g_cfgHost);
  String curBase = htmlEscape(g_cfgBase);

  // 当前 SSID 单独一行显示，**不放进手输框的 value**。
  //
  // 放 value 的话手输框永远非空，保存时手输值会盖掉下拉框的选择 ——
  // 下拉框等于废了。手输框留空，用户想改就自己动手。
  String curLabel = "";
  if (String(g_cfgSsid).length() > 0) {
    curLabel = "<label>当前 WiFi：" + curSsid + "</label>";
  }

  String html =
    "<!doctype html><meta charset='utf-8'>"
    "<meta name='viewport' content='width=device-width,initial-scale=1'>"
    "<title>eink-mini setup</title>"
    "<style>body{font-family:sans-serif;max-width:420px;margin:24px auto;padding:0 14px}"
    "input,select,button{width:100%;padding:10px;margin:6px 0 12px;box-sizing:border-box;font-size:15px}"
    "label{font-size:13px;color:#444;display:block}"
    "a.btn{float:right;font-size:12px;color:#06c;text-decoration:none}</style>"
    "<h3>eink-mini 配网</h3>"
    "<form action='/save' method='POST'>"
    "<label>选择 WiFi（仅 2.4GHz）<a class='btn' href='/rescan'>重新扫描</a></label>"
    "<select name='ssid_sel'><option value=''>-- 请选择或下方手动输入 --</option>" + g_wifiOptionsHtml + "</select>"
    + curLabel +
    "<label>或手动输入 WiFi 名称（填了以手输为准）</label>"
    "<input name='ssid_manual' placeholder='隐藏网络可在此手输' value=''>"
    "<label>WiFi 密码</label><input name='pass' type='password' value='" + curPass + "'>"
    "<label>服务器域名</label><input name='host' value='" + curHost + "'>"
    "<label>服务路径前缀</label><input name='base' value='" + curBase + "'>"
    "<button type='submit'>保存并重启</button>"
    "</form>";
  g_cfgServer->send(200, "text/html", html);
}

static void handleRescan()
{
  scanWifiOptions();
  g_cfgServer->sendHeader("Location", "/", true);
  g_cfgServer->send(302, "text/plain", "");
}

static void handleSave()
{
  // 手输优先：填了就以手输为准；没填才用下拉框选的。
  //
  // 手输框默认留空 —— 预填当前 SSID 会让下拉框的选择永远被盖掉。
  String chosen = "";
  if (g_cfgServer->hasArg("ssid_manual")) chosen = g_cfgServer->arg("ssid_manual");
  chosen.trim();
  if (chosen.length() == 0 && g_cfgServer->hasArg("ssid_sel")) {
    chosen = g_cfgServer->arg("ssid_sel");
  }
  chosen.trim();

  // 两处都没选：保留原 SSID，别把配置洗成空。
  if (chosen.length() > 0) copyStr(g_cfgSsid, sizeof(g_cfgSsid), chosen);

  if (g_cfgServer->hasArg("pass")) copyStr(g_cfgPass, sizeof(g_cfgPass), g_cfgServer->arg("pass"));
  if (g_cfgServer->hasArg("host")) copyStr(g_cfgHost, sizeof(g_cfgHost), g_cfgServer->arg("host"));
  if (g_cfgServer->hasArg("base")) copyStr(g_cfgBase, sizeof(g_cfgBase), g_cfgServer->arg("base"));

  // 落盘，重启后生效
  nvsSetStr("ssid", g_cfgSsid);
  nvsSetStr("pass", g_cfgPass);
  nvsSetStr("host", g_cfgHost);
  nvsSetStr("base", g_cfgBase);

  g_cfgServer->send(200, "text/html", "<!doctype html><meta charset='utf-8'><h3>已保存，正在重启...</h3>");
  delay(800);
  ESP.restart();
}

void InkNet::runConfigPortal()
{
  // 回填当前已保存的配置。
  //
  // 原来只拷了 ssid/pass，host/base 没拷 —— 打开配网页时域名和路径框
  // 是空的。用户不知道该填什么，填错一个字符就连不上自己的服务器。
  copyStr(g_cfgSsid, sizeof(g_cfgSsid), ssid_);
  copyStr(g_cfgPass, sizeof(g_cfgPass), pass_);
  copyStr(g_cfgHost, sizeof(g_cfgHost), host_);
  copyStr(g_cfgBase, sizeof(g_cfgBase), base_);

  // WIFI_AP_STA 而不是 WIFI_AP：双模才能边开热点边扫描。
  //
  // WIFI_AP 模式下射频被 SoftAP 占着，scanNetworks() 扫不到东西。
  // 双模下扫到的天然全是 2.4GHz —— C3 的射频只支持 2.4G，
  // 5GHz 热点根本不会被扫出来，也就不存在"连不上的 5G"。
  WiFi.mode(WIFI_AP_STA);
  // 先起热点再扫：扫描要几秒，起早了用户就能先连上等着。
  WiFi.softAP("eink-mini-setup");
  IPAddress ip = WiFi.softAPIP();
  scanWifiOptions();

  if (!g_cfgServer) g_cfgServer = new WebServer(80);
  g_cfgServer->on("/", HTTP_GET, handleRoot);
  g_cfgServer->on("/rescan", HTTP_GET, handleRescan);
  g_cfgServer->on("/save", HTTP_POST, handleSave);
  g_cfgServer->on("/done", HTTP_GET, []() {
    if (g_cfgServer) g_cfgServer->send(200, "text/html", "<!doctype html><meta charset='utf-8'><h3>配置完成</h3>");
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
