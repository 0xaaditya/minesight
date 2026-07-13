# MineSight — Mining Fleet Monitoring & Anti-Theft Platform

## What this project is

MineSight is a fleet monitoring and anti-theft product for small mining contractors in India (10–50 vehicles: tippers, excavators, loaders, rock drills, diesel bowsers). It catches diesel theft, false trip reporting, and inflated work-hour claims by cross-verifying independent sensors, and gives the owner a live dashboard plus WhatsApp alerts so he no longer has to be physically present on site.

The four product pillars:
1. **Fuel truth** — calibrated fuel level sensing; every fill/drain event with litres, time, place. Drain with engine off = theft alert within ~90 seconds.
2. **Trip truth** — geofenced loading/dumping zones auto-count ore cycles; claimed trips vs verified trips.
3. **Driver truth** — RFID/iButton driver sessions; who drove, hours, driver-wise fuel and trips.
4. **Load truth** — weighbridge reconciliation against trip counts (later phase).

Positioning: the gap between cheap generic telematics (LocoNav/Fleetx, no mining workflow) and enterprise mining FMS (Samarth/MineStar, unaffordable for small contractors). Benchmark UI: Amnex Samarth dashboard (live equipment map with asset IDs, 5-state status taxonomy, route replay, dynamic excavator work-radius zones).

## Current status (update this section as we progress)

- [x] ESP32-S3 + Neo-6M GPS wired; coordinates + SATS + HDOP printing over serial (Arduino IDE)
- [ ] Clean outdoor fix (SATS ≥ 6, HDOP < 2.5) — field test in progress
- [x] Traccar server deployed — Docker via Colima, `docker-compose.yml`, running locally on the laptop (port 8082 web/API, 5055 OsmAnd)
- [x] ESP32 sending positions to Traccar (OsmAnd protocol) — firmware in `firmware/sketch_jul10a/` (config.h, packet.h, ring_buffer.h, transport.h); verified end-to-end incl. store-and-forward (buffered fix delivered ~6 min late after a WiFi gap, fixTime vs serverTime confirmed the ring buffer replay)
- [ ] RFID driver ID integrated
- [ ] Fuel input simulated via potentiometer
- [x] FastAPI processing service — `backend/` (FastAPI + SQLAlchemy + Alembic + Postgres via docker-compose); vehicle registry, webhook ingestion, **zones + trip-cycle engine** (`app/trip_engine.py`, `app/geo.py`) all verified end-to-end incl. anti-flap dwell confirmation, breakdown detect/resume, excavator-pairing hysteresis, and anomalous-entry flagging. Excavator vehicle status (Running/Idle) is derived from whether a truck is currently paired to its loading circle (`trip_engine.excavator_is_paired`), since an excavator's own GPS speed stays ~0 whether it's digging or parked — real fix is ignition sensing (hardware table, not yet built), this is the interim signal, verified against a synthetic pairing scenario. Lead distance per trip (`haul_distance_m` = load→dump, `trip_distance_m` = full trip row) recorded from Traccar's `totalDistance` odometer delta (haversine breadcrumb sum as fallback for positions missing it), verified against a synthetic webhook-driven cycle. Fuel classifier and auth/multi-tenancy enforcement still outstanding (org_id columns exist everywhere but aren't enforced yet — real gap, documented, deferred until a second customer is imminent).
- [x] React dashboard — `frontend/` (Vite + React + TanStack Query + Leaflet/Esri World Imagery); full "Lodestar" app shell implemented from a Claude Design mockup (`frontend/src/layout/Shell.tsx`) — collapsible sidebar nav, header with live IST clock and EN/hi/mr i18n (`frontend/src/i18n/strings.tsx`), Home dashboard (real fleet status counts + fleet wheel/grid donut chart + equipment-in/out-of-zone card, `frontend/src/pages/HomePage.tsx`), Live Map (real Leaflet/Esri map restyled with vehicle list + status filter chips, `frontend/src/pages/MapPage.tsx`), and Vehicles & Devices (registration form + table). Zone drawing (hand-rolled click-to-place polygon editor, not Leaflet.draw) and a shared vehicle detail drawer are wired to real backend data; the drawer shows a trip-phase pill (Loading/Hauling/Dumping/Returning) next to the 5-state status pill — two axes, deliberately separate — plus a today's-trips list (cycle #, IST times, lead distance, anomalous-entry flag), and the Live Map vehicle list shows the active trip phase instead of raw speed. Trip totals, fuel totals, incident counts, and the live events feed have no backend source yet — the Home screen shows these as explicit "not available yet" placeholders rather than fabricated numbers. Route replay is built: drawer's "Replay today" button switches the Live Map into a replay view (`frontend/src/components/ReplayPanel.tsx`) showing that vehicle's full IST-day breadcrumb as a polyline with a play/scrub-able position marker, backed by `/vehicles/{id}/positions?date=` (`backend/app/routers/positions.py`); verified in-browser via Playwright. Excavator drawers show "Trucks filled" + a today's-loads list (which truck, when) instead of trips — backed by `GET /vehicles/{id}/loads`, the excavator-facing view of the trips table — and truck trip rows show which excavator filled them (`load_excavator_asset_id` on TripOut). The zone editor is collapsed behind a "Zones" map button by default and hidden entirely during replay. Fuel curves are still unbuilt (drawer has a disabled "coming soon" button for it).
- [ ] ESP32-CAM snapshot node

Firmware development is currently in **Arduino IDE** (ESP32-S3 Dev Module, USB CDC On Boot = Enabled). Keep all firmware compilable in Arduino IDE — single .ino plus header files, no PlatformIO-only features. Backend/dashboard work starts after device milestones.

## Hardware (prototype)

| Component | Interface | Pins (ESP32-S3) |
|---|---|---|
| Neo-6M GPS module | UART1, 9600 baud | RX=GPIO44, TX=GPIO43 (GPIO18/17 didn't work on this board, moved off) |
| RFID reader (assume MFRC522 unless told otherwise) | SPI | SS=GPIO10, SCK=12, MOSI=11, MISO=13, RST=9 |
| Fuel level (simulated first via potentiometer, real analog sensor later) | ADC | GPIO4, via 10k/20k voltage divider (sensor 0–5V → pin 0–3.3V) |
| Ignition sense (later) | GPIO digital in | GPIO5 |
| ESP32-CAM (separate independent node) | own board, OV2640 + microSD | flashed via FTDI |

Production hardware (do NOT build for it yet, but never block it): Teltonika FMC125 telematics boxes + RS485 LLS fuel sensors + iButton, speaking native Teltonika protocol to the same Traccar server. The DIY node and Teltonika devices must coexist on one platform — this is why we use standard protocols.

## Architecture (locked decisions — do not change without discussion)

```
[GPS/RFID/Fuel] → ESP32-S3 firmware → flash ring buffer → transport (WiFi now, GSM later)
      → Traccar server (OsmAnd HTTP protocol) → webhook → FastAPI processing service
      → PostgreSQL → React dashboard (REST + WebSocket) + WhatsApp/push alerts
[ESP32-CAM] → SD card → bulk HTTP upload when gate WiFi visible → FastAPI → photo store
```

1. **Device protocol: OsmAnd over HTTP.** `GET /?id=<device>&lat=..&lon=..&speed=..&hdop=..&fuel=..&driver=..&ignition=..&batt=..` Never invent a custom protocol. Commercial trackers plug into the same server later with zero code changes.
2. **Traccar** handles ingestion, device registry, raw position storage, basic geofences, route replay API. We do not rebuild what Traccar provides.
3. **FastAPI (Python) service** holds all proprietary logic: trip-cycle state machine, fuel event classifier, driver sessions, dynamic excavator zones, alerts, command queue. Consumes Traccar webhooks/API.
4. **PostgreSQL** (TimescaleDB extension when needed). Photos on disk/S3-compatible store, paths in DB.
5. **Dashboard: React + Leaflet + Esri World Imagery satellite tiles** (free). Leaflet.draw for zone editing. No Google Maps API unless a customer pays for it.
6. **Transport abstraction in firmware:** a single `Transport` interface with `sendPacket()`. WiFi implementation now; SIM800L/SIM7670 (AT commands over UART2) later; the rest of the firmware never knows which is active.

## Firmware rules

- Sample GPS at 1 Hz; SEND on smart trigger: every 30 s OR heading change >15° OR any event (RFID tap, ignition change, fuel jump).
- Every packet is written to a flash ring buffer (LittleFS) FIRST and marked sent only on HTTP 200. On reconnect, replay oldest-first. Store-and-forward is non-negotiable.
- Timestamps come from GPS satellite time (UTC), not the ESP32 clock. Every packet carries its true event time so buffered data lands correctly.
- Quality gate: discard fixes with HDOP > 3 or sats < 5 before buffering.
- Device identity: each node has a device ID + secret token in config, sent with every packet.
- Config lives in one header (`config.h`): pins, WiFi creds, server URL, device ID, intervals. No magic numbers in logic files.
- ESP32-CAM node is fully independent: timestamped JPEGs to SD (`<deviceid>_<utc>.jpg`), scans for the configured "gate" SSID, and when visible, uploads all un-synced photos via HTTP POST then marks them synced. Photo triggers: every N minutes while moving, on request flag from server, on boot.

## Backend rules

- **Process by event timestamp, not arrival time.** Late buffered data must produce correct trips/alerts (alerts fired late are marked "delayed").
- **Multi-tenant from day one:** every table has `org_id`. Roles: owner (edit), supervisor (view/ack), driver (none).
- **Trip engine:** state machine per vehicle: IDLE → (enter LOADING) LOADING → (exit LOADING) HAULING → (enter DUMPING) cycle++ → RETURNING → (enter LOADING) …. Stationary >15 min outside any zone → status BREAKDOWN (cycle pauses, not reset).
- **Vehicle status taxonomy (Samarth-style, 5 states):** Running / Idle / Breakdown / No-comm (installed) / Not-installed. Device silence >10 min while ignition was on → No-comm + tamper-suspect alert.
- **Fuel classifier:** evaluate only when stationary; require 2–3 consecutive falling readings; drain = drop faster than max burn rate (configurable L/min) → theft event with litres, time, location, zone, driver-session context. Rises = fill events; compare fill litres vs bowser/bill later.
- **Dynamic excavator zones:** each excavator's latest position is a circle zone. The engine circle is a tight **fill radius (20 m enter / 40 m sustain)** — truck length (7.5–10 m) + boom reach (~7 m) + combined GPS error of both devices, so only a truck physically alongside the excavator pairs/loads, queuing trucks don't, and attribution stays unambiguous when excavators work close enough that wider circles would overlap. Nearest excavator wins the residual ambiguity. A wider 50 m "work area" ring is display-only on the dashboard. Implemented in FastAPI (haversine), not Traccar.
- **Static zones:** GeoJSON polygons in Postgres, versioned with validity dates; historical reports always use zones as-of that date. Every zone/rule edit goes to an audit log (who, what, when, old→new).
- **Command queue (downlink):** dashboard → FastAPI → pending commands table → device receives commands in the HTTP response to its next upload → executes → ACKs. Commands: set interval, request snapshot, immobilize (relay) — immobilize only executes when speed = 0.
- **Alerts:** WhatsApp Cloud API + web push. Dedup (one event = one alert), escalation to second contact if unacknowledged 10 min, quiet-hours routing: only theft-signature events alert at night; everything else goes to the 7 am daily summary. Daily summary per vehicle: trips, tonnes (when available), engine hours, fuel consumed/filled/drained, discrepancy flags — designed to be read in 30 seconds, Hindi/Marathi-ready strings (i18n from the start).

## Simulator (build early, keep forever)

A Python script that emulates N vehicles speaking OsmAnd: configurable routes between zone polygons, realistic speeds, fuel burn while ignition on, and injectable scenarios: `night_drain`, `fake_trip_attempt`, `short_fill`, `breakdown`, `gps_dropout` (tests buffering). This is our regression suite and sales demo. Every engine feature must be demonstrated against the simulator before hardware.

## Dashboard requirements (v0)

- Live map: vehicle icons with asset-ID labels (S-052 tipper, EX-148 excavator, L-006 loader, BB-589 bowser convention), colored by 5-state status; dynamic excavator circles rendered.
- Vehicle detail: fuel curve (fills green, drains red), today's trips with cycle times, driver session, breadcrumb trail (dotted polyline), route replay with play/scrub (Traccar positions API).
- Zone editor: draw/edit polygons (Leaflet.draw), name + type (LOADING/DUMPING/FUEL/PARKING/NO-GO), versioned saves.
- Fleet view: equipment-type × status count matrix; sunburst wheel view optional later (demo weapon).
- Events feed + alert acknowledgement. Photo timeline per vehicle once CAM node lands.
- Mobile-responsive PWA. No native apps in v0.

## Build phases (work in this order)

- **Phase 1 (now):** firmware — GPS fix quality gate → WiFi OsmAnd upload → flash buffering → RFID tap events → potentiometer "fuel" on ADC. Local Traccar (Docker) on laptop.
- **Phase 2:** simulator + FastAPI engines (trip, fuel, sessions, status) + Postgres schema; prove every engine against simulator scenarios.
- **Phase 3:** React dashboard v0 (map, detail, zones, events) + WhatsApp alerts + daily summary. Move server to VPS.
- **Phase 4:** ESP32-CAM node + photo pipeline + gate-SSID sync.
- **Phase 5 (hardware swap):** SIM800L/SIM7670 GSM transport; then first Teltonika FMC125 + real RS485 fuel sensor on the same Traccar — prototype and production hardware side by side.

## Future plans (design for, don't build yet)

- Teltonika fleet as production device; RS485 LLS fuel sensors with staged-fill calibration tables (volts→litres lookup per tank).
- LoRaWAN dead-zone site kit: LoRa nodes + rim gateway + local site server running the same detection engines offline, syncing to cloud when backhaul exists.
- Weighbridge integration (tonnage per trip reconciled vs cycles), contractor billing reports.
- AIS-140 compliance wedge: state mineral portal integrations (Mahakhanij, Khanij Online), secondary-IP single-box model when we become an approved vendor.
- Mine-gate kit: ANPR + boom barrier + weighbridge automation. Drone stockpile volumetrics (partner).
- Driver scorecards → wage/bonus reports (protect honest drivers; social self-enforcement).

## Conventions

- Firmware: C++ (Arduino framework), readable over clever; every module has a header comment explaining its role. Backend: Python 3.11+, FastAPI, SQLAlchemy, Pydantic; type hints everywhere. Frontend: React + Vite, functional components, TanStack Query.
- All times stored UTC, displayed IST. All money in INR. Vehicle asset-ID convention: `S-` tipper/dumper, `EX-` excavator, `L-` loader, `BB-` bowser, `K-` drill, `CSM-` surface miner.
- Never delete raw positions inside retention window (90 days raw, then 5-min downsample; events/cycles/sessions kept forever — they are legal evidence).
- Secrets in `.env`, never committed. One `docker-compose.yml` runs the whole backend stack locally.
- When something is ambiguous, prefer the choice that keeps DIY and commercial hardware interchangeable.
