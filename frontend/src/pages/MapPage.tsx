import { useEffect, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { PanelLeftClose, Satellite } from 'lucide-react'
import { useVehicleRoute, useVehicles, type Vehicle, type VehicleStatus } from '../api/client'
import { LiveMap } from '../components/LiveMap'
import { ReplayPanel } from '../components/ReplayPanel'
import type { ReplayRequest } from '../layout/Shell'
import { ACTIVE_TRIP_PHASES, STATUS_META, TRIP_META } from '../lib/status'
import { TYPE_ICON } from '../lib/vehicleIcons'
import { useT } from '../i18n/strings'

const STATUS_ORDER: VehicleStatus[] = ['running', 'idle', 'breakdown', 'no_comm', 'not_installed']

type OutletCtx = {
  openVehicle: (id: string) => void
  replay: ReplayRequest | null
  setReplay: (replay: ReplayRequest | null) => void
}
type Filter = 'all' | VehicleStatus

function minutesSince(iso: string): number {
  return Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000))
}

export function MapPage() {
  const { data: vehicles, isLoading, error } = useVehicles()
  const { openVehicle, replay, setReplay } = useOutletContext<OutletCtx>()
  const [listOpen, setListOpen] = useState(true)
  const [filter, setFilter] = useState<Filter>('all')
  const [replayIndex, setReplayIndex] = useState(0)
  const T = useT()

  const list = vehicles ?? []
  const counts: Record<Filter, number> = { all: list.length, running: 0, idle: 0, breakdown: 0, no_comm: 0, not_installed: 0 }
  list.forEach((v) => {
    if (v.status) counts[v.status] += 1
  })

  const matches = (v: Vehicle) => filter === 'all' || v.status === filter
  const filtered = list.filter(matches)

  const replayVehicle = replay ? list.find((v) => v.id === replay.vehicleId) ?? null : null
  const { data: routePositions, isLoading: routeLoading } = useVehicleRoute(replay?.vehicleId, replay?.date ?? '')

  // New route loaded (vehicle or date changed) — snap the scrub position back to the start.
  useEffect(() => {
    setReplayIndex(0)
  }, [replay?.vehicleId, replay?.date])

  return (
    <div className="ls-map-page">
      {isLoading && <p className="ls-map-status">Loading…</p>}
      {error && <p className="error ls-map-status">{(error as Error).message}</p>}

      {replay && replayVehicle && (
        <ReplayPanel
          vehicle={replayVehicle}
          positions={routePositions ?? []}
          isLoading={routeLoading}
          index={replayIndex}
          onIndexChange={setReplayIndex}
          onClose={() => setReplay(null)}
        />
      )}

      {!replay && listOpen && (
        <div className="ls-vehicle-list-panel">
          <div className="ls-vehicle-list-head">
            <div className="ls-vehicle-list-count">
              {T('equipment')} <span>· {filtered.length}</span>
            </div>
            <button className="ls-icon-btn" onClick={() => setListOpen(false)} aria-label="Collapse list">
              <PanelLeftClose size={15} />
            </button>
          </div>
          <div className="ls-filter-chips">
            {(['all', ...STATUS_ORDER] as Filter[]).map((key) => (
              <button
                key={key}
                className={`ls-filter-chip${filter === key ? ' ls-filter-chip-active' : ''}`}
                onClick={() => setFilter(key)}
              >
                {key !== 'all' && <span className="ls-legend-swatch" style={{ background: STATUS_META[key].color }} />}
                {key === 'all' ? T('all') : T(key)} {counts[key]}
              </button>
            ))}
          </div>
          <div className="ls-vehicle-list">
            {filtered.map((v) => {
              const Icon = TYPE_ICON[v.vehicle_type]
              const meta = STATUS_META[v.status ?? 'not_installed']
              const stale = v.latest_position ? minutesSince(v.latest_position.event_time) > 10 : true
              // Trip phase beats raw speed as the row's one-liner: "Loading" tells the
              // owner what the truck is doing; "0 km/h" only tells him it isn't moving.
              const activePhase =
                v.trip_status && ACTIVE_TRIP_PHASES.includes(v.trip_status) ? v.trip_status : null
              const metaText = v.latest_position
                ? stale
                  ? `${minutesSince(v.latest_position.event_time)}m ago`
                  : activePhase
                    ? T(activePhase)
                    : v.latest_position.speed_knots != null
                      ? `${Math.round(v.latest_position.speed_knots * 1.852)} km/h`
                      : v.status
                        ? T(v.status)
                        : T('unknown')
                : T('unknown')
              return (
                <div className="ls-vehicle-row" key={v.id} onClick={() => openVehicle(v.id)}>
                  <span className="ls-status-dot" style={{ background: v.status ? meta.color : '#D1D5DB' }} />
                  <Icon size={15} />
                  <span className="ls-vehicle-row-id">{v.asset_id}</span>
                  <span
                    className="ls-vehicle-row-meta"
                    style={activePhase && !stale ? { color: TRIP_META[activePhase].color, fontWeight: 600 } : undefined}
                  >
                    {metaText}
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      <div className="ls-map-canvas">
        <div className="ls-map-toolbar">
          {!replay && !listOpen && (
            <button className="ls-map-toolbar-btn" onClick={() => setListOpen(true)}>
              {T('equipment')}
            </button>
          )}
        </div>
        <div className="ls-map-satellite-badge">
          <Satellite size={13} />
          Esri World Imagery
        </div>
        {vehicles && (
          <LiveMap
            vehicles={vehicles}
            onSelectVehicle={openVehicle}
            replay={
              replay && replayVehicle
                ? { vehicle: replayVehicle, positions: routePositions ?? [], index: replayIndex }
                : null
            }
          />
        )}
      </div>
    </div>
  )
}
