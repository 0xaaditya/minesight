import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Plus, X } from 'lucide-react'
import { useVehicles } from '../api/client'
import { VehicleForm } from '../components/VehicleForm'
import { STATUS_META, VEHICLE_TYPE_LABEL } from '../lib/status'
import { formatLastSeen, minutesSince } from '../lib/format'
import { useT } from '../i18n/strings'

export function VehiclesPage() {
  const { data: vehicles, isLoading, error } = useVehicles()
  const [registerOpen, setRegisterOpen] = useState(false)
  const T = useT()

  return (
    <div className="ls-vehicles-page">
      <div className="ls-card">
        <div className="ls-card-head">
          <span className="ls-card-title">{T('vehiclesDevices')}</span>
          <button className="ls-btn-primary" onClick={() => setRegisterOpen(true)}>
            <Plus size={15} />
            {T('registerVehicle')}
          </button>
        </div>
        {isLoading && <p className="ls-placeholder-body">Loading…</p>}
        {error && <p className="error">{(error as Error).message}</p>}
        <div className="ls-table-wrap">
          <table className="vehicle-table">
            <thead>
              <tr>
                <th>{T('assetId')}</th>
                <th>Type</th>
                <th>Status</th>
                <th>{T('lastActive')}</th>
                <th>{T('details')}</th>
              </tr>
            </thead>
            <tbody>
              {vehicles?.map((v) => {
                const meta = STATUS_META[v.status ?? 'not_installed']
                return (
                  <tr key={v.id}>
                    <td>{v.asset_id}</td>
                    <td>{VEHICLE_TYPE_LABEL[v.vehicle_type]}</td>
                    <td>
                      <span className="ls-status-pill" style={{ background: meta.tint, color: meta.color }}>
                        <span className="ls-status-dot" style={{ background: meta.color }} />
                        {v.status ? T(v.status) : T('unknown')}
                      </span>
                    </td>
                    <td>
                      {v.latest_position
                        ? formatLastSeen(minutesSince(v.latest_position.event_time))
                        : 'no data yet'}
                    </td>
                    <td>
                      <Link className="ls-table-link" to={`/vehicles/${v.id}`}>
                        {T('seeDetails')}
                      </Link>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {registerOpen && (
        <div className="ls-modal-backdrop" onClick={() => setRegisterOpen(false)}>
          <div className="ls-modal" onClick={(e) => e.stopPropagation()}>
            <div className="ls-modal-head">
              <span className="ls-card-title">{T('registerVehicle')}</span>
              <button className="ls-icon-btn" onClick={() => setRegisterOpen(false)} aria-label="Close">
                <X size={16} />
              </button>
            </div>
            <VehicleForm onDone={() => setRegisterOpen(false)} />
          </div>
        </div>
      )}
    </div>
  )
}
