import { Activity, Camera, Clock, Fuel as FuelIcon, Gauge, History, RotateCw, User, WifiOff, X } from 'lucide-react'
import type { Vehicle } from '../api/client'
import { todayIST, useVehicleTrips } from '../api/client'
import { statusMeta, VEHICLE_TYPE_LABEL } from '../lib/status'
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

export function VehicleDrawer({ vehicle, onClose }: { vehicle: Vehicle; onClose: () => void }) {
  const T = useT()
  const meta = statusMeta(vehicle.status)
  const Icon = TYPE_ICON[vehicle.vehicle_type]
  const pos = vehicle.latest_position
  const fixMin = pos ? minutesSince(pos.event_time) : null
  const stale = fixMin !== null && fixMin > STALE_THRESHOLD_MIN
  const speedKmh = pos?.speed_knots != null ? Math.round(pos.speed_knots * 1.852) : null

  const { data: trips, isLoading: tripsLoading } = useVehicleTrips(vehicle.id, todayIST())
  const cyclesToday = trips?.filter((t) => t.status === 'completed').length

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
                {T('cyclesToday')}
              </div>
              <div className="ls-drawer-stat-value">{tripsLoading ? '…' : cyclesToday ?? '—'}</div>
            </div>
          </div>

          {vehicle.trip_status && (
            <div className="ls-drawer-row">
              <span>{T('tripStatus')}</span>
              <strong>{vehicle.trip_status}</strong>
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
              <button disabled title={T('comingSoon')}>
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
