# MineSight

Fleet monitoring and anti-theft platform for small mining contractors in India
(10–50 vehicles: tippers, excavators, loaders, rock drills, diesel bowsers). It
catches diesel theft, false trip reporting, and inflated work-hour claims by
cross-verifying independent sensors, and gives the owner a live dashboard plus
alerts so he no longer has to be physically present on site.

Four product pillars: **fuel truth** (calibrated fuel sensing, theft alerts),
**trip truth** (geofenced load/dump cycle counting), **driver truth**
(RFID/iButton sessions), **load truth** (weighbridge reconciliation, later
phase).

## Architecture

```
[GPS/RFID/Fuel] → ESP32-S3 firmware → flash ring buffer → WiFi (GSM later)
      → Traccar server (OsmAnd HTTP protocol) → webhook → FastAPI service
      → PostgreSQL → React dashboard (REST) + WhatsApp/push alerts (planned)
[ESP32-CAM] → SD card → bulk HTTP upload when gate WiFi visible → FastAPI (planned)
```

- **Devices** speak the OsmAnd HTTP protocol (never a custom one) so
  commercial trackers (Teltonika, etc.) can plug into the same server later
  with zero code changes.
- **Traccar** handles device registry, raw position ingestion, and forwards
  positions to the backend via webhook.
- **FastAPI backend** (`backend/`) owns all proprietary logic: trip-cycle
  state machine, zones, excavator pairing, events/alerts. Postgres via
  SQLAlchemy + Alembic.
- **React dashboard** (`frontend/`) — live map, vehicle detail, zone editor,
  events feed.
- **Simulator** (`simulator/`) — emulates a fleet over the real OsmAnd
  protocol against a real local Traccar + backend stack; the project's
  regression suite and sales demo.

## Repo layout

| Path | What |
|---|---|
| `firmware/sketch_jul10a/` | ESP32-S3 Arduino sketch (GPS, ring buffer, transport) |
| `backend/` | FastAPI + SQLAlchemy + Alembic processing service |
| `frontend/` | React + Vite + Leaflet dashboard ("Lodestar") |
| `simulator/` | Fleet simulator + sweep/eval harness for regression testing |
| `traccar/` | Traccar server config (`traccar.xml`) |
| `docker-compose.yml` | Postgres + Traccar + backend, for local dev |

## Running the backend stack locally

Requires Docker (Colima is fine on macOS).

```bash
# create .env in the repo root with:
#   TRACCAR_API_USER=<traccar admin email>
#   TRACCAR_API_PASSWORD=<traccar admin password>
# (used for device auto-registration; leave unset and it's just skipped)
docker compose up -d   # postgres, traccar, backend
```

- Backend API: `http://localhost:8000`
- Traccar web UI / REST API: `http://localhost:8082`
- Traccar OsmAnd ingest (device endpoint): `http://localhost:5055`

Migrations run against Postgres via Alembic (`backend/alembic/`). To run them
manually inside the backend container or a local venv:

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/alembic upgrade head
```

## Running the frontend

```bash
cd frontend
npm install
npm run dev       # Vite dev server
npm run build     # type-check + production build
npm run lint       # oxlint
```

Points at the backend on `http://localhost:8000` by default.

## Running the simulator

Bring up `docker compose up -d` first, then:

```bash
cd simulator
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

.venv/bin/python3 -m simulator.cli run --vehicles 10 --hours 8 --seed 42 \
  --date 2026-07-17 --shift-start-ist 06:00 --pace fast

.venv/bin/python3 -m simulator.cli eval --run-id <printed_run_id>
cat runs/<run_id>/report.md
```

See [simulator/README.md](simulator/README.md) for the sweep harness, known
findings, and open issues (notably an intermittently unreliable Traccar
forward-relay in this Docker Compose setup — always sanity-check a run's
Positions before trusting its numbers).

## Firmware

Developed in Arduino IDE (ESP32-S3 Dev Module, USB CDC On Boot = Enabled) —
kept as a single `.ino` + headers, no PlatformIO-only features. See
`firmware/sketch_jul10a/config.example.h` for the config template (WiFi
creds, server URL, device ID — copy to `config.h`, which is gitignored).

