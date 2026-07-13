import { useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { PanelLeftClose, Satellite } from 'lucide-react'
import { useVehicles, type Vehicle, type VehicleStatus } from '../api/client'
import { LiveMap } from '../components/LiveMap'
import { STATUS_META } from '../lib/status'
import { TYPE_ICON } from '../lib/vehicleIcons'
import { useT } from '../i18n/strings'

const STATUS_ORDER: VehicleStatus[] = ['running', 'idle', 'breakdown', 'no_comm', 'not_installed']

type OutletCtx = { openVehicle: (id: string) => void }
type Filter = 'all' | VehicleStatus

function minutesSince(iso: string): number {
  return Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000))
}

export function MapPage() {
  const { data: vehicles, isLoading, error } = useVehicles()
  const { openVehicle } = useOutletContext<OutletCtx>()
  const [listOpen, setListOpen] = useState(true)
  const [filter, setFilter] = useState<Filter>('all')
  const T = useT()

  const list = vehicles ?? []
  const counts: Record<Filter, number> = { all: list.length, running: 0, idle: 0, breakdown: 0, no_comm: 0, not_installed: 0 }
  list.forEach((v) => {
    if (v.status) counts[v.status] += 1
  })

  const matches = (v: Vehicle) => filter === 'all' || v.status === filter
  const filtered = list.filter(matches)

  return (
    <div className="ls-map-page">
      {isLoading && <p className="ls-map-status">Loading…</p>}
      {error && <p className="error ls-map-status">{(error as Error).message}</p>}

      {listOpen && (
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
              const metaText = v.latest_position
                ? stale
                  ? `${minutesSince(v.latest_position.event_time)}m ago`
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
                  <span className="ls-vehicle-row-meta">{metaText}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      <div className="ls-map-canvas">
        <div className="ls-map-toolbar">
          {!listOpen && (
            <button className="ls-map-toolbar-btn" onClick={() => setListOpen(true)}>
              {T('equipment')}
            </button>
          )}
        </div>
        <div className="ls-map-satellite-badge">
          <Satellite size={13} />
          Esri World Imagery
        </div>
        {vehicles && <LiveMap vehicles={vehicles} onSelectVehicle={openVehicle} />}
      </div>
    </div>
  )
}
