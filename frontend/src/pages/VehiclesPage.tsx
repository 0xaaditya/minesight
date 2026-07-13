import { Link } from 'react-router-dom'
import { useVehicles } from '../api/client'
import { VehicleForm } from '../components/VehicleForm'

export function VehiclesPage() {
  const { data: vehicles, isLoading, error } = useVehicles()

  return (
    <div className="page">
      <h1>Vehicles</h1>
      <VehicleForm />

      {isLoading && <p>Loading...</p>}
      {error && <p className="error">{error.message}</p>}

      <table className="vehicle-table">
        <thead>
          <tr>
            <th>Asset ID</th>
            <th>Type</th>
            <th>Last fix</th>
            <th>Speed</th>
          </tr>
        </thead>
        <tbody>
          {vehicles?.map((v) => (
            <tr key={v.id}>
              <td>{v.asset_id}</td>
              <td>{v.vehicle_type}</td>
              <td>
                {v.latest_position
                  ? new Date(v.latest_position.event_time).toLocaleString()
                  : 'no data yet'}
              </td>
              <td>{v.latest_position?.speed_knots?.toFixed(1) ?? '—'} kn</td>
            </tr>
          ))}
        </tbody>
      </table>

      <p>
        <Link to="/map">View live map →</Link>
      </p>
    </div>
  )
}
