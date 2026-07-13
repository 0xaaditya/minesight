// transport.h — Transport interface (CLAUDE.md architecture rule: firmware logic never
// knows which transport is active). OsmAndWifiTransport is the only implementation today;
// a SIM800L/SIM7670 AT-command transport lands in Phase 5 behind the same interface.
#pragma once
#include <WiFi.h>
#include <HTTPClient.h>
#include "packet.h"
#include "config.h"

class Transport {
public:
  virtual ~Transport() {}
  virtual bool isReady() = 0;
  virtual bool sendPacket(const PositionPacket& pkt) = 0;
};

class OsmAndWifiTransport : public Transport {
public:
  void begin() {
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.print("[wifi] connecting");
    uint32_t start = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - start < WIFI_CONNECT_TIMEOUT_MS) {
      delay(250);
      Serial.print(".");
    }
    Serial.println();
    if (WiFi.status() == WL_CONNECTED) {
      Serial.print("[wifi] connected, IP=");
      Serial.println(WiFi.localIP());
    } else {
      Serial.print("[wifi] not connected yet, status=");
      Serial.println(statusString(WiFi.status()));
    }
  }

  bool isReady() override {
    maybeReconnect();
    return WiFi.status() == WL_CONNECTED;
  }

  bool sendPacket(const PositionPacket& pkt) override {
    if (WiFi.status() != WL_CONNECTED) return false;

    HTTPClient http;
    http.setTimeout(HTTP_TIMEOUT_MS);
    http.begin(buildUrl(pkt));
    int code = http.GET();
    http.end();

    if (code == 200) return true;
    Serial.printf("[wifi] upload failed, HTTP %d\n", code);
    return false;
  }

private:
  uint32_t _lastReconnectAttempt = 0;

  void maybeReconnect() {
    wl_status_t status = WiFi.status();
    if (status == WL_CONNECTED) return;
    uint32_t now = millis();
    // Give each attempt the same runway as the initial boot connect (WIFI_CONNECT_TIMEOUT_MS)
    // before trying again — retrying too aggressively can abort an association in progress
    // (especially over a phone hotspot with slower DHCP), which looks identical to a real failure.
    if (now - _lastReconnectAttempt < WIFI_CONNECT_TIMEOUT_MS) return;
    _lastReconnectAttempt = now;
    Serial.print("[wifi] reconnecting... last status=");
    Serial.println(statusString(status));
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  }

  static const char* statusString(wl_status_t status) {
    switch (status) {
      case WL_IDLE_STATUS:     return "IDLE";
      case WL_NO_SSID_AVAIL:   return "NO_SSID_AVAIL (SSID not seen - check name/band)";
      case WL_SCAN_COMPLETED:  return "SCAN_COMPLETED";
      case WL_CONNECTED:       return "CONNECTED";
      case WL_CONNECT_FAILED:  return "CONNECT_FAILED (likely wrong password)";
      case WL_CONNECTION_LOST: return "CONNECTION_LOST";
      case WL_DISCONNECTED:    return "DISCONNECTED";
      default:                 return "UNKNOWN";
    }
  }

  // OsmAnd protocol per CLAUDE.md: GET /?id=..&lat=..&lon=..&speed=..&hdop=..&fuel=..&driver=..&ignition=..&batt=..
  // fuel/driver/ignition/batt omitted until those sensors land later in Phase 1.
  String buildUrl(const PositionPacket& pkt) {
    double lat = pkt.latE6 / 1e6;
    double lon = pkt.lonE6 / 1e6;
    double speedKnots = pkt.speedKnotsX10 / 10.0;
    double course = pkt.courseX10 / 10.0;
    double hdop = pkt.hdopX100 / 100.0;

    String url = "http://";
    url += SERVER_HOST;
    url += ":";
    url += String(SERVER_PORT);
    url += "/?id=" + String(DEVICE_ID);
    url += "&timestamp=" + String(pkt.epochUtc);
    url += "&lat=" + String(lat, 6);
    url += "&lon=" + String(lon, 6);
    url += "&speed=" + String(speedKnots, 1);
    url += "&bearing=" + String(course, 1);
    url += "&hdop=" + String(hdop, 2);
    url += "&sat=" + String(pkt.sats);
    url += "&devicetoken=" + String(DEVICE_TOKEN);
    return url;
  }
};
