// ring_buffer.h — flash-backed FIFO of PositionPacket records on LittleFS.
// Every packet is written here BEFORE any network attempt, and only reclaimed once the
// transport confirms delivery (HTTP 200). head/tail are monotonic counters persisted in
// NVS (Preferences) so a reboot mid-buffer replays exactly where it left off, oldest-first.
#pragma once
#include <LittleFS.h>
#include <Preferences.h>
#include "packet.h"
#include "config.h"

class RingBuffer {
public:
  bool begin() {
    if (!LittleFS.begin(true)) {
      Serial.println("[ring] LittleFS mount failed");
      return false;
    }
    _prefs.begin("ring", false);
    _head = _prefs.getULong("head", 0);
    _tail = _prefs.getULong("tail", 0);

    if (!LittleFS.exists(RING_FILE_PATH)) {
      if (!preallocate()) return false;
    }
    _file = LittleFS.open(RING_FILE_PATH, "r+");
    if (!_file) {
      Serial.println("[ring] failed to open ring file");
      return false;
    }
    Serial.printf("[ring] ready, head=%lu tail=%lu pending=%lu\n",
                  (unsigned long)_head, (unsigned long)_tail, (unsigned long)pendingCount());
    return true;
  }

  uint32_t pendingCount() const { return _head - _tail; }
  bool hasPending() const { return _head > _tail; }

  void push(const PositionPacket& pkt) {
    if (_head - _tail >= RING_CAPACITY) {
      // Buffer is full of un-sent packets (WiFi down for hours). Drop the oldest
      // rather than block ingestion — this is a prototype tradeoff, not a legal-evidence path.
      Serial.println("[ring] buffer full, dropping oldest unsent packet");
      _tail++;
      _prefs.putULong("tail", _tail);
    }
    PositionPacket toWrite = pkt;
    toWrite.status = SLOT_PENDING;
    writeSlot(_head % RING_CAPACITY, toWrite);
    _head++;
    _prefs.putULong("head", _head);
  }

  bool peekOldest(PositionPacket& out) {
    if (!hasPending()) return false;
    return readSlot(_tail % RING_CAPACITY, out);
  }

  void markOldestSent() {
    if (!hasPending()) return;
    _tail++;
    _prefs.putULong("tail", _tail);
  }

private:
  File _file;
  Preferences _prefs;
  uint32_t _head = 0;
  uint32_t _tail = 0;

  bool preallocate() {
    File f = LittleFS.open(RING_FILE_PATH, "w+");
    if (!f) return false;
    PositionPacket empty = {};
    empty.status = SLOT_EMPTY;
    for (uint32_t i = 0; i < RING_CAPACITY; i++) {
      f.write((const uint8_t*)&empty, sizeof(PositionPacket));
    }
    f.close();
    _head = 0;
    _tail = 0;
    _prefs.putULong("head", 0);
    _prefs.putULong("tail", 0);
    return true;
  }

  void writeSlot(uint32_t index, const PositionPacket& pkt) {
    _file.seek((uint32_t)(index * sizeof(PositionPacket)));
    _file.write((const uint8_t*)&pkt, sizeof(PositionPacket));
    _file.flush();
  }

  bool readSlot(uint32_t index, PositionPacket& out) {
    _file.seek((uint32_t)(index * sizeof(PositionPacket)));
    size_t n = _file.read((uint8_t*)&out, sizeof(PositionPacket));
    return n == sizeof(PositionPacket);
  }
};
