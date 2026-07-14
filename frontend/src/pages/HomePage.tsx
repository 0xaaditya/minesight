import { useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { Check, Grid3x3, Inbox, PieChart } from 'lucide-react'
import { useAckEvent, useEvents, useVehicles, useZones, type FleetEvent, type VehicleStatus } from '../api/client'
import { eventMeta, STATUS_META } from '../lib/status'
import { isInsideAnyZone } from '../lib/geo'
import { TYPE_ICON } from '../lib/vehicleIcons'
import { formatIST, formatISTDate } from '../lib/format'
import { FleetWheel } from '../components/FleetWheel'
import { useT, type StringKey } from '../i18n/strings'

const STATUS_ORDER: VehicleStatus[] = ['running', 'idle', 'breakdown', 'no_comm', 'not_installed']

type OutletCtx = { openVehicle: (id: string) => void }

function eventDetailLine(e: FleetEvent): string | null {
  const d = (e.details ?? {}) as Record<string, unknown>
  switch (e.event_type) {
    case 'night_movement':
      return typeof d.speed_kmph === 'number' ? `${d.speed_kmph} km/h` : null
    case 'boundary_exit':
      return e.zone_name ?? (Array.isArray(d.zone_names) ? (d.zone_names as string[]).join(', ') : null)
    case 'zone_overspeed': {
      const speed = d.max_speed_kmph ?? d.speed_kmph
      const limit = d.limit_kmph
      const zonePart = e.zone_name ? `${e.zone_name} · ` : ''
      return typeof speed === 'number' && typeof limit === 'number'
        ? `${zonePart}${speed} km/h (limit ${limit})`
        : e.zone_name ?? null
    }
    default:
      return null
  }
}

function EventRow({ event }: { event: FleetEvent }) {
  const T = useT()
  const ackEvent = useAckEvent()
  const meta = eventMeta(event.event_type)
  const Icon = meta.icon
  const detail = eventDetailLine(event)
  const acked = !!event.acknowledged_at
  return (
    <div className={`ls-event-row${acked ? '' : ' ls-event-row-unacked'}`}>
      <span className="ls-event-icon" style={{ background: meta.tint, color: meta.color }}>
        <Icon size={14} />
      </span>
      <div className="ls-event-body">
        <div className="ls-event-top">
          <span className="ls-event-vehicle">{event.vehicle_asset_id ?? '—'}</span>
          <span className="ls-event-label" style={{ color: meta.color }}>
            {T(meta.labelKey as StringKey)}
          </span>
          {event.delayed && <span className="ls-event-delayed-tag">{T('delayedTag')}</span>}
          {!event.ended_at && <span className="ls-event-ongoing-tag">{T('ongoing')}</span>}
        </div>
        <div className="ls-event-meta">
          {formatISTDate(event.event_time)} · {formatIST(event.event_time)}
          {detail && <> · {detail}</>}
        </div>
      </div>
      {acked ? (
        <span className="ls-event-acked">
          <Check size={13} />
        </span>
      ) : (
        <button
          className="ls-event-ack-btn"
          disabled={ackEvent.isPending}
          onClick={() => ackEvent.mutate(event.id)}
        >
          {T('acknowledge')}
        </button>
      )}
    </div>
  )
}

function PlaceholderCard({ title, note }: { title: string; note: string }) {
  return (
    <div className="ls-card">
      <div className="ls-card-title">{title}</div>
      <div className="ls-placeholder-body">{note}</div>
    </div>
  )
}

export function HomePage() {
  const { data: vehicles } = useVehicles()
  const { data: zones } = useZones()
  const { data: events } = useEvents()
  const { openVehicle } = useOutletContext<OutletCtx>()
  const [view, setView] = useState<'wheel' | 'grid'>('wheel')
  const T = useT()

  const unackedCount = (events ?? []).filter((e) => !e.acknowledged_at).length

  const list = vehicles ?? []
  const counts: Record<VehicleStatus, number> = {
    running: 0,
    idle: 0,
    breakdown: 0,
    no_comm: 0,
    not_installed: 0,
  }
  list.forEach((v) => {
    if (v.status) counts[v.status] += 1
  })
  const active = counts.running + counts.idle + counts.breakdown
  const inactive = counts.no_comm + counts.not_installed

  const withPosition = list.filter((v) => v.latest_position)
  const insideCount =
    zones && zones.length
      ? withPosition.filter((v) => isInsideAnyZone(v.latest_position!.latitude, v.latest_position!.longitude, zones))
          .length
      : 0
  const outsideCount = withPosition.length - insideCount

  return (
    <div className="ls-home">
      <div className="ls-home-left">
        <div className="ls-card">
          <div className="ls-card-head">
            <span className="ls-card-title">{T('overallFleetStatus')}</span>
            <span className="ls-card-total">{list.length}</span>
          </div>
          <div className="ls-fleet-split">
            <div className="ls-fleet-split-cell ls-fleet-split-active">
              <div className="ls-fleet-split-label">{T('activeFleet')}</div>
              <div className="ls-fleet-split-value">{active}</div>
            </div>
            <div className="ls-fleet-split-cell">
              <div className="ls-fleet-split-label">{T('inactiveFleet')}</div>
              <div className="ls-fleet-split-value">{inactive}</div>
            </div>
          </div>
          <div className="ls-status-list">
            {STATUS_ORDER.map((status) => (
              <div className="ls-status-row" key={status}>
                <span className="ls-status-dot" style={{ background: STATUS_META[status].color }} />
                <span className="ls-status-row-label">{T(status)}</span>
                <span className="ls-status-row-count">{counts[status]}</span>
              </div>
            ))}
          </div>
        </div>

        <PlaceholderCard title={T('todayTrips')} note={T('notWiredTrips')} />
        <PlaceholderCard title={T('todayFuel')} note={T('notWiredFuelSummary')} />
        <PlaceholderCard title={T('todayIncidents')} note={T('notWiredIncidents')} />

        <div className="ls-card">
          <div className="ls-card-title">{T('equipmentLocation')}</div>
          <div className="ls-location-split">
            <div className="ls-location-cell">
              <div className="ls-location-value" style={{ color: '#16A34A' }}>
                {insideCount}
              </div>
              <div className="ls-location-label">{T('insideZones')}</div>
            </div>
            <div className="ls-location-divider" />
            <div className="ls-location-cell">
              <div className="ls-location-value" style={{ color: '#F59E0B' }}>
                {outsideCount}
              </div>
              <div className="ls-location-label">{T('outsideZones')}</div>
            </div>
          </div>
        </div>
      </div>

      <div className="ls-home-right">
        <div className="ls-card">
          <div className="ls-wheel-head">
            <div>
              <div className="ls-wheel-title">{T('fleetWheel')}</div>
              <div className="ls-wheel-sub">{T('wheelSub')}</div>
            </div>
            <div className="ls-wheel-controls">
              <div className="ls-wheel-legend">
                {STATUS_ORDER.map((status) => (
                  <span className="ls-wheel-legend-item" key={status}>
                    <span className="ls-legend-swatch" style={{ background: STATUS_META[status].color }} />
                    {T(status)}
                  </span>
                ))}
              </div>
              <div className="ls-toggle-group">
                <button className={view === 'wheel' ? 'ls-toggle-active' : ''} onClick={() => setView('wheel')}>
                  <PieChart size={14} />
                  {T('wheel')}
                </button>
                <button className={view === 'grid' ? 'ls-toggle-active' : ''} onClick={() => setView('grid')}>
                  <Grid3x3 size={14} />
                  {T('grid')}
                </button>
              </div>
            </div>
          </div>

          {view === 'wheel' ? (
            <div className="ls-wheel-wrap">
              <FleetWheel vehicles={list} onSelect={openVehicle} />
            </div>
          ) : (
            <div className="ls-grid-tiles">
              {list.map((v) => {
                const meta = STATUS_META[v.status ?? 'not_installed']
                const Icon = TYPE_ICON[v.vehicle_type]
                return (
                  <div
                    key={v.id}
                    className="ls-grid-tile"
                    style={{ background: meta.color }}
                    title={`${v.asset_id} · ${v.status ? T(v.status) : T('unknown')}`}
                    onClick={() => openVehicle(v.id)}
                  >
                    <Icon size={15} />
                    <span>{v.asset_id}</span>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        <div className="ls-card ls-events-card">
          <div className="ls-card-head">
            <span className="ls-card-title-lg">{T('liveEvents')}</span>
            {unackedCount > 0 && <span className="ls-badge">{unackedCount}</span>}
          </div>
          {!events || events.length === 0 ? (
            <div className="ls-empty-state">
              <Inbox size={22} />
              <p>{T('noEventsYet')}</p>
            </div>
          ) : (
            <div className="ls-event-list">
              {events.map((e) => (
                <EventRow key={e.id} event={e} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
