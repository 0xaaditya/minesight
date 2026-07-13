import { Fragment, useEffect, useState, type Dispatch, type SetStateAction } from 'react'
import L from 'leaflet'
import {
  Circle,
  MapContainer,
  Marker,
  Polygon,
  Polyline,
  TileLayer,
  Tooltip,
  useMap,
  useMapEvents,
  ZoomControl,
} from 'react-leaflet'
import { Hexagon, X } from 'lucide-react'
import type { Position, Vehicle, VehicleStatus, VehicleType, Zone, ZoneType } from '../api/client'
import { useCreateZone, useDeleteZone, useUpdateZone, useZones } from '../api/client'
import { statusMeta, ZONE_META } from '../lib/status'
import { useT } from '../i18n/strings'

const REPLAY_TRAIL_COLOR = '#2563EB'
const REPLAY_MARKER_COLOR = '#2563EB'

// No Google Maps API per CLAUDE.md — Esri World Imagery (free) is the locked choice.
const ESRI_WORLD_IMAGERY =
  'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'

const DEFAULT_CENTER: [number, number] = [18.6129, 73.7433] // falls back near the field-test site

// Mirrors EXCAVATOR_ENTER_RADIUS_M in backend/app/trip_engine.py — a truck inside this
// tight circle is physically alongside the excavator being filled (truck length + boom
// reach + GPS error), and gets paired to it. This is the circle that drives the engine.
const EXCAVATOR_FILL_RADIUS_M = 20
// Display-only outer ring (Samarth-style "work radius") giving the operator a visual
// sense of the bench area; the backend does nothing with this distance.
const EXCAVATOR_WORK_AREA_M = 50
const EXCAVATOR_CIRCLE_COLOR = '#1abc9c'

// LOADING is deliberately not offered here — an excavator vehicle's own live position
// already creates a moving loading circle automatically (trip_engine.py:
// EXCAVATOR_ENTER_RADIUS_M), which is strictly better since excavators reposition as they
// dig. A drawn static polygon for loading doesn't reflect real operations. ZoneType.LOADING
// still exists in the backend/data model, just not exposed as a choice here.
const ZONE_TYPE_OPTIONS: { value: ZoneType; label: string }[] = [
  { value: 'dumping', label: 'Dumping' },
  { value: 'parking', label: 'Parking' },
  { value: 'no_go', label: 'No-Go' },
]

// Simple silhouettes distinguishing equipment shape (Samarth-style), 24x18 viewBox.
// Not a literal render of each machine — just enough shape difference (arm+bucket vs
// box-on-wheels vs mast vs tank) to tell types apart at map scale.
const VEHICLE_TYPE_SHAPES: Record<VehicleType, string> = {
  excavator:
    '<circle cx="9" cy="12" r="5"/><rect x="8.5" y="2" width="2.5" height="11" transform="rotate(35 9 12)"/><polygon points="19,3 23,5 20,9 16,7"/>',
  loader:
    '<rect x="3" y="7" width="12" height="6" rx="1"/><polygon points="15,6 21,3 21,13 15,13"/><circle cx="6.5" cy="15" r="2.3"/><circle cx="12.5" cy="15" r="2.3"/>',
  bowser:
    '<rect x="1" y="6" width="19" height="7" rx="3.5"/><circle cx="6" cy="15" r="2.3"/><circle cx="16" cy="15" r="2.3"/>',
  drill:
    '<rect x="9.5" y="1" width="3" height="12"/><rect x="4" y="12" width="14" height="4" rx="1"/><circle cx="7" cy="17.5" r="1.8"/><circle cx="15" cy="17.5" r="1.8"/>',
  surface_miner:
    '<rect x="1" y="6" width="20" height="6" rx="1"/><circle cx="5" cy="14.5" r="2.2"/><circle cx="11" cy="14.5" r="2.2"/><circle cx="17" cy="14.5" r="2.2"/>',
  tipper:
    '<rect x="1" y="5" width="13" height="8" rx="1"/><polygon points="14,7 20,7 22,10 22,13 14,13"/><circle cx="5.5" cy="15.5" r="2.3"/><circle cx="18" cy="15.5" r="2.3"/>',
}

function vehicleIcon(assetId: string, vehicleType: VehicleType, status: VehicleStatus | null): L.DivIcon {
  const color = statusMeta(status).color
  const shape = VEHICLE_TYPE_SHAPES[vehicleType]
  return L.divIcon({
    className: 'vehicle-marker',
    html: `
      <div class="vehicle-marker-icon">
        <svg viewBox="0 0 24 18" width="30" height="23" fill="${color}" stroke="#1a1a1a" stroke-width="0.75">${shape}</svg>
        <span class="vehicle-marker-label">${assetId}</span>
      </div>
    `,
    iconSize: [30, 23],
    iconAnchor: [15, 11],
  })
}

function replayIcon(assetId: string, vehicleType: VehicleType): L.DivIcon {
  const shape = VEHICLE_TYPE_SHAPES[vehicleType]
  return L.divIcon({
    className: 'vehicle-marker',
    html: `
      <div class="vehicle-marker-icon">
        <svg viewBox="0 0 24 18" width="30" height="23" fill="${REPLAY_MARKER_COLOR}" stroke="#1a1a1a" stroke-width="0.75">${shape}</svg>
        <span class="vehicle-marker-label">${assetId}</span>
      </div>
    `,
    iconSize: [30, 23],
    iconAnchor: [15, 11],
  })
}

// Recenters the map on the route once per (vehicle, day) — not on every scrub step,
// or the user's own pan/zoom while scrubbing would get fought on each slider tick.
function FitRouteBounds({ positions }: { positions: Position[] }) {
  const map = useMap()
  useEffect(() => {
    if (positions.length === 0) return
    const bounds = L.latLngBounds(positions.map((p) => [p.latitude, p.longitude] as [number, number]))
    map.fitBounds(bounds, { padding: [40, 40] })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [positions.length > 0 ? positions[0].id : null, positions.length])
  return null
}

const CLOSE_RING_PIXEL_THRESHOLD = 12

// Clicking back near the first vertex closes the ring, same convention as most polygon
// drawing tools (geojson.io, Leaflet.draw) — avoids double-click's timing quirks (a
// native dblclick fires two click events first, which would silently add a stray point).
function DrawClickCapture({
  points,
  onPoint,
  onClose,
}: {
  points: [number, number][]
  onPoint: (point: [number, number]) => void
  onClose: () => void
}) {
  const map = useMapEvents({
    click(e) {
      if (points.length >= 3) {
        const clickPx = map.latLngToContainerPoint(e.latlng)
        const firstPx = map.latLngToContainerPoint(points[0])
        if (clickPx.distanceTo(firstPx) < CLOSE_RING_PIXEL_THRESHOLD) {
          onClose()
          return
        }
      }
      onPoint([e.latlng.lat, e.latlng.lng])
    },
  })
  return null
}

const vertexIcon = L.divIcon({ className: 'zone-vertex-marker', iconSize: [14, 14], iconAnchor: [7, 7] })
const firstVertexIcon = L.divIcon({
  className: 'zone-vertex-marker zone-vertex-marker-first',
  iconSize: [16, 16],
  iconAnchor: [8, 8],
})

function DraggableVertex({
  index,
  position,
  onMove,
}: {
  index: number
  position: [number, number]
  onMove: (index: number, position: [number, number]) => void
}) {
  return (
    <Marker
      position={position}
      icon={index === 0 ? firstVertexIcon : vertexIcon}
      draggable
      eventHandlers={{
        dragend: (e) => {
          const { lat, lng } = (e.target as L.Marker).getLatLng()
          onMove(index, [lat, lng])
        },
      }}
    />
  )
}

function toGeoJSONPolygon(points: [number, number][]): Zone['geometry'] {
  const ring = points.map(([lat, lon]) => [lon, lat])
  ring.push(ring[0]) // GeoJSON rings close on themselves — first point repeated as last.
  return { type: 'Polygon', coordinates: [ring] }
}

type DrawState =
  | { mode: 'idle' }
  | { mode: 'drawing'; editingZone: Zone | null; points: [number, number][]; formOpen: boolean }

function ZoneEditorPanel({
  zones,
  draw,
  setDraw,
}: {
  zones: Zone[]
  draw: DrawState
  setDraw: Dispatch<SetStateAction<DrawState>>
}) {
  const T = useT()
  // Collapsed by default — the zone list/editor is an occasional admin task, not
  // something worth permanently covering map area with (user feedback).
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [zoneType, setZoneType] = useState<ZoneType>('dumping')
  const createZone = useCreateZone()
  const updateZone = useUpdateZone()
  const deleteZone = useDeleteZone()

  const startNew = () => {
    setDraw({ mode: 'drawing', editingZone: null, points: [], formOpen: false })
    setName('')
    setZoneType('dumping')
  }

  const startRedraw = (zone: Zone) => {
    setDraw({ mode: 'drawing', editingZone: zone, points: [], formOpen: false })
    setName(zone.name)
    setZoneType(zone.zone_type)
  }

  const cancel = () => {
    setDraw({ mode: 'idle' })
    createZone.reset()
    updateZone.reset()
  }

  if (draw.mode === 'idle' && !open) {
    return (
      <button className="zone-editor-toggle" onClick={() => setOpen(true)}>
        <Hexagon size={14} />
        {T('drawZones')}
      </button>
    )
  }

  if (draw.mode === 'idle') {
    return (
      <div className="zone-editor-panel">
        <div className="zone-editor-head">
          <button onClick={startNew}>+ New zone</button>
          <button className="zone-editor-close" onClick={() => setOpen(false)} aria-label="Close zones panel">
            <X size={15} />
          </button>
        </div>
        <ul className="zone-editor-list">
          {zones.map((zone) => (
            <li key={zone.id}>
              <span style={{ color: ZONE_META[zone.zone_type].color }}>●</span> {zone.name}{' '}
              <span className="zone-editor-type">({zone.zone_type})</span>
              <div className="zone-editor-row-actions">
                <button onClick={() => startRedraw(zone)}>Redraw</button>
                <button
                  className="zone-editor-delete"
                  disabled={deleteZone.isPending && deleteZone.variables === zone.zone_key}
                  onClick={() => {
                    if (confirm(`Delete "${zone.name}"? It'll stop counting for new loading/dumping detection.`)) {
                      deleteZone.mutate(zone.zone_key)
                    }
                  }}
                >
                  ✕
                </button>
              </div>
            </li>
          ))}
        </ul>
        {deleteZone.isError && <p className="error">{(deleteZone.error as Error).message}</p>}
      </div>
    )
  }

  const { editingZone, points, formOpen } = draw
  const isSaving = createZone.isPending || updateZone.isPending
  const saveError = (createZone.error as Error | null)?.message ?? (updateZone.error as Error | null)?.message

  const submit = () => {
    const geometry = toGeoJSONPolygon(points)
    const onSuccess = () => setDraw({ mode: 'idle' })
    if (editingZone) {
      updateZone.mutate({ zoneKey: editingZone.zone_key, name, zone_type: zoneType, geometry }, { onSuccess })
    } else {
      createZone.mutate({ name, zone_type: zoneType, geometry }, { onSuccess })
    }
  }

  return (
    <div className="zone-editor-panel">
      {!formOpen ? (
        <>
          <p>
            {editingZone ? `Redrawing "${editingZone.name}"` : 'New zone'} — click the map to place points (
            {points.length} placed, need ≥3). Drag a point to nudge it, or click back on the red first point
            to close the shape.
          </p>
          <div className="zone-editor-actions">
            <button
              onClick={() => setDraw({ ...draw, points: points.slice(0, -1) })}
              disabled={points.length === 0}
            >
              Undo point
            </button>
            <button
              onClick={() => setDraw({ ...draw, formOpen: true })}
              disabled={points.length < 3}
            >
              Finish
            </button>
            <button onClick={cancel}>Cancel</button>
          </div>
        </>
      ) : (
        <form
          onSubmit={(e) => {
            e.preventDefault()
            submit()
          }}
        >
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Zone name"
            required
            autoFocus
          />
          <select value={zoneType} onChange={(e) => setZoneType(e.target.value as ZoneType)}>
            {ZONE_TYPE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <div className="zone-editor-actions">
            <button type="submit" disabled={isSaving}>
              {isSaving ? 'Saving…' : 'Save'}
            </button>
            <button type="button" onClick={cancel}>
              Cancel
            </button>
          </div>
          {saveError && <p className="error">{saveError}</p>}
        </form>
      )}
    </div>
  )
}

export function LiveMap({
  vehicles,
  onSelectVehicle,
  replay,
}: {
  vehicles: Vehicle[]
  onSelectVehicle: (vehicleId: string) => void
  replay?: { vehicle: Vehicle; positions: Position[]; index: number } | null
}) {
  const { data: zones } = useZones()
  const [draw, setDraw] = useState<DrawState>({ mode: 'idle' })

  const withPosition = vehicles.filter((v) => v.latest_position !== null)
  const center: [number, number] = withPosition.length
    ? [withPosition[0].latest_position!.latitude, withPosition[0].latest_position!.longitude]
    : DEFAULT_CENTER

  return (
    <div className="live-map-wrapper">
      <MapContainer center={center} zoom={17} style={{ height: '100%', width: '100%' }} zoomControl={false}>
        <TileLayer
          url={ESRI_WORLD_IMAGERY}
          attribution="Tiles &copy; Esri"
        />
        <ZoomControl position="bottomright" />
        {zones?.map((zone) => (
          <Polygon
            key={zone.id}
            // GeoJSON is [lon, lat]; Leaflet wants [lat, lon].
            positions={zone.geometry.coordinates[0].map(([lon, lat]) => [lat, lon] as [number, number])}
            pathOptions={{ color: ZONE_META[zone.zone_type].color, weight: 2, fillOpacity: 0.1 }}
          >
            <Tooltip sticky>{zone.name} ({zone.zone_type})</Tooltip>
          </Polygon>
        ))}
        {!replay &&
          withPosition
            .filter((v) => v.vehicle_type === 'excavator')
            .map((excavator) => {
              const pos = excavator.latest_position!
              return (
                <Fragment key={`ex-radius-${excavator.id}`}>
                  <Circle
                    center={[pos.latitude, pos.longitude]}
                    radius={EXCAVATOR_WORK_AREA_M}
                    pathOptions={{
                      color: EXCAVATOR_CIRCLE_COLOR,
                      weight: 1.5,
                      fillOpacity: 0.04,
                      opacity: 0.5,
                      dashArray: '6 4',
                    }}
                  >
                    <Tooltip sticky>{excavator.asset_id} work area ({EXCAVATOR_WORK_AREA_M} m)</Tooltip>
                  </Circle>
                  <Circle
                    center={[pos.latitude, pos.longitude]}
                    radius={EXCAVATOR_FILL_RADIUS_M}
                    pathOptions={{
                      color: EXCAVATOR_CIRCLE_COLOR,
                      weight: 2,
                      fillOpacity: 0.12,
                    }}
                  >
                    <Tooltip sticky>{excavator.asset_id} fill radius ({EXCAVATOR_FILL_RADIUS_M} m) — trucks inside are loading</Tooltip>
                  </Circle>
                </Fragment>
              )
            })}
        {/* Route replay takes over the map: normal fleet markers step aside for the
            one vehicle's breadcrumb + a scrubbable position marker (CLAUDE.md dashboard
            spec: "breadcrumb trail, route replay with play/scrub"). */}
        {!replay &&
          withPosition.map((vehicle) => {
            const pos = vehicle.latest_position!
            return (
              <Marker
                key={vehicle.id}
                position={[pos.latitude, pos.longitude]}
                icon={vehicleIcon(vehicle.asset_id, vehicle.vehicle_type, vehicle.status)}
                eventHandlers={{
                  click: () => onSelectVehicle(vehicle.id),
                }}
              />
            )
          })}
        {replay && replay.positions.length > 0 && (
          <>
            <FitRouteBounds positions={replay.positions} />
            <Polyline
              positions={replay.positions.map((p) => [p.latitude, p.longitude] as [number, number])}
              pathOptions={{ color: REPLAY_TRAIL_COLOR, weight: 3, opacity: 0.8 }}
            />
            <Marker
              position={[replay.positions[replay.index].latitude, replay.positions[replay.index].longitude]}
              icon={replayIcon(replay.vehicle.asset_id, replay.vehicle.vehicle_type)}
            />
          </>
        )}

        {draw.mode === 'drawing' && !draw.formOpen && (
          <DrawClickCapture
            points={draw.points}
            onPoint={(pt) => setDraw({ ...draw, points: [...draw.points, pt] })}
            onClose={() => setDraw({ ...draw, formOpen: true })}
          />
        )}
        {draw.mode === 'drawing' && draw.points.length > 0 && (
          <Polygon
            positions={draw.points}
            pathOptions={{ color: '#ffffff', weight: 2, dashArray: '4 4', fillOpacity: 0.15 }}
          />
        )}
        {draw.mode === 'drawing' &&
          draw.points.map((pt, i) => (
            <DraggableVertex
              key={i}
              index={i}
              position={pt}
              onMove={(index, newPos) =>
                setDraw((prev) =>
                  prev.mode === 'drawing'
                    ? { ...prev, points: prev.points.map((p, idx) => (idx === index ? newPos : p)) }
                    : prev,
                )
              }
            />
          ))}
      </MapContainer>
      {/* Zone editing has no business on screen during a replay — it's the one other
          floating panel and it visually collides with the replay controls. */}
      {!replay && <ZoneEditorPanel zones={zones ?? []} draw={draw} setDraw={setDraw} />}
    </div>
  )
}
