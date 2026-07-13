import { Activity, AlertTriangle, Camera, Clock, Fuel as FuelIcon, Gauge, History, Route, RotateCw, User, WifiOff, X } from 'lucide-react'
import type { Trip, Vehicle } from '../api/client'
import { todayIST, useExcavatorLoads, useVehicleTrips } from '../api/client'
import { ACTIVE_TRIP_PHASES, statusMeta, TRIP_META, VEHICLE_TYPE_LABEL } from '../lib/status'
import { TYPE_ICON } from '../lib/vehicleIcons'
import { useT } from '../i18n/strings'

// fixMin-equivalent: minutes since the vehicle's last known fix.
function minutesSince(iso: string): number {
  return Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000))
}

function formatLastSeen(minutes: number): string {
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} min ago`
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m ago`
}

const STALE_THRESHOLD_MIN = 10 // matches CLAUDE.md no-comm threshold

// All times stored UTC, displayed IST (CLAUDE.md convention).
function formatIST(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-IN', {
    timeZone: 'Asia/Kolkata',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

function formatDistance(meters: number): string {
  return meters >= 1000 ? `${(meters / 1000).toFixed(1)} km` : `${Math.round(meters)} m`
}

function formatCycleTime(seconds: number): string {
  const min = Math.round(seconds / 60)
  return min < 60 ? `${min} min` : `${Math.floor(min / 60)}h ${min % 60}m`
}

function TripRow({ trip }: { trip: Trip }) {
  const T = useT()
  const ExcavatorIcon = TYPE_ICON.excavator
  return (
    <div className="ls-trip-row">
      <div className="ls-trip-row-top">
        <span className="ls-trip-cycle">{trip.cycle_number != null ? `#${trip.cycle_number}` : '—'}</span>
        <span className="ls-trip-times">
          {formatIST(trip.started_at)} → {trip.completed_at ? formatIST(trip.completed_at) : '…'}
        </span>
        <span className={`ls-trip-status ls-trip-status-${trip.status}`}>{T(trip.status)}</span>
      </div>
      <div className="ls-trip-row-meta">
        {trip.load_excavator_asset_id && (
          <span className="ls-trip-excavator">
            <ExcavatorIcon size={12} />
            {trip.load_excavator_asset_id}
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
    </div>
  )
}

// One row per truck this excavator filled: which truck, when the fill started/ended.
function LoadRow({ trip }: { trip: Trip }) {
  const T = useT()
  const TruckIcon = TYPE_ICON.tipper
  return (
    <div className="ls-trip-row">
      <div className="ls-trip-row-top">
        <span className="ls-trip-excavator">
          <TruckIcon size={12} />
          {trip.vehicle_asset_id ?? '—'}
        </span>
        <span className="ls-trip-times">
          {formatIST(trip.started_at)} → {trip.loaded_at ? formatIST(trip.loaded_at) : '…'}
        </span>
        <span className={`ls-trip-status ls-trip-status-${trip.status}`}>{T(trip.status)}</span>
      </div>
    </div>
  )
}

export function VehicleDrawer({
  vehicle,
  onClose,
  onReplay,
}: {
  vehicle: Vehicle
  onClose: () => void
  onReplay: (vehicleId: string) => void
}) {
  const T = useT()
  const meta = statusMeta(vehicle.status)
  const Icon = TYPE_ICON[vehicle.vehicle_type]
  const pos = vehicle.latest_position
  const fixMin = pos ? minutesSince(pos.event_time) : null
  const stale = fixMin !== null && fixMin > STALE_THRESHOLD_MIN
  const speedKmh = pos?.speed_knots != null ? Math.round(pos.speed_knots * 1.852) : null

  // Trips make no sense on an excavator card — it fills trucks, it doesn't haul. Query
  // the excavator-facing /loads view instead and show "trucks filled" (see backend
  // trips.py list_loads).
  const isExcavator = vehicle.vehicle_type === 'excavator'
  const { data: trips, isLoading: tripsLoading } = useVehicleTrips(vehicle.id, todayIST(), !isExcavator)
  const { data: loads, isLoading: loadsLoading } = useExcavatorLoads(vehicle.id, todayIST(), isExcavator)
  const cyclesToday = trips?.filter((t) => t.status === 'completed').length
  const trucksFilledToday = loads?.length

  return (
    <>
      <div className="ls-drawer-backdrop" onClick={onClose} />
      <div className="ls-drawer">
        <div className="ls-drawer-head">
          <div className="ls-drawer-head-top">
            <div className="ls-drawer-title">
              <div className="ls-drawer-icon">
                <Icon size={20} />
              </div>
              <div>
                <div className="ls-drawer-id">{vehicle.asset_id}</div>
                <div className="ls-drawer-type">{VEHICLE_TYPE_LABEL[vehicle.vehicle_type]}</div>
              </div>
            </div>
            <button className="ls-icon-btn" onClick={onClose} aria-label="Close">
              <X size={16} />
            </button>
          </div>
          <div className="ls-drawer-chips">
            <span className="ls-status-pill" style={{ background: meta.tint, color: meta.color }}>
              <span className="ls-status-dot" style={{ background: meta.color }} />
              {vehicle.status ? T(vehicle.status) : T('unknown')}
            </span>
            {/* Trip phase shown as its own pill: "Idle" (not moving) and "Loading" (waiting
                under the excavator) are both true at once — two axes, two pills. */}
            {vehicle.trip_status && ACTIVE_TRIP_PHASES.includes(vehicle.trip_status) && (
              <span
                className="ls-status-pill"
                style={{ background: TRIP_META[vehicle.trip_status].tint, color: TRIP_META[vehicle.trip_status].color }}
              >
                <span className="ls-status-dot" style={{ background: TRIP_META[vehicle.trip_status].color }} />
                {T(vehicle.trip_status)}
              </span>
            )}
            {pos && (
              <span className={`ls-fix-chip${stale ? ' ls-fix-chip-stale' : ''}`}>
                <Clock size={12} />
                {formatLastSeen(fixMin!)}
              </span>
            )}
          </div>
          {stale && (
            <div className="ls-stale-warn">
              <WifiOff size={14} />
              {T('staleWarn')}
            </div>
          )}
        </div>

        <div className="ls-drawer-body">
          <div className="ls-drawer-driver">
            <div className="ls-drawer-driver-avatar">
              <User size={16} />
            </div>
            <div>
              <div className="ls-drawer-driver-name">{T('noDriver')}</div>
              <div className="ls-drawer-driver-note">{T('notWiredDriver')}</div>
            </div>
          </div>

          <div className="ls-drawer-stats">
            <div className="ls-drawer-stat">
              <div className="ls-drawer-stat-label">
                <Gauge size={13} />
                {T('speed')}
              </div>
              <div className="ls-drawer-stat-value">
                {speedKmh ?? '—'} <span>km/h</span>
              </div>
            </div>
            <div className="ls-drawer-stat">
              <div className="ls-drawer-stat-label">
                <RotateCw size={13} />
                {isExcavator ? T('trucksFilled') : T('cyclesToday')}
              </div>
              <div className="ls-drawer-stat-value">
                {isExcavator
                  ? loadsLoading
                    ? '…'
                    : trucksFilledToday ?? '—'
                  : tripsLoading
                    ? '…'
                    : cyclesToday ?? '—'}
              </div>
            </div>
          </div>

          {isExcavator ? (
            <div className="ls-drawer-panel">
              <div className="ls-drawer-panel-head">
                <Route size={14} />
                {T('trucksFilledToday')}
              </div>
              {loadsLoading ? (
                <div className="ls-drawer-placeholder">…</div>
              ) : !loads || loads.length === 0 ? (
                <div className="ls-drawer-placeholder">{T('noLoadsToday')}</div>
              ) : (
                <div className="ls-trip-list">
                  {loads.map((t) => (
                    <LoadRow trip={t} key={t.id} />
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="ls-drawer-panel">
              <div className="ls-drawer-panel-head">
                <Route size={14} />
                {T('todayTrips')}
              </div>
              {tripsLoading ? (
                <div className="ls-drawer-placeholder">…</div>
              ) : !trips || trips.length === 0 ? (
                <div className="ls-drawer-placeholder">{T('noTripsToday')}</div>
              ) : (
                <div className="ls-trip-list">
                  {trips.map((t) => (
                    <TripRow trip={t} key={t.id} />
                  ))}
                </div>
              )}
            </div>
          )}

          <div className="ls-drawer-panel">
            <div className="ls-drawer-panel-head">
              <FuelIcon size={14} />
              {T('fuelLevel')}
            </div>
            <div className="ls-drawer-placeholder">{T('notWiredFuel')}</div>
          </div>

          <div>
            <div className="ls-drawer-section-label">{T('quickActions')}</div>
            <div className="ls-drawer-actions">
              <button onClick={() => onReplay(vehicle.id)}>
                <History size={16} />
                {T('replayToday')}
              </button>
              <button disabled title={T('comingSoon')}>
                <Activity size={16} />
                {T('fuelCurve')}
              </button>
              <button disabled title={T('comingSoon')}>
                <Camera size={16} />
                {T('requestSnap')}
              </button>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
