import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  AlertTriangle,
  ArrowLeft,
  Clock,
  Cpu,
  Factory,
  Pencil,
  Route as RouteIcon,
  Trash2,
  Weight,
  X,
} from 'lucide-react'
import {
  todayIST,
  useDeleteVehicle,
  useExcavatorLoadsRange,
  useTripRoute,
  useVehicle,
  useVehicleStats,
  useVehicleTripsRange,
  useZones,
  type Trip,
} from '../api/client'
import { statusMeta, VEHICLE_TYPE_LABEL } from '../lib/status'
import { formatCycleTime, formatDistance, formatIST, formatISTDate, formatLastSeen, minutesSince } from '../lib/format'
import { TYPE_ICON } from '../lib/vehicleIcons'
import { TripRouteMap } from '../components/TripRouteMap'
import { VehicleForm } from '../components/VehicleForm'
import { useT, type StringKey } from '../i18n/strings'

type Period = 'day' | 'week' | 'all'

const PERIODS: { key: Period; labelKey: StringKey }[] = [
  { key: 'day', labelKey: 'day' },
  { key: 'week', labelKey: 'week' },
  { key: 'all', labelKey: 'allTime' },
]

function istDaysAgo(days: number): string {
  return new Date(Date.now() - days * 86400000).toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' })
}

// Dummy demo indicators (explicit user request) until the fuel classifier and
// engine-hour pipelines exist — each renders with a visible "Sample data" badge so
// they can't be mistaken for real numbers. Distance used to be here too; it's now a
// real value from GET /vehicles/{id}/stats (Traccar's own odometer, CLAUDE.md: don't
// rebuild what Traccar provides) — see the ls-stat-tiles block below.
const SAMPLE_TILES: { labelKey: StringKey; value: string }[] = [
  { labelKey: 'engineHours', value: '38.5 h' },
  { labelKey: 'fuelUsed', value: '260 L' },
]

function TripListRow({
  trip,
  isExcavator,
  selected,
  onSelect,
  zoneNameById,
}: {
  trip: Trip
  isExcavator: boolean
  selected: boolean
  onSelect: () => void
  zoneNameById: Map<string, string>
}) {
  const T = useT()
  // Load source (excavator asset or loading-zone name) → dump zone name, so the row
  // itself says where the material came from and went, not just when.
  const loadLabel =
    !isExcavator && (trip.load_excavator_asset_id ?? (trip.load_zone_id ? zoneNameById.get(trip.load_zone_id) : null))
  const dumpLabel = trip.dump_zone_id ? zoneNameById.get(trip.dump_zone_id) : null
  return (
    <button className={`ls-detail-trip-row${selected ? ' ls-detail-trip-row-selected' : ''}`} onClick={onSelect}>
      <div className="ls-trip-row-top">
        <span className="ls-trip-cycle">
          {isExcavator ? trip.vehicle_asset_id ?? '—' : trip.cycle_number != null ? `#${trip.cycle_number}` : '—'}
        </span>
        <span className="ls-trip-times">
          {formatISTDate(trip.started_at)} · {formatIST(trip.started_at)} →{' '}
          {trip.completed_at ? formatIST(trip.completed_at) : '…'}
        </span>
        <span className={`ls-trip-status ls-trip-status-${trip.status}`}>{T(trip.status)}</span>
      </div>
      <div className="ls-trip-row-meta">
        {(loadLabel || dumpLabel) && (
          <span>
            {loadLabel ?? '—'} → {dumpLabel ?? '—'}
          </span>
        )}
        {trip.haul_distance_m != null && (
          <span>
            {T('leadDistance')} {formatDistance(trip.haul_distance_m)}
          </span>
        )}
        {trip.cycle_time_seconds != null && <span>{formatCycleTime(trip.cycle_time_seconds)}</span>}
        {trip.had_anomalous_entry && (
          <span className="ls-trip-anom">
            <AlertTriangle size={11} />
            {T('anomalousEntry')}
          </span>
        )}
      </div>
    </button>
  )
}

export function VehicleDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const T = useT()
  const { data: vehicle, isLoading, error } = useVehicle(id)
  const [period, setPeriod] = useState<Period>('day')
  const [selectedTrip, setSelectedTrip] = useState<Trip | null>(null)
  const [editOpen, setEditOpen] = useState(false)
  const [justDeactivated, setJustDeactivated] = useState(false)
  const deleteVehicle = useDeleteVehicle()

  const handleDelete = () => {
    if (!id || !window.confirm(T('confirmDeleteVehicle'))) return
    deleteVehicle.mutate(id, {
      onSuccess: (result) => {
        if (result.action === 'deleted') {
          navigate('/vehicles')
        } else {
          setJustDeactivated(true)
        }
      },
    })
  }

  const start = period === 'day' ? todayIST() : period === 'week' ? istDaysAgo(6) : undefined
  const end = period === 'all' ? undefined : todayIST()

  const isExcavator = vehicle?.vehicle_type === 'excavator'
  const tripsQuery = useVehicleTripsRange(id, start, end, !!vehicle && !isExcavator)
  const loadsQuery = useExcavatorLoadsRange(id, start, end, !!vehicle && isExcavator)
  const statsQuery = useVehicleStats(id, start, end)
  const rows = (isExcavator ? loadsQuery.data : tripsQuery.data) ?? []
  const rowsLoading = isExcavator ? loadsQuery.isLoading : tripsQuery.isLoading
  // Backend returns oldest-first; the owner wants the latest trip on top.
  const rowsNewestFirst = useMemo(() => [...rows].reverse(), [rows])
  const tripCount = isExcavator ? rows.length : rows.filter((t) => t.status === 'completed').length

  // Stable per selected trip — a fresh new Date() per render would churn the query key.
  const routeUntil = useMemo(() => {
    if (!selectedTrip) return undefined
    if (selectedTrip.completed_at) return selectedTrip.completed_at
    if (selectedTrip.dumped_at) return selectedTrip.dumped_at
    // Aborted trips have neither timestamp: they end the moment the vehicle's NEXT
    // trip opens (that's what marked them aborted), so bound the route there. The old
    // fallthrough to "now" swept the vehicle's entire subsequent day of driving into
    // one giant route polyline. A trip with no successor really is still running, so
    // "now" stays correct only for that case.
    const successor = rows
      .filter((t) => t.id !== selectedTrip.id && t.started_at > selectedTrip.started_at)
      .reduce<Trip | null>((best, t) => (best == null || t.started_at < best.started_at ? t : best), null)
    return successor?.started_at ?? new Date().toISOString()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTrip?.id, rows])
  const routeQuery = useTripRoute(selectedTrip ? id : undefined, selectedTrip?.started_at, routeUntil)

  // Zone context for the route map + trip rows: id -> zone, current versions only.
  const { data: zones } = useZones()
  const zoneNameById = useMemo(() => new Map((zones ?? []).map((z) => [z.id, z.name])), [zones])
  const tripZones = useMemo(() => {
    if (!selectedTrip || !zones) return []
    return zones.filter((z) => z.id === selectedTrip.load_zone_id || z.id === selectedTrip.dump_zone_id)
  }, [selectedTrip?.id, zones])

  if (isLoading) return <div className="ls-detail-page"><p className="ls-placeholder-body">Loading…</p></div>
  if (error || !vehicle) {
    return (
      <div className="ls-detail-page">
        <p className="error">{(error as Error | null)?.message ?? 'Vehicle not found'}</p>
        <Link className="ls-table-link" to="/vehicles">
          <ArrowLeft size={14} /> {T('back')}
        </Link>
      </div>
    )
  }

  const meta = statusMeta(vehicle.status)
  const Icon = TYPE_ICON[vehicle.vehicle_type]

  return (
    <div className="ls-detail-page">
      <div className="ls-card ls-detail-head">
        <div className="ls-detail-head-top">
          <Link className="ls-table-link ls-detail-back" to="/vehicles">
            <ArrowLeft size={14} /> {T('back')}
          </Link>
          <div className="ls-detail-head-actions">
            <button className="ls-icon-btn" onClick={() => setEditOpen(true)} aria-label={T('edit')}>
              <Pencil size={15} />
            </button>
            <button
              className="ls-icon-btn ls-icon-btn-danger"
              onClick={handleDelete}
              disabled={deleteVehicle.isPending}
              aria-label={T('deleteVehicle')}
            >
              <Trash2 size={15} />
            </button>
          </div>
        </div>
        {justDeactivated && (
          <div className="ls-stale-warn">
            <AlertTriangle size={14} />
            {T('vehicleDeactivated')}
          </div>
        )}
        <div className="ls-detail-title">
          <div className="ls-drawer-icon">
            <Icon size={20} />
          </div>
          <div>
            <div className="ls-drawer-id">{vehicle.asset_id}</div>
            <div className="ls-drawer-type">{VEHICLE_TYPE_LABEL[vehicle.vehicle_type]}</div>
          </div>
          <span className="ls-status-pill" style={{ background: meta.tint, color: meta.color }}>
            <span className="ls-status-dot" style={{ background: meta.color }} />
            {vehicle.status ? T(vehicle.status) : T('unknown')}
          </span>
          {vehicle.deactivated_at && (
            <span className="ls-status-pill ls-status-pill-deactivated">{T('deactivated')}</span>
          )}
        </div>
        <div className="ls-detail-facts">
          <span>
            <Cpu size={13} /> {T('deviceUniqueId')}: {vehicle.traccar_unique_id}
          </span>
          <span>
            <RouteIcon size={13} /> {T('registrationNumber')}: {vehicle.registration_number ?? '—'}
          </span>
          <span>
            <Factory size={13} /> {T('manufacturer')}: {vehicle.manufacturer ?? '—'}
          </span>
          <span>
            <Weight size={13} /> {T('capacityTonnes')}: {vehicle.capacity_tonnes ?? '—'}
          </span>
          <span>
            <Clock size={13} /> {T('lastActive')}:{' '}
            {vehicle.latest_position ? formatLastSeen(minutesSince(vehicle.latest_position.event_time)) : '—'}
          </span>
        </div>
      </div>

      <div className="ls-detail-controls">
        <div className="ls-period-tabs">
          {PERIODS.map((p) => (
            <button
              key={p.key}
              className={period === p.key ? 'ls-period-tab-active' : ''}
              onClick={() => {
                setPeriod(p.key)
                setSelectedTrip(null)
              }}
            >
              {T(p.labelKey)}
            </button>
          ))}
        </div>
      </div>

      <div className="ls-stat-tiles">
        <div className="ls-stat-tile">
          <div className="ls-stat-tile-label">{isExcavator ? T('trucksFilled') : T('tripsInPeriod')}</div>
          <div className="ls-stat-tile-value">{rowsLoading ? '…' : tripCount}</div>
        </div>
        <div className="ls-stat-tile">
          <div className="ls-stat-tile-label">{T('distance')}</div>
          <div className="ls-stat-tile-value">
            {statsQuery.isLoading
              ? '…'
              : statsQuery.data?.distance_m != null
                ? formatDistance(statsQuery.data.distance_m)
                : '—'}
          </div>
        </div>
        {SAMPLE_TILES.map((tile) => (
          <div className="ls-stat-tile" key={tile.labelKey}>
            <div className="ls-stat-tile-label">
              {T(tile.labelKey)}
              <span className="ls-sample-badge">{T('sampleData')}</span>
            </div>
            <div className="ls-stat-tile-value">{tile.value}</div>
          </div>
        ))}
      </div>

      <div className="ls-detail-grid">
        <div className="ls-card ls-detail-trips">
          <div className="ls-card-title">{isExcavator ? T('trucksFilledToday') : T('tripsInPeriod')}</div>
          {rowsLoading ? (
            <div className="ls-drawer-placeholder">…</div>
          ) : rowsNewestFirst.length === 0 ? (
            <div className="ls-drawer-placeholder">{T('noTripsPeriod')}</div>
          ) : (
            <div className="ls-trip-list">
              {rowsNewestFirst.map((t) => (
                <TripListRow
                  key={t.id}
                  trip={t}
                  isExcavator={isExcavator}
                  selected={selectedTrip?.id === t.id}
                  onSelect={() => setSelectedTrip(selectedTrip?.id === t.id ? null : t)}
                  zoneNameById={zoneNameById}
                />
              ))}
            </div>
          )}
        </div>
        <div className="ls-card ls-detail-route">
          <div className="ls-card-title">{T('tripRoute')}</div>
          {selectedTrip ? (
            <TripRouteMap positions={routeQuery.data ?? []} isLoading={routeQuery.isLoading} zones={tripZones} />
          ) : (
            <div className="ls-drawer-placeholder ls-detail-route-empty">{T('selectTrip')}</div>
          )}
        </div>
      </div>

      {editOpen && (
        <div className="ls-modal-backdrop" onClick={() => setEditOpen(false)}>
          <div className="ls-modal" onClick={(e) => e.stopPropagation()}>
            <div className="ls-modal-head">
              <span className="ls-card-title">{T('editVehicle')}</span>
              <button className="ls-icon-btn" onClick={() => setEditOpen(false)} aria-label="Close">
                <X size={16} />
              </button>
            </div>
            <VehicleForm vehicle={vehicle} onDone={() => setEditOpen(false)} />
          </div>
        </div>
      )}
    </div>
  )
}
