// packet.h — the fixed-size record that flows: GPS fix -> ring buffer -> transport.
// Packed and fixed-size so it can be written at a byte offset in the LittleFS ring file.
#pragma once
#include <stdint.h>

enum PacketStatus : uint8_t {
  SLOT_EMPTY   = 0,  // never written / already sent and reclaimed
  SLOT_PENDING = 1,  // buffered, not yet delivered
  SLOT_SENT    = 2,  // delivered, kept only until overwritten
};

struct __attribute__((packed)) PositionPacket {
  uint32_t epochUtc;       // seconds since Unix epoch, from GPS satellite time
  int32_t  latE6;          // latitude  * 1e6
  int32_t  lonE6;          // longitude * 1e6
  uint16_t speedKnotsX10;  // speed over ground, knots * 10 (Traccar OsmAnd decoder expects knots)
  uint16_t courseX10;      // course/heading, degrees * 10
  uint16_t hdopX100;       // HDOP * 100
  uint8_t  sats;           // satellite count
  uint8_t  status;         // PacketStatus
};

// Days-from-civil-date algorithm (Howard Hinnant), avoids relying on mktime/timegm
// timezone behavior on the ESP32 newlib. Valid for any Gregorian y/m/d.
inline int32_t daysFromCivil(int y, int m, int d) {
  y -= m <= 2;
  const int32_t era = (y >= 0 ? y : y - 399) / 400;
  const uint32_t yoe = (uint32_t)(y - era * 400);
  const uint32_t doy = (153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1;
  const uint32_t doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
  return era * 146097 + (int32_t)doe - 719468;
}

inline uint32_t gpsUtcEpoch(int year, int month, int day, int hour, int minute, int second) {
  int32_t days = daysFromCivil(year, month, day);
  return (uint32_t)days * 86400u + (uint32_t)hour * 3600u + (uint32_t)minute * 60u + (uint32_t)second;
}
