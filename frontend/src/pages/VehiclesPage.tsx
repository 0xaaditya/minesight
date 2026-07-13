import { useVehicles } from '../api/client'
import { VehicleForm } from '../components/VehicleForm'
import { STATUS_META, VEHICLE_TYPE_LABEL } from '../lib/status'
import { useT } from '../i18n/strings'

export function VehiclesPage() {
  const { data: vehicles, isLoading, error } = useVehicles()
  const T = useT()

  return (
    <div className="ls-vehicles-page">
      <div className="ls-card">
        <div className="ls-card-title">{T('registerVehicle')}</div>
        <VehicleForm />
      </div>

      <div className="ls-card">
        <div className="ls-card-title">{T('vehiclesDevices')}</div>
        {isLoading && <p className="ls-placeholder-body">Loading…</p>}
        {error && <p className="error">{(error as Error).message}</p>}
        <table className="vehicle-table">
          <thead>
            <tr>
              <th>{T('assetId')}</th>
              <th>Type</th>
              <th>Status</th>
              <th>{T('lastFix')}</th>
              <th>{T('speed')}</th>
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
                      ? new Date(v.latest_position.event_time).toLocaleString()
                      : 'no data yet'}
                  </td>
                  <td>{v.latest_position?.speed_knots?.toFixed(1) ?? '—'} kn</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
