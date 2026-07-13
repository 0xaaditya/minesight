import { Link } from 'react-router-dom'
import { useVehicles } from '../api/client'
import { LiveMap } from '../components/LiveMap'

export function MapPage() {
  const { data: vehicles, isLoading, error } = useVehicles()

  return (
    <div className="page map-page">
      <div className="map-header">
        <h1>Live Map</h1>
        <Link to="/">← Vehicles</Link>
      </div>
      {isLoading && <p>Loading...</p>}
      {error && <p className="error">{error.message}</p>}
      <div className="map-container">{vehicles && <LiveMap vehicles={vehicles} />}</div>
    </div>
  )
}
