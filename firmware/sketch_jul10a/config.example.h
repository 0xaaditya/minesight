// config.example.h — copy this to config.h and fill in real values.
// config.h itself is gitignored since it holds WiFi credentials + device token.
#pragma once

// ---- Device identity (sent with every packet) ----
#define DEVICE_ID     "S-052"          // asset-ID convention from CLAUDE.md, e.g. S-052 tipper
#define DEVICE_TOKEN  "changeme-shared-secret"  // shared secret, checked later by FastAPI

// ---- WiFi ----
#define WIFI_SSID     "YOUR_WIFI_SSID"
#define WIFI_PASSWORD "YOUR_WIFI_PASSWORD"
#define WIFI_CONNECT_TIMEOUT_MS 15000

// ---- Traccar server (OsmAnd protocol) ----
#define SERVER_HOST   "YOUR_SERVER_HOST"
#define SERVER_PORT   5055
#define HTTP_TIMEOUT_MS 8000

// ---- GPS UART (verified on this board: GPIO18/17 didn't work, moved to 44/43) ----
#define GPS_RX_PIN 44   // ESP32 RX <- GPS TX
#define GPS_TX_PIN 43   // ESP32 TX -> GPS RX
#define GPS_BAUD   9600

// ---- Quality gate (CLAUDE.md: discard fixes with HDOP > 3 or sats < 5 before buffering) ----
#define MIN_SATELLITES   5
#define MAX_HDOP_X100    300   // HDOP * 100, i.e. 3.00

// ---- Smart send trigger ----
#define SEND_INTERVAL_MS      30000  // every 30s
#define HEADING_CHANGE_DEG    15.0   // OR heading change > 15 degrees

// ---- Moving-average smoothing (position noise filter, independent of ring buffer) ----
#define AVG_SAMPLES 10

// ---- Flash ring buffer (LittleFS) ----
#define RING_FILE_PATH   "/ring.dat"
#define RING_CAPACITY    500   // ~4 hours of packets at one every 30s
#define RING_FLUSH_INTERVAL_MS 2000  // how often we try to drain pending packets over WiFi
