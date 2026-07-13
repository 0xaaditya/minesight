// sketch_jul10a.ino — MineSight prototype node: GPS read -> quality gate -> smart trigger
// -> flash ring buffer (LittleFS) -> WiFi/OsmAnd upload to Traccar.
// Phase 1 (CLAUDE.md): RFID/fuel/ignition are not wired yet; hooks are left for them below.
#include <HardwareSerial.h>
#include <TinyGPS++.h>
#include <math.h>
#include "config.h"
#include "packet.h"
#include "ring_buffer.h"
#include "transport.h"

TinyGPSPlus gps;
HardwareSerial gpsSerial(1);
RingBuffer ring;
OsmAndWifiTransport transport;

// Moving average buffer to keep position noise down, independent of the ring buffer.
double latBuffer[AVG_SAMPLES] = {0.0};
double lngBuffer[AVG_SAMPLES] = {0.0};
int bufferIndex = 0;
bool bufferFull = false;

// Smart-trigger state
uint32_t lastSendMs = 0;
double lastCourseDeg = -1;
bool firstPacketSent = false;

void setup() {
  Serial.begin(115200);
  gpsSerial.begin(GPS_BAUD, SERIAL_8N1, GPS_RX_PIN, GPS_TX_PIN);

  Serial.println("=========================================");
  Serial.println("  MineSight node starting: " DEVICE_ID);
  Serial.println("=========================================");

  if (!ring.begin()) {
    Serial.println("[fatal] ring buffer init failed, halting");
    while (true) delay(1000);
  }
  transport.begin();

  Serial.println("Step into open ground and watch satellite count grow...");
}

void loop() {
  while (gpsSerial.available() > 0) {
    if (gps.encode(gpsSerial.read())) {
      processGPSData();
    }
  }
  flushRingBuffer();
}

void processGPSData() {
  float hdopValue = gps.hdop.value() / 100.0;
  int totalSatellites = gps.satellites.value();

  if (!gps.location.isValid()) {
    Serial.print("Acquiring high precision fix... Connected Satellites: ");
    Serial.println(totalSatellites);
    return;
  }

  // Quality gate (CLAUDE.md): discard fixes with HDOP > 3 or sats < 5 before buffering.
  if (hdopValue > 3.0 || totalSatellites < MIN_SATELLITES) {
    Serial.print("Fix below quality gate (sats=");
    Serial.print(totalSatellites);
    Serial.print(", hdop=");
    Serial.print(hdopValue);
    Serial.println(") - not buffered");
    return;
  }

  // Smooth out jumping reflections using rolling average array.
  latBuffer[bufferIndex] = gps.location.lat();
  lngBuffer[bufferIndex] = gps.location.lng();
  bufferIndex++;
  if (bufferIndex >= AVG_SAMPLES) {
    bufferIndex = 0;
    bufferFull = true;
  }

  int samplesToCount = bufferFull ? AVG_SAMPLES : bufferIndex;
  double latSum = 0, lngSum = 0;
  for (int i = 0; i < samplesToCount; i++) {
    latSum += latBuffer[i];
    lngSum += lngBuffer[i];
  }
  double refinedLat = latSum / samplesToCount;
  double refinedLng = lngSum / samplesToCount;

  Serial.println("\n--- TRACKING TARGET LOCKED ---");
  Serial.print("Coordinates: ");
  Serial.print(refinedLat, 6);
  Serial.print(", ");
  Serial.println(refinedLng, 6);
  Serial.print("Satellites: "); Serial.println(totalSatellites);
  Serial.print("HDOP: "); Serial.println(hdopValue);

  if (gps.time.isValid() && gps.date.isValid()) {
    int localHour = gps.time.hour() + 5;
    int localMinute = gps.time.minute() + 30;
    if (localMinute >= 60) { localMinute -= 60; localHour += 1; }
    if (localHour >= 24) { localHour -= 24; }
    Serial.print("Local Time (IST): ");
    if (localHour < 10) Serial.print("0"); Serial.print(localHour); Serial.print(":");
    if (localMinute < 10) Serial.print("0"); Serial.print(localMinute); Serial.print(":");
    if (gps.time.second() < 10) Serial.print("0"); Serial.println(gps.time.second());
  }
  Serial.println("------------------------------");

  evaluateSmartTrigger(refinedLat, refinedLng, hdopValue, totalSatellites);
}

void evaluateSmartTrigger(double refinedLat, double refinedLng, float hdopValue, int totalSatellites) {
  if (!gps.date.isValid() || !gps.time.isValid()) return;  // need a real UTC timestamp to buffer

  uint32_t now = millis();
  bool shouldSend = !firstPacketSent || (now - lastSendMs >= SEND_INTERVAL_MS);

  double courseDeg = gps.course.isValid() ? gps.course.deg() : -1;
  if (lastCourseDeg >= 0 && courseDeg >= 0) {
    double delta = fabs(courseDeg - lastCourseDeg);
    if (delta > 180) delta = 360 - delta;
    if (delta > HEADING_CHANGE_DEG) shouldSend = true;
  }
  // TODO: OR any event (RFID tap, ignition change, fuel jump) — wired once those sensors land.

  if (!shouldSend) return;

  PositionPacket pkt = {};
  pkt.epochUtc = gpsUtcEpoch(gps.date.year(), gps.date.month(), gps.date.day(),
                             gps.time.hour(), gps.time.minute(), gps.time.second());
  pkt.latE6 = (int32_t)(refinedLat * 1e6);
  pkt.lonE6 = (int32_t)(refinedLng * 1e6);
  pkt.speedKnotsX10 = (uint16_t)(gps.speed.knots() * 10);
  pkt.courseX10 = (uint16_t)((courseDeg >= 0 ? courseDeg : 0) * 10);
  pkt.hdopX100 = (uint16_t)(hdopValue * 100);
  pkt.sats = (uint8_t)totalSatellites;

  ring.push(pkt);
  lastSendMs = now;
  if (courseDeg >= 0) lastCourseDeg = courseDeg;
  firstPacketSent = true;

  Serial.printf("[buffer] packet queued (epoch=%lu), pending=%lu\n",
                (unsigned long)pkt.epochUtc, (unsigned long)ring.pendingCount());
}

void flushRingBuffer() {
  static uint32_t lastFlush = 0;
  uint32_t now = millis();
  if (now - lastFlush < RING_FLUSH_INTERVAL_MS) return;
  lastFlush = now;

  if (!transport.isReady()) return;

  const int MAX_PER_CYCLE = 5;  // cap per loop so we don't block GPS reads for long
  int sent = 0;
  PositionPacket pkt;
  while (sent < MAX_PER_CYCLE && ring.peekOldest(pkt)) {
    if (!transport.sendPacket(pkt)) {
      Serial.println("[ring] send failed, will retry next cycle");
      break;
    }
    ring.markOldestSent();
    sent++;
  }
  if (sent > 0) {
    Serial.printf("[ring] flushed %d packet(s), %lu pending\n", sent, (unsigned long)ring.pendingCount());
  }
}
